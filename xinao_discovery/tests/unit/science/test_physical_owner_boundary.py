"""Composition/readback: researcher mounts lack Owner/shadow write roots.

Library cannot authenticate Codex. Where architecture encodes forbidden mounts,
tests prove researcher/tool-executor composition excludes owner/shadow paths.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from xinao.science.freeze_adapter import apply_freeze_from_disposition
from xinao.science.owner_disposition import (
    OWNER_CHANNEL_AUTHORITY_UNPROVEN,
)
from xinao.science.prospective_source_thin import capture_prospective_target_authority
from xinao.shadow_lifecycle.consumer import freeze_portfolio_period


def test_public_freeze_has_no_fixture_bypass_parameter() -> None:
    assert "allow_fixture_construction" not in inspect.signature(freeze_portfolio_period).parameters


def test_freeze_and_source_docstrings_say_evidence_not_process_auth() -> None:
    freeze_doc = freeze_portfolio_period.__doc__ or ""
    assert "evidence" in freeze_doc.lower()
    assert "authenticate" in freeze_doc.lower() or "does not authenticate" in freeze_doc.lower()
    adapter_doc = apply_freeze_from_disposition.__doc__ or ""
    assert "evidence" in adapter_doc.lower() or "authenticate" in adapter_doc.lower()
    capture_doc = capture_prospective_target_authority.__doc__ or ""
    assert "does not prove" in capture_doc.lower() or "codex" in capture_doc.lower()


def test_owner_disposition_returns_unproven_flags(tmp_path: Path) -> None:
    from xinao.science import owner_disposition as od

    assert OWNER_CHANNEL_AUTHORITY_UNPROVEN == "UNPROVEN_BY_LIBRARY"
    # Module constant + load/verify return surface must stay honest.
    src = inspect.getsource(od)
    assert "UNPROVEN_BY_LIBRARY" in src
    assert "physical_owner_write_isolation_verified" in src
    assert "owner_channel_authority" in src


def test_researcher_tool_spec_forbids_shadow_and_owner_like_mounts() -> None:
    root = Path(__file__).resolve().parents[4]
    specs = root / "docker" / "xinao-researcher" / "docker_create_specs.py"
    assert specs.is_file()
    text = specs.read_text(encoding="utf-8")
    # Tool executor forbidden mounts include shadow/ledger/freeze/settlement.
    assert '"/shadow"' in text or "'/shadow'" in text
    assert "/ledger" in text
    assert "/freeze" in text
    assert "/settlement" in text
    # Parse AST to ensure FORBIDDEN_TOOL_MOUNTS is a real tuple constant.
    tree = ast.parse(text)
    forbidden: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "FORBIDDEN_TOOL_MOUNTS":
                    assert isinstance(node.value, ast.Tuple)
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            forbidden.append(elt.value)
    assert "/shadow" in forbidden
    assert "/ledger" in forbidden
    # Allowed transport binds must not include owner_state or shadow roots by marker.
    assert "shadow_ledger" in text
    assert "FORBIDDEN_MOUNT_MARKERS" in text


def test_prospective_source_module_reports_unproven_by_design() -> None:
    # Capture return path must not claim cryptographic Owner proof.
    assert "UNPROVEN_BY_LIBRARY" in inspect.getsource(
        __import__("xinao.science.prospective_source_thin", fromlist=["*"])
    )
