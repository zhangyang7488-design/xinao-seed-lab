from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_REPO_ROOT = Path(r"E:\XINAO_RESEARCH_WORKSPACES\S")
RECOVERY_ROOT = REPO_ROOT / "infra" / "codex_productivity_recovery"
LEGACY_V1_ROOT = RECOVERY_ROOT / "v1"
DEFAULT_OUTPUT_ROOT = RECOVERY_ROOT / "v2"
ARCHIVE_NAME = "codex-productivity-recovery.non-pi.v2.zip"
MANIFEST_NAME = "manifest.v2.json"

MAIN_HOME = Path(r"C:\Users\xx363\.codex")
ACCOUNT_B_HOME = Path(r"C:\Users\xx363\.codex-s-hardmode-account-b")
LAUNCHER_ROOT = Path(r"C:\Users\xx363\CodexLaunchers")
SITUATION_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island")
STABLE_MAIN_ENTRY = Path(
    r"C:\Users\xx363\Desktop\主线\00_先读我_主线入口与读取顺序.txt"
)
GROK_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\grok-worker-pool")
GROK_RUNTIME_MANIFEST = GROK_RUNTIME_ROOT / "runtime-manifest.v1.json"
GROK_BRIDGE_ROOT = GROK_RUNTIME_ROOT / "bridge"

NON_PI_GENERIC_SKILLS = (
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
    "research-external-reality",
    "verified-agent-loop",
)

# Product-specific Pi stewardship is deliberately outside this archive's effect
# scope.  Keep the name here only as a fail-closed inventory boundary: build,
# verify-live, and restore never enumerate or read that tree.
EXCLUDED_PRODUCT_SKILL_TREES = ("steward-pis-evolution",)
EXCLUDED_ARCHIVE_PREFIXES = tuple(
    f"main-home/skills/{skill_name}/" for skill_name in EXCLUDED_PRODUCT_SKILL_TREES
)

MAIN_FILES = (
    "AGENTS.md",
    "config.toml",
    "hooks.json",
    "cold-capabilities.config.toml",
    "native-collaboration.config.toml",
    "inner-luna.config.toml",
    "inner-terra.config.toml",
    "inner-sol-verifier.config.toml",
    "agents/luna-worker.toml",
)

LAUNCHER_FILES = ("CODEX_PRODUCTIVITY_PROFILE.md",)

GROK_OPERATOR_SOURCES = (
    (
        LAUNCHER_ROOT / "Invoke-Codex-GrokWorkerPool.ps1",
        "launchers/Invoke-Codex-GrokWorkerPool.ps1",
        "grok_worker_pool_public_launcher",
    ),
    (
        LAUNCHER_ROOT / "Invoke-GrokWorkerOAuthRecovery.ps1",
        "launchers/Invoke-GrokWorkerOAuthRecovery.ps1",
        "grok_worker_pool_oauth_recovery_entry",
    ),
    (
        LAUNCHER_ROOT / "CODEX_GROK_WORKER_POOL_DEFAULT.md",
        "contracts/CODEX_GROK_WORKER_POOL_DEFAULT.md",
        "grok_worker_pool_operator_contract",
    ),
)

SHARED_RUNTIME_SOURCES = (
    (
        REPO_ROOT / "scripts" / "Open-Codex-S-SharedRuntime.ps1",
        "launchers/Open-Codex-S-SharedRuntime.ps1",
        "canonical_shared_runtime_launcher",
    ),
    (
        REPO_ROOT / "scripts" / "launchers" / "Open-Codex-S-Hardmode.ps1",
        "launchers/Open-Codex-S-Hardmode.ps1",
        "credential_a_compatibility_entry",
    ),
    (
        REPO_ROOT / "scripts" / "launchers" / "Open-Codex-S-Hardmode-Account-B.ps1",
        "launchers/Open-Codex-S-Hardmode-Account-B.ps1",
        "credential_b_compatibility_entry",
    ),
    (
        REPO_ROOT / "docs" / "tool_glue" / "CODEX_SHARED_RUNTIME_ACCOUNT_SLOTS_CURRENT.md",
        "contracts/CODEX_SHARED_RUNTIME_ACCOUNT_SLOTS_CURRENT.md",
        "shared_runtime_credential_boundary",
    ),
)

INSTALLED_ENTRY_LINKS = (
    (
        LAUNCHER_ROOT / "Open-Codex-S-Hardmode.ps1",
        LIVE_REPO_ROOT / "scripts" / "launchers" / "Open-Codex-S-Hardmode.ps1",
    ),
    (
        LAUNCHER_ROOT / "Open-Codex-S-Hardmode-Account-B.ps1",
        LIVE_REPO_ROOT / "scripts" / "launchers" / "Open-Codex-S-Hardmode-Account-B.ps1",
    ),
)

SITUATION_FILES = {
    "README.md": "situation_island_contract",
    "scripts/manage_explicit_continuation_locator_v1.ps1": (
        "on_demand_explicit_continuation_consumer"
    ),
    "scripts/bind_active_task_continuation_v1.ps1": "cold_continuity_repair_material",
    "scripts/restore_parent_task_continuation_v1.ps1": "cold_continuity_repair_material",
    "scripts/session_start_continuity_pointer_v1.ps1": "cold_continuity_repair_material",
    "scripts/turn_finalization_gate_v1.ps1": "cold_continuity_repair_material",
    "scripts/user_prompt_zero_beat_v1.ps1": "active_user_prompt_hook",
}

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

    for skill_name in NON_PI_GENERIC_SKILLS:
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

    for source, archive_path, role in SHARED_RUNTIME_SOURCES:
        entries.append(
            SourceEntry(
                source=source,
                archive_path=archive_path,
                role=role,
            )
        )

    for source, archive_path, role in GROK_OPERATOR_SOURCES:
        entries.append(
            SourceEntry(
                source=source,
                archive_path=archive_path,
                role=role,
            )
        )

    runtime_manifest = json.loads(GROK_RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    if runtime_manifest.get("schema_version") != "xinao.grok_worker_pool_runtime_manifest.v1":
        raise ValueError("Grok WorkerPool runtime manifest schema mismatch")
    declared_bridge = Path(str(runtime_manifest.get("bridge_root", "")))
    if declared_bridge.resolve() != GROK_BRIDGE_ROOT.resolve():
        raise ValueError("Grok WorkerPool runtime manifest bridge root mismatch")
    runtime_files = runtime_manifest.get("files")
    if not isinstance(runtime_files, list) or len(runtime_files) != 15:
        raise ValueError("Grok WorkerPool runtime manifest must declare 15 exact files")
    entries.append(
        SourceEntry(
            source=GROK_RUNTIME_MANIFEST,
            archive_path="runtime/grok-worker-pool/runtime-manifest.v1.json",
            role="grok_worker_pool_runtime_manifest",
        )
    )
    seen_runtime_paths: set[str] = set()
    for item in runtime_files:
        if not isinstance(item, dict):
            raise ValueError("Grok WorkerPool runtime manifest file entry must be an object")
        relative_text = str(item.get("path", ""))
        relative = PurePosixPath(relative_text)
        if (
            not relative_text
            or relative.is_absolute()
            or len(relative.parts) != 1
            or relative.parts[0] in {".", ".."}
            or relative_text in seen_runtime_paths
        ):
            raise ValueError(f"unsafe or duplicate Grok runtime path: {relative_text!r}")
        seen_runtime_paths.add(relative_text)
        source = GROK_BRIDGE_ROOT / relative_text
        expected_sha256 = str(item.get("sha256", "")).lower()
        if len(expected_sha256) != 64 or _sha256_file(source) != expected_sha256:
            raise ValueError(f"Grok runtime source does not match sealed manifest: {relative_text}")
        entries.append(
            SourceEntry(
                source=source,
                archive_path=PurePosixPath(
                    "runtime", "grok-worker-pool", "bridge", relative_text
                ).as_posix(),
                role="grok_worker_pool_sealed_transport",
            )
        )

    for relative, role in SITUATION_FILES.items():
        source = SITUATION_ROOT / Path(relative)
        entries.append(
            SourceEntry(
                source=source,
                archive_path=PurePosixPath(
                    "runtime", "Codex_Situation_Island", *Path(relative).parts
                ).as_posix(),
                role=role,
            )
        )

    entries.append(
        SourceEntry(
            source=STABLE_MAIN_ENTRY,
            archive_path="human-entries/00_先读我_主线入口与读取顺序.txt",
            role="stable_human_reentry_entry",
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
    if output_root.resolve() == LEGACY_V1_ROOT.resolve():
        raise ValueError(
            "legacy v1 recovery media is immutable; build the scoped non-Pi v2 package"
        )
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
        "schema_version": "xinao.codex_productivity_recovery.v2",
        "sentinel": "SENTINEL:CODEX_NON_PI_PRODUCTIVITY_RECOVERY_COLD_V2",
        "authority": False,
        "runtime_loaded": False,
        "completion_claim_allowed": False,
        "effect_scope": {
            "id": "codex_non_pi_productivity_runtime",
            "self_contained": True,
            "excluded_product_skill_trees": list(EXCLUDED_PRODUCT_SKILL_TREES),
            "excluded_trees_are_not_read_verified_or_restored": True,
        },
        "archive": ARCHIVE_NAME,
        "archive_sha256": _sha256_file(archive_path),
        "entry_count": len(manifest_entries),
        "entries": manifest_entries,
        "source_and_projection": {
            "main_home_is_canonical_shared_runtime_source": True,
            "account_b_credential_home_links_to_shared_runtime": True,
            "account_b_is_not_a_configuration_or_recovery_source": True,
            "cold_archive_is_immutable_recovery_media_not_a_second_runtime_truth": True,
            "legacy_v1_is_separate_history_not_a_build_input": True,
            "grok_worker_pool_live_manifest_is_the_runtime_truth": True,
            "local_docker_is_exception_only_not_a_default_runtime_dependency": True,
            "dated_worker_pool_recovery_snapshots_are_not_current_sources": True,
            "live_continuation_locator_is_not_a_recovery_source": True,
        },
        "excluded_on_purpose": [
            "authentication credentials and refresh tokens",
            "live explicit-continuation locator and live task runs",
            "sessions transcripts and memory data",
            "plugin caches and reinstallable bundled or curated plugins",
            "conduct-xinao-native-research and all science-domain authority",
            "retired pretool_task_provenance_guard_v1.ps1",
            "legacy platform control planes and runtime state",
            (
                "steward-pis-evolution and its complete product-specific tree; "
                "Pi is frozen outside this non-Pi effect scope"
            ),
        ],
        "science_boundary": {
            "science_domain_authority_owner": "E:/XINAO_RESEARCH_WORKSPACES/xinao-native-research",
            "restore_into_s_or_global_generic_router": False,
            "retired_science_routing_remains_retired": True,
        },
        "recovery_contract": {
            "automatic_live_restore": False,
            "staged_restore_supported": True,
            "legacy_v1_must_not_be_refreshed_or_used_as_a_source": True,
            "owner_must_verify_exact_targets_backup_and_live_consumers_before_apply": True,
            "account_b_auth_and_sessions_must_never_be_copied_from_main": True,
            "required_post_apply_readback": [
                "B shared file and directory links resolve to the canonical main runtime",
                "A/B credential files and active session state remain private",
                "fresh app-server hooks/list trust from each installed account",
                "changed-context positive and negative behavior consumer",
                "Grok public launcher verifies the restored 15-file runtime manifest",
                "fresh SelectionOnly succeeds before any real Grok dispatch",
                "fresh common read-only dispatch uses a disposable host worktree while Docker is stopped",
            ],
            "selector_release_rebuild_source": (
                "the current S repository plus pyproject.toml and uv.lock; "
                "a dated recovery snapshot or ambient Python is not a selector source"
            ),
        },
    }
    manifest_path = output_root / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _load_manifest(output_root: Path) -> dict[str, object]:
    manifest = json.loads((output_root / MANIFEST_NAME).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "xinao.codex_productivity_recovery.v2":
        raise ValueError("non-Pi recovery manifest schema mismatch")
    scope = manifest.get("effect_scope")
    if not isinstance(scope, dict) or scope.get("id") != "codex_non_pi_productivity_runtime":
        raise ValueError("non-Pi recovery effect scope mismatch")
    return manifest


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
        *EXCLUDED_ARCHIVE_PREFIXES,
        "pretool_task_provenance_guard_v1.ps1",
        "auth.json",
        "/sessions/",
        "/memories/",
    )
    lowered = "\n".join(expected).lower()
    for forbidden in forbidden_paths:
        if forbidden.lower() in lowered:
            raise ValueError(f"forbidden recovery entry present: {forbidden}")
    lowered_live_sources = "\n".join(
        str(row.get("live_source", "")) for row in manifest["entries"]
    ).lower()
    for skill_name in EXCLUDED_PRODUCT_SKILL_TREES:
        windows_fragment = f"\\skills\\{skill_name}\\"
        posix_fragment = f"/skills/{skill_name}/"
        if windows_fragment in lowered_live_sources or posix_fragment in lowered_live_sources:
            raise ValueError(f"excluded product live source present: {skill_name}")
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

    shared_files = (
        "AGENTS.md",
        "config.toml",
        "hooks.json",
        *sorted(path.name for path in MAIN_HOME.glob("*.config.toml")),
    )
    for relative in dict.fromkeys(shared_files):
        main = MAIN_HOME / relative
        account_b = ACCOUNT_B_HOME / relative
        if not account_b.is_symlink():
            raise ValueError(f"B shared file is not a direct link: {account_b}")
        if account_b.resolve(strict=True) != main.resolve(strict=True):
            raise ValueError(f"B shared file link target drift: {account_b}")

    for relative in ("agents", "skills", "rules", "plugins"):
        main = MAIN_HOME / relative
        account_b = ACCOUNT_B_HOME / relative
        is_link = account_b.is_symlink() or (
            hasattr(account_b, "is_junction") and account_b.is_junction()
        )
        if not is_link:
            raise ValueError(f"B shared directory is not a direct link: {account_b}")
        if account_b.resolve(strict=True) != main.resolve(strict=True):
            raise ValueError(f"B shared directory link target drift: {account_b}")

    for installed, canonical in INSTALLED_ENTRY_LINKS:
        if not installed.is_symlink():
            raise ValueError(f"installed credential entry is not a direct link: {installed}")
        if installed.resolve(strict=True) != canonical.resolve(strict=True):
            raise ValueError(f"installed credential entry link target drift: {installed}")
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
