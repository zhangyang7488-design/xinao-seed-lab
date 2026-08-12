from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "Protect-SContextFabricState.ps1"
PWSH = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\powershell\7.6.4\pwsh.exe")


def test_acl_script_refuses_every_non_production_target(tmp_path: Path) -> None:
    command = [
        str(PWSH),
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(SCRIPT),
        "-Root",
        str(tmp_path),
    ]
    completed = subprocess.run(command, capture_output=True, check=False)
    assert completed.returncode != 0
    combined = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
    assert "Refusing ACL operation outside the exact S Context Fabric root" in combined


def test_acl_script_source_is_bounded_and_apply_is_explicit() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "D:\\XINAO_RESEARCH_RUNTIME\\state\\S_Context_Fabric" in text
    assert "[switch]$Apply" in text
    assert "if ($Apply)" in text
    assert "SetAccessRuleProtection($true, $false)" in text
    assert "Set-Acl -LiteralPath $resolved" in text
    assert "S-1-5-18" in text
    assert "S-1-5-32-544" in text
    assert "missing_full_control_count" in text
    assert "($_.Rights -band $fullControl) -eq $fullControl" in text
