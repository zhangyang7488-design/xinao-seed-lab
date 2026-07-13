from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RECOVERY_SCRIPTS = REPO_ROOT / "scripts" / "recovery"


def test_downstream_recovery_is_restore_oriented_and_disclosure_scoped() -> None:
    backup = (RECOVERY_SCRIPTS / "Backup-XinaoDownstreamState.ps1").read_text(
        encoding="utf-8"
    )
    drill = (RECOVERY_SCRIPTS / "Test-XinaoDownstreamRecovery.ps1").read_text(
        encoding="utf-8"
    )
    restore = (RECOVERY_SCRIPTS / "Restore-XinaoDownstreamState.ps1").read_text(
        encoding="utf-8"
    )

    assert "pg_dump" in backup
    assert "--format=c" in backup
    assert "--no-owner" in backup
    assert "credentials_exported = $false" in backup
    assert "pg_dumpall" not in backup
    assert "Config.Env" not in backup
    assert "SkipLatestPointer" in backup
    assert "verified_quiesced_snapshot" in backup
    assert "application_writes_quiesced" in backup
    assert "opaque_payloads_may_contain_user_task_material" in backup
    assert "naijiu-shiwu" in backup
    assert "postgres_isolated_restore_drill" in drill
    assert "pg_restore" in drill
    assert "temporal_langgraph_real_canary" in drill
    assert "canonical_grok_real_canary" in drill
    assert "runtimeClosureRequested" in drill
    assert "closure_claim_allowed" in drill
    assert "existing_target_preserved" in restore
    assert "pre_restore_snapshot" in restore
    assert "rollback_attempted" in restore
    assert "-SkipLatestPointer" in restore
    assert "RunRestoreDrill = $true" in restore


def test_downstream_recovery_defaults_large_state_to_d_drive() -> None:
    for name in (
        "Backup-XinaoDownstreamState.ps1",
        "Test-XinaoDownstreamRecovery.ps1",
        "Restore-XinaoDownstreamState.ps1",
    ):
        text = (RECOVERY_SCRIPTS / name).read_text(encoding="utf-8")
        assert "D:\\XINAO_RESEARCH_RUNTIME" in text
        assert "Desktop" not in text
