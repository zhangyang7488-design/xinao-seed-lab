from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "invoke_l0_one_command_rerun.py"
    spec = importlib.util.spec_from_file_location("l0_one_command_rerun", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixtures() -> tuple[dict, dict, dict]:
    manifest = {"sha256": "ABC"}
    m1 = {"data_pin": {"sha256": "ABC"}, "sample": {"N": 300}, "completion_claim_allowed": False}
    m2m4 = {
        "data_pin": {"sha256": "ABC"},
        "sample": {"N": 300},
        "n_oos_cycles": 6,
        "not_m1_stub": True,
        "completion_claim_allowed": False,
        "edge_claim": False,
    }
    return manifest, m1, m2m4


def test_acceptance_requires_one_pinned_source_and_real_oos() -> None:
    manifest, m1, m2m4 = _fixtures()

    checks = _module()._acceptance_checks(manifest, "ABC", m1, m2m4)

    assert all(checks.values())


def test_acceptance_rejects_m2m4_snapshot_drift() -> None:
    manifest, m1, m2m4 = _fixtures()
    m2m4["data_pin"]["sha256"] = "DIFFERENT"

    checks = _module()._acceptance_checks(manifest, "ABC", m1, m2m4)

    assert checks["m2m4_uses_same_pinned_snapshot"] is False


def test_m2_command_forces_tsv_pin() -> None:
    command = _module()._m2_command(Path("python"), Path("runner.py"), Path("evidence"))

    assert command[command.index("--prefer") + 1] == "tsv"
