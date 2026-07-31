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
LIVE_GEN6_RELEASE_DIR = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill\researcher_container\releases"
) / LIVE_GEN6_RELEASE_ID
LIVE_GEN6_RELEASE_JSON_SHA256 = (
    "21b712aba72da3e1a24de5347cf7a301ba07afadc479e22d608ca1ee836a734f"
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
    shadow_lock_hash = shadow_lock if shadow_lock is not None else hashes["shadow_runtime_lock_sha256"]
    shadow_tree_hash = shadow_tree if shadow_tree is not None else ("e" * 64)
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
    assert (
        module._source_identity_generation(manifest["source_identity"]) == "pre_modules"
    )


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
        lambda m: m["source_identity"].__setitem__(
            "researcher_image_modules_tree_sha256", "f" * 64
        )
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
        module._validate_journal(
            json.loads(journal_path.read_text(encoding="utf-8")), journal_path
        )
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
    assert observed == "ccba1c6578d0369809de1946d7caa78612176610422531aa871353612235a1df"
    assert len(observed) == 64


def test_wave76b_donor_lock_not_drifted() -> None:
    """Wave76B donor pin must remain the Wave68 Grok 0.2.117 clean image."""

    lock_path = SKILL_ROOT / "references" / "researcher-runtime-lock.v1.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock.get("grok_cli_version") == "0.2.117"
    assert "wave68-grok02117" in str(lock.get("grok_donor_image", ""))
    assert str(lock.get("grok_donor_image_id", "")).startswith("sha256:")
    assert len(str(lock.get("grok_donor_image_id", ""))) == 71
