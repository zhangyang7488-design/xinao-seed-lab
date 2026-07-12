"""Subprocess wrapper around amq.exe — no daemon, no network listener."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ..module_config import load_module_config

DEFAULT_AMQ_BIN = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\amq\bin\amq.exe")
DEFAULT_CANARY_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary")
DEFAULT_CANARY_AMQ = DEFAULT_CANARY_ROOT / "amq"
DEFAULT_AGENTS = ("admin", "codex", "grok", "user")
QUARANTINE_DIRNAME = "quarantine"
DEAD_LETTER_DIRNAME = "dead-letter"


def amq_policy() -> dict[str, object]:
    config, provenance = load_module_config("amq")
    mailbox = config.get("mailbox", {}) if isinstance(config.get("mailbox"), dict) else {}
    paths = mailbox.get("paths", {}) if isinstance(mailbox.get("paths"), dict) else {}
    amq = mailbox.get("amq", {}) if isinstance(mailbox.get("amq"), dict) else {}
    return {
        "enabled": mailbox.get("enabled", True) is True,
        "auto_promote": False,
        "max_payload_bytes": int(mailbox.get("max_payload_bytes") or 1_048_576),
        "canary_state_root": str(paths.get("canary_state_root") or DEFAULT_CANARY_ROOT),
        "root": str(paths.get("root") or DEFAULT_CANARY_AMQ),
        "bin": str(amq.get("bin") or DEFAULT_AMQ_BIN),
        "version_pinned": str(amq.get("version_pinned") or ""),
        "sha256": str(amq.get("sha256") or ""),
        "license": str(amq.get("license") or ""),
        "config_provenance": provenance,
    }


def default_amq_bin() -> Path:
    env = os.environ.get("XINAO_AMQ_BIN") or os.environ.get("AMQ")
    return Path(env) if env else Path(str(amq_policy()["bin"]))


def default_canary_root() -> Path:
    env = os.environ.get("XINAO_COORD_CANARY_ROOT")
    return Path(env) if env else Path(str(amq_policy()["canary_state_root"]))


def default_canary_amq_root() -> Path:
    env = os.environ.get("XINAO_AMQ_ROOT")
    return Path(env) if env else Path(str(amq_policy()["root"]))


class AmqTransportError(RuntimeError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class AmqTransport:
    """Thin CLI adapter. Business rules stay in CoordinationService."""

    def __init__(
        self,
        *,
        bin_path: str | Path | None = None,
        root: str | Path | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.bin_path = Path(bin_path) if bin_path else default_amq_bin()
        self.root = Path(root) if root else default_canary_amq_root()
        self.timeout_seconds = timeout_seconds

    @property
    def quarantine_root(self) -> Path:
        return self.root / QUARANTINE_DIRNAME

    @property
    def dead_letter_root(self) -> Path:
        return self.root / DEAD_LETTER_DIRNAME

    def ensure_layout(self, agents: list[str] | tuple[str, ...] = DEFAULT_AGENTS) -> dict[str, Any]:
        """Ensure canary spool layout: AMQ init + quarantine/dead-letter isolation dirs."""
        self.root.mkdir(parents=True, exist_ok=True)
        init_result = self.init(list(agents), force=False)
        for name in (QUARANTINE_DIRNAME, DEAD_LETTER_DIRNAME):
            (self.root / name).mkdir(parents=True, exist_ok=True)
            for sub in ("tmp", "new", "cur"):
                (self.root / name / sub).mkdir(parents=True, exist_ok=True)
        meta = self.root / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        return {
            "ok": True,
            "root": str(self.root),
            "quarantine": str(self.quarantine_root),
            "dead_letter": str(self.dead_letter_root),
            "agents": list(agents),
            "init": init_result,
        }

    def write_quarantine(
        self,
        *,
        reason: str,
        raw: dict[str, Any],
        details: dict[str, Any] | None = None,
    ) -> Path:
        """Atomically park a rejected raw message under quarantine/new (isolation, not kernel)."""
        message_id = str(
            raw.get("id") or raw.get("message_id") or (details.get("message_id") if details else "") or ""
        )
        if not message_id:
            message_id = f"unknown-{os.getpid()}-{id(raw)}"
        # Strip path-like characters for safe filename.
        safe = re_safe_filename(message_id)
        quarantine_new = self.quarantine_root / "new"
        quarantine_tmp = self.quarantine_root / "tmp"
        quarantine_new.mkdir(parents=True, exist_ok=True)
        quarantine_tmp.mkdir(parents=True, exist_ok=True)
        payload = {
            "reason": reason,
            "isolated_at_utc": _utc_now(),
            "message_id": message_id,
            "details": details or {},
            "raw": raw,
            "kernel_written": False,
        }
        tmp_path = quarantine_tmp / f"{safe}.json"
        final_path = quarantine_new / f"{safe}.json"
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        tmp_path.write_text(text, encoding="utf-8")
        # Atomic replace into new/
        os.replace(tmp_path, final_path)
        return final_path

    def _run(self, args: list[str], *, expect_json: bool = True) -> Any:
        if not self.bin_path.is_file():
            raise AmqTransportError(
                "amq binary missing",
                details={"bin": str(self.bin_path)},
            )
        cmd = [str(self.bin_path), *args]
        child_env = os.environ.copy()
        # amq >= 0.42 rejects a --root that differs from inherited AM_ROOT unless
        # cross-tree routing is explicit. This adapter represents one local tree,
        # so bind the child process to that same tree without mutating parent env.
        child_env["AM_ROOT"] = str(self.root)
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                env=child_env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise AmqTransportError("amq command timed out", details={"cmd": cmd}) from exc
        if completed.returncode != 0:
            raise AmqTransportError(
                "amq command failed",
                details={
                    "cmd": cmd,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout[-2000:],
                    "stderr": completed.stderr[-2000:],
                },
            )
        stdout = completed.stdout.strip()
        if not expect_json:
            return {"ok": True, "stdout": stdout, "stderr": completed.stderr}
        if not stdout:
            return None
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            # Some commands emit one JSON object per line.
            lines = [line for line in stdout.splitlines() if line.strip()]
            parsed: list[Any] = []
            for line in lines:
                try:
                    parsed.append(json.loads(line))
                except json.JSONDecodeError:
                    return {"ok": True, "raw": stdout}
            if len(parsed) == 1:
                return parsed[0]
            return parsed

    def version(self) -> str:
        result = self._run(["--version"], expect_json=False)
        return str(result.get("stdout", "")).strip()

    def init(self, agents: list[str], *, force: bool = False) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        args = ["init", "--root", str(self.root), "--agents", ",".join(agents)]
        if force:
            args.append("--force")
        try:
            return self._run(args, expect_json=False)
        except AmqTransportError as exc:
            # Existing root without --force is acceptable for canary re-entry.
            stderr = str((exc.details or {}).get("stderr") or "")
            stdout = str((exc.details or {}).get("stdout") or "")
            if not force and ("already" in (stderr + stdout).lower() or "exist" in (stderr + stdout).lower()):
                return {"ok": True, "stdout": stdout, "stderr": stderr, "already_initialized": True}
            raise

    def send(
        self,
        *,
        me: str,
        to: str,
        body: str,
        subject: str = "",
        kind: str = "status",
        thread: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        args = [
            "send",
            "--root",
            str(self.root),
            "--me",
            me,
            "--to",
            to,
            "--kind",
            kind,
            "--body",
            body,
            "--json",
        ]
        if subject:
            args.extend(["--subject", subject])
        if thread:
            args.extend(["--thread", thread])
        if context:
            args.extend(["--context", json.dumps(context, ensure_ascii=False, separators=(",", ":"))])
        result = self._run(args, expect_json=True)
        if not isinstance(result, dict):
            raise AmqTransportError("unexpected send response", details={"result": result})
        return result

    def list_new(self, *, me: str) -> list[dict[str, Any]]:
        result = self._run(
            ["list", "--root", str(self.root), "--me", me, "--new", "--json"],
            expect_json=True,
        )
        return _as_message_list(result)

    def list_cur(self, *, me: str) -> list[dict[str, Any]]:
        result = self._run(
            ["list", "--root", str(self.root), "--me", me, "--cur", "--json"],
            expect_json=True,
        )
        return _as_message_list(result)

    def drain(self, *, me: str, include_body: bool = True, limit: int = 20) -> list[dict[str, Any]]:
        args = [
            "drain",
            "--root",
            str(self.root),
            "--me",
            me,
            "--limit",
            str(limit),
            "--json",
        ]
        if include_body:
            args.append("--include-body")
        result = self._run(args, expect_json=True)
        return _as_message_list(result)

    def read(self, *, me: str, message_id: str) -> dict[str, Any]:
        result = self._run(
            ["read", "--root", str(self.root), "--me", me, "--id", message_id, "--json"],
            expect_json=True,
        )
        if not isinstance(result, dict):
            raise AmqTransportError("unexpected read response", details={"result": result})
        return result


def _as_message_list(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        for key in ("messages", "items", "new", "cur", "drained"):
            value = result.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        # Single message object
        if "id" in result or "message_id" in result:
            return [result]
        if result.get("count") == 0:
            return []
    return []


def re_safe_filename(message_id: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-@" else "_" for ch in message_id)
    return cleaned[:180] or "unknown"


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
