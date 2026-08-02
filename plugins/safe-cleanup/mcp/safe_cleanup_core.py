from __future__ import annotations

import csv
import ctypes
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

PLAN_SCHEMA = "safe-cleanup.plan.v1"
RECEIPT_SCHEMA = "safe-cleanup.receipt.v1"
MAX_TARGETS = 32
MAX_TEXT_CHARS = 2_000
DEFAULT_TTL_SECONDS = 1_800
MAX_TTL_SECONDS = 3_600
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_NORMAL = 0x80
ALLOWED_DISPOSITIONS = {"quarantine", "permanent"}
ALLOWED_CLASSIFICATIONS = {
    "authorized_disposable",
    "committed_recoverable",
    "redundant_rebuildable",
    "quarantine_unclassified",
}
PERMANENT_CLASSIFICATIONS = {
    "authorized_disposable",
    "committed_recoverable",
    "redundant_rebuildable",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _plan_sha256(plan_without_sha: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(plan_without_sha)).hexdigest()


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right))
    )


def _is_same_or_child(path: str | Path, root: str | Path) -> bool:
    normalized_path = os.path.normcase(os.path.abspath(os.path.normpath(str(path))))
    normalized_root = os.path.normcase(os.path.abspath(os.path.normpath(str(root))))
    try:
        return os.path.commonpath([normalized_path, normalized_root]) == normalized_root
    except ValueError:
        return False


def _extended_path(path: str | Path) -> str:
    value = os.path.abspath(str(path))
    if value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def _bounded_text(name: str, value: str, *, required: bool = True) -> str:
    normalized = str(value or "").strip()
    if required and not normalized:
        raise ValueError(f"{name} is required")
    if len(normalized) > MAX_TEXT_CHARS:
        raise ValueError(f"{name} exceeds {MAX_TEXT_CHARS} characters")
    return normalized


def _normalize_exact_path(value: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("path is required")
    if not os.path.isabs(raw):
        raise ValueError(f"path must be absolute: {raw}")
    if any(token in raw for token in ("*", "?")):
        raise ValueError(f"wildcards are not supported: {raw}")
    if any(token in raw for token in ("%", "${", "$env:", "~")):
        raise ValueError(f"unresolved path expressions are not supported: {raw}")
    return Path(os.path.abspath(os.path.normpath(raw)))


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            yield


def current_process_is_administrator() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _current_user_sid() -> str | None:
    if os.name != "nt":
        return None
    completed = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        return None
    rows = list(csv.reader(completed.stdout.splitlines()))
    if not rows or len(rows[0]) < 2:
        return None
    return rows[0][1].strip() or None


def _root_attributes(path: Path) -> int:
    value = getattr(os.lstat(path), "st_file_attributes", 0)
    return int(value or 0)


def _path_kind(st: os.stat_result) -> str:
    attrs = int(getattr(st, "st_file_attributes", 0) or 0)
    if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
        return "reparse"
    if stat.S_ISDIR(st.st_mode):
        return "directory"
    if stat.S_ISREG(st.st_mode):
        return "file"
    return "other"


def _scan_tree(path: Path) -> dict[str, Any]:
    root = os.lstat(path)
    root_kind = _path_kind(root)
    snapshot: dict[str, Any] = {
        "st_dev": int(root.st_dev),
        "st_ino": int(root.st_ino),
        "root_kind": root_kind,
        "root_mtime_ns": int(root.st_mtime_ns),
        "root_size": int(root.st_size),
        "root_attributes": int(getattr(root, "st_file_attributes", 0) or 0),
        "scan_complete": True,
        "file_count": 0,
        "directory_count": 0,
        "reparse_count": 0,
        "byte_count": 0,
        "scan_errors": [],
    }
    if root_kind == "reparse":
        snapshot["reparse_count"] = 1
        return snapshot
    if root_kind != "directory":
        snapshot["file_count"] = 1
        snapshot["byte_count"] = int(root.st_size)
        return snapshot

    snapshot["directory_count"] = 1
    pending = [_extended_path(path)]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        item = entry.stat(follow_symlinks=False)
                        attrs = int(getattr(item, "st_file_attributes", 0) or 0)
                        if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                            snapshot["reparse_count"] += 1
                        elif stat.S_ISDIR(item.st_mode):
                            snapshot["directory_count"] += 1
                            pending.append(entry.path)
                        else:
                            snapshot["file_count"] += 1
                            snapshot["byte_count"] += int(item.st_size)
                    except OSError as exc:
                        snapshot["scan_complete"] = False
                        if len(snapshot["scan_errors"]) < 20:
                            snapshot["scan_errors"].append(
                                {
                                    "path": str(entry.path),
                                    "winerror": getattr(exc, "winerror", None),
                                    "errno": exc.errno,
                                }
                            )
        except OSError as exc:
            snapshot["scan_complete"] = False
            if len(snapshot["scan_errors"]) < 20:
                snapshot["scan_errors"].append(
                    {
                        "path": str(current),
                        "winerror": getattr(exc, "winerror", None),
                        "errno": exc.errno,
                    }
                )
    return snapshot


def _snapshot_differences(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    identity_fields = ["st_dev", "st_ino", "root_kind", "root_mtime_ns", "root_attributes"]
    differences = [field for field in identity_fields if before.get(field) != after.get(field)]
    if before.get("scan_complete") is True:
        if after.get("scan_complete") is not True:
            differences.append("scan_complete")
        for field in ("file_count", "directory_count", "reparse_count", "byte_count"):
            if before.get(field) != after.get(field):
                differences.append(field)
    return sorted(set(differences))


def _set_normal_attributes(path: str) -> None:
    if os.name != "nt":
        return
    ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_NORMAL)


def _remove_tree_without_following_reparse(path: Path) -> None:
    source = _extended_path(path)

    def remove(item_path: str) -> None:
        try:
            item = os.lstat(item_path)
        except FileNotFoundError:
            return
        attrs = int(getattr(item, "st_file_attributes", 0) or 0)
        if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
            _set_normal_attributes(item_path)
            if attrs & FILE_ATTRIBUTE_DIRECTORY:
                os.rmdir(item_path)
            else:
                os.unlink(item_path)
            return
        if stat.S_ISDIR(item.st_mode):
            with os.scandir(item_path) as entries:
                for entry in entries:
                    remove(entry.path)
            _set_normal_attributes(item_path)
            os.rmdir(item_path)
            return
        _set_normal_attributes(item_path)
        os.unlink(item_path)

    remove(source)


def _repair_acl(path: Path) -> dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "error_code": "WINDOWS_REQUIRED", "commands": []}
    if not current_process_is_administrator():
        return {"ok": False, "error_code": "ELEVATION_REQUIRED", "commands": []}
    commands: list[dict[str, Any]] = []
    takeown = subprocess.run(
        ["takeown.exe", "/F", str(path), "/A", "/R", "/D", "Y"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    commands.append({"name": "takeown", "returncode": takeown.returncode})
    sid = _current_user_sid()
    principals = ["*S-1-5-32-544"]
    if sid:
        principals.append(f"*{sid}")
    for principal in principals:
        remove_deny = subprocess.run(
            ["icacls.exe", str(path), "/remove:d", principal, "/T", "/C", "/Q"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        commands.append(
            {
                "name": "icacls_remove_deny",
                "principal": principal,
                "returncode": remove_deny.returncode,
            }
        )
        grant = subprocess.run(
            [
                "icacls.exe",
                str(path),
                "/grant:r",
                f"{principal}:(OI)(CI)F",
                "/T",
                "/C",
                "/Q",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        commands.append(
            {
                "name": "icacls_grant",
                "principal": principal,
                "returncode": grant.returncode,
            }
        )
    return {
        "ok": takeown.returncode == 0
        and any(
            command["name"] == "icacls_grant" and command["returncode"] == 0 for command in commands
        ),
        "error_code": None,
        "commands": commands,
    }


def _classify_os_error(exc: OSError) -> str:
    winerror = getattr(exc, "winerror", None)
    if winerror in {32, 33}:
        return "LOCKED"
    if winerror in {5, 1314} or isinstance(exc, PermissionError):
        return "ACL_DENIED"
    if winerror in {206}:
        return "PATH_TOO_LONG"
    return "DELETE_FAILED"


class SafeCleanupService:
    def __init__(
        self,
        *,
        state_root: str | Path | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        plugin_root = Path(__file__).resolve().parents[1]
        self.plugin_root = plugin_root
        self.state_root = Path(
            state_root
            or os.environ.get("SAFE_CLEANUP_STATE_ROOT")
            or r"D:\XINAO_RESEARCH_RUNTIME\state\safe_cleanup"
        )
        self.config_path = Path(
            config_path
            or os.environ.get("SAFE_CLEANUP_CONFIG_PATH")
            or plugin_root / "config" / "protected_paths.json"
        )
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.plans_root = self.state_root / "plans"
        self.receipts_root = self.state_root / "receipts"
        self.lock_root = self.state_root / "locks"

    def _active_git_worktrees(self, targets: list[Path]) -> list[Path]:
        roots = [Path(value) for value in self.config.get("git_roots", [])]
        roots.extend(targets)
        observed: dict[str, Path] = {}
        for root in roots:
            if not root.exists():
                continue
            completed = subprocess.run(
                ["git", "-C", str(root), "worktree", "list", "--porcelain"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
            if completed.returncode != 0:
                continue
            for line in completed.stdout.splitlines():
                if not line.startswith("worktree "):
                    continue
                candidate = _normalize_exact_path(line.removeprefix("worktree ").strip())
                observed[os.path.normcase(str(candidate))] = candidate
        return sorted(observed.values(), key=lambda item: os.path.normcase(str(item)))

    def _protection(self, target: Path, active_worktrees: list[Path]) -> dict[str, Any] | None:
        if target.parent == target:
            return {"error_code": "PROTECTED_PATH", "reason": "drive_or_filesystem_root"}
        for value in self.config.get("protected_exact", []):
            if _same_path(target, value) or _is_same_or_child(value, target):
                return {
                    "error_code": "PROTECTED_PATH",
                    "reason": "protected_exact_or_ancestor",
                    "root": value,
                }
        protected_subtrees = [Path(value) for value in self.config.get("protected_subtrees", [])]
        protected_subtrees.extend([self.plugin_root, self.state_root])
        for root in protected_subtrees:
            if _is_same_or_child(target, root) or _is_same_or_child(root, target):
                return {
                    "error_code": "PROTECTED_PATH",
                    "reason": "protected_subtree",
                    "root": str(root),
                }
        for value in self.config.get("quarantine_roots", {}).values():
            root = Path(value)
            if _same_path(target, root) or _is_same_or_child(root, target):
                return {
                    "error_code": "PROTECTED_PATH",
                    "reason": "quarantine_root_or_ancestor",
                    "root": str(root),
                }
        for worktree in active_worktrees:
            if _is_same_or_child(target, worktree) or _is_same_or_child(worktree, target):
                return {
                    "error_code": "ACTIVE_GIT_WORKTREE",
                    "reason": "registered_worktree",
                    "root": str(worktree),
                }
        try:
            if _root_attributes(target) & FILE_ATTRIBUTE_REPARSE_POINT:
                return {"error_code": "REPARSE_TARGET", "reason": "target_root_is_reparse_point"}
        except OSError:
            pass
        return None

    @staticmethod
    def _active_consumers(targets: list[Path]) -> list[dict[str, Any]]:
        try:
            import psutil
        except ImportError as exc:
            raise ValueError("process consumer scan requires psutil") from exc
        normalized = [(target, os.path.normcase(str(target))) for target in targets]
        consumers: list[dict[str, Any]] = []
        for process in psutil.process_iter(["pid", "name", "exe", "cmdline", "cwd"]):
            if process.pid == os.getpid():
                continue
            try:
                info = process.info
                cwd = str(info.get("cwd") or "")
                exe = str(info.get("exe") or "")
                command = " ".join(str(part) for part in (info.get("cmdline") or []))
                for target, target_key in normalized:
                    cwd_hit = bool(cwd) and _is_same_or_child(cwd, target)
                    exe_hit = bool(exe) and _is_same_or_child(exe, target)
                    command_hit = bool(command) and target_key in os.path.normcase(command)
                    if cwd_hit or exe_hit or command_hit:
                        consumers.append(
                            {
                                "path": str(target),
                                "pid": int(process.pid),
                                "name": str(info.get("name") or ""),
                                "matches": {
                                    "cwd": cwd_hit,
                                    "exe": exe_hit,
                                    "command_line": command_hit,
                                },
                            }
                        )
                        break
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                continue
        return consumers

    def _quarantine_root(self, target: Path) -> Path:
        roots = {
            str(key).upper(): Path(value)
            for key, value in self.config.get("quarantine_roots", {}).items()
        }
        drive = target.drive.upper()
        root = roots.get(drive)
        if root is None:
            raise ValueError(f"no same-volume quarantine root configured for {drive}")
        if root.drive.upper() != drive:
            raise ValueError(f"quarantine root for {drive} is on a different volume")
        return root

    def plan_cleanup(
        self,
        *,
        paths: list[str],
        disposition: str,
        classification: str,
        justification: str,
        recovery_basis: str = "",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> dict[str, Any]:
        try:
            if os.name != "nt":
                raise ValueError("safe-cleanup supports Windows only")
            if not paths or len(paths) > MAX_TARGETS:
                raise ValueError(f"paths must contain 1..{MAX_TARGETS} exact items")
            if disposition not in ALLOWED_DISPOSITIONS:
                raise ValueError(f"unsupported disposition: {disposition}")
            if classification not in ALLOWED_CLASSIFICATIONS:
                raise ValueError(f"unsupported classification: {classification}")
            if disposition == "permanent" and classification not in PERMANENT_CLASSIFICATIONS:
                raise ValueError("permanent cleanup requires a classified disposable object")
            normalized_justification = _bounded_text("justification", justification)
            normalized_recovery = _bounded_text(
                "recovery_basis", recovery_basis, required=disposition == "permanent"
            )
            ttl = int(ttl_seconds)
            if ttl < 60 or ttl > MAX_TTL_SECONDS:
                raise ValueError(f"ttl_seconds must be between 60 and {MAX_TTL_SECONDS}")
            targets = [_normalize_exact_path(value) for value in paths]
            if len({os.path.normcase(str(path)) for path in targets}) != len(targets):
                raise ValueError("duplicate paths are not supported")
            for index, left in enumerate(targets):
                for right in targets[index + 1 :]:
                    if _is_same_or_child(left, right) or _is_same_or_child(right, left):
                        raise ValueError("overlapping target paths are not supported")
            missing = [str(path) for path in targets if not os.path.lexists(path)]
            if missing:
                return {"ok": False, "ready": False, "error_code": "PATH_MISSING", "paths": missing}
            active_worktrees = self._active_git_worktrees(targets)
            for target in targets:
                protection = self._protection(target, active_worktrees)
                if protection:
                    return {
                        "ok": False,
                        "ready": False,
                        "path": str(target),
                        **protection,
                    }
            consumers = self._active_consumers(targets)
            if consumers:
                return {
                    "ok": False,
                    "ready": False,
                    "error_code": "ACTIVE_CONSUMER",
                    "active_consumers": consumers,
                }
            snapshots = []
            for target in targets:
                snapshot = _scan_tree(target)
                snapshots.append({"path": str(target), "snapshot": snapshot})
            if disposition == "quarantine":
                for target in targets:
                    self._quarantine_root(target)
            now = _utc_now()
            plan_id = uuid.uuid4().hex
            payload: dict[str, Any] = {
                "schema_version": PLAN_SCHEMA,
                "plan_id": plan_id,
                "created_at": _iso(now),
                "expires_at": _iso(now + timedelta(seconds=ttl)),
                "disposition": disposition,
                "classification": classification,
                "justification": normalized_justification,
                "recovery_basis": normalized_recovery,
                "targets": snapshots,
                "protected_roots_checked": True,
                "active_worktrees_checked": [str(path) for path in active_worktrees],
                "active_consumers_checked": True,
                "acl_repair_policy": "on_access_denied_exact_target_only",
                "reparse_policy": "never_traverse",
            }
            digest = _plan_sha256(payload)
            plan = {**payload, "plan_sha256": digest}
            _atomic_write_json(self.plans_root / f"{plan_id}.json", plan)
            return {
                "ok": True,
                "ready": True,
                "plan_id": plan_id,
                "plan_sha256": digest,
                "expires_at": plan["expires_at"],
                "disposition": disposition,
                "classification": classification,
                "targets": snapshots,
                "warnings": [
                    {"path": row["path"], "scan_errors": row["snapshot"]["scan_errors"]}
                    for row in snapshots
                    if not row["snapshot"]["scan_complete"]
                ],
            }
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return {
                "ok": False,
                "ready": False,
                "error_code": "PLAN_INVALID",
                "message": str(exc),
            }

    def _load_plan(self, plan_id: str, expected_sha: str) -> dict[str, Any]:
        normalized_id = str(plan_id or "").strip().lower()
        normalized_sha = str(expected_sha or "").strip().lower()
        if len(normalized_id) != 32 or any(
            character not in "0123456789abcdef" for character in normalized_id
        ):
            raise ValueError("plan_id must be 32 lowercase hexadecimal characters")
        if len(normalized_sha) != 64 or any(
            character not in "0123456789abcdef" for character in normalized_sha
        ):
            raise ValueError("plan_sha256 must be 64 lowercase hexadecimal characters")
        path = self.plans_root / f"{normalized_id}.json"
        plan = json.loads(path.read_text(encoding="utf-8"))
        observed_sha = str(plan.pop("plan_sha256", "")).lower()
        recomputed = _plan_sha256(plan)
        if observed_sha != recomputed or normalized_sha != recomputed:
            raise ValueError("plan digest mismatch")
        return {**plan, "plan_sha256": recomputed}

    def _preflight_execute(self, plan: dict[str, Any]) -> dict[str, Any] | None:
        if plan.get("schema_version") != PLAN_SCHEMA:
            return {"error_code": "PLAN_INVALID", "message": "unsupported plan schema"}
        if plan.get("disposition") not in ALLOWED_DISPOSITIONS:
            return {"error_code": "PLAN_INVALID", "message": "unsupported disposition"}
        if plan.get("classification") not in ALLOWED_CLASSIFICATIONS:
            return {"error_code": "PLAN_INVALID", "message": "unsupported classification"}
        if (
            plan.get("disposition") == "permanent"
            and plan.get("classification") not in PERMANENT_CLASSIFICATIONS
        ):
            return {"error_code": "PLAN_INVALID", "message": "invalid permanent classification"}
        rows = plan.get("targets")
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_TARGETS:
            return {"error_code": "PLAN_INVALID", "message": "invalid target count"}
        expires_at = datetime.fromisoformat(str(plan["expires_at"]).replace("Z", "+00:00"))
        if _utc_now() > expires_at:
            return {"error_code": "PLAN_EXPIRED", "message": "cleanup plan expired"}
        try:
            targets = [_normalize_exact_path(row["path"]) for row in rows]
        except (KeyError, TypeError, ValueError) as exc:
            return {"error_code": "PLAN_INVALID", "message": str(exc)}
        if len({os.path.normcase(str(path)) for path in targets}) != len(targets):
            return {"error_code": "PLAN_INVALID", "message": "duplicate targets"}
        for index, left in enumerate(targets):
            for right in targets[index + 1 :]:
                if _is_same_or_child(left, right) or _is_same_or_child(right, left):
                    return {"error_code": "PLAN_INVALID", "message": "overlapping targets"}
        missing = [str(path) for path in targets if not os.path.lexists(path)]
        if missing:
            return {"error_code": "PLAN_STALE", "message": "target is missing", "paths": missing}
        active_worktrees = self._active_git_worktrees(targets)
        for target in targets:
            protection = self._protection(target, active_worktrees)
            if protection:
                return {"path": str(target), **protection}
        consumers = self._active_consumers(targets)
        if consumers:
            return {"error_code": "ACTIVE_CONSUMER", "active_consumers": consumers}
        stale: list[dict[str, Any]] = []
        for row in plan["targets"]:
            current = _scan_tree(Path(row["path"]))
            differences = _snapshot_differences(row["snapshot"], current)
            if differences:
                stale.append({"path": row["path"], "differences": differences})
        if stale:
            return {
                "error_code": "PLAN_STALE",
                "message": "target changed after planning",
                "stale": stale,
            }
        return None

    def _execute_target(self, plan: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
        target = Path(row["path"])
        disposition = str(plan["disposition"])
        acl_repair_attempted = False
        acl_repair: dict[str, Any] | None = None
        destination: Path | None = None
        try:
            if disposition == "quarantine":
                destination_root = self._quarantine_root(target) / str(plan["plan_id"])
                destination_root.mkdir(parents=True, exist_ok=True)
                destination = destination_root / target.name
                if os.path.lexists(destination):
                    raise FileExistsError(f"quarantine destination already exists: {destination}")
                os.replace(_extended_path(target), _extended_path(destination))
            else:
                _remove_tree_without_following_reparse(target)
        except OSError as first_error:
            if _classify_os_error(first_error) != "ACL_DENIED":
                return {
                    "ok": False,
                    "path": str(target),
                    "error_code": _classify_os_error(first_error),
                    "winerror": getattr(first_error, "winerror", None),
                    "message": str(first_error),
                    "acl_repair_attempted": False,
                    "source_absent": not os.path.lexists(target),
                }
            acl_repair_attempted = True
            acl_repair = _repair_acl(target)
            if not acl_repair["ok"]:
                return {
                    "ok": False,
                    "path": str(target),
                    "error_code": str(acl_repair.get("error_code") or "ACL_REPAIR_FAILED"),
                    "message": str(first_error),
                    "acl_repair_attempted": True,
                    "acl_repair": acl_repair,
                    "source_absent": not os.path.lexists(target),
                }
            try:
                if disposition == "quarantine":
                    assert destination is not None
                    os.replace(_extended_path(target), _extended_path(destination))
                else:
                    _remove_tree_without_following_reparse(target)
            except OSError as retry_error:
                return {
                    "ok": False,
                    "path": str(target),
                    "error_code": _classify_os_error(retry_error),
                    "winerror": getattr(retry_error, "winerror", None),
                    "message": str(retry_error),
                    "acl_repair_attempted": True,
                    "acl_repair": acl_repair,
                    "source_absent": not os.path.lexists(target),
                }
        return {
            "ok": not os.path.lexists(target),
            "path": str(target),
            "disposition": disposition,
            "destination": str(destination) if destination else None,
            "acl_repair_attempted": acl_repair_attempted,
            "acl_repair": acl_repair,
            "source_absent": not os.path.lexists(target),
            "planned_bytes": int(row["snapshot"].get("byte_count") or 0),
        }

    def execute_cleanup(self, *, plan_id: str, plan_sha256: str) -> dict[str, Any]:
        try:
            normalized_id = str(plan_id or "").strip().lower()
            with _exclusive_lock(self.lock_root / f"{normalized_id}.lock"):
                receipt_path = self.receipts_root / f"{normalized_id}.json"
                if receipt_path.is_file():
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                    if receipt.get("plan_sha256") != str(plan_sha256).strip().lower():
                        raise ValueError("receipt plan digest mismatch")
                    if receipt.get("status") == "completed":
                        reappeared = [
                            str(row["path"])
                            for row in receipt.get("targets", [])
                            if os.path.lexists(str(row.get("path") or ""))
                        ]
                        if reappeared:
                            return {
                                "ok": False,
                                "status": "rejected",
                                "error_code": "TARGET_REAPPEARED",
                                "message": "a completed target was recreated; create a fresh plan",
                                "paths": reappeared,
                                "idempotent_replay": True,
                            }
                        return {**receipt, "idempotent_replay": True}
                plan = self._load_plan(normalized_id, plan_sha256)
                preflight = self._preflight_execute(plan)
                if preflight:
                    return {"ok": False, "status": "rejected", **preflight}
                drives = sorted({Path(row["path"]).drive.upper() for row in plan["targets"]})
                before_free = {drive: shutil.disk_usage(f"{drive}\\").free for drive in drives}
                results = [self._execute_target(plan, row) for row in plan["targets"]]
                after_free = {drive: shutil.disk_usage(f"{drive}\\").free for drive in drives}
                completed = all(
                    result.get("ok") and result.get("source_absent") for result in results
                )
                receipt: dict[str, Any] = {
                    "schema_version": RECEIPT_SCHEMA,
                    "plan_id": normalized_id,
                    "plan_sha256": plan["plan_sha256"],
                    "executed_at": _iso(_utc_now()),
                    "status": "completed" if completed else "partial",
                    "ok": completed,
                    "disposition": plan["disposition"],
                    "targets": results,
                    "disk_free_before": before_free,
                    "disk_free_after": after_free,
                    "disk_free_delta": {
                        drive: int(after_free[drive] - before_free[drive]) for drive in drives
                    },
                    "idempotent_replay": False,
                }
                _atomic_write_json(receipt_path, receipt)
                return receipt
        except FileNotFoundError as exc:
            return {
                "ok": False,
                "status": "rejected",
                "error_code": "PLAN_NOT_FOUND",
                "message": str(exc),
            }
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "ok": False,
                "status": "rejected",
                "error_code": "EXECUTION_INVALID",
                "message": str(exc),
            }
