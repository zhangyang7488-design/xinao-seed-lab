"""Wave87: historical pre_modules sealed generation for forward-upgrade.

Live gen6 active (researcher-1.2.1-a8be2b624f891038) seals:
  source_identity = base5 + shadow_runtime_tree/lock (no modules/tool fields)
  image_labels    = pre-shadow labels + shadow tree/lock (no modules/episode)
  skill_hashes    = current set including shadow_runtime_lock_sha256
  top-level       = transport-only PRE_TOOL_IMAGE_RELEASE_KEYS

This generation is readable only via generation-aware sealed validation for
forward-upgrade / restore / terminal journal history. Ordinary exact-current
validation and bootstrap-migrate continue to reject it. PREPARED / CAS switch
targets remain exact-current dual-image only.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "xinao"

# Live gen6 release observed by Wave84C2 (read-only source; tests copy into tmp state).
LIVE_GEN6_RELEASE_ID = "researcher-1.2.1-a8be2b624f891038"
LIVE_GEN6_RELEASE_DIR = (
    Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill\researcher_container\releases")
    / LIVE_GEN6_RELEASE_ID
)
LIVE_GEN6_RELEASE_JSON_SHA256 = "21b712aba72da3e1a24de5347cf7a301ba07afadc479e22d608ca1ee836a734f"
LIVE_GEN17_SHADOW_RUNTIME_LOCK_SHA256 = (
    "0919d1275322f87919e94418428cbf8bb824e64434235e766f84ecb9387eb235"
)
LIVE_GEN17_SHADOW_RUNTIME_TREE_SHA256 = (
    "da94969e338e6105074be9c5b6c47fb6a99db2d7192b7d8756f24960bd75fa19"
)
LIVE_GEN17_SHADOW_RUNTIME_LOCK_FIXTURE = (
    ROOT / "tests" / "fixtures" / "xinao" / "live_gen17_shadow_runtime_lock.v1.json"
)
LIVE_GEN6_SI_KEYS = frozenset(
    {
        "source_commit",
        "source_tree",
        "source_dirty",
        "grok_donor_image_id",
        "grok_donor_binary_sha256",
        "shadow_runtime_tree_sha256",
        "shadow_runtime_lock_sha256",
    }
)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module():
    return _load_module(SKILL_ROOT / "scripts" / "xinao_runtime.py", "xinao_runtime_hist_gen")


def _bootstrap_module():
    return _load_module(SKILL_ROOT / "scripts" / "xinao.py", "xinao_bootstrap_hist_gen")


def _live_gen17_shadow_lock_payload() -> bytes:
    payload = LIVE_GEN17_SHADOW_RUNTIME_LOCK_FIXTURE.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == LIVE_GEN17_SHADOW_RUNTIME_LOCK_SHA256
    return payload


def test_source_shadow_seal_generation_advances_past_live_gen17() -> None:
    """Changed shadow-runtime bytes must mint a new lock/version generation.

    Live generation 17 sealed the pre-integration runtime tree above.  If the
    source inventory changes while the lock bytes stay identical, historical
    validation mistakes the current source rows for the old release generation
    and rejects the real release before forward-upgrade can build its successor.
    """

    module = _module()
    registry = json.loads(
        (SKILL_ROOT / "references" / "capabilities.v1.json").read_text(encoding="utf-8")
    )
    shadow = next(
        item
        for item in registry["capabilities"]
        if item["capability_id"] == "shadow-lifecycle-leg-a"
    )
    lock_path = SKILL_ROOT / "references" / "shadow-runtime-lock.v1.json"
    lock = module._load_shadow_runtime_lock(SKILL_ROOT)
    rows = module._collect_shadow_runtime_rows(ROOT, lock)

    assert lock["shadow_runtime_version"] == shadow["version"] == "0.3.2"
    assert module._sha256(lock_path) != LIVE_GEN17_SHADOW_RUNTIME_LOCK_SHA256
    assert module._shadow_runtime_tree_sha256(rows) != LIVE_GEN17_SHADOW_RUNTIME_TREE_SHA256


def _state(module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(state))
    monkeypatch.setenv("XINAO_RESEARCHER_RUN_ROOT", str(tmp_path / "runs"))
    lock = state / "researcher_container" / ".activation.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(b"\0")
    return state


def _pre_modules_skill_hashes(module, root: Path) -> dict[str, str]:
    keys = module.PRE_MODULES_SKILL_HASH_KEYS
    return module._reference_hashes_for_keys(root, keys)


def _sealed_pre_modules_v2_release(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    image_character: str = "a",
    package_version: str = "1.3.4",
    capability_version: str = "1.2.1",
    variant: bytes | None = None,
    shadow_tree: str | None = None,
    shadow_lock: str | None = None,
) -> tuple[dict[str, object], Path]:
    """Seal a historical pre_modules release matching live gen6 key sets."""

    state = _state(module, tmp_path, monkeypatch)
    source_rows = module._source_bundle_files(SKILL_ROOT)
    if variant is not None:
        source_rows.append(
            (
                "references/test-release-variant.txt",
                tmp_path / "unused-source-path",
                variant,
            )
        )
        source_rows.sort(key=lambda item: item[0])
    bundle_manifest = module._skill_bundle_manifest(source_rows, package_version=package_version)
    temp_bundle = tmp_path / f"pre-modules-bundle-{image_character}"
    if temp_bundle.exists():
        shutil.rmtree(temp_bundle)
    module._materialize_skill_bundle(temp_bundle, source_rows, bundle_manifest)
    hashes = _pre_modules_skill_hashes(module, temp_bundle)
    shadow_lock_hash = (
        shadow_lock if shadow_lock is not None else hashes["shadow_runtime_lock_sha256"]
    )
    if shadow_tree is not None:
        shadow_tree_hash = shadow_tree
    else:
        # Default: real shadow tree from source package rows (Wave91 A1b requires this).
        lock_obj = module._load_shadow_runtime_lock(SKILL_ROOT)
        shadow_rows = module._collect_shadow_runtime_rows(ROOT, lock_obj)
        shadow_tree_hash = module._shadow_runtime_tree_sha256(shadow_rows)
    source_identity = {
        "source_commit": "c" * 40,
        "source_tree": "d" * 40,
        "source_dirty": False,
        "grok_donor_image_id": "sha256:" + "b" * 64,
        "grok_donor_binary_sha256": "a" * 64,
        "shadow_runtime_tree_sha256": shadow_tree_hash,
        "shadow_runtime_lock_sha256": shadow_lock_hash,
    }
    assert set(source_identity) == set(module.PRE_MODULES_SOURCE_IDENTITY_KEYS)
    source_identity_sha256 = module._sha256_bytes(module._canonical_bytes(source_identity))
    image_id = "sha256:" + image_character * 64
    labels = {
        "io.xinao.researcher.chain": "dedicated-xinao-science",
        "io.xinao.researcher.generic-worker-route": "forbidden",
        "io.xinao.researcher.grok-donor-image-id": source_identity["grok_donor_image_id"],
        "io.xinao.researcher.grok-donor-binary.sha256": source_identity["grok_donor_binary_sha256"],
        "io.xinao.researcher.charter.sha256": hashes["charter_sha256"],
        "io.xinao.researcher.output-schema.sha256": hashes["output_schema_sha256"],
        "io.xinao.researcher.material-bundle-schema.sha256": hashes[
            "material_bundle_schema_sha256"
        ],
        "io.xinao.researcher.runtime-lock.sha256": hashes["runtime_lock_sha256"],
        "io.xinao.researcher.skill-invoker.sha256": hashes["skill_invoker_sha256"],
        "io.xinao.researcher.dockerfile.sha256": "1" * 64,
        "io.xinao.researcher.entrypoint.sha256": "2" * 64,
        "io.xinao.researcher.source-identity.sha256": source_identity_sha256,
        "io.xinao.researcher.shadow-runtime.sha256": shadow_tree_hash,
        "io.xinao.researcher.shadow-runtime-lock.sha256": shadow_lock_hash,
        "io.xinao.researcher.requested-model": "grok-4.5",
    }
    assert set(labels) == set(module.PRE_MODULES_IMAGE_LABEL_KEYS)
    manifest: dict[str, object] = {
        "schema_version": module.RELEASE_SCHEMA,
        "release_id": "pending",
        "package_version": package_version,
        "capability_id": "researcher-container",
        "capability_version": capability_version,
        "charter_version": capability_version,
        "runtime_version": capability_version,
        "release_identity_sha256": "pending",
        "source_identity": source_identity,
        "skill_bundle_path": "pending",
        "skill_bundle_manifest_path": "pending",
        "skill_bundle_manifest_sha256": "pending",
        "skill_bundle_tree_sha256": bundle_manifest["tree_sha256"],
        "image_tag_observational": "xinao-researcher:pre-modules-test",
        "image_id": image_id,
        "image_entrypoint": ["python", "-I", module.RESEARCHER_CANARY_ENTRYPOINT_IMAGE_PATH],
        "image_labels": labels,
        "skill_hashes": hashes,
        "required_bootstrap_protocol": 2,
        "generic_worker_route_allowed": False,
        "state_namespace": "xinao_skill/researcher_container",
        "run_namespace": "xinao_researcher",
    }
    assert set(manifest) == set(module.PRE_TOOL_IMAGE_RELEASE_KEYS)
    identity_sha256 = module._sha256_bytes(
        module._canonical_bytes(
            module._release_identity_payload(manifest, include_shadow_runtime=True)
        )
    )
    release_id = f"researcher-{capability_version}-{identity_sha256[:16]}"
    release_root = state / "researcher_container" / "releases" / release_id
    manifest_path = release_root / "release.json"
    manifest.update(
        {
            "release_id": release_id,
            "release_identity_sha256": identity_sha256,
            "skill_bundle_path": str(release_root / "skill-bundle"),
            "skill_bundle_manifest_path": str(release_root / "skill-bundle.manifest.json"),
            "skill_bundle_manifest_sha256": module._sha256_bytes(
                module._canonical_bytes(bundle_manifest)
            ),
        }
    )
    module._materialize_skill_bundle(release_root / "skill-bundle", source_rows, bundle_manifest)
    module._write_json_atomic(
        release_root / "skill-bundle.manifest.json", bundle_manifest, create_new=True
    )
    module._write_json_atomic(manifest_path, manifest, create_new=True)
    return manifest, manifest_path


def _terminal_forward_upgrade_pointer(
    module,
    manifest: dict[str, object],
    manifest_path: Path,
    *,
    generation: int = 6,
    txn_suffix: str = "a" * 16,
) -> tuple[dict[str, object], dict[str, object], Path]:
    txn_id = f"xra_20260730T213358_{txn_suffix}"
    active = module._release_ref_from_manifest(manifest, manifest_path, activation_txn_id=txn_id)
    pointer = {
        "schema_version": module.CURRENT_POINTER_SCHEMA,
        "generation": generation,
        "active": active,
        "previous_verified": None,
        "switched_at": "2026-07-30T21:34:00Z",
    }
    journal_path = module._journal_path(txn_id)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    canary_path = journal_path.parent / "canary.receipt.json"
    module._write_json_atomic(canary_path, {"status": "PASS"}, create_new=True)
    restore_root = journal_path.parent / "legacy_restore"
    restore_root.mkdir(parents=True, exist_ok=True)
    journal = {
        "schema_version": module.ACTIVATION_JOURNAL_SCHEMA,
        "revision": 4,
        "txn_id": txn_id,
        "operation": "FORWARD_UPGRADE",
        "state": "VERIFIED",
        "from": {
            "source_pointer_sha256": "f" * 64,
            "source_pointer": {
                "schema_version": module.CURRENT_POINTER_SCHEMA,
                "generation": generation - 1,
                "active": active,
                "previous_verified": None,
                "switched_at": "2026-07-30T20:00:00Z",
            },
            "previous_verified": None,
            "legacy_restore_path": str(restore_root),
            "legacy_restore_manifest_sha256": "1" * 64,
            "legacy_restore_tree_sha256": "2" * 64,
            "installed_projection_receipt_sha256": "3" * 64,
        },
        "requested_to": active,
        "to": active,
        "expected_generation": generation,
        "prepared_at": "2026-07-30T21:33:00Z",
        "updated_at": "2026-07-30T21:34:00Z",
        "switched_pointer_sha256": None,
        "canary": {
            "status": "PASS",
            "receipt_path": str(canary_path),
            "receipt_sha256": module._sha256(canary_path),
        },
        "failure_reason": None,
        "terminal_pointer_sha256": None,
    }
    module._write_json_atomic(journal_path, journal, create_new=True)
    pointer_path = module._state_paths()["pointer"]
    module._write_json_atomic(pointer_path, pointer)
    pointer_sha256 = module._sha256(pointer_path)
    journal["switched_pointer_sha256"] = pointer_sha256
    journal["terminal_pointer_sha256"] = pointer_sha256
    module._write_json_atomic(journal_path, journal)
    return pointer, journal, journal_path


def _copy_live_gen6_release(module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy live gen6 release bytes into tmp state with path localization only."""

    if not LIVE_GEN6_RELEASE_DIR.is_dir():
        pytest.skip(f"live gen6 release absent: {LIVE_GEN6_RELEASE_DIR}")
    live_json = LIVE_GEN6_RELEASE_DIR / "release.json"
    observed_sha = hashlib.sha256(live_json.read_bytes()).hexdigest()
    if observed_sha != LIVE_GEN6_RELEASE_JSON_SHA256:
        pytest.skip(
            f"live gen6 release.json sha drift: {observed_sha} != {LIVE_GEN6_RELEASE_JSON_SHA256}"
        )
    state = _state(module, tmp_path, monkeypatch)
    dest = state / "researcher_container" / "releases" / LIVE_GEN6_RELEASE_ID
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(LIVE_GEN6_RELEASE_DIR, dest)
    manifest_path = dest / "release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Path localization only: identity payload / skill hashes stay live bytes.
    manifest["skill_bundle_path"] = str(dest / "skill-bundle")
    manifest["skill_bundle_manifest_path"] = str(dest / "skill-bundle.manifest.json")
    module._write_json_atomic(manifest_path, manifest)
    return manifest_path


def test_pre_modules_key_sets_are_exact_frozensets() -> None:
    module = _module()
    base = set(module.PRE_SHADOW_SOURCE_IDENTITY_KEYS)
    pre_modules = set(module.PRE_MODULES_SOURCE_IDENTITY_KEYS)
    pre_tool = set(module.PRE_TOOL_IMAGE_SOURCE_IDENTITY_KEYS)
    current = set(module.CURRENT_SOURCE_IDENTITY_KEYS)
    assert pre_modules == base | {
        "shadow_runtime_tree_sha256",
        "shadow_runtime_lock_sha256",
    }
    assert pre_tool == pre_modules | {"researcher_image_modules_tree_sha256"}
    assert current == pre_tool | {
        "tool_executor_dockerfile_sha256",
        "tool_executor_modules_tree_sha256",
    }
    assert set(module.PRE_MODULES_IMAGE_LABEL_KEYS) == set(module.PRE_SHADOW_IMAGE_LABEL_KEYS) | {
        "io.xinao.researcher.shadow-runtime.sha256",
        "io.xinao.researcher.shadow-runtime-lock.sha256",
    }
    assert "io.xinao.researcher.image-modules.sha256" not in module.PRE_MODULES_IMAGE_LABEL_KEYS
    assert module.PRE_MODULES_SKILL_HASH_KEYS == module.CURRENT_SKILL_HASH_KEYS
    assert "shadow_runtime_lock_sha256" in module.PRE_MODULES_SKILL_HASH_KEYS


def test_live_gen6_bytes_match_pre_modules_taxonomy() -> None:
    """Prove against real live gen6 release.json key sets, not only ideal fixtures."""

    live_json = LIVE_GEN6_RELEASE_DIR / "release.json"
    if not live_json.is_file():
        pytest.skip(f"live gen6 release absent: {live_json}")
    raw = live_json.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == LIVE_GEN6_RELEASE_JSON_SHA256
    manifest = json.loads(raw.decode("utf-8"))
    module = _module()
    assert set(manifest) == set(module.PRE_TOOL_IMAGE_RELEASE_KEYS)
    assert set(manifest["source_identity"]) == LIVE_GEN6_SI_KEYS
    assert set(manifest["source_identity"]) == set(module.PRE_MODULES_SOURCE_IDENTITY_KEYS)
    assert set(manifest["skill_hashes"]) == set(module.PRE_MODULES_SKILL_HASH_KEYS)
    assert set(manifest["image_labels"]) == set(module.PRE_MODULES_IMAGE_LABEL_KEYS)
    assert "tool_image_id" not in manifest
    assert "researcher_image_modules_tree_sha256" not in manifest["source_identity"]
    assert "tool_executor_dockerfile_sha256" not in manifest["source_identity"]
    assert module._source_identity_generation(manifest["source_identity"]) == "pre_modules"


def test_sealed_pre_modules_readable_exact_current_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_pre_modules_v2_release(module, tmp_path, monkeypatch)
    # Generation-aware sealed path accepts the historical shape.
    module._validate_sealed_protocol_v2_release(manifest, manifest_path)
    assert module._source_identity_generation(manifest["source_identity"]) == "pre_modules"
    assert module._active_release_requires_forward_upgrade(manifest) is True
    # Ordinary exact-current dual-image fence still rejects.
    with pytest.raises(module.XinaoError) as exact_failure:
        module._validate_release_manifest(manifest, manifest_path)
    assert exact_failure.value.reason_code in {
        "RELEASE_SOURCE_IDENTITY_INVALID",
        "RELEASE_SCHEMA_INVALID",
    }
    # Seal identity must stay byte-stable under revalidation.
    original = manifest_path.read_bytes()
    module._validate_sealed_protocol_v2_release_ref(
        module._release_ref_from_manifest(
            manifest, manifest_path, activation_txn_id="xra_20260730T213358_" + "b" * 16
        ),
        verify_bundle=True,
    )
    assert manifest_path.read_bytes() == original


def test_live_gen6_copy_sealed_pass_ordinary_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest_path = _copy_live_gen6_release(module, tmp_path, monkeypatch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    module._validate_sealed_protocol_v2_release(manifest, manifest_path, verify_bundle=True)
    assert module._source_identity_generation(manifest["source_identity"]) == "pre_modules"
    assert module._active_release_requires_forward_upgrade(manifest) is True
    with pytest.raises(module.XinaoError) as exact_failure:
        module._validate_release_manifest(manifest, manifest_path)
    assert exact_failure.value.reason_code in {
        "RELEASE_SOURCE_IDENTITY_INVALID",
        "RELEASE_SCHEMA_INVALID",
    }


def test_pre_modules_malformed_and_cross_generation_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    good, good_path = _sealed_pre_modules_v2_release(
        module, tmp_path, monkeypatch, image_character="a", variant=b"good\n"
    )

    def _rewrite(mutator) -> Path:
        manifest = copy.deepcopy(good)
        mutator(manifest)
        if manifest.get("release_identity_sha256") == "recompute":
            identity = module._sha256_bytes(
                module._canonical_bytes(
                    module._release_identity_payload(manifest, include_shadow_runtime=True)
                )
            )
            manifest["release_identity_sha256"] = identity
        path = good_path
        module._write_json_atomic(path, manifest)
        return path

    # Missing shadow field -> not exact pre_modules frozenset.
    path = _rewrite(lambda m: m["source_identity"].pop("shadow_runtime_tree_sha256"))
    with pytest.raises(module.XinaoError) as missing:
        module._validate_sealed_protocol_v2_release(
            json.loads(path.read_text(encoding="utf-8")), path
        )
    assert missing.value.reason_code == "RELEASE_SOURCE_IDENTITY_INVALID"

    # Restore good and add fake modules field (cross-generation / denylist trap).
    module._write_json_atomic(good_path, good)
    path = _rewrite(
        lambda m: m["source_identity"].__setitem__("researcher_image_modules_tree_sha256", "f" * 64)
    )
    with pytest.raises(module.XinaoError) as extra:
        module._validate_sealed_protocol_v2_release(
            json.loads(path.read_text(encoding="utf-8")), path
        )
    # Adding modules keys alone promotes the identity set into pre_tool_image, which then
    # fail-closes on exact label/modules requirements (not a soft subset accept).
    assert extra.value.reason_code in {
        "RELEASE_SOURCE_IDENTITY_INVALID",
        "RELEASE_IMAGE_IDENTITY_INVALID",
        "RELEASE_RESEARCHER_IMAGE_MODULES_TREE_INVALID",
    }

    # Pseudo tool fields on transport-only top-level.
    module._write_json_atomic(good_path, good)
    path = _rewrite(lambda m: m.__setitem__("tool_image_id", "sha256:" + "9" * 64))
    with pytest.raises(module.XinaoError) as tool_top:
        module._validate_sealed_protocol_v2_release(
            json.loads(path.read_text(encoding="utf-8")), path
        )
    assert tool_top.value.reason_code in {
        "RELEASE_SCHEMA_INVALID",
        "RELEASE_SOURCE_IDENTITY_INVALID",
    }

    # Wrong shadow hash in labels.
    module._write_json_atomic(good_path, good)
    path = _rewrite(
        lambda m: m["image_labels"].__setitem__(
            "io.xinao.researcher.shadow-runtime.sha256", "0" * 64
        )
    )
    with pytest.raises(module.XinaoError) as bad_label:
        module._validate_sealed_protocol_v2_release(
            json.loads(path.read_text(encoding="utf-8")), path
        )
    assert bad_label.value.reason_code in {
        "RELEASE_IMAGE_IDENTITY_INVALID",
        "RELEASE_IDENTITY_MISMATCH",
    }

    # Wrong entrypoint.
    module._write_json_atomic(good_path, good)
    path = _rewrite(lambda m: m.__setitem__("image_entrypoint", ["python", "-I", "/wrong.py"]))
    with pytest.raises(module.XinaoError) as bad_ep:
        module._validate_sealed_protocol_v2_release(
            json.loads(path.read_text(encoding="utf-8")), path
        )
    assert bad_ep.value.reason_code in {
        "RELEASE_IMAGE_IDENTITY_INVALID",
        "RELEASE_IDENTITY_MISMATCH",
    }

    # Wrong skill hash.
    module._write_json_atomic(good_path, good)
    path = _rewrite(lambda m: m["skill_hashes"].__setitem__("skill_md_sha256", "0" * 64))
    with pytest.raises(module.XinaoError) as bad_hash:
        module._validate_sealed_protocol_v2_release(
            json.loads(path.read_text(encoding="utf-8")), path
        )
    assert bad_hash.value.reason_code == "RELEASE_SKILL_HASHES_MISMATCH"

    # Extra episode label (current dual-profile noise) -> label set mismatch.
    module._write_json_atomic(good_path, good)
    path = _rewrite(
        lambda m: m["image_labels"].__setitem__("io.xinao.researcher.default-profile", "canary")
    )
    with pytest.raises(module.XinaoError) as extra_label:
        module._validate_sealed_protocol_v2_release(
            json.loads(path.read_text(encoding="utf-8")), path
        )
    assert extra_label.value.reason_code in {
        "RELEASE_IMAGE_IDENTITY_INVALID",
        "RELEASE_IDENTITY_MISMATCH",
    }

    # Restore pristine good for any later fixture reuse.
    module._write_json_atomic(good_path, good)


def test_forward_upgrade_journal_target_historical_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_pre_modules_v2_release(
        module, tmp_path, monkeypatch, image_character="c", variant=b"journal-target\n"
    )
    _pointer, journal, journal_path = _terminal_forward_upgrade_pointer(
        module, manifest, manifest_path, generation=6, txn_suffix="c" * 16
    )
    # Generation-aware terminal journal validation accepts historical FORWARD_UPGRADE target.
    module._validate_journal(journal, journal_path)
    pending = module._pending_journals()
    assert pending == []
    # Exact ref validation still rejects historical target.
    with pytest.raises(module.XinaoError) as exact_ref:
        module._validate_release_ref(journal["to"])
    assert exact_ref.value.reason_code in {
        "RELEASE_SOURCE_IDENTITY_INVALID",
        "RELEASE_SCHEMA_INVALID",
    }


def test_prepared_historical_target_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PREPARED FORWARD_UPGRADE journal must reject historical to/requested_to."""

    module = _module()
    manifest, manifest_path = _sealed_pre_modules_v2_release(
        module, tmp_path, monkeypatch, image_character="p", variant=b"prepared-hist\n"
    )
    _pointer, journal, journal_path = _terminal_forward_upgrade_pointer(
        module, manifest, manifest_path, generation=6, txn_suffix="a1" * 8
    )
    # Demote terminal journal to PREPARED with historical target still bound.
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["state"] = "PREPARED"
    journal["revision"] = 1
    journal["switched_pointer_sha256"] = None
    journal["terminal_pointer_sha256"] = None
    journal["canary"] = None
    module._write_json_atomic(journal_path, journal)
    with pytest.raises(module.XinaoError) as prepared_fail:
        module._validate_journal(json.loads(journal_path.read_text(encoding="utf-8")), journal_path)
    assert prepared_fail.value.reason_code in {
        "RELEASE_SOURCE_IDENTITY_INVALID",
        "RELEASE_SCHEMA_INVALID",
    }
    # CAS switch fence also rejects historical target even if journal state were forced.
    with pytest.raises(module.XinaoError) as cas_fail:
        module._switch_forward_upgrade_pointer(
            {
                **json.loads(journal_path.read_text(encoding="utf-8")),
                "state": "PREPARED",
            },
            journal_path,
        )
    assert cas_fail.value.reason_code in {
        "RELEASE_SOURCE_IDENTITY_INVALID",
        "RELEASE_SCHEMA_INVALID",
    }


def test_new_prepare_target_remains_exact_current_dual_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PREPARED / build path must still require exact dual-image current generation."""

    module = _module()
    historical, historical_path = _sealed_pre_modules_v2_release(
        module, tmp_path, monkeypatch, image_character="d", variant=b"hist\n"
    )
    with pytest.raises(module.XinaoError) as prepare_reject:
        module._validate_release_manifest(historical, historical_path)
    assert prepare_reject.value.reason_code in {
        "RELEASE_SOURCE_IDENTITY_INVALID",
        "RELEASE_SCHEMA_INVALID",
    }
    # A dual-image current fixture (minimal seal via existing build identity keys) must pass
    # exact validation after proper materialization; smoke that CURRENT keys are still enforced.
    assert "tool_executor_dockerfile_sha256" in module.CURRENT_SOURCE_IDENTITY_KEYS
    assert "tool_image_id" in module.CURRENT_RELEASE_KEYS
    assert (
        module._source_identity_generation(
            {
                "source_commit": "c" * 40,
                "source_tree": "d" * 40,
                "source_dirty": False,
                "grok_donor_image_id": "sha256:" + "b" * 64,
                "grok_donor_binary_sha256": "a" * 64,
                "shadow_runtime_tree_sha256": "e" * 64,
                "shadow_runtime_lock_sha256": "f" * 64,
                "researcher_image_modules_tree_sha256": "1" * 64,
                "tool_executor_dockerfile_sha256": "2" * 64,
                "tool_executor_modules_tree_sha256": "3" * 64,
            }
        )
        == "current"
    )


def test_ordinary_bootstrap_launcher_rejects_pre_modules_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_pre_modules_v2_release(
        module, tmp_path, monkeypatch, image_character="e", variant=b"bootstrap\n"
    )
    _terminal_forward_upgrade_pointer(
        module, manifest, manifest_path, generation=6, txn_suffix="e" * 16
    )
    with pytest.raises(module.XinaoError) as load_failure:
        module._load_current_context(require_terminal=True)
    assert load_failure.value.reason_code in {
        "RELEASE_SOURCE_IDENTITY_INVALID",
        "RELEASE_SCHEMA_INVALID",
        "FORWARD_UPGRADE_REQUIRED",
    }
    with pytest.raises(module.XinaoError) as migrate_failure:
        module.bootstrap_migrate()
    assert migrate_failure.value.reason_code == "FORWARD_UPGRADE_REQUIRED"


def test_companion_runtime_seal_matches_repository_bytes() -> None:
    bootstrap = _bootstrap_module()
    runtime_path = bootstrap._companion_runtime_path()
    observed = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    assert observed == bootstrap.EXPECTED_COMPANION_RUNTIME_SHA256
    # Wave106: Windows host cannot exec Linux donor ELF; runtime probe uses Docker-mount
    # of staged bytes. Companion pin tracks exact xinao_runtime.py seal.
    assert observed == "d091b47efcbcba31e62fbfd0d49950fccf3a01d5f441ff8befaea38534f0edb6"
    assert len(observed) == 64


def test_wave76b_donor_lock_not_drifted() -> None:
    """Wave76B donor pin must remain the Wave68 Grok 0.2.117 clean image."""

    lock_path = SKILL_ROOT / "references" / "researcher-runtime-lock.v1.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock.get("grok_cli_version") == "0.2.117"
    assert "wave68-grok02117" in str(lock.get("grok_donor_image", ""))
    assert str(lock.get("grok_donor_image_id", "")).startswith("sha256:")
    assert len(str(lock.get("grok_donor_image_id", ""))) == 71


# ---------------------------------------------------------------------------
# Wave90: A-only shadow_lock cross-bind + B-shape full forward-upgrade E2E
# ---------------------------------------------------------------------------


def _rewrite_pre_modules_release_with_si_lock(
    module,
    good: dict[str, object],
    good_path: Path,
    *,
    forged_lock: str,
) -> Path:
    """Identity-recompute + path-rebind after SI/label lock replacement; skill_hashes unchanged."""

    mutated = copy.deepcopy(good)
    mutated["source_identity"]["shadow_runtime_lock_sha256"] = forged_lock
    mutated["image_labels"]["io.xinao.researcher.shadow-runtime-lock.sha256"] = forged_lock
    source_identity = mutated["source_identity"]
    assert isinstance(source_identity, dict)
    source_identity_sha256 = module._sha256_bytes(module._canonical_bytes(source_identity))
    labels = mutated["image_labels"]
    assert isinstance(labels, dict)
    labels["io.xinao.researcher.source-identity.sha256"] = source_identity_sha256
    identity = module._sha256_bytes(
        module._canonical_bytes(
            module._release_identity_payload(mutated, include_shadow_runtime=True)
        )
    )
    capability_version = str(mutated["capability_version"])
    new_release_id = f"researcher-{capability_version}-{identity[:16]}"
    old_root = good_path.parent
    new_root = old_root.parent / new_release_id
    if new_root.exists():
        shutil.rmtree(new_root)
    shutil.copytree(old_root, new_root)
    new_path = new_root / "release.json"
    mutated["release_id"] = new_release_id
    mutated["release_identity_sha256"] = identity
    mutated["skill_bundle_path"] = str(new_root / "skill-bundle")
    mutated["skill_bundle_manifest_path"] = str(new_root / "skill-bundle.manifest.json")
    # skill_hashes remain real lock-file binding from the copied bundle.
    module._write_json_atomic(new_path, mutated)
    return new_path


def test_pre_modules_rejects_si_vs_skill_hashes_shadow_lock_desync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-only attack: SI/label lock replaced with another format-valid hex; skill_hashes keep real lock."""

    module = _module()
    good, path = _sealed_pre_modules_v2_release(
        module, tmp_path, monkeypatch, image_character="1", variant=b"crossbind-si\n"
    )
    module._validate_sealed_protocol_v2_release(good, path)
    real_lock = good["skill_hashes"]["shadow_runtime_lock_sha256"]
    forged_lock = "a" * 64
    assert forged_lock != real_lock
    assert module.HEX_SHA256_PATTERN.fullmatch(forged_lock)

    new_path = _rewrite_pre_modules_release_with_si_lock(
        module, good, path, forged_lock=forged_lock
    )
    mutated = json.loads(new_path.read_text(encoding="utf-8"))
    assert mutated["skill_hashes"]["shadow_runtime_lock_sha256"] == real_lock
    assert mutated["source_identity"]["shadow_runtime_lock_sha256"] == forged_lock
    with pytest.raises(module.XinaoError) as failure:
        module._validate_sealed_protocol_v2_release(mutated, new_path)
    assert failure.value.reason_code == "RELEASE_SHADOW_RUNTIME_LOCK_INVALID"
    assert "skill_hashes_cross_check" in failure.value.detail


def test_pre_modules_rejects_skill_hashes_vs_si_shadow_lock_desync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only skill_hashes.shadow_runtime_lock_sha256 replaced with another format-valid hex."""

    module = _module()
    good, path = _sealed_pre_modules_v2_release(
        module, tmp_path, monkeypatch, image_character="2", variant=b"crossbind-sh\n"
    )
    real_lock = good["source_identity"]["shadow_runtime_lock_sha256"]
    forged_lock = "b" * 64
    assert forged_lock != real_lock
    assert module.HEX_SHA256_PATTERN.fullmatch(forged_lock)

    mutated = copy.deepcopy(good)
    # Keep SI + labels on real lock; only skill_hashes field desyncs.
    mutated["skill_hashes"]["shadow_runtime_lock_sha256"] = forged_lock
    module._write_json_atomic(path, mutated)
    with pytest.raises(module.XinaoError) as failure:
        module._validate_sealed_protocol_v2_release(
            json.loads(path.read_text(encoding="utf-8")), path
        )
    # Either bundle hash mismatch (skill_hashes != file) or cross-check may fire first
    # depending on check order; both are reject, never accept.
    assert failure.value.reason_code in {
        "RELEASE_SKILL_HASHES_MISMATCH",
        "RELEASE_SHADOW_RUNTIME_LOCK_INVALID",
    }


def test_live_gen6_shadow_lock_cross_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Live gen6 bytes already satisfy skill_hashes.shadow_lock == SI.shadow_lock."""

    module = _module()
    path = _copy_live_gen6_release(module, tmp_path, monkeypatch)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    si_lock = manifest["source_identity"]["shadow_runtime_lock_sha256"]
    sh_lock = manifest["skill_hashes"]["shadow_runtime_lock_sha256"]
    label_lock = manifest["image_labels"]["io.xinao.researcher.shadow-runtime-lock.sha256"]
    assert si_lock == sh_lock == label_lock
    module._validate_sealed_protocol_v2_release(manifest, path, verify_bundle=True)
    # Desync only SI/label after path-rebind must still fail closed via cross-check.
    forged = "c" * 64
    assert forged != si_lock
    new_path = _rewrite_pre_modules_release_with_si_lock(module, manifest, path, forged_lock=forged)
    with pytest.raises(module.XinaoError) as failure:
        module._validate_sealed_protocol_v2_release(
            json.loads(new_path.read_text(encoding="utf-8")), new_path, verify_bundle=True
        )
    assert failure.value.reason_code == "RELEASE_SHADOW_RUNTIME_LOCK_INVALID"
    assert "skill_hashes_cross_check" in failure.value.detail


# ---------------------------------------------------------------------------
# Wave95 / Wave91: A1b tree recompute + A1c/A1d/A1e cross-generation lock bind
# ---------------------------------------------------------------------------


def _rewrite_pre_modules_release_with_si_tree(
    module,
    good: dict[str, object],
    good_path: Path,
    *,
    forged_tree: str,
) -> Path:
    """Identity-recompute after SI/label shadow_tree replacement; lock/skill_hashes unchanged."""

    mutated = copy.deepcopy(good)
    mutated["source_identity"]["shadow_runtime_tree_sha256"] = forged_tree
    mutated["image_labels"]["io.xinao.researcher.shadow-runtime.sha256"] = forged_tree
    source_identity = mutated["source_identity"]
    assert isinstance(source_identity, dict)
    source_identity_sha256 = module._sha256_bytes(module._canonical_bytes(source_identity))
    labels = mutated["image_labels"]
    assert isinstance(labels, dict)
    labels["io.xinao.researcher.source-identity.sha256"] = source_identity_sha256
    identity = module._sha256_bytes(
        module._canonical_bytes(
            module._release_identity_payload(mutated, include_shadow_runtime=True)
        )
    )
    capability_version = str(mutated["capability_version"])
    new_release_id = f"researcher-{capability_version}-{identity[:16]}"
    old_root = good_path.parent
    new_root = old_root.parent / new_release_id
    if new_root.exists():
        shutil.rmtree(new_root)
    shutil.copytree(old_root, new_root)
    new_path = new_root / "release.json"
    mutated["release_id"] = new_release_id
    mutated["release_identity_sha256"] = identity
    mutated["skill_bundle_path"] = str(new_root / "skill-bundle")
    mutated["skill_bundle_manifest_path"] = str(new_root / "skill-bundle.manifest.json")
    module._write_json_atomic(new_path, mutated)
    return new_path


def test_pre_modules_rejects_forged_shadow_tree_a1b(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave91 A1b: arbitrary SI/label shadow_tree must fail when lock matches source cone."""

    module = _module()
    good, path = _sealed_pre_modules_v2_release(
        module, tmp_path, monkeypatch, image_character="3", variant=b"a1b-tree\n"
    )
    module._validate_sealed_protocol_v2_release(good, path, verify_bundle=True)
    real_tree = good["source_identity"]["shadow_runtime_tree_sha256"]
    forged_tree = "f" * 64
    assert forged_tree != real_tree
    assert module.HEX_SHA256_PATTERN.fullmatch(forged_tree)
    new_path = _rewrite_pre_modules_release_with_si_tree(
        module, good, path, forged_tree=forged_tree
    )
    mutated = json.loads(new_path.read_text(encoding="utf-8"))
    assert mutated["source_identity"]["shadow_runtime_tree_sha256"] == forged_tree
    assert mutated["image_labels"]["io.xinao.researcher.shadow-runtime.sha256"] == forged_tree
    with pytest.raises(module.XinaoError) as failure:
        module._validate_sealed_protocol_v2_release(mutated, new_path, verify_bundle=True)
    assert failure.value.reason_code == "RELEASE_SHADOW_RUNTIME_TREE_INVALID"
    assert "tree_cross_check" in failure.value.detail


def test_pre_tool_rejects_si_vs_skill_hashes_shadow_lock_desync_a1d(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave91 A1d: pre_tool_image must enforce skill_hashes_cross_check like pre_modules."""

    module = _module()
    # Build a pre_tool_image-shaped release (modules tree present, no tool image fields).
    state = _state(module, tmp_path, monkeypatch)
    source_rows = module._source_bundle_files(SKILL_ROOT)
    source_rows.append(
        ("references/test-release-variant.txt", tmp_path / "unused", b"pre-tool-desync\n")
    )
    source_rows.sort(key=lambda item: item[0])
    package_version = "1.3.6"
    capability_version = "1.2.2"
    bundle_manifest = module._skill_bundle_manifest(source_rows, package_version=package_version)
    temp_bundle = tmp_path / "pre-tool-bundle"
    module._materialize_skill_bundle(temp_bundle, source_rows, bundle_manifest)
    hashes = module._reference_hashes_for_keys(temp_bundle, module.CURRENT_SKILL_HASH_KEYS)
    lock_obj = module._load_shadow_runtime_lock(SKILL_ROOT)
    shadow_rows = module._collect_shadow_runtime_rows(ROOT, lock_obj)
    shadow_tree = module._shadow_runtime_tree_sha256(shadow_rows)
    shadow_lock = hashes["shadow_runtime_lock_sha256"]
    module_rows = module._collect_researcher_image_module_rows(ROOT)
    modules_tree = module._researcher_image_modules_tree_sha256(module_rows)
    forged_lock = "a" * 64
    assert forged_lock != shadow_lock
    source_identity = {
        "source_commit": "c" * 40,
        "source_tree": "d" * 40,
        "source_dirty": False,
        "grok_donor_image_id": "sha256:" + "b" * 64,
        "grok_donor_binary_sha256": "a" * 64,
        "shadow_runtime_tree_sha256": shadow_tree,
        "shadow_runtime_lock_sha256": forged_lock,
        "researcher_image_modules_tree_sha256": modules_tree,
    }
    assert set(source_identity) == set(module.PRE_TOOL_IMAGE_SOURCE_IDENTITY_KEYS)
    si_sha = module._sha256_bytes(module._canonical_bytes(source_identity))
    labels = {
        "io.xinao.researcher.chain": "dedicated-xinao-science",
        "io.xinao.researcher.generic-worker-route": "forbidden",
        "io.xinao.researcher.grok-donor-image-id": source_identity["grok_donor_image_id"],
        "io.xinao.researcher.grok-donor-binary.sha256": source_identity["grok_donor_binary_sha256"],
        "io.xinao.researcher.charter.sha256": hashes["charter_sha256"],
        "io.xinao.researcher.output-schema.sha256": hashes["output_schema_sha256"],
        "io.xinao.researcher.material-bundle-schema.sha256": hashes[
            "material_bundle_schema_sha256"
        ],
        "io.xinao.researcher.runtime-lock.sha256": hashes["runtime_lock_sha256"],
        "io.xinao.researcher.skill-invoker.sha256": hashes["skill_invoker_sha256"],
        "io.xinao.researcher.dockerfile.sha256": "1" * 64,
        "io.xinao.researcher.entrypoint.sha256": "2" * 64,
        "io.xinao.researcher.source-identity.sha256": si_sha,
        "io.xinao.researcher.shadow-runtime.sha256": shadow_tree,
        "io.xinao.researcher.shadow-runtime-lock.sha256": forged_lock,
        "io.xinao.researcher.requested-model": "grok-4.5",
        **module._dual_profile_image_labels(researcher_image_modules_tree_sha256=modules_tree),
    }
    manifest: dict[str, object] = {
        "schema_version": module.RELEASE_SCHEMA,
        "release_id": "pending",
        "package_version": package_version,
        "capability_id": "researcher-container",
        "capability_version": capability_version,
        "charter_version": capability_version,
        "runtime_version": capability_version,
        "release_identity_sha256": "pending",
        "source_identity": source_identity,
        "skill_bundle_path": "pending",
        "skill_bundle_manifest_path": "pending",
        "skill_bundle_manifest_sha256": "pending",
        "skill_bundle_tree_sha256": bundle_manifest["tree_sha256"],
        "image_tag_observational": "xinao-researcher:pre-tool-test",
        "image_id": "sha256:" + "4" * 64,
        "image_entrypoint": ["python", "-I", module.RESEARCHER_CANARY_ENTRYPOINT_IMAGE_PATH],
        "image_labels": labels,
        "skill_hashes": hashes,
        "required_bootstrap_protocol": 2,
        "generic_worker_route_allowed": False,
        "state_namespace": "xinao_skill/researcher_container",
        "run_namespace": "xinao_researcher",
    }
    assert set(manifest) == set(module.PRE_TOOL_IMAGE_RELEASE_KEYS)
    identity = module._sha256_bytes(
        module._canonical_bytes(
            module._release_identity_payload(manifest, include_shadow_runtime=True)
        )
    )
    release_id = f"researcher-{capability_version}-{identity[:16]}"
    release_root = state / "researcher_container" / "releases" / release_id
    manifest_path = release_root / "release.json"
    manifest.update(
        {
            "release_id": release_id,
            "release_identity_sha256": identity,
            "skill_bundle_path": str(release_root / "skill-bundle"),
            "skill_bundle_manifest_path": str(release_root / "skill-bundle.manifest.json"),
            "skill_bundle_manifest_sha256": module._sha256_bytes(
                module._canonical_bytes(bundle_manifest)
            ),
        }
    )
    module._materialize_skill_bundle(release_root / "skill-bundle", source_rows, bundle_manifest)
    module._write_json_atomic(
        release_root / "skill-bundle.manifest.json", bundle_manifest, create_new=True
    )
    module._write_json_atomic(manifest_path, manifest, create_new=True)
    with pytest.raises(module.XinaoError) as failure:
        module._validate_sealed_protocol_v2_release(
            json.loads(manifest_path.read_text(encoding="utf-8")),
            manifest_path,
            verify_bundle=True,
        )
    assert failure.value.reason_code == "RELEASE_SHADOW_RUNTIME_LOCK_INVALID"
    assert "skill_hashes_cross_check" in failure.value.detail


def test_exact_current_rejects_si_vs_skill_hashes_shadow_lock_desync_a1e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave91 A1e: exact-current production gate must reject SI/label lock desync."""

    module = _module()
    good, path = _sealed_current_dual_image_release(
        module, tmp_path, monkeypatch, image_character="c", variant=b"a1e-desync\n"
    )
    module._validate_release_manifest(good, path, verify_bundle=True)
    real_lock = good["skill_hashes"]["shadow_runtime_lock_sha256"]
    forged_lock = "d" * 64
    assert forged_lock != real_lock
    mutated = copy.deepcopy(good)
    mutated["source_identity"]["shadow_runtime_lock_sha256"] = forged_lock
    mutated["image_labels"]["io.xinao.researcher.shadow-runtime-lock.sha256"] = forged_lock
    source_identity = mutated["source_identity"]
    assert isinstance(source_identity, dict)
    si_sha = module._sha256_bytes(module._canonical_bytes(source_identity))
    mutated["image_labels"]["io.xinao.researcher.source-identity.sha256"] = si_sha
    identity = module._sha256_bytes(
        module._canonical_bytes(module._release_identity_payload(mutated))
    )
    capability_version = str(mutated["capability_version"])
    new_release_id = f"researcher-{capability_version}-{identity[:16]}"
    old_root = path.parent
    new_root = old_root.parent / new_release_id
    if new_root.exists():
        shutil.rmtree(new_root)
    shutil.copytree(old_root, new_root)
    new_path = new_root / "release.json"
    mutated["release_id"] = new_release_id
    mutated["release_identity_sha256"] = identity
    mutated["skill_bundle_path"] = str(new_root / "skill-bundle")
    mutated["skill_bundle_manifest_path"] = str(new_root / "skill-bundle.manifest.json")
    module._write_json_atomic(new_path, mutated)
    loaded = json.loads(new_path.read_text(encoding="utf-8"))
    assert loaded["skill_hashes"]["shadow_runtime_lock_sha256"] == real_lock
    assert loaded["source_identity"]["shadow_runtime_lock_sha256"] == forged_lock
    with pytest.raises(module.XinaoError) as failure:
        module._validate_release_manifest(loaded, new_path, verify_bundle=True)
    assert failure.value.reason_code == "RELEASE_SHADOW_RUNTIME_LOCK_INVALID"
    assert "skill_hashes_cross_check" in failure.value.detail


def test_exact_current_rejects_forged_shadow_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exact-current must reject SI/label shadow_tree forged away from source package rows."""

    module = _module()
    good, path = _sealed_current_dual_image_release(
        module, tmp_path, monkeypatch, image_character="e", variant=b"cur-tree\n"
    )
    real_tree = good["source_identity"]["shadow_runtime_tree_sha256"]
    forged_tree = "f" * 64
    assert forged_tree != real_tree
    mutated = copy.deepcopy(good)
    mutated["source_identity"]["shadow_runtime_tree_sha256"] = forged_tree
    mutated["image_labels"]["io.xinao.researcher.shadow-runtime.sha256"] = forged_tree
    source_identity = mutated["source_identity"]
    assert isinstance(source_identity, dict)
    si_sha = module._sha256_bytes(module._canonical_bytes(source_identity))
    mutated["image_labels"]["io.xinao.researcher.source-identity.sha256"] = si_sha
    identity = module._sha256_bytes(
        module._canonical_bytes(module._release_identity_payload(mutated))
    )
    capability_version = str(mutated["capability_version"])
    new_release_id = f"researcher-{capability_version}-{identity[:16]}"
    old_root = path.parent
    new_root = old_root.parent / new_release_id
    if new_root.exists():
        shutil.rmtree(new_root)
    shutil.copytree(old_root, new_root)
    new_path = new_root / "release.json"
    mutated["release_id"] = new_release_id
    mutated["release_identity_sha256"] = identity
    mutated["skill_bundle_path"] = str(new_root / "skill-bundle")
    mutated["skill_bundle_manifest_path"] = str(new_root / "skill-bundle.manifest.json")
    module._write_json_atomic(new_path, mutated)
    with pytest.raises(module.XinaoError) as failure:
        module._validate_release_manifest(
            json.loads(new_path.read_text(encoding="utf-8")), new_path, verify_bundle=True
        )
    assert failure.value.reason_code == "RELEASE_SHADOW_RUNTIME_TREE_INVALID"
    assert "tree_cross_check" in failure.value.detail


def test_cross_generation_integrity_helpers_present() -> None:
    """Wave91 A1c: pre_modules, pre_tool, and exact-current all carry cross-binds."""

    src = (SKILL_ROOT / "scripts" / "xinao_runtime.py").read_text(encoding="utf-8")
    pm = src.find("def _validate_pre_modules_release")
    pt = src.find("def _validate_pre_tool_image_release")
    cur = src.find("def _validate_release_manifest")
    ref = src.find("def _reference_hashes_for_keys")
    sealed_ref = src.find("def _validate_sealed_protocol_v2_release_ref")
    assert pm != -1 and pt != -1 and cur != -1
    pm_block = src[pm:pt]
    pt_block = src[pt:sealed_ref]
    cur_block = src[cur:ref]
    assert (
        "skill_hashes_cross_check" in pm_block
        or "_assert_skill_hashes_shadow_lock_cross_bound" in pm_block
    )
    assert "_assert_skill_hashes_shadow_lock_cross_bound" in pt_block
    assert "_assert_skill_hashes_shadow_lock_cross_bound" in cur_block
    assert "expected_labels" in pt_block
    assert "expected_labels" in cur_block
    assert "shadow-runtime-lock" in cur_block
    assert "_verify_shadow_runtime_tree_from_source_bundle" in pm_block
    assert "_verify_shadow_runtime_tree_from_source_bundle" in pt_block
    assert "_verify_shadow_runtime_tree_from_source_bundle" in cur_block


def _sealed_current_dual_image_release(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    image_character: str = "c",
    package_version: str = "1.3.6",
    capability_version: str = "1.2.2",
    variant: bytes | None = None,
    shadow_runtime_lock_payload: bytes | None = None,
    shadow_runtime_tree_sha256: str | None = None,
) -> tuple[dict[str, object], Path]:
    """Minimal exact-current dual-image target for isolated FU E2E (tmp state only)."""

    state = _state(module, tmp_path, monkeypatch)
    source_rows = module._source_bundle_files(SKILL_ROOT)
    if shadow_runtime_lock_payload is not None:
        source_rows = [
            (
                relative,
                source_path,
                (
                    shadow_runtime_lock_payload
                    if relative == "references/shadow-runtime-lock.v1.json"
                    else payload
                ),
            )
            for relative, source_path, payload in source_rows
        ]
    if variant is not None:
        source_rows.append(
            (
                "references/test-release-variant.txt",
                tmp_path / "unused-source-path",
                variant,
            )
        )
        source_rows.sort(key=lambda item: item[0])
    bundle_manifest = module._skill_bundle_manifest(source_rows, package_version=package_version)
    hashes = module._reference_hashes(SKILL_ROOT)
    if shadow_runtime_lock_payload is not None:
        hashes["shadow_runtime_lock_sha256"] = module._sha256_bytes(shadow_runtime_lock_payload)
    shadow_lock = module._load_shadow_runtime_lock(SKILL_ROOT)
    shadow_rows = module._collect_shadow_runtime_rows(ROOT, shadow_lock)
    shadow_tree = (
        shadow_runtime_tree_sha256
        if shadow_runtime_tree_sha256 is not None
        else module._shadow_runtime_tree_sha256(shadow_rows)
    )
    shadow_lock_hash = hashes["shadow_runtime_lock_sha256"]
    module_rows = module._collect_researcher_image_module_rows(ROOT)
    modules_tree = module._researcher_image_modules_tree_sha256(module_rows)
    tool_df_path = ROOT / module.TOOL_EXECUTOR_DOCKERFILE_RELATIVE
    tool_df_sha = module._sha256_bytes(tool_df_path.read_bytes())
    tool_rows = module._collect_tool_executor_module_rows(ROOT)
    tool_mod_sha = module._tool_executor_modules_tree_sha256(tool_rows)
    if image_character not in "0123456789abcdef":
        raise AssertionError(f"image_character must be hex digit, got {image_character!r}")
    tool_char = format((int(image_character, 16) + 7) % 16, "x")
    source_identity = {
        "source_commit": "c" * 40,
        "source_tree": "d" * 40,
        "source_dirty": False,
        "grok_donor_image_id": "sha256:" + "b" * 64,
        "grok_donor_binary_sha256": "a" * 64,
        "shadow_runtime_tree_sha256": shadow_tree,
        "shadow_runtime_lock_sha256": shadow_lock_hash,
        "researcher_image_modules_tree_sha256": modules_tree,
        "tool_executor_dockerfile_sha256": tool_df_sha,
        "tool_executor_modules_tree_sha256": tool_mod_sha,
    }
    source_identity_sha256 = module._sha256_bytes(module._canonical_bytes(source_identity))
    image_id = "sha256:" + image_character * 64
    tool_image_id = "sha256:" + tool_char * 64
    labels = {
        "io.xinao.researcher.chain": "dedicated-xinao-science",
        "io.xinao.researcher.generic-worker-route": "forbidden",
        "io.xinao.researcher.grok-donor-image-id": source_identity["grok_donor_image_id"],
        "io.xinao.researcher.grok-donor-binary.sha256": source_identity["grok_donor_binary_sha256"],
        "io.xinao.researcher.charter.sha256": hashes["charter_sha256"],
        "io.xinao.researcher.output-schema.sha256": hashes["output_schema_sha256"],
        "io.xinao.researcher.material-bundle-schema.sha256": hashes[
            "material_bundle_schema_sha256"
        ],
        "io.xinao.researcher.runtime-lock.sha256": hashes["runtime_lock_sha256"],
        "io.xinao.researcher.skill-invoker.sha256": hashes["skill_invoker_sha256"],
        "io.xinao.researcher.dockerfile.sha256": "1" * 64,
        "io.xinao.researcher.entrypoint.sha256": "2" * 64,
        "io.xinao.researcher.source-identity.sha256": source_identity_sha256,
        "io.xinao.researcher.shadow-runtime.sha256": shadow_tree,
        "io.xinao.researcher.shadow-runtime-lock.sha256": shadow_lock_hash,
        "io.xinao.researcher.requested-model": "grok-4.5",
        **module._dual_profile_image_labels(researcher_image_modules_tree_sha256=modules_tree),
    }
    tool_labels = module._tool_executor_expected_labels(
        dockerfile_sha256=tool_df_sha, modules_tree_sha256=tool_mod_sha
    )
    manifest: dict[str, object] = {
        "schema_version": module.RELEASE_SCHEMA,
        "release_id": "pending",
        "package_version": package_version,
        "capability_id": "researcher-container",
        "capability_version": capability_version,
        "charter_version": capability_version,
        "runtime_version": capability_version,
        "release_identity_sha256": "pending",
        "source_identity": source_identity,
        "skill_bundle_path": "pending",
        "skill_bundle_manifest_path": "pending",
        "skill_bundle_manifest_sha256": "pending",
        "skill_bundle_tree_sha256": bundle_manifest["tree_sha256"],
        "image_tag_observational": "xinao-researcher:test",
        "image_id": image_id,
        "image_entrypoint": ["python", "-I", module.RESEARCHER_CANARY_ENTRYPOINT_IMAGE_PATH],
        "image_labels": labels,
        "tool_image_tag_observational": "xinao-tool-executor:test",
        "tool_image_id": tool_image_id,
        "tool_image_entrypoint": list(module.TOOL_EXECUTOR_ENTRYPOINT),
        "tool_image_labels": tool_labels,
        "skill_hashes": hashes,
        "required_bootstrap_protocol": 2,
        "generic_worker_route_allowed": False,
        "state_namespace": "xinao_skill/researcher_container",
        "run_namespace": "xinao_researcher",
    }
    identity_sha256 = module._sha256_bytes(
        module._canonical_bytes(module._release_identity_payload(manifest))
    )
    release_id = f"researcher-{capability_version}-{identity_sha256[:16]}"
    release_root = state / "researcher_container" / "releases" / release_id
    manifest_path = release_root / "release.json"
    manifest.update(
        {
            "release_id": release_id,
            "release_identity_sha256": identity_sha256,
            "skill_bundle_path": str(release_root / "skill-bundle"),
            "skill_bundle_manifest_path": str(release_root / "skill-bundle.manifest.json"),
            "skill_bundle_manifest_sha256": module._sha256_bytes(
                module._canonical_bytes(bundle_manifest)
            ),
        }
    )
    module._materialize_skill_bundle(release_root / "skill-bundle", source_rows, bundle_manifest)
    module._write_json_atomic(
        release_root / "skill-bundle.manifest.json", bundle_manifest, create_new=True
    )
    module._write_json_atomic(manifest_path, manifest, create_new=True)
    module._validate_release_manifest(manifest, manifest_path)
    return manifest, manifest_path


def _terminal_activate_pointer(
    module,
    manifest: dict[str, object],
    manifest_path: Path,
    *,
    generation: int = 6,
    txn_suffix: str = "1" * 16,
    previous_verified: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object], Path]:
    """Terminal ACTIVATE journal for historical active (sealed path, not PREPARED)."""

    txn_id = f"xra_20260730T120000_{txn_suffix}"
    active = module._release_ref_from_manifest(manifest, manifest_path, activation_txn_id=txn_id)
    pointer = {
        "schema_version": module.CURRENT_POINTER_SCHEMA,
        "generation": generation,
        "active": active,
        "previous_verified": previous_verified,
        "switched_at": "2026-07-30T12:00:00Z",
    }
    journal_path = module._journal_path(txn_id)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    canary_path = journal_path.parent / "canary.receipt.json"
    module._write_json_atomic(canary_path, {"status": "PASS"}, create_new=True)
    journal = {
        "schema_version": module.ACTIVATION_JOURNAL_SCHEMA,
        "revision": 4,
        "txn_id": txn_id,
        "operation": "ACTIVATE",
        "state": "VERIFIED",
        "from": None,
        "requested_to": active,
        "to": active,
        "expected_generation": generation,
        "prepared_at": "2026-07-30T12:00:00Z",
        "updated_at": "2026-07-30T12:00:01Z",
        "switched_pointer_sha256": None,
        "canary": {
            "status": "PASS",
            "receipt_path": str(canary_path),
            "receipt_sha256": module._sha256(canary_path),
        },
        "failure_reason": None,
        "terminal_pointer_sha256": None,
    }
    module._write_json_atomic(journal_path, journal, create_new=True)
    pointer_path = module._state_paths()["pointer"]
    module._write_json_atomic(pointer_path, pointer)
    pointer_sha256 = module._sha256(pointer_path)
    journal["switched_pointer_sha256"] = pointer_sha256
    journal["terminal_pointer_sha256"] = pointer_sha256
    module._write_json_atomic(journal_path, journal)
    return pointer, journal, journal_path


def _canary_value(module, journal: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "xinao.researcher_activation_canary.v1",
        "status": "CANARY_READY",
        "txn_id": journal["txn_id"],
        "pointer_generation": journal["expected_generation"],
        "pointer_sha256": journal["switched_pointer_sha256"],
        "release_id": journal["to"]["release_id"],
        "release_manifest_sha256": journal["to"]["release_manifest_sha256"],
        "skill_bundle_tree_sha256": journal["to"]["skill_bundle_tree_sha256"],
        "provider_effect_verified": False,
        "completion_claim_allowed": False,
    }


def _installed_tree_map(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _install_bootstrap_fence(
    module,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
) -> dict[str, object]:
    state_root = module._state_paths()["state_root"]
    bootstrap = _bootstrap_module()
    _runtime_path, _runtime_payload, fence = bootstrap._runtime_entry_locked(command, state_root)
    monkeypatch.setattr(module, "_BOOTSTRAP_FENCE_CACHE", None)
    monkeypatch.setenv(
        module.BOOTSTRAP_FENCE_ENVIRONMENT,
        json.dumps(fence, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
    )
    return fence


def _prepare_pre_modules_forward_upgrade_world(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    """B-shape world: historical pre_modules active + exact-current dual-image target stub."""

    previous, previous_path = _sealed_pre_modules_v2_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="a",
        package_version="1.3.4",
        capability_version="1.2.1",
        variant=b"previous-pre-modules\n",
    )
    active, active_path = _sealed_pre_modules_v2_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="b",
        package_version="1.3.4",
        capability_version="1.2.1",
        variant=b"active-pre-modules-1.3.4\n",
    )
    previous_ref = module._release_ref_from_manifest(
        previous, previous_path, activation_txn_id="xra_20260730T120000_" + "c" * 16
    )
    pointer, journal, journal_path = _terminal_activate_pointer(
        module,
        active,
        active_path,
        generation=6,
        txn_suffix="a" * 16,
        previous_verified=previous_ref,
    )
    active_bundle = Path(str(active["skill_bundle_path"]))
    installed = tmp_path / "installed_skill_pre_modules"
    if installed.exists():
        shutil.rmtree(installed)
    shutil.copytree(active_bundle, installed)
    (installed / "SKILL.md").write_bytes(
        (installed / "SKILL.md").read_bytes() + b"\n# installed-pre-modules-drift\n"
    )
    monkeypatch.setenv("XINAO_INSTALLED_SKILL_ROOT", str(installed))
    monkeypatch.setattr(module, "DEFAULT_INSTALLED_SKILL_ROOT", installed)
    installed_snapshot = _installed_tree_map(installed)

    # Target must match current source skill-bundle identity so post-upgrade
    # idempotent re-entry can return ALREADY_* (no variant drift).
    current_source = module._current_source_skill_bundle_identity()
    target, target_path = _sealed_current_dual_image_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="c",
        package_version=str(current_source["package_version"]),
        capability_version=str(current_source["capability_version"]),
    )
    monkeypatch.setattr(
        module,
        "_prepare_forward_upgrade_target",
        lambda: (target, target_path),
    )
    return {
        "active": active,
        "active_path": active_path,
        "active_manifest_bytes": active_path.read_bytes(),
        "previous": previous,
        "previous_path": previous_path,
        "previous_manifest_bytes": previous_path.read_bytes(),
        "pointer": pointer,
        "pointer_path": module._state_paths()["pointer"],
        "pointer_bytes": module._state_paths()["pointer"].read_bytes(),
        "journal": journal,
        "journal_path": journal_path,
        "installed": installed,
        "installed_snapshot": installed_snapshot,
        "target": target,
        "target_path": target_path,
    }


def _prepare_gen17_shadow_generation_forward_upgrade_world(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    active, active_path = _sealed_current_dual_image_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="d",
        package_version="1.3.15",
        capability_version="1.2.11",
        variant=b"live-gen17-shadow-generation\n",
        shadow_runtime_lock_payload=_live_gen17_shadow_lock_payload(),
        shadow_runtime_tree_sha256=LIVE_GEN17_SHADOW_RUNTIME_TREE_SHA256,
    )
    pointer, journal, journal_path = _terminal_activate_pointer(
        module,
        active,
        active_path,
        generation=17,
        txn_suffix="d" * 16,
        previous_verified=None,
    )
    installed = tmp_path / "installed_skill_gen17"
    shutil.copytree(Path(str(active["skill_bundle_path"])), installed)
    monkeypatch.setenv("XINAO_INSTALLED_SKILL_ROOT", str(installed))
    monkeypatch.setattr(module, "DEFAULT_INSTALLED_SKILL_ROOT", installed)

    source = module._current_source_skill_bundle_identity()
    target, target_path = _sealed_current_dual_image_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="e",
        package_version=str(source["package_version"]),
        capability_version=str(source["capability_version"]),
    )
    monkeypatch.setattr(
        module,
        "_prepare_forward_upgrade_target",
        lambda: (target, target_path),
    )
    return {
        "active": active,
        "active_path": active_path,
        "active_manifest_bytes": active_path.read_bytes(),
        "pointer": pointer,
        "pointer_path": module._state_paths()["pointer"],
        "journal": journal,
        "journal_path": journal_path,
        "installed": installed,
        "target": target,
        "target_path": target_path,
    }


def test_bootstrap_forward_upgrade_live_gen17_shadow_generation_to_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real gen17 lock/tree identity reaches the versioned current target in tmp state."""

    module = _module()
    world = _prepare_gen17_shadow_generation_forward_upgrade_world(module, tmp_path, monkeypatch)
    active = module._load_json(Path(world["active_path"]))
    module._validate_release_manifest(active, Path(world["active_path"]), verify_bundle=True)
    assert module._active_release_requires_forward_upgrade(active) is True
    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda journal: _canary_value(module, journal),
    )

    receipt = module.bootstrap_forward_upgrade()

    assert receipt["status"] == "UPGRADED"
    pointer = module._load_json(module._state_paths()["pointer"])
    assert pointer["generation"] == 18
    assert pointer["active"]["release_id"] == world["target"]["release_id"]
    assert pointer["active"]["package_version"] == "1.3.18"
    assert pointer["active"]["capability_version"] == "1.2.14"
    assert Path(world["active_path"]).read_bytes() == world["active_manifest_bytes"]


def test_bootstrap_forward_upgrade_pre_modules_to_dual_image_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full prepare→journal→CAS/pointer-switch→canary green path (tmp state; build stubbed)."""

    module = _module()
    world = _prepare_pre_modules_forward_upgrade_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda journal: _canary_value(module, journal),
    )
    receipt = module.bootstrap_forward_upgrade()
    assert receipt["status"] == "UPGRADED"
    assert receipt["operation"] == "FORWARD_UPGRADE"
    assert receipt["release_id"] == world["target"]["release_id"]
    assert receipt["completion_claim_allowed"] is False
    pointer = module._load_json(module._state_paths()["pointer"])
    assert pointer["generation"] == 7
    assert pointer["active"]["release_id"] == world["target"]["release_id"]
    assert pointer["previous_verified"] is None
    # Historical release bytes never rewritten.
    assert Path(world["active_path"]).read_bytes() == world["active_manifest_bytes"]
    assert Path(world["previous_path"]).read_bytes() == world["previous_manifest_bytes"]
    target_manifest = module._load_json(Path(world["target_path"]))
    module._validate_release_manifest(target_manifest, Path(world["target_path"]))
    assert set(target_manifest["source_identity"]) == set(module.CURRENT_SOURCE_IDENTITY_KEYS)
    again = module.bootstrap_forward_upgrade()
    assert again["status"] in {"ALREADY_UPGRADED", "ALREADY_CURRENT"}


def test_bootstrap_forward_upgrade_pre_modules_crash_after_pointer_switch_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interrupt after pointer switch → rollback restore; re-entry finishes upgrade."""

    module = _module()
    world = _prepare_pre_modules_forward_upgrade_world(module, tmp_path, monkeypatch)
    original_post = module._project_migration_post_pointer
    calls = {"n": 0}

    def crash_once(journal: dict[str, object]) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise module.XinaoError("INJECTED_CRASH", "after pointer switch")
        return original_post(journal)

    monkeypatch.setattr(module, "_project_migration_post_pointer", crash_once)
    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda journal: _canary_value(module, journal),
    )
    rolled = module.bootstrap_forward_upgrade()
    assert rolled["status"] == "ROLLED_BACK"
    assert rolled["operation"] == "FORWARD_UPGRADE"
    assert module._state_paths()["pointer"].read_bytes() == world["pointer_bytes"]
    assert Path(world["active_path"]).read_bytes() == world["active_manifest_bytes"]
    monkeypatch.setattr(module, "_project_migration_post_pointer", original_post)
    receipt = module.bootstrap_forward_upgrade()
    assert receipt["status"] == "UPGRADED"
    pointer = module._load_json(module._state_paths()["pointer"])
    assert pointer["active"]["release_id"] == world["target"]["release_id"]


def test_bootstrap_forward_upgrade_pre_modules_tamper_rejects_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_pre_modules_forward_upgrade_world(module, tmp_path, monkeypatch)
    active_path = Path(world["active_path"])
    payload = json.loads(active_path.read_text(encoding="utf-8"))
    payload["image_labels"]["io.xinao.researcher.chain"] = "tampered"
    active_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_forward_upgrade()
    assert failure.value.reason_code in {
        "RELEASE_IMAGE_IDENTITY_INVALID",
        "RELEASE_IDENTITY_MISMATCH",
        "RELEASE_MANIFEST_IDENTITY_MISMATCH",
        "RELEASE_POINTER_IDENTITY_MISMATCH",
    }
    assert module._state_paths()["pointer"].read_bytes() == world["pointer_bytes"]


def test_forged_prepared_activate_historical_to_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PREPARED ACTIVATE with historical to must fail journal + switch commitment boundary."""

    module = _module()
    historical, historical_path = _sealed_pre_modules_v2_release(
        module, tmp_path, monkeypatch, image_character="3", variant=b"forged-prepared\n"
    )
    current, current_path = _sealed_current_dual_image_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="4",
        package_version="1.3.6",
        capability_version="1.2.2",
        variant=b"current-active\n",
    )
    # Plant ordinary current pointer first.
    current_ref = module._release_ref_from_manifest(
        current, current_path, activation_txn_id="xra_20260730T120000_" + "4" * 16
    )
    pointer = {
        "schema_version": module.CURRENT_POINTER_SCHEMA,
        "generation": 7,
        "active": current_ref,
        "previous_verified": None,
        "switched_at": "2026-07-30T12:00:00Z",
    }
    pointer_path = module._state_paths()["pointer"]
    module._write_json_atomic(pointer_path, pointer)
    pointer_sha256 = module._sha256(pointer_path)
    historical_ref = module._release_ref_from_manifest(
        historical, historical_path, activation_txn_id="xra_20260730T130000_" + "3" * 16
    )
    txn_id = "xra_20260730T140000_" + "f" * 16
    journal_path = module._journal_path(txn_id)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal = {
        "schema_version": module.ACTIVATION_JOURNAL_SCHEMA,
        "revision": 1,
        "txn_id": txn_id,
        "operation": "ACTIVATE",
        "state": "PREPARED",
        "from": {
            "generation": 7,
            "pointer_sha256": pointer_sha256,
            "active": current_ref,
            "previous_verified": None,
        },
        "requested_to": historical_ref,
        "to": historical_ref,
        "expected_generation": 8,
        "prepared_at": "2026-07-30T14:00:00Z",
        "updated_at": "2026-07-30T14:00:00Z",
        "switched_pointer_sha256": None,
        "canary": None,
        "failure_reason": None,
        "terminal_pointer_sha256": None,
    }
    module._write_json_atomic(journal_path, journal, create_new=True)
    with pytest.raises(module.XinaoError) as journal_fail:
        module._validate_journal(json.loads(journal_path.read_text(encoding="utf-8")), journal_path)
    assert journal_fail.value.reason_code in {
        "RELEASE_SOURCE_IDENTITY_INVALID",
        "RELEASE_SCHEMA_INVALID",
    }
    with pytest.raises(module.XinaoError) as switch_fail:
        module._switch_prepared_pointer(
            json.loads(journal_path.read_text(encoding="utf-8")), journal_path
        )
    assert switch_fail.value.reason_code in {
        "RELEASE_SOURCE_IDENTITY_INVALID",
        "RELEASE_SCHEMA_INVALID",
    }
    # Pointer never mutated.
    assert module._state_paths()["pointer"].read_bytes() == pointer_path.read_bytes()
    assert module._load_json(pointer_path)["active"]["release_id"] == current["release_id"]
