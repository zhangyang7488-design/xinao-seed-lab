import json
from pathlib import Path

from services.agent_runtime import task_package_resolver as resolver


def test_manifest_resources_are_current_package_and_exclude_reference_only(tmp_path: Path) -> None:
    root = tmp_path / "新系统"
    root.mkdir()
    (root / "current.txt").write_text("current\n", encoding="utf-8")
    (root / "plan.txt").write_text("plan\n", encoding="utf-8")
    (root / "old.txt").write_text("old\n", encoding="utf-8")
    (root / "TASK_PACKAGE.json").write_text(
        json.dumps(
            {
                "package_mode": "unit_current",
                "entrypoint": "current.txt",
                "resources": [
                    {"path": "current.txt", "role": "entrypoint"},
                    {"path": "plan.txt", "role": "plan"},
                    {"path": "old.txt", "read": "reference_only"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    package = resolver.resolve_task_package(root, include_manifest_ref=False)

    assert package["package_mode"] == "unit_current"
    assert package["resolution"] == "task_package_manifest"
    assert package["manifest_driven"] is True
    assert package["legacy_fallback"] is False
    assert [Path(ref["path"]).name for ref in package["refs"]] == ["current.txt", "plan.txt"]
    assert "old.txt" not in package["required_files"]
    assert package["all_required_sources_read_full"] is True


def test_explicit_entry_path_is_single_file_package_without_code_name_change(
    tmp_path: Path,
) -> None:
    root = tmp_path / "新系统"
    root.mkdir()
    entry = tmp_path / "new_task.txt"
    entry.write_text("new task\n", encoding="utf-8")

    package = resolver.resolve_task_package(root, entry_path=entry)

    assert package["resolution"] == "explicit_task_entry_path"
    assert package["single_entry_driven"] is True
    assert package["legacy_fallback"] is False
    assert package["required_files"] == ["new_task.txt"]
    assert package["refs"][0]["path"] == str(entry)


def test_legacy_authority_is_only_fallback_when_no_current_anchor(tmp_path: Path) -> None:
    root = tmp_path / "新系统"
    root.mkdir()
    (root / "AUTHORITY_READ_ORDER.txt").write_text("legacy\n", encoding="utf-8")

    package = resolver.resolve_task_package(root)

    assert package["resolution"] == "legacy_authority_fallback"
    assert package["legacy_fallback"] is True
    assert package["manifest_driven"] is False
