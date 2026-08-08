from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "infra" / "codex_productivity_recovery" / "v1"
ARCHIVE_NAME = "codex-productivity-recovery.v1.zip"
MANIFEST_NAME = "manifest.v1.json"

MAIN_HOME = Path(r"C:\Users\xx363\.codex")
ACCOUNT_B_HOME = Path(r"C:\Users\xx363\.codex-s-hardmode-account-b")
LAUNCHER_ROOT = Path(r"C:\Users\xx363\CodexLaunchers")
SITUATION_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island")

GENERIC_SKILLS = (
    "amplify-supervisor-worker",
    "ast-grep-structural-search",
    "dispatch-grok-worker-pool",
    "dispatch-luna-worker-pool",
    "dispatch-terra-worker-pool",
    "human-agency-grounding",
    "maintain-personal-decision-model",
    "mcp-inspector-admission",
    "operate-for-user",
    "playwright-cli",
    "productivity",
    "promptfoo-agent-evals",
    "repair-agent-behavior",
    "verified-agent-loop",
)

MAIN_FILES = (
    "AGENTS.md",
    "config.toml",
    "hooks.json",
    "cold-capabilities.config.toml",
    "inner-luna.config.toml",
    "inner-terra.config.toml",
    "inner-sol-verifier.config.toml",
    "agents/luna-worker.toml",
)

LAUNCHER_FILES = (
    "Open-Codex-S-Hardmode.ps1",
    "Open-Codex-S-Hardmode-Account-B.ps1",
    "CODEX_PRODUCTIVITY_PROFILE.md",
)

SITUATION_FILES = (
    "README.md",
    "scripts/bind_active_task_continuation_v1.ps1",
    "scripts/restore_parent_task_continuation_v1.ps1",
    "scripts/session_start_continuity_pointer_v1.ps1",
    "scripts/turn_finalization_gate_v1.ps1",
    "scripts/user_prompt_zero_beat_v1.ps1",
)

EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".key", ".secret"}


@dataclass(frozen=True)
class SourceEntry:
    source: Path
    archive_path: str
    role: str


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _allowed_relative_file(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    return path.is_file()


def _collect_sources() -> list[SourceEntry]:
    entries: list[SourceEntry] = []
    for relative in MAIN_FILES:
        source = MAIN_HOME / Path(relative)
        entries.append(
            SourceEntry(
                source=source,
                archive_path=PurePosixPath("main-home", *Path(relative).parts).as_posix(),
                role="main_live_source",
            )
        )

    for skill_name in GENERIC_SKILLS:
        skill_root = MAIN_HOME / "skills" / skill_name
        if not skill_root.is_dir():
            raise FileNotFoundError(f"generic skill is missing: {skill_root}")
        for source in sorted(skill_root.rglob("*"), key=lambda item: str(item).lower()):
            if not _allowed_relative_file(source, skill_root):
                continue
            relative = source.relative_to(skill_root)
            entries.append(
                SourceEntry(
                    source=source,
                    archive_path=PurePosixPath(
                        "main-home", "skills", skill_name, *relative.parts
                    ).as_posix(),
                    role="generic_custom_skill",
                )
            )

    for relative in LAUNCHER_FILES:
        source = LAUNCHER_ROOT / relative
        entries.append(
            SourceEntry(
                source=source,
                archive_path=PurePosixPath("launchers", relative).as_posix(),
                role="launcher_or_profile",
            )
        )

    for relative in SITUATION_FILES:
        source = SITUATION_ROOT / Path(relative)
        entries.append(
            SourceEntry(
                source=source,
                archive_path=PurePosixPath(
                    "runtime", "Codex_Situation_Island", *Path(relative).parts
                ).as_posix(),
                role="continuity_runtime",
            )
        )

    missing = [str(entry.source) for entry in entries if not entry.source.is_file()]
    if missing:
        raise FileNotFoundError("recovery sources are missing: " + "; ".join(missing))
    archive_paths = [entry.archive_path for entry in entries]
    if len(archive_paths) != len(set(archive_paths)):
        raise ValueError("duplicate archive paths in recovery source inventory")
    return sorted(entries, key=lambda entry: entry.archive_path)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build(output_root: Path) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    archive_path = output_root / ARCHIVE_NAME
    entries = _collect_sources()
    manifest_entries: list[dict[str, object]] = []
    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for entry in entries:
            content = entry.source.read_bytes()
            archive.writestr(_zip_info(entry.archive_path), content)
            manifest_entries.append(
                {
                    "archive_path": entry.archive_path,
                    "live_source": str(entry.source),
                    "role": entry.role,
                    "size": len(content),
                    "sha256": _sha256_bytes(content),
                }
            )

    manifest: dict[str, object] = {
        "schema_version": "xinao.codex_productivity_recovery.v1",
        "sentinel": "SENTINEL:CODEX_PRODUCTIVITY_RECOVERY_COLD_V1",
        "authority": False,
        "runtime_loaded": False,
        "completion_claim_allowed": False,
        "archive": ARCHIVE_NAME,
        "archive_sha256": _sha256_file(archive_path),
        "entry_count": len(manifest_entries),
        "entries": manifest_entries,
        "source_and_projection": {
            "main_home_is_live_source": True,
            "account_b_is_generated_projection": True,
            "cold_archive_is_immutable_recovery_media_not_a_second_runtime_truth": True,
        },
        "excluded_on_purpose": [
            "authentication credentials and refresh tokens",
            "sessions transcripts and memory data",
            "plugin caches and reinstallable bundled or curated plugins",
            "conduct-xinao-native-research and all science-domain authority",
            "retired pretool_task_provenance_guard_v1.ps1",
            "legacy platform control planes and runtime state",
        ],
        "science_boundary": {
            "science_domain_authority_owner": "E:/XINAO_RESEARCH_WORKSPACES/xinao-native-research",
            "restore_into_s_or_global_generic_router": False,
            "retired_science_routing_remains_retired": True,
        },
        "recovery_contract": {
            "automatic_live_restore": False,
            "staged_restore_supported": True,
            "owner_must_verify_exact_targets_backup_and_live_consumers_before_apply": True,
            "account_b_auth_and_sessions_must_never_be_copied_from_main": True,
            "required_post_apply_readback": [
                "A/B projection equality for AGENTS hooks and cold capability overlay",
                "fresh app-server hooks/list trust from each installed account",
                "changed-context positive and negative behavior consumer",
            ],
        },
    }
    manifest_path = output_root / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _load_manifest(output_root: Path) -> dict[str, object]:
    return json.loads((output_root / MANIFEST_NAME).read_text(encoding="utf-8"))


def verify_archive(output_root: Path) -> dict[str, object]:
    manifest = _load_manifest(output_root)
    archive_path = output_root / str(manifest["archive"])
    if _sha256_file(archive_path) != manifest["archive_sha256"]:
        raise ValueError("recovery archive SHA256 mismatch")
    expected = {str(entry["archive_path"]): entry for entry in manifest["entries"]}
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("recovery archive entry inventory mismatch")
        for name in names:
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise ValueError(f"unsafe archive path: {name}")
            content = archive.read(name)
            row = expected[name]
            if len(content) != row["size"]:
                raise ValueError(f"recovery entry size mismatch: {name}")
            if _sha256_bytes(content) != row["sha256"]:
                raise ValueError(f"recovery entry SHA256 mismatch: {name}")

    forbidden_paths = (
        "conduct-xinao-native-research",
        "pretool_task_provenance_guard_v1.ps1",
        "auth.json",
        "/sessions/",
        "/memories/",
    )
    lowered = "\n".join(expected).lower()
    for forbidden in forbidden_paths:
        if forbidden.lower() in lowered:
            raise ValueError(f"forbidden recovery entry present: {forbidden}")
    return manifest


def verify_live(output_root: Path) -> dict[str, object]:
    manifest = verify_archive(output_root)
    for row in manifest["entries"]:
        source = Path(str(row["live_source"]))
        if not source.is_file():
            raise FileNotFoundError(f"live recovery source is missing: {source}")
        if source.stat().st_size != row["size"]:
            raise ValueError(f"live source size drift: {source}")
        if _sha256_file(source) != row["sha256"]:
            raise ValueError(f"live source SHA256 drift: {source}")

    for relative in (
        "AGENTS.md",
        "hooks.json",
        "cold-capabilities.config.toml",
    ):
        main = MAIN_HOME / relative
        account_b = ACCOUNT_B_HOME / relative
        if _sha256_file(main) != _sha256_file(account_b):
            raise ValueError(f"A/B projection drift: {relative}")
    return manifest


def restore_to(output_root: Path, target: Path) -> dict[str, object]:
    manifest = verify_archive(output_root)
    if target.exists() and any(target.iterdir()):
        raise ValueError(f"restore target must be absent or empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    archive_path = output_root / str(manifest["archive"])
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(target)
    for row in manifest["entries"]:
        restored = target / Path(*PurePosixPath(str(row["archive_path"])).parts)
        if _sha256_file(restored) != row["sha256"]:
            raise ValueError(f"restored entry SHA256 mismatch: {restored}")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("build", "verify-archive", "verify-live", "restore-to"),
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--target", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.action == "build":
        result = build(args.output_root)
    elif args.action == "verify-archive":
        result = verify_archive(args.output_root)
    elif args.action == "verify-live":
        result = verify_live(args.output_root)
    else:
        if args.target is None:
            raise ValueError("--target is required for restore-to")
        result = restore_to(args.output_root, args.target)
    print(
        json.dumps(
            {
                "ok": True,
                "action": args.action,
                "entry_count": result["entry_count"],
                "archive_sha256": result["archive_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"CODEX_PRODUCTIVITY_RECOVERY_ERROR: {error}", file=sys.stderr)
        raise
