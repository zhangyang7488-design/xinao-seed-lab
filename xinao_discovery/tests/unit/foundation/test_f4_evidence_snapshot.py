from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from xinao.foundation import f4_evidence_snapshot as snapshot


def _source_tree(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    external = tmp_path / "external" / "leaf.json"
    source.mkdir(parents=True)
    external.parent.mkdir(parents=True)
    external.write_text('{"leaf":true}\n', encoding="utf-8")
    (source / "child.json").write_text('{"value":1}\n', encoding="utf-8")
    (source / "index.json").write_text(
        json.dumps(
            {
                "pack_ref": str(source.resolve()),
                "child_ref": str(external.resolve()),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return source, external


def _build(tmp_path: Path, name: str = "snapshot") -> Path:
    source, _ = _source_tree(tmp_path)
    builder = snapshot.EvidenceSnapshotBuilder(
        tmp_path / name,
        allowed_source_roots=[tmp_path],
    )
    builder.add_root("primary", source)
    return builder.build()


def _rewrite_manifest(path: Path, value: dict[str, object]) -> None:
    core = dict(value)
    core.pop("content_sha256", None)
    value["content_sha256"] = snapshot.canonical_sha256(core)
    path.write_bytes(snapshot.canonical_json_bytes(value))


def test_snapshot_identity_is_output_root_independent_and_movable(tmp_path: Path) -> None:
    source, external = _source_tree(tmp_path)
    manifests = []
    for name in ("capsule-a", "capsule-b"):
        builder = snapshot.EvidenceSnapshotBuilder(
            tmp_path / name,
            allowed_source_roots=[tmp_path],
        )
        builder.add_root("primary", source)
        manifests.append(builder.build())

    assert manifests[0].read_bytes() == manifests[1].read_bytes()
    resolver = snapshot.SnapshotResolver(manifests[0])
    logical_ref = "root/primary/index.json"
    retained = resolver.load_json(logical_ref)
    assert retained["pack_ref"] == str(source.resolve())
    assert retained["child_ref"] == str(external.resolve())
    assert resolver.resolve_reference(
        source_ref=logical_ref,
        json_pointer="/pack_ref",
        recorded_value=retained["pack_ref"],
    ) == resolver.logical_root("primary")
    assert (
        resolver.resolve_reference(
            source_ref=logical_ref,
            json_pointer="/child_ref",
            recorded_value=retained["child_ref"],
        ).read_bytes()
        == external.read_bytes()
    )

    moved = tmp_path / "moved-capsule"
    shutil.copytree(manifests[0].parent, moved)
    moved_resolver = snapshot.SnapshotResolver(moved / snapshot.MANIFEST_NAME)
    assert moved_resolver.load_json(logical_ref) == retained
    assert str(moved) in str(
        moved_resolver.resolve_reference(
            source_ref=logical_ref,
            json_pointer="/child_ref",
            recorded_value=retained["child_ref"],
        )
    )


@pytest.mark.parametrize("mutation", ["missing", "extra", "hash", "size"])
def test_snapshot_exact_inventory_rejects_file_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest_path = _build(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = manifest_path.parent / manifest["inventory"][0]["relative_path"]
    if mutation == "missing":
        target.unlink()
    elif mutation == "extra":
        (manifest_path.parent / "extra.bin").write_bytes(b"extra")
    elif mutation == "hash":
        target.write_bytes(target.read_bytes() + b"drift")
    else:
        manifest["inventory"][0]["size_bytes"] += 1
        manifest["inventory_sha256"] = snapshot.canonical_sha256(manifest["inventory"])
        _rewrite_manifest(manifest_path, manifest)

    with pytest.raises(snapshot.SnapshotError):
        snapshot.verify_snapshot_manifest(manifest_path)


def test_snapshot_manifest_rejects_traversal_and_casefold_aliases(tmp_path: Path) -> None:
    manifest_path = _build(tmp_path)
    original = json.loads(manifest_path.read_text(encoding="utf-8"))

    traversal = copy.deepcopy(original)
    traversal["inventory"][0]["relative_path"] = "../escape"
    traversal["inventory_sha256"] = snapshot.canonical_sha256(traversal["inventory"])
    _rewrite_manifest(manifest_path, traversal)
    with pytest.raises(snapshot.SnapshotError, match=r"canonical|absolute"):
        snapshot.verify_snapshot_manifest(manifest_path)

    _rewrite_manifest(manifest_path, original)
    collision = copy.deepcopy(original)
    duplicate = copy.deepcopy(collision["logical_refs"][0])
    duplicate["logical_ref"] = duplicate["logical_ref"].upper()
    collision["logical_refs"].append(duplicate)
    collision["logical_refs"].sort(key=lambda item: item["logical_ref"])
    collision["logical_ref_count"] += 1
    collision["full_archival_logical_ref_count"] += 1
    _rewrite_manifest(manifest_path, collision)
    with pytest.raises(snapshot.SnapshotError, match="casefold"):
        snapshot.verify_snapshot_manifest(manifest_path)


def test_snapshot_reparse_and_live_fallback_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _build(tmp_path)
    resolver = snapshot.SnapshotResolver(manifest_path)
    with pytest.raises(snapshot.SnapshotError, match="no declared edge"):
        resolver.resolve_reference(
            source_ref="root/primary/index.json",
            json_pointer="/not-recorded",
            recorded_value=str((tmp_path / "source" / "child.json").resolve()),
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = (
        manifest_path.parent / Path(*manifest["inventory"][0]["relative_path"].split("/"))
    ).resolve()
    original_is_reparse = snapshot._is_reparse

    def marked(path: Path) -> bool:
        return path.resolve() == target or original_is_reparse(path)

    monkeypatch.setattr(snapshot, "_is_reparse", marked)
    with pytest.raises(snapshot.SnapshotError, match="reparse"):
        snapshot.verify_snapshot_manifest(manifest_path)


def test_path_registry_binds_uri_manifest_path_and_rejects_edge_retarget(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    external = tmp_path / "external"
    source.mkdir()
    external.mkdir()
    left = external / "left.json"
    right = external / "right.json"
    left.write_text('{"side":"left"}\n', encoding="utf-8")
    right.write_text('{"side":"right"}\n', encoding="utf-8")
    (source / "index.json").write_text(
        json.dumps(
            {
                "uri": str(left.resolve()),
                "manifest_path": str(right.resolve()),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    builder = snapshot.EvidenceSnapshotBuilder(
        tmp_path / "snapshot",
        allowed_source_roots=[tmp_path],
    )
    builder.add_root("primary", source)
    manifest_path = builder.build()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    edges = {edge["json_pointer"]: edge for edge in manifest["reference_edges"]}
    assert set(edges) == {"/manifest_path", "/uri"}

    tampered = copy.deepcopy(manifest)
    by_pointer = {edge["json_pointer"]: edge for edge in tampered["reference_edges"]}
    by_pointer["/uri"]["target_ref"] = by_pointer["/manifest_path"]["target_ref"]
    _rewrite_manifest(manifest_path, tampered)
    with pytest.raises(snapshot.SnapshotError, match="retargeted"):
        snapshot.verify_snapshot_manifest(manifest_path)


def test_same_bytes_keep_distinct_logical_identities_but_share_cas(tmp_path: Path) -> None:
    source = tmp_path / "source"
    external = tmp_path / "external"
    source.mkdir()
    external.mkdir()
    left = external / "left.json"
    right = external / "right.json"
    left.write_bytes(b'{"same":true}\n')
    right.write_bytes(left.read_bytes())
    (source / "index.json").write_text(
        json.dumps({"left_ref": str(left.resolve()), "right_ref": str(right.resolve())}) + "\n",
        encoding="utf-8",
    )
    builder = snapshot.EvidenceSnapshotBuilder(
        tmp_path / "snapshot",
        allowed_source_roots=[tmp_path],
    )
    builder.add_root("primary", source)
    manifest = json.loads(builder.build().read_text(encoding="utf-8"))
    external_refs = [
        item
        for item in manifest["logical_refs"]
        if item["logical_ref"].startswith("external/reference/")
    ]
    assert len(external_refs) == 2
    assert len({item["logical_ref"] for item in external_refs}) == 2
    assert len({item["source_identity"] for item in external_refs}) == 2
    assert len({item["cas_ref"] for item in external_refs}) == 1


def test_empty_files_are_valid_but_empty_directory_targets_fail_closed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "empty.bin").write_bytes(b"")
    builder = snapshot.EvidenceSnapshotBuilder(tmp_path / "valid")
    builder.add_root("primary", source)
    manifest = snapshot.verify_snapshot_manifest(builder.build())
    empty = next(item for item in manifest["logical_refs"] if item["size_bytes"] == 0)
    assert empty["size_bytes"] == 0

    empty_directory = source / "empty-directory"
    empty_directory.mkdir()
    (source / "index.json").write_text(
        json.dumps({"path": str(empty_directory.resolve())}) + "\n",
        encoding="utf-8",
    )
    rejected = snapshot.EvidenceSnapshotBuilder(
        tmp_path / "rejected",
        allowed_source_roots=[tmp_path],
    )
    rejected.add_root("primary", source)
    with pytest.raises(snapshot.SnapshotError, match="no archived files"):
        rejected.build()


def test_overlapping_roots_and_self_rehashed_graph_or_path_lies_are_rejected(
    tmp_path: Path,
) -> None:
    source, _ = _source_tree(tmp_path)
    nested = source / "nested"
    nested.mkdir()
    (nested / "value.txt").write_text("value", encoding="utf-8")
    builder = snapshot.EvidenceSnapshotBuilder(tmp_path / "overlap")
    builder.add_root("parent", source)
    with pytest.raises(snapshot.SnapshotError, match="overlap"):
        builder.add_root("child", nested)

    graph_root = tmp_path / "graph-fixture"
    graph_root.mkdir()
    manifest_path = _build(graph_root, "graph")
    original = json.loads(manifest_path.read_text(encoding="utf-8"))
    graph_lie = copy.deepcopy(original)
    graph_lie["reachable_logical_ref_count"] -= 1
    _rewrite_manifest(manifest_path, graph_lie)
    with pytest.raises(snapshot.SnapshotError, match="reachable"):
        snapshot.verify_snapshot_manifest(manifest_path)

    _rewrite_manifest(manifest_path, original)
    path_lie = copy.deepcopy(original)
    path_lie["inventory"][0]["relative_path"] = "C:drive-relative"
    path_lie["inventory_sha256"] = snapshot.canonical_sha256(path_lie["inventory"])
    _rewrite_manifest(manifest_path, path_lie)
    with pytest.raises(snapshot.SnapshotError, match="drive-relative"):
        snapshot.verify_snapshot_manifest(manifest_path)


def test_source_alias_cannot_hide_a_nested_reparse_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    alias_target = tmp_path / "alias-target"
    nested = alias_target / "child"
    source.mkdir()
    nested.mkdir(parents=True)
    (nested / "leaf.json").write_text('{"ok":true}\n', encoding="utf-8")
    (source / "index.json").write_text(
        json.dumps({"child_ref": "/logical/child/leaf.json"}) + "\n",
        encoding="utf-8",
    )
    original_is_reparse = snapshot._is_reparse

    def marked(path: Path) -> bool:
        return path.absolute() == nested.absolute() or original_is_reparse(path)

    monkeypatch.setattr(snapshot, "_is_reparse", marked)
    builder = snapshot.EvidenceSnapshotBuilder(
        tmp_path / "snapshot",
        allowed_source_roots=[tmp_path],
        source_aliases={"/logical": alias_target},
    )
    builder.add_root("primary", source)
    with pytest.raises(snapshot.SnapshotError, match="reparse"):
        builder.build()


@pytest.mark.parametrize(
    "recorded",
    [
        "/logical/../outside/leaf.json",
        "/logical/child:stream/leaf.json",
        "/logical/child//leaf.json",
        "/logical/child./leaf.json",
        "/logical/CON/leaf.json",
        "/logical//?/C:/outside/leaf.json",
    ],
)
def test_source_alias_suffix_rejects_noncanonical_windows_spellings(
    tmp_path: Path,
    recorded: str,
) -> None:
    source = tmp_path / "source"
    alias_target = tmp_path / "alias-target"
    source.mkdir()
    alias_target.mkdir()
    (source / "index.json").write_text(
        json.dumps({"child_ref": recorded}) + "\n",
        encoding="utf-8",
    )
    builder = snapshot.EvidenceSnapshotBuilder(
        tmp_path / "snapshot",
        allowed_source_roots=[tmp_path],
        source_aliases={"/logical": alias_target},
    )
    builder.add_root("primary", source)
    with pytest.raises(snapshot.SnapshotError):
        builder.build()


@pytest.mark.parametrize("key", ["uri", "manifest_path"])
def test_declared_missing_absolute_local_reference_fails_closed(
    tmp_path: Path,
    key: str,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    missing = tmp_path / "missing" / "operation-spec.json"
    (source / "index.json").write_text(
        json.dumps({key: str(missing.resolve())}) + "\n",
        encoding="utf-8",
    )
    builder = snapshot.EvidenceSnapshotBuilder(
        tmp_path / "snapshot",
        allowed_source_roots=[tmp_path],
    )
    builder.add_root("primary", source)
    with pytest.raises(snapshot.SnapshotError, match="required local reference is missing"):
        builder.build()


def test_semantic_reference_is_not_misclassified_as_a_missing_local_path(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.json").write_text(
        json.dumps(
            {
                "schema_ref": "schema:xinao.contract.v1",
                "implementation_ref": "xinao.foundation.worker.run",
                "uri": "https://example.invalid/schema.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    builder = snapshot.EvidenceSnapshotBuilder(tmp_path / "snapshot")
    builder.add_root("primary", source)
    manifest = snapshot.verify_snapshot_manifest(builder.build())
    assert manifest["reference_edge_count"] == 0


@pytest.mark.parametrize("mutation", ["hash", "missing", "extra-file", "extra-directory"])
def test_logical_root_revalidates_exact_tree_after_resolver_initialization(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest_path = _build(tmp_path)
    resolver = snapshot.SnapshotResolver(manifest_path)
    root = manifest_path.parent / "roots" / "primary"
    if mutation == "hash":
        (root / "child.json").write_bytes(b'{"drift":true}\n')
    elif mutation == "missing":
        (root / "child.json").unlink()
    elif mutation == "extra-file":
        (root / "extra.json").write_text("{}\n", encoding="utf-8")
    else:
        (root / "empty-extra").mkdir()

    with pytest.raises(snapshot.SnapshotError):
        resolver.logical_root("primary")
    assert resolver.trace_report()["event_count"] == 0


def test_logical_file_and_root_reject_post_init_reparse_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _build(tmp_path)
    resolver = snapshot.SnapshotResolver(manifest_path)
    primary = manifest_path.parent / "roots" / "primary"
    original_is_reparse = snapshot._is_reparse

    def marked(path: Path) -> bool:
        return path.absolute() == primary.absolute() or original_is_reparse(path)

    monkeypatch.setattr(snapshot, "_is_reparse", marked)
    with pytest.raises(snapshot.SnapshotError, match="reparse"):
        resolver.logical_path("root/primary/child.json")
    with pytest.raises(snapshot.SnapshotError, match="reparse"):
        resolver.logical_root("primary")
    assert resolver.trace_report()["event_count"] == 0


def test_directory_edge_reachability_is_limited_to_the_target_subtree(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    selected = data / "a"
    sibling = data / "b"
    entry = tmp_path / "entry.json"
    selected.mkdir(parents=True)
    sibling.mkdir(parents=True)
    (selected / "x.json").write_text('{"selected":true}\n', encoding="utf-8")
    (sibling / "y.json").write_text('{"sibling":true}\n', encoding="utf-8")
    entry.write_text(json.dumps({"path": str(selected.resolve())}) + "\n", encoding="utf-8")

    builder = snapshot.EvidenceSnapshotBuilder(
        tmp_path / "snapshot",
        allowed_source_roots=[tmp_path],
    )
    builder.add_root("data", data, entry_point=False)
    builder.add_file("entry", entry)
    manifest = snapshot.verify_snapshot_manifest(builder.build())

    assert manifest["full_archival_logical_ref_count"] == 3
    assert manifest["reachable_logical_ref_count"] == 2
    edge = manifest["reference_edges"][0]
    assert edge["target_kind"] == "directory"
    assert edge["target_relative_path"] == "a"


def test_missing_optional_local_ref_is_diagnostic_and_has_no_fallback(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    missing = tmp_path / "removed" / "state.json"
    (source / "index.json").write_text(
        json.dumps(
            {
                "last_state_ref": str(missing.resolve()),
                "frontier_ref": r"/app/D:\XINAO_RESEARCH_RUNTIME/state/frontier.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    builder = snapshot.EvidenceSnapshotBuilder(
        tmp_path / "snapshot",
        allowed_source_roots=[tmp_path],
    )
    builder.add_root("primary", source)
    manifest_path = builder.build()
    manifest = snapshot.verify_snapshot_manifest(manifest_path)
    diagnostics = {item["json_pointer"]: item for item in manifest["unresolved_metadata_refs"]}
    assert manifest["unresolved_metadata_ref_count"] == 2
    assert diagnostics["/last_state_ref"]["reason"] == "missing_local_target"
    assert diagnostics["/frontier_ref"]["reason"] == "invalid_local_identity"
    resolver = snapshot.SnapshotResolver(manifest_path)
    with pytest.raises(snapshot.SnapshotError, match="no declared edge"):
        resolver.resolve_reference(
            source_ref="root/primary/index.json",
            json_pointer="/last_state_ref",
            recorded_value=str(missing.resolve()),
        )


def test_consumer_registry_promotes_optional_pointer_to_required(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.json").write_text(
        json.dumps({"last_state_ref": str((tmp_path / "missing.json").resolve())}) + "\n",
        encoding="utf-8",
    )
    builder = snapshot.EvidenceSnapshotBuilder(
        tmp_path / "snapshot",
        allowed_source_roots=[tmp_path],
        required_reference_registry={
            "source": "test.consumer",
            "version": "v1",
            "rules": [
                {
                    "rule_id": "last-state",
                    "source_ref_glob": "root/primary/*",
                    "json_pointer_glob": "/last_state_ref",
                    "expected_match_count": 1,
                }
            ],
        },
    )
    builder.add_root("primary", source)
    with pytest.raises(snapshot.SnapshotError, match="required local reference is missing"):
        builder.build()


def test_consumer_registry_rule_must_match_its_exact_declared_count(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "history.json"
    target.write_text("{}\n", encoding="utf-8")
    (source / "index.json").write_text(
        json.dumps({"history_ref": str(target.resolve())}) + "\n",
        encoding="utf-8",
    )
    builder = snapshot.EvidenceSnapshotBuilder(
        tmp_path / "snapshot",
        allowed_source_roots=[tmp_path],
        required_reference_registry={
            "source": "test.consumer",
            "version": "v1",
            "rules": [
                {
                    "rule_id": "history",
                    "source_ref_glob": "root/primary/*",
                    "json_pointer_glob": "/histroy_ref",
                    "expected_match_count": 1,
                }
            ],
        },
    )
    builder.add_root("primary", source)
    with pytest.raises(snapshot.SnapshotError, match="match count drifted"):
        builder.build()


def test_registry_and_unresolved_diagnostics_are_self_authenticating(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.json").write_text(
        json.dumps({"last_state_ref": str((tmp_path / "missing.json").resolve())}) + "\n",
        encoding="utf-8",
    )
    builder = snapshot.EvidenceSnapshotBuilder(tmp_path / "snapshot")
    builder.add_root("primary", source)
    manifest_path = builder.build()
    original = json.loads(manifest_path.read_text(encoding="utf-8"))

    registry_lie = copy.deepcopy(original)
    registry_lie["required_reference_registry"]["source"] = "tampered"
    _rewrite_manifest(manifest_path, registry_lie)
    with pytest.raises(snapshot.SnapshotError, match="registry identity"):
        snapshot.verify_snapshot_manifest(manifest_path)

    missing_diagnostic = copy.deepcopy(original)
    missing_diagnostic["unresolved_metadata_refs"] = []
    missing_diagnostic["unresolved_metadata_ref_count"] = 0
    _rewrite_manifest(manifest_path, missing_diagnostic)
    with pytest.raises(snapshot.SnapshotError, match="neither bound nor diagnosed"):
        snapshot.verify_snapshot_manifest(manifest_path)
