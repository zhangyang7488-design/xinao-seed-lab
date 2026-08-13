from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from scripts import context_rollout_consumer as consumer
from services.agent_runtime import context_fabric

SESSION_A = "019ff84f-eb50-79e2-b2f8-9f808700ba56"
SESSION_B = "019ff848-3a2e-7493-baf1-c778de8399e1"
SESSION_C = "019ff995-2a5c-7391-9baa-e362ba5f5e4d"
TURN_ID = "turn-context-rollout-consumer"
BASE_NOW = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)


def _line(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )


def _rollout(
    home: Path,
    *,
    session_id: str,
    timestamp: datetime,
    marker: str,
    source: str = "cli",
    thread_source: str = "user",
    subagent: bool = False,
    invalid_complete_line: bool = False,
    payload_timestamp: datetime | None = None,
) -> Path:
    local_timestamp = timestamp.astimezone(consumer.ROLLOUT_LOCAL_TIMEZONE)
    local_day = local_timestamp.date()
    directory = (
        home
        / "sessions"
        / f"{local_day.year:04d}"
        / f"{local_day.month:02d}"
        / f"{local_day.day:02d}"
    )
    directory.mkdir(parents=True, exist_ok=True)
    stamp = local_timestamp.strftime("%Y-%m-%dT%H-%M-%S")
    path = directory / f"rollout-{stamp}-{session_id}.jsonl"
    timestamp_text = (
        (payload_timestamp or timestamp).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    payload: dict[str, object] = {
        "id": session_id,
        "session_id": SESSION_A if subagent else session_id,
        "thread_source": thread_source,
        "source": source,
        "cwd": r"E:\XINAO_RESEARCH_WORKSPACES\S",
        "timestamp": timestamp_text,
    }
    if subagent:
        payload.update(
            {
                "parent_thread_id": SESSION_A,
                "agent_path": "/root/test_worker",
                "agent_role": "worker",
            }
        )
    records = [
        {
            "timestamp": timestamp_text,
            "ordinal": 0,
            "type": "session_meta",
            "payload": payload,
        },
        {
            "timestamp": (timestamp + timedelta(seconds=1))
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "ordinal": 1,
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": session_id,
                "turn_id": TURN_ID,
                "item": {
                    "type": "UserMessage",
                    "id": f"item-{session_id}",
                    "content": [{"type": "text", "text": marker}],
                },
            },
        },
    ]
    body = _line(records[0])
    body += b"{not-valid-json}\n" if invalid_complete_line else _line(records[1])
    path.write_bytes(body)
    modified_ns = int(timestamp.timestamp() * 1_000_000_000)
    os.utime(path, ns=(modified_ns, modified_ns))
    return path


def _runtime(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    root = tmp_path / "fabric"
    context_fabric.initialize_context_fabric(root)
    home = tmp_path / ".codex"
    return root, home, {str(home): "s-primary"}


def _append_user_record(
    path: Path,
    *,
    session_id: str,
    ordinal: int,
    timestamp: datetime,
    marker: str,
    newline: bool = True,
) -> None:
    timestamp_text = timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    record = {
        "timestamp": timestamp_text,
        "ordinal": ordinal,
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "thread_id": session_id,
            "turn_id": TURN_ID,
            "item": {
                "type": "UserMessage",
                "id": f"item-{session_id}-{ordinal}",
                "content": [{"type": "text", "text": marker}],
            },
        },
    }
    encoded = _line(record)
    with path.open("ab") as handle:
        handle.write(encoded if newline else encoded[:-1])


def _raw_messages(root: Path) -> list[str]:
    with sqlite3.connect(root / "context_fabric.sqlite3") as connection:
        return [
            bytes(row[0]).decode("utf-8")
            for row in connection.execute("SELECT raw_text FROM events ORDER BY seq")
        ]


def _mock_installer_audit(
    *,
    last_task_result: int,
    receipt_age_minutes: int = 0,
    extra_receipt_field: str = "",
    extra_file_field: str = "",
    extra_count_field: str = "",
    trusted_acl: bool = True,
    task_has_run: bool = True,
    receipt_status: str = "completed",
    tamper_bundle: bool = False,
    action_drift: bool = False,
    extra_bundle_file: bool = False,
) -> tuple[int, dict[str, object], str]:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    installer = consumer.REPO_ROOT / "scripts" / "Install-SContextRolloutConsumer.ps1"
    extra_json = f',"{extra_receipt_field}":"TOP-SECRET-RAW-BODY"' if extra_receipt_field else ""
    extra_file_json = f',"{extra_file_field}":"TOP-SECRET-NESTED-BODY"' if extra_file_field else ""
    extra_count_json = f',"{extra_count_field}":1' if extra_count_field else ""
    official_python_hash = "ef8f51028ac5329641985112f8efb1c2d4c47c86b8011ddf7e6fae21e2b4e5a1"
    import tempfile

    temporary_root = Path(tempfile.mkdtemp(prefix="xinao-installer-audit-")).resolve()
    try:
        local_app_data = temporary_root / "LocalAppData"
        bundle_base = local_app_data / "XINAO" / "SContextRolloutConsumer"
        payloads: dict[str, bytes] = {
            "python/python.exe": b"mock-official-python-distribution",
            "app/scripts/context_rollout_consumer.py": b"# mock consumer\n",
            "app/services/__init__.py": b"# mock package\n",
            "app/services/agent_runtime/__init__.py": b"# mock package\n",
            "app/services/agent_runtime/context_fabric.py": b"# mock fabric\n",
            "app/services/agent_runtime/context_runtime_completion.py": b"# mock completion\n",
        }
        records: list[dict[str, object]] = []
        for relative_path, body in payloads.items():
            sha256 = (
                official_python_hash
                if relative_path == "python/python.exe"
                else hashlib.sha256(body).hexdigest()
            )
            records.append(
                {
                    "relative_path": relative_path,
                    "size": len(body),
                    "sha256": sha256,
                }
            )
        canonical = "".join(
            f"{record['relative_path']}\0{record['size']}\0{record['sha256']}\n"
            for record in sorted(records, key=lambda item: str(item["relative_path"]))
        ).encode()
        content_id = hashlib.sha256(canonical).hexdigest()
        bundle_root = bundle_base / content_id
        for relative_path, body in payloads.items():
            target = bundle_root / Path(relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        manifest = {
            "schema_version": "s.context_rollout_consumer.bundle.v1",
            "content_id": content_id,
            "files": sorted(records, key=lambda item: str(item["relative_path"])),
            "authority": False,
        }
        manifest_bytes = (
            json.dumps(manifest, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
        )
        (bundle_root / "manifest.json").write_bytes(manifest_bytes)
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        if tamper_bundle:
            (bundle_root / "app" / "scripts" / "context_rollout_consumer.py").write_bytes(
                b"# tampered bundle\n"
            )
        if extra_bundle_file:
            (bundle_root / "app" / "unexpected-secret.txt").write_text(
                "TOP-SECRET-BUNDLE-BODY", encoding="utf-8"
            )
        bundle_python = bundle_root / "python" / "python.exe"
        bundle_consumer = bundle_root / "app" / "scripts" / "context_rollout_consumer.py"
        bundle_working = bundle_root / "app"
        action_execute = Path(r"C:\drift\python.exe") if action_drift else bundle_python
        rule_sid = "$mockSid" if trusted_acl else "'S-1-5-11'"
        command = rf"""
$ErrorActionPreference = 'Stop'
$env:LOCALAPPDATA = '{str(local_app_data).replace("'", "''")}'
$mockSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$mockName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$mockNow = [DateTimeOffset]::Now
$mockLocatorHash = 'a' * 64
$mockToken = 'c' * 32
$mockTaskHasRun = ${str(task_has_run).lower()}
$mockDescription = 'XINAO S context rollout consumer v1; registration=' + $mockToken + ';content_id={content_id};manifest_sha256={manifest_hash}'
$mockReceipt = @'
{{"schema_version":"s.context_rollout_consumer.receipt.v1","status":"{receipt_status}","started_at":"$($mockNow.AddMinutes(-{receipt_age_minutes}).AddSeconds(-20).ToString('o'))","finished_at":"$($mockNow.AddMinutes(-{receipt_age_minutes}).ToString('o'))","bootstrap":false,"state_recovered":false,"scan_start":"$($mockNow.AddMinutes(-{receipt_age_minutes}).AddSeconds(-20).ToString('o'))","scan_end":"$($mockNow.AddMinutes(-{receipt_age_minutes}).AddSeconds(-1).ToString('o'))","counts":{{"appended":1,"inventoried":1{extra_count_json}}},"files":[{{"carrier_id":"s-primary","locator_sha256":"$($mockLocatorHash)","status":"imported","appended":1,"duplicate":0,"ignored":0,"incomplete_tail":false{extra_file_json}}}],"file_receipts_total":1,"file_receipts_omitted":0,"authority":false{extra_json}}}
'@
function Get-ScheduledTask {{
    [CmdletBinding()] param([string]$TaskName, [string]$TaskPath)
    [pscustomobject]@{{
        Description = $mockDescription
        State = 'Ready'
        Principal = [pscustomobject]@{{ UserId = $mockSid; RunLevel = 'Limited'; LogonType = 'Interactive' }}
        Actions = @([pscustomobject]@{{
            Execute = '{str(action_execute).replace("'", "''")}'
            Arguments = '-I -B "{str(bundle_consumer).replace("'", "''")}' + '"'
            WorkingDirectory = '{str(bundle_working).replace("'", "''")}'
        }})
        Triggers = @([pscustomobject]@{{
            Enabled = $true
            StartBoundary = $mockNow.AddDays(-1).ToString('o')
            Repetition = [pscustomobject]@{{ Interval = 'PT2M'; Duration = 'P3650D'; StopAtDurationEnd = $false }}
        }})
        Settings = [pscustomobject]@{{
            MultipleInstances = 'IgnoreNew'
            StartWhenAvailable = $true
            DisallowStartIfOnBatteries = $false
            StopIfGoingOnBatteries = $false
            ExecutionTimeLimit = 'PT5M'
            Enabled = $true
            Hidden = $false
            RunOnlyIfIdle = $false
            WakeToRun = $false
        }}
    }}
}}
function Get-ScheduledTaskInfo {{
    [CmdletBinding()] param([string]$TaskName, [string]$TaskPath)
    [pscustomobject]@{{
        LastTaskResult = {last_task_result}
        LastRunTime = if ($mockTaskHasRun) {{ $mockNow.AddMinutes(-1) }} else {{ [DateTime]::MinValue }}
        NextRunTime = $mockNow.AddMinutes(1)
    }}
}}
function Test-Path {{
    [CmdletBinding()] param([string]$LiteralPath, [string]$PathType)
    if ($LiteralPath -eq 'D:\XINAO_RESEARCH_RUNTIME\state\S_Context_Fabric\_consumer\last_receipt.json') {{ return $true }}
    if ([string]::Equals($PathType, 'Leaf', [System.StringComparison]::OrdinalIgnoreCase)) {{ return [System.IO.File]::Exists($LiteralPath) }}
    if ([string]::Equals($PathType, 'Container', [System.StringComparison]::OrdinalIgnoreCase)) {{ return [System.IO.Directory]::Exists($LiteralPath) }}
    return [System.IO.File]::Exists($LiteralPath) -or [System.IO.Directory]::Exists($LiteralPath)
}}
function Get-Item {{
    [CmdletBinding()] param([string]$LiteralPath, [switch]$Force)
    if ($LiteralPath -eq 'D:\XINAO_RESEARCH_RUNTIME\state\S_Context_Fabric\_consumer\last_receipt.json') {{
        return [pscustomobject]@{{ FullName = $LiteralPath; PSIsContainer = $false; Length = 1024; Attributes = [System.IO.FileAttributes]::Normal }}
    }}
    return Microsoft.PowerShell.Management\Get-Item -LiteralPath $LiteralPath -Force
}}
function Get-Acl {{
    [CmdletBinding()] param([string]$LiteralPath)
    [pscustomobject]@{{
        Owner = $mockSid
        AreAccessRulesProtected = $true
        Access = @([pscustomobject]@{{
            AccessControlType = 'Allow'
            FileSystemRights = [System.Security.AccessControl.FileSystemRights]::FullControl
            IdentityReference = {rule_sid}
            IsInherited = $false
        }}, [pscustomobject]@{{
            AccessControlType = 'Allow'
            FileSystemRights = [System.Security.AccessControl.FileSystemRights]::FullControl
            IdentityReference = 'S-1-5-18'
            IsInherited = $false
        }}, [pscustomobject]@{{
            AccessControlType = 'Allow'
            FileSystemRights = [System.Security.AccessControl.FileSystemRights]::FullControl
            IdentityReference = 'S-1-5-32-544'
            IsInherited = $false
        }})
    }}
}}
function Get-FileHash {{
    [CmdletBinding()] param([string]$LiteralPath, [string]$Algorithm)
    if ($LiteralPath.EndsWith('\python\python.exe', [System.StringComparison]::OrdinalIgnoreCase) -and
        $LiteralPath.Contains('\SContextRolloutConsumer\')) {{
        return [pscustomobject]@{{ Hash = '{official_python_hash}' }}
    }}
    return Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $LiteralPath -Algorithm SHA256
}}
function Get-Content {{
    [CmdletBinding()] param([string]$LiteralPath, [switch]$Raw, [string]$Encoding)
    if ($LiteralPath -eq 'D:\XINAO_RESEARCH_RUNTIME\state\S_Context_Fabric\_consumer\last_receipt.json') {{
        return $ExecutionContext.InvokeCommand.ExpandString($mockReceipt)
    }}
    return Microsoft.PowerShell.Management\Get-Content -LiteralPath $LiteralPath -Raw -Encoding UTF8
}}
. '{str(installer).replace("'", "''")}' -Audit
"""
        encoded = command.encode("utf-16-le")
        completed = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                base64.b64encode(encoded).decode(),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
        assert output_lines, completed.stderr
        return (
            completed.returncode,
            json.loads("\n".join(output_lines)),
            completed.stdout + completed.stderr,
        )
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def _copy_adopted_bundle_sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    python_source = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\cpython-3.13.14-official")
    assert python_source.is_dir()
    python_root = tmp_path / "source-python"
    shutil.copytree(
        python_source,
        python_root,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    app_root = tmp_path / "source-app"
    app_paths = (
        Path("scripts/context_rollout_consumer.py"),
        Path("services/__init__.py"),
        Path("services/agent_runtime/__init__.py"),
        Path("services/agent_runtime/context_fabric.py"),
        Path("services/agent_runtime/context_runtime_completion.py"),
    )
    for relative_path in app_paths:
        destination = app_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        canonical_bytes = subprocess.check_output(
            ["git", "cat-file", "blob", f"HEAD:{relative_path.as_posix()}"],
            cwd=consumer.REPO_ROOT,
        )
        destination.write_bytes(canonical_bytes)
    lock_path = app_root / "scripts" / "context_rollout_consumer.bundle.lock.json"
    shutil.copy2(
        consumer.REPO_ROOT / "scripts" / "context_rollout_consumer.bundle.lock.json",
        lock_path,
    )
    return python_root, app_root, lock_path


def _render_source_lock_installer(
    tmp_path: Path,
    *,
    python_root: Path,
    app_root: Path,
    lock_path: Path,
    expected_lock_sha256: str | None = None,
) -> Path:
    installer = consumer.REPO_ROOT / "scripts" / "Install-SContextRolloutConsumer.ps1"
    script = installer.read_text(encoding="utf-8-sig")

    def replace_once(old: str, new: str) -> None:
        nonlocal script
        assert script.count(old) == 1, old
        script = script.replace(old, new)

    def ps_literal(path: Path) -> str:
        return str(path.resolve()).replace("'", "''")

    replace_once(
        "$sourcePythonRoot = 'D:\\XINAO_RESEARCH_RUNTIME\\tools\\cpython-3.13.14-official'",
        f"$sourcePythonRoot = '{ps_literal(python_root)}'",
    )
    replace_once(
        "$sourcePythonPath = 'D:\\XINAO_RESEARCH_RUNTIME\\tools\\cpython-3.13.14-official\\python.exe'",
        f"$sourcePythonPath = '{ps_literal(python_root / 'python.exe')}'",
    )
    replace_once(
        "$sourceRepositoryRoot = 'E:\\XINAO_RESEARCH_WORKSPACES\\S'",
        f"$sourceRepositoryRoot = '{ps_literal(app_root)}'",
    )
    replace_once(
        "$sourceConsumerScript = 'E:\\XINAO_RESEARCH_WORKSPACES\\S\\scripts\\context_rollout_consumer.py'",
        f"$sourceConsumerScript = '{ps_literal(app_root / 'scripts/context_rollout_consumer.py')}'",
    )
    replace_once(
        "$bundleLockPath = 'E:\\XINAO_RESEARCH_WORKSPACES\\S\\scripts\\context_rollout_consumer.bundle.lock.json'",
        f"$bundleLockPath = '{ps_literal(lock_path)}'",
    )
    if expected_lock_sha256 is not None:
        current_lock_sha256 = hashlib.sha256(
            (consumer.REPO_ROOT / "scripts/context_rollout_consumer.bundle.lock.json").read_bytes()
        ).hexdigest()
        replace_once(
            f"$expectedBundleLockSha256 = '{current_lock_sha256}'",
            f"$expectedBundleLockSha256 = '{expected_lock_sha256}'",
        )
    rendered = tmp_path / "Install-SContextRolloutConsumer.preflight.ps1"
    rendered.write_text(script, encoding="utf-8", newline="\n")
    return rendered


def _run_source_lock_probe(installer: Path) -> tuple[int, dict[str, object], str]:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    command = rf"""
$ErrorActionPreference = 'Stop'
$installerText = [System.IO.File]::ReadAllText('{str(installer).replace("'", "''")}')
$prefix = $installerText.Substring(0, $installerText.IndexOf('function Get-ConsumerTaskAudit'))
. ([scriptblock]::Create($prefix))
try {{
    $plan = @(Get-SourceBundlePlan)
    [ordered]@{{
        status = 'valid'
        file_count = $plan.Count
        total_bytes = [long](($plan | Measure-Object size -Sum).Sum)
        content_id = Get-BundleContentId $plan
    }} | ConvertTo-Json -Compress
    exit 0
}}
catch {{
    [ordered]@{{ status = 'rejected'; error_type = [string]$_.Exception.Message }} |
        ConvertTo-Json -Compress
    exit 2
}}
"""
    completed = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(command.encode("utf-16-le")).decode(),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert output_lines, completed.stderr
    return (
        completed.returncode,
        json.loads(output_lines[-1]),
        completed.stdout + completed.stderr,
    )


def _run_apply_source_rejection(
    installer: Path,
    *,
    local_app_data: Path,
    task_marker: Path,
) -> tuple[int, dict[str, object], str]:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    command = rf"""
$ErrorActionPreference = 'Stop'
$env:LOCALAPPDATA = '{str(local_app_data.resolve()).replace("'", "''")}'
$taskMarker = '{str(task_marker.resolve()).replace("'", "''")}'
function Get-ScheduledTask {{
    [CmdletBinding()] param([string]$TaskName, [string]$TaskPath)
    return $null
}}
function Register-ScheduledTask {{
    [CmdletBinding()] param([string]$TaskName, [string]$TaskPath, [object]$InputObject)
    [System.IO.File]::WriteAllText($taskMarker, 'CALLED')
}}
$failed = $false
$errorType = ''
try {{
    . '{str(installer.resolve()).replace("'", "''")}' -Apply
}}
catch {{
    $failed = $true
    $errorType = [string]$_.Exception.Message
}}
$bundleBase = Join-Path $env:LOCALAPPDATA 'XINAO\SContextRolloutConsumer'
[ordered]@{{
    preflight_failed = $failed
    error_type = $errorType
    task_registered = Test-Path -LiteralPath $taskMarker
    bundle_residual = Test-Path -LiteralPath $bundleBase
}} | ConvertTo-Json -Compress
if ($failed) {{ exit 0 }}
exit 9
"""
    completed = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(command.encode("utf-16-le")).decode(),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert output_lines, completed.stderr
    return (
        completed.returncode,
        json.loads(output_lines[-1]),
        completed.stdout + completed.stderr,
    )


@pytest.mark.parametrize("engine_name", ["pwsh", "powershell"])
def test_installer_removes_only_the_exact_owned_staging_path(
    tmp_path: Path,
    engine_name: str,
) -> None:
    engine = shutil.which(engine_name)
    if engine is None:
        pytest.skip(f"{engine_name} is unavailable")
    installer = consumer.REPO_ROOT / "scripts" / "Install-SContextRolloutConsumer.ps1"
    bundle_base = (tmp_path / "bundle[literal]").resolve()
    content_id = "a" * 64
    registration_token = "b" * 32
    staging = bundle_base / f".{content_id}.staging.{registration_token}"
    sibling = bundle_base / f".{content_id}.staging.{'c' * 32}"
    command = rf"""
$ErrorActionPreference = 'Stop'
$installerText = [System.IO.File]::ReadAllText('{str(installer).replace("'", "''")}')
$prefix = $installerText.Substring(0, $installerText.IndexOf('function New-ProtectedConsumerBundle'))
. ([scriptblock]::Create($prefix))
$bundleBase = '{str(bundle_base).replace("'", "''")}'
$staging = '{str(staging).replace("'", "''")}'
$sibling = '{str(sibling).replace("'", "''")}'
[void][System.IO.Directory]::CreateDirectory($staging)
[void][System.IO.Directory]::CreateDirectory($sibling)
[System.IO.File]::WriteAllText((Join-Path $staging 'owned.txt'), 'owned')
[System.IO.File]::WriteAllText((Join-Path $sibling 'sibling.txt'), 'sibling')
Remove-OwnedBundleStaging $staging '{content_id}' '{registration_token}'
[ordered]@{{
    staging_absent = -not (Test-Path -LiteralPath $staging)
    sibling_present = Test-Path -LiteralPath $sibling
    sibling_body = [System.IO.File]::ReadAllText((Join-Path $sibling 'sibling.txt'))
}} | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(command.encode("utf-16-le")).decode(),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output_lines, completed.stderr
    assert json.loads(output_lines[-1]) == {
        "staging_absent": True,
        "sibling_present": True,
        "sibling_body": "sibling",
    }


@pytest.mark.parametrize("engine_name", ["pwsh", "powershell"])
def test_installer_builds_tiny_bundle_through_real_destination_parent_path(
    tmp_path: Path,
    engine_name: str,
) -> None:
    engine = shutil.which(engine_name)
    if engine is None:
        pytest.skip(f"{engine_name} is unavailable")
    installer = consumer.REPO_ROOT / "scripts" / "Install-SContextRolloutConsumer.ps1"
    bundle_base = (tmp_path / "bundle-build[literal]").resolve()
    python_source = (tmp_path / "source-python.exe").resolve()
    consumer_source = (tmp_path / "source-consumer.py").resolve()
    python_body = b"tiny-python-executable"
    consumer_body = b"# tiny consumer\n"
    python_source.write_bytes(python_body)
    consumer_source.write_bytes(consumer_body)
    registration_token = "d" * 32
    command = rf"""
$ErrorActionPreference = 'Stop'
$installerText = [System.IO.File]::ReadAllText('{str(installer).replace("'", "''")}')
$prefix = $installerText.Substring(0, $installerText.IndexOf('function Get-ConsumerTaskAudit'))
. ([scriptblock]::Create($prefix))
$bundleBase = '{str(bundle_base).replace("'", "''")}'
function Ensure-ProtectedBundleBase {{
    [void][System.IO.Directory]::CreateDirectory($bundleBase)
}}
function Set-ProtectedBundlePathAcl {{ param([string]$LiteralPath) }}
function Set-ProtectedBundleTreeAcl {{ param([string]$BundleRoot) }}
function Test-BundlePayload {{
    param([string]$BundleRoot, [string]$ExpectedContentId, [string]$ExpectedManifestSha256)
    return [pscustomobject]@{{
        valid = $true
        bundle_root = $BundleRoot
        content_id = $ExpectedContentId
        manifest_sha256 = $ExpectedManifestSha256
    }}
}}
$plan = @(
    [pscustomobject]@{{
        relative_path = 'python/python.exe'
        source_path = '{str(python_source).replace("'", "''")}'
        size = {len(python_body)}
        sha256 = '{hashlib.sha256(python_body).hexdigest()}'
    }},
    [pscustomobject]@{{
        relative_path = 'app/scripts/context_rollout_consumer.py'
        source_path = '{str(consumer_source).replace("'", "''")}'
        size = {len(consumer_body)}
        sha256 = '{hashlib.sha256(consumer_body).hexdigest()}'
    }}
)
$result = New-ProtectedConsumerBundle $plan '{registration_token}'
$finalRoot = [string]$result.bundle_root
$stagingResidual = @(
    [System.IO.Directory]::EnumerateDirectories($bundleBase) |
        Where-Object {{ [System.IO.Path]::GetFileName($_).Contains('.staging.') }}
)
[ordered]@{{
    final_root = $finalRoot
    python_body = [System.IO.File]::ReadAllText((Join-Path $finalRoot 'python\python.exe'))
    consumer_body = [System.IO.File]::ReadAllText((Join-Path $finalRoot 'app\scripts\context_rollout_consumer.py'))
    manifest_present = [System.IO.File]::Exists((Join-Path $finalRoot 'manifest.json'))
    staging_residual = $stagingResidual.Count
}} | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(command.encode("utf-16-le")).decode(),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output_lines, completed.stderr
    result = json.loads(output_lines[-1])
    assert Path(result["final_root"]).parent == bundle_base
    assert result["python_body"] == python_body.decode()
    assert result["consumer_body"] == consumer_body.decode()
    assert result["manifest_present"] is True
    assert result["staging_residual"] == 0


def test_bootstrap_imports_only_latest_recent_root_and_never_opens_old_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    old_history = _rollout(
        home,
        session_id=SESSION_C,
        timestamp=datetime(2020, 1, 2, tzinfo=timezone.utc),
        marker="OLD-HISTORY-MUST-NOT-SCAN",
    )
    older = _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(hours=2),
        marker="OLDER-ROOT-MUST-NOT-BOOTSTRAP",
    )
    latest = _rollout(
        home,
        session_id=SESSION_B,
        timestamp=BASE_NOW - timedelta(hours=1),
        marker="LATEST-ROOT-BOOTSTRAP",
    )
    seen: list[Path] = []
    real_classifier = consumer.classify_rollout

    def observing_classifier(path: Path, **kwargs: object) -> consumer.RolloutClassification:
        seen.append(path)
        return real_classifier(path, **kwargs)

    monkeypatch.setattr(consumer, "classify_rollout", observing_classifier)
    receipt = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)

    assert receipt["status"] == "completed"
    assert latest in seen
    assert older in seen
    assert old_history not in seen
    assert _raw_messages(root) == ["LATEST-ROOT-BOOTSTRAP"]
    state = json.loads((root / "_consumer" / "state.json").read_text(encoding="utf-8"))
    assert state["carriers"]["s-primary"]["bootstrap_locator_sha256"] == consumer._locator_sha256(
        str(Path("sessions") / latest.relative_to(home / "sessions"))
    )
    assert not list((root / "_consumer").glob("*.tmp"))


def test_bootstrap_uses_locator_time_and_quarantines_forged_future_session_meta(
    tmp_path: Path,
) -> None:
    root, home, homes = _runtime(tmp_path)
    _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(hours=3),
        marker="GENUINE-OLDER-ROOT",
    )
    forged = _rollout(
        home,
        session_id=SESSION_B,
        timestamp=BASE_NOW - timedelta(hours=2),
        payload_timestamp=datetime(2099, 1, 1, tzinfo=timezone.utc),
        marker="FORGED-FUTURE-MUST-NOT-WIN",
    )
    genuine_latest = _rollout(
        home,
        session_id=SESSION_C,
        timestamp=BASE_NOW - timedelta(hours=1),
        marker="GENUINE-LATEST-ROOT",
    )

    receipt = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)

    assert _raw_messages(root) == ["GENUINE-LATEST-ROOT"]
    forged_hash = consumer._locator_sha256(
        str(Path("sessions") / forged.relative_to(home / "sessions"))
    )
    latest_hash = consumer._locator_sha256(
        str(Path("sessions") / genuine_latest.relative_to(home / "sessions"))
    )
    assert any(
        item.get("locator_sha256") == forged_hash
        and item.get("status") == "quarantined"
        and item.get("error_type") == "session_meta_timestamp_future"
        for item in receipt["files"]
    )
    state = json.loads((root / "_consumer" / "state.json").read_text(encoding="utf-8"))
    assert state["carriers"]["s-primary"]["bootstrap_locator_sha256"] == latest_hash


def test_old_directory_root_is_stat_inventoried_then_promoted_only_after_growth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    old_timestamp = datetime(2020, 1, 2, tzinfo=timezone.utc)
    old = _rollout(
        home,
        session_id=SESSION_C,
        timestamp=old_timestamp,
        marker="OLD-BASELINE-ROOT",
    )
    opened: list[Path] = []
    real_classifier = consumer.classify_rollout

    def observing_classifier(path: Path, **kwargs: object) -> consumer.RolloutClassification:
        opened.append(path)
        return real_classifier(path, **kwargs)

    monkeypatch.setattr(consumer, "classify_rollout", observing_classifier)
    first = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    assert first["counts"]["inventoried"] == 1
    assert old not in opened
    assert _raw_messages(root) == []
    state = json.loads((root / "_consumer" / "state.json").read_text(encoding="utf-8"))
    inventory = state["carriers"]["s-primary"]["inventory"]
    old_locator = str(Path("sessions") / old.relative_to(home / "sessions"))
    old_locator_hash = consumer._locator_sha256(old_locator)
    assert inventory[old_locator_hash] == {
        "mtime_ns": old.stat().st_mtime_ns,
        "size": old.stat().st_size,
    }

    newly_copied_old = _rollout(
        home,
        session_id=SESSION_A,
        timestamp=datetime(2020, 1, 3, tzinfo=timezone.utc),
        marker="NEWLY-COPIED-PRE-CUTOFF",
    )
    copied_old = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(seconds=30),
    )
    assert copied_old["counts"]["new_pre_cutoff_ignored"] == 1
    assert newly_copied_old not in opened

    baseline_size = old.stat().st_size
    touched_ns = int((BASE_NOW + timedelta(minutes=1)).timestamp() * 1_000_000_000)
    os.utime(old, ns=(touched_ns, touched_ns))
    mtime_only = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=1),
    )
    assert mtime_only["counts"]["unadopted_non_growth_ignored"] == 1
    assert old not in opened
    rewritten = old.read_bytes().replace(b"BASELINE", b"REWR1TEN")
    assert len(rewritten) == baseline_size
    old.write_bytes(rewritten)
    rewritten_ns = int((BASE_NOW + timedelta(minutes=2)).timestamp() * 1_000_000_000)
    os.utime(old, ns=(rewritten_ns, rewritten_ns))
    same_size = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=2),
    )
    assert same_size["counts"]["unadopted_non_growth_ignored"] == 1
    assert old not in opened
    assert _raw_messages(root) == []

    _append_user_record(
        old,
        session_id=SESSION_C,
        ordinal=2,
        timestamp=BASE_NOW + timedelta(minutes=1),
        marker="OLD-ROOT-GREW-AFTER-BASELINE",
    )
    changed_ns = int((BASE_NOW + timedelta(minutes=3)).timestamp() * 1_000_000_000)
    os.utime(old, ns=(changed_ns, changed_ns))
    second = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=3),
    )

    assert old in opened
    assert second["counts"]["awaiting_stable"] == 1
    third = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=5),
    )
    assert third["counts"]["imported"] == 1
    assert _raw_messages(root) == ["OLD-REWR1TEN-ROOT", "OLD-ROOT-GREW-AFTER-BASELINE"]


def test_future_root_is_discovered_from_last_scan_and_imported(tmp_path: Path) -> None:
    root, home, homes = _runtime(tmp_path)
    _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=10),
        marker="BOOTSTRAP-ROOT",
    )
    first = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    assert first["counts"]["imported"] == 1

    future = _rollout(
        home,
        session_id=SESSION_B,
        timestamp=BASE_NOW + timedelta(minutes=1),
        marker="FUTURE-ROOT",
    )
    second = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=2),
    )

    assert second["counts"]["awaiting_stable"] == 1
    third = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=4),
    )
    assert third["counts"]["imported"] == 1
    assert _raw_messages(root) == ["BOOTSTRAP-ROOT", "FUTURE-ROOT"]
    future_hash = consumer._locator_sha256(
        str(Path("sessions") / future.relative_to(home / "sessions"))
    )
    assert any(item.get("locator_sha256") == future_hash for item in third["files"])


def test_bootstrap_selects_one_latest_root_for_each_carrier(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    context_fabric.initialize_context_fabric(root)
    home_s = tmp_path / ".codex"
    home_b = tmp_path / ".codex-b"
    homes = {str(home_s): "s-primary", str(home_b): "s-account-b"}
    _rollout(
        home_s,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=2),
        marker="S-LATEST-ROOT",
    )
    _rollout(
        home_b,
        session_id=SESSION_B,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="B-LATEST-ROOT",
    )

    receipt = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)

    assert receipt["counts"]["imported"] == 2
    with sqlite3.connect(root / "context_fabric.sqlite3") as connection:
        carriers = dict(
            connection.execute(
                "SELECT carrier_id,COUNT(*) FROM events GROUP BY carrier_id ORDER BY carrier_id"
            )
        )
    assert carriers == {"s-account-b": 1, "s-primary": 1}


def test_subagent_and_exec_rollouts_are_excluded_by_first_metadata(tmp_path: Path) -> None:
    root, home, homes = _runtime(tmp_path)
    _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=3),
        marker="ROOT-ONLY",
    )
    _rollout(
        home,
        session_id=SESSION_B,
        timestamp=BASE_NOW - timedelta(minutes=2),
        marker="SUBAGENT-MUST-NOT-IMPORT",
        thread_source="subagent",
        subagent=True,
    )
    exec_path = _rollout(
        home,
        session_id=SESSION_C,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="EXEC-MUST-NOT-IMPORT",
        source="exec",
    )

    receipt = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)

    assert receipt["counts"]["classified_excluded_subagent"] == 1
    assert receipt["counts"]["classified_excluded_non_cli"] == 1
    assert consumer.classify_rollout(exec_path).status == "excluded_non_cli"
    assert _raw_messages(root) == ["ROOT-ONLY"]


def test_unchanged_cursor_skips_public_importer_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="UNCHANGED-CURSOR",
    )
    calls = 0
    real_importer = consumer.import_codex_rollout

    def counted_importer(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return real_importer(*args, **kwargs)

    monkeypatch.setattr(consumer, "import_codex_rollout", counted_importer)
    consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    second = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=1),
    )

    assert calls == 1
    assert second["counts"]["unchanged_cursor"] == 1


def test_rotating_periodic_integrity_recheck_detects_same_size_restored_mtime_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    rollout = _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="INTEGRITY-ORIGINAL",
    )
    calls = 0
    real_importer = consumer.import_codex_rollout

    def counted_importer(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return real_importer(*args, **kwargs)

    monkeypatch.setattr(consumer, "import_codex_rollout", counted_importer)
    consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    original_stat = rollout.stat()
    tampered = rollout.read_bytes().replace(b"INTEGRITY-ORIGINAL", b"INTEGRITY-TAMPERED")
    assert len(tampered) == original_stat.st_size
    rollout.write_bytes(tampered)
    os.utime(
        rollout,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )

    before_due = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + consumer.INTEGRITY_RECHECK_INTERVAL - timedelta(seconds=1),
    )
    assert calls == 1
    assert before_due["counts"]["unchanged_cursor"] == 1
    detected = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + consumer.INTEGRITY_RECHECK_INTERVAL,
    )

    assert calls == 2
    assert detected["status"] == "completed_with_errors"
    assert detected["counts"]["file_error"] == 1
    assert detected["files"][0]["error_type"] == "context_fabric_rejected"
    assert "error" not in detected["files"][0]
    quarantined = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + consumer.INTEGRITY_RECHECK_INTERVAL + timedelta(minutes=2),
    )
    assert calls == 2
    assert quarantined["status"] == "completed_with_errors"
    assert quarantined["counts"]["persistent_integrity_quarantine"] == 1
    assert quarantined["files"] == [
        {
            "carrier_id": "s-primary",
            "locator_sha256": consumer._locator_sha256(
                str(Path("sessions") / rollout.relative_to(home / "sessions"))
            ),
            "status": "quarantined",
            "error_type": "context_fabric_rejected",
        }
    ]
    assert "locator" not in quarantined["files"][0]
    assert "error" not in quarantined["files"][0]
    state = json.loads((root / "_consumer" / "state.json").read_text(encoding="utf-8"))
    metadata = next(iter(state["carriers"]["s-primary"]["tracked_roots"].values()))
    assert metadata["last_status"] == "error"
    assert metadata["quarantine_size"] == original_stat.st_size
    assert metadata["quarantine_mtime_ns"] == original_stat.st_mtime_ns

    restored = rollout.read_bytes().replace(b"INTEGRITY-TAMPERED", b"INTEGRITY-ORIGINAL")
    assert len(restored) == original_stat.st_size
    rollout.write_bytes(restored)
    changed_ns = original_stat.st_mtime_ns + 1_000_000_000
    os.utime(rollout, ns=(original_stat.st_atime_ns, changed_ns))
    pending = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + consumer.INTEGRITY_RECHECK_INTERVAL + timedelta(minutes=4),
    )
    assert pending["counts"]["awaiting_stable"] == 1
    recovered = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + consumer.INTEGRITY_RECHECK_INTERVAL + timedelta(minutes=6),
    )
    assert calls == 3
    assert recovered["status"] == "completed"
    assert recovered["counts"]["imported"] == 1
    recovered_state = json.loads((root / "_consumer" / "state.json").read_text(encoding="utf-8"))
    recovered_metadata = next(
        iter(recovered_state["carriers"]["s-primary"]["tracked_roots"].values())
    )
    assert recovered_metadata["last_status"] == "imported"
    assert "quarantine_size" not in recovered_metadata
    assert "quarantine_mtime_ns" not in recovered_metadata


def test_periodic_integrity_recheck_is_bounded_and_rotates_across_carriers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fabric"
    context_fabric.initialize_context_fabric(root)
    home_s = tmp_path / ".codex"
    home_b = tmp_path / ".codex-b"
    homes = {str(home_s): "s-primary", str(home_b): "s-account-b"}
    _rollout(
        home_s,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=2),
        marker="INTEGRITY-S",
    )
    _rollout(
        home_b,
        session_id=SESSION_B,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="INTEGRITY-B",
    )
    calls = 0
    real_importer = consumer.import_codex_rollout

    def counted_importer(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return real_importer(*args, **kwargs)

    monkeypatch.setattr(consumer, "import_codex_rollout", counted_importer)
    consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    assert calls == 2
    first_due = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + consumer.INTEGRITY_RECHECK_INTERVAL,
    )
    assert calls == 3
    assert first_due["counts"]["integrity_verified"] == 1
    assert first_due["counts"]["integrity_recheck_deferred"] == 1
    second_due = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + consumer.INTEGRITY_RECHECK_INTERVAL + timedelta(minutes=2),
    )
    assert calls == 4
    assert second_due["counts"]["integrity_verified"] == 1


def test_stable_completed_roots_are_pruned_after_bounded_canonical_sweep_and_regrow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    rollouts = [
        _rollout(
            home,
            session_id=SESSION_A,
            timestamp=BASE_NOW - timedelta(days=10, minutes=index),
            marker=f"STABLE-HISTORY-{index}",
        )
        for index in range(5)
    ]
    for rollout in rollouts:
        context_fabric.import_codex_rollout(
            rollout,
            carrier_home=home,
            root=root,
            allowed_homes=homes,
        )
    rebuilt = consumer._rebuild_state_from_cursors(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW,
    )
    rebuilt_tracked = rebuilt["carriers"]["s-primary"]["tracked_roots"]
    for metadata in rebuilt_tracked.values():
        metadata["last_integrity_check_at"] = consumer._utc_text(BASE_NOW - timedelta(days=1))
    consumer_dir = consumer._consumer_directory(root)
    consumer._atomic_json(consumer_dir / consumer.STATE_FILE_NAME, rebuilt)
    monkeypatch.setattr(consumer, "INTEGRITY_RECHECK_INTERVAL", timedelta(0))
    monkeypatch.setattr(consumer, "TRACKED_STABLE_PRUNE_AFTER", timedelta(0))

    calls = 0
    classified: list[Path] = []
    real_importer = consumer.import_codex_rollout
    real_classifier = consumer.classify_rollout

    def counted_importer(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return real_importer(*args, **kwargs)

    def observing_classifier(path: Path, **kwargs: object) -> consumer.RolloutClassification:
        classified.append(path)
        return real_classifier(path, **kwargs)

    monkeypatch.setattr(consumer, "import_codex_rollout", counted_importer)
    monkeypatch.setattr(consumer, "classify_rollout", observing_classifier)
    per_run_calls: list[int] = []
    for minute in range(1, 6):
        before = calls
        receipt = consumer.run_consumer(
            root=root,
            allowed_homes=homes,
            now=BASE_NOW + timedelta(minutes=minute),
        )
        per_run_calls.append(calls - before)
        assert receipt["counts"]["integrity_verified"] == 1
        assert receipt["counts"]["stable_roots_pruned"] == 1

    assert per_run_calls == [1, 1, 1, 1, 1]
    state = json.loads((consumer_dir / consumer.STATE_FILE_NAME).read_text(encoding="utf-8"))
    assert state["carriers"]["s-primary"]["tracked_roots"] == {}
    assert len(state["carriers"]["s-primary"]["inventory"]) == len(rollouts)

    touched_ns = int((BASE_NOW + timedelta(minutes=6)).timestamp() * 1_000_000_000)
    os.utime(rollouts[1], ns=(touched_ns, touched_ns))
    same_size_rewrite = rollouts[2].read_bytes().replace(b"STABLE-HISTORY-2", b"STABLE-HIST0RY-2")
    assert len(same_size_rewrite) == rollouts[2].stat().st_size
    rollouts[2].write_bytes(same_size_rewrite)
    os.utime(rollouts[2], ns=(touched_ns, touched_ns))
    before_idle = calls
    idle = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=6),
    )
    assert calls == before_idle
    assert idle["counts"].get("integrity_verified", 0) == 0
    assert idle["counts"]["unadopted_non_growth_ignored"] == 2
    assert classified == []

    grown = rollouts[0]
    _append_user_record(
        grown,
        session_id=SESSION_A,
        ordinal=2,
        timestamp=BASE_NOW + timedelta(minutes=7),
        marker="PRUNED-ROOT-GREW",
    )
    grown_ns = int((BASE_NOW + timedelta(minutes=7)).timestamp() * 1_000_000_000)
    os.utime(grown, ns=(grown_ns, grown_ns))
    pending = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=8),
    )
    assert pending["counts"]["awaiting_stable"] == 1
    imported = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=9),
    )
    assert imported["counts"]["imported"] == 1
    assert calls == before_idle + 1
    assert classified == [grown]
    assert "PRUNED-ROOT-GREW" in _raw_messages(root)


def test_unchanged_incomplete_tail_skips_rehash_until_file_grows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    rollout = _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="COMPLETE-PREFIX",
    )
    _append_user_record(
        rollout,
        session_id=SESSION_A,
        ordinal=2,
        timestamp=BASE_NOW,
        marker="TAIL-WAITS-FOR-NEWLINE",
        newline=False,
    )
    calls = 0
    real_importer = consumer.import_codex_rollout

    def counted_importer(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return real_importer(*args, **kwargs)

    monkeypatch.setattr(consumer, "import_codex_rollout", counted_importer)
    first = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    assert first["files"][0]["incomplete_tail"] is True
    assert calls == 1

    same_size = rollout.stat().st_size
    assert rollout.stat().st_size == same_size
    second = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=1),
    )
    assert calls == 1
    assert second["counts"]["unchanged_incomplete_tail"] == 1

    with rollout.open("ab") as handle:
        handle.write(b"\n")
    grown_ns = int((BASE_NOW + timedelta(minutes=2)).timestamp() * 1_000_000_000)
    os.utime(rollout, ns=(grown_ns, grown_ns))
    third = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=3),
    )
    assert calls == 1
    assert third["counts"]["awaiting_stable"] == 1
    fourth = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=5),
    )
    assert calls == 2
    assert fourth["counts"]["imported"] == 1
    assert _raw_messages(root) == ["COMPLETE-PREFIX", "TAIL-WAITS-FOR-NEWLINE"]


def test_same_size_completed_tail_is_revalidated_after_stable_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    rollout = _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="SAME-SIZE-PREFIX",
    )
    _append_user_record(
        rollout,
        session_id=SESSION_A,
        ordinal=2,
        timestamp=BASE_NOW,
        marker="SAME-SIZE-TAIL-COMPLETED",
        newline=False,
    )
    with rollout.open("ab") as handle:
        handle.write(b"x")
    calls = 0
    real_importer = consumer.import_codex_rollout

    def counted_importer(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return real_importer(*args, **kwargs)

    monkeypatch.setattr(consumer, "import_codex_rollout", counted_importer)
    first = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    assert first["files"][0]["incomplete_tail"] is True
    original_size = rollout.stat().st_size

    with rollout.open("r+b") as handle:
        handle.seek(-1, os.SEEK_END)
        handle.write(b"\n")
    changed_ns = int((BASE_NOW + timedelta(minutes=1)).timestamp() * 1_000_000_000)
    os.utime(rollout, ns=(changed_ns, changed_ns))
    assert rollout.stat().st_size == original_size
    pending = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=2),
    )
    assert pending["counts"]["awaiting_stable"] == 1
    completed = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=4),
    )

    assert calls == 2
    assert completed["counts"]["imported"] == 1
    assert _raw_messages(root) == ["SAME-SIZE-PREFIX", "SAME-SIZE-TAIL-COMPLETED"]


def test_one_bad_rollout_does_not_block_another_future_root(tmp_path: Path) -> None:
    root, home, homes = _runtime(tmp_path)
    _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="BOOTSTRAP",
    )
    consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    bad = _rollout(
        home,
        session_id=SESSION_B,
        timestamp=BASE_NOW + timedelta(minutes=1),
        marker="BAD-MUST-NOT-IMPORT",
        invalid_complete_line=True,
    )
    good = _rollout(
        home,
        session_id=SESSION_C,
        timestamp=BASE_NOW + timedelta(minutes=2),
        marker="GOOD-SURVIVES-BAD-NEIGHBOR",
    )

    deferred = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=3),
    )
    assert deferred["counts"]["awaiting_stable"] == 2
    receipt = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=5),
    )

    assert receipt["status"] == "completed_with_errors"
    bad_hash = consumer._locator_sha256(str(Path("sessions") / bad.relative_to(home / "sessions")))
    good_hash = consumer._locator_sha256(
        str(Path("sessions") / good.relative_to(home / "sessions"))
    )
    by_hash = {str(item["locator_sha256"]): item for item in receipt["files"]}
    assert by_hash[bad_hash]["status"] == "error"
    assert by_hash[good_hash]["status"] == "imported"
    assert _raw_messages(root) == ["BOOTSTRAP", "GOOD-SURVIVES-BAD-NEIGHBOR"]


def test_permanent_failures_back_off_so_sixty_fifth_candidate_is_not_starved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="BOOTSTRAP-BEFORE-BURST",
    )
    consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    candidates: list[Path] = []
    for index in range(65):
        session_id = f"019f{index:04x}-2a5c-7391-9baa-e362ba5f5e4d"
        candidates.append(
            _rollout(
                home,
                session_id=session_id,
                timestamp=BASE_NOW + timedelta(minutes=1, seconds=index),
                marker=f"BURST-{index}",
            )
        )
    first = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=3),
    )
    assert first["counts"]["awaiting_stable"] == 65

    candidate_hashes = {
        path: consumer._locator_sha256(str(Path("sessions") / path.relative_to(home / "sessions")))
        for path in candidates
    }
    ordered = sorted(candidates, key=lambda path: candidate_hashes[path])
    good = ordered[-1]
    calls: dict[Path, int] = {path: 0 for path in candidates}
    real_importer = consumer.import_codex_rollout

    def mostly_rejected(path: Path, **kwargs: object) -> dict[str, object]:
        calls[path] += 1
        if path != good:
            raise context_fabric.ContextFabricError("permanent rejection")
        return real_importer(path, **kwargs)

    monkeypatch.setattr(consumer, "import_codex_rollout", mostly_rejected)
    saturated = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=5),
    )
    assert saturated["counts"]["file_error"] == consumer.MAX_IMPORTS_PER_RUN
    assert saturated["counts"]["deferred"] == 1
    assert calls[good] == 0
    next_run = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=6),
    )
    assert next_run["counts"]["retry_backoff"] == consumer.MAX_IMPORTS_PER_RUN
    assert next_run["counts"]["imported"] == 1
    assert calls[good] == 1
    assert all(calls[path] == 1 for path in ordered[: consumer.MAX_IMPORTS_PER_RUN])
    assert f"BURST-{candidates.index(good)}" in _raw_messages(root)


def test_overlap_returns_typed_skip_without_mutating_consumer_state(tmp_path: Path) -> None:
    root, _home, homes = _runtime(tmp_path)
    consumer_dir = consumer._consumer_directory(root)
    lock = consumer.ConsumerFileLock(consumer_dir / consumer.LOCK_FILE_NAME)
    assert lock.acquire() is True
    try:
        receipt = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    finally:
        lock.release()

    assert receipt["status"] == "skipped_overlap"
    assert receipt["reason"] == "consumer_lock_busy"
    assert not (consumer_dir / "state.json").exists()


def test_file_receipts_are_bounded_while_errors_remain_counted(tmp_path: Path) -> None:
    root, home, homes = _runtime(tmp_path)
    directory = home / "sessions" / "2026" / "08" / "13"
    directory.mkdir(parents=True)
    for index in range(consumer.MAX_RECEIPT_FILES + 7):
        path = directory / f"rollout-invalid-{index:03d}.jsonl"
        path.write_bytes(b"not-json\n")
        modified_ns = int((BASE_NOW - timedelta(minutes=1)).timestamp() * 1_000_000_000)
        os.utime(path, ns=(modified_ns, modified_ns))

    receipt = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)

    assert len(receipt["files"]) == consumer.MAX_RECEIPT_FILES
    assert receipt["file_receipts_total"] == consumer.MAX_RECEIPT_FILES + 7
    assert receipt["file_receipts_omitted"] == 7
    assert receipt["counts"]["quarantined_locator"] == consumer.MAX_RECEIPT_FILES + 7
    assert all(item["status"] == "quarantined" for item in receipt["files"])


def test_consumer_state_receipt_and_typed_errors_do_not_persist_locator_or_secret_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    root = tmp_path / "fabric"
    context_fabric.initialize_context_fabric(root)
    home = tmp_path / f"home-{secret}"
    homes = {str(home): "s-primary"}
    rollout = _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="SAFE-MARKER",
    )

    def rejected_importer(*args: object, **kwargs: object) -> dict[str, object]:
        raise context_fabric.ContextFabricError(f"rejected {secret} at {rollout}")

    monkeypatch.setattr(consumer, "import_codex_rollout", rejected_importer)
    receipt = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)

    assert receipt["files"][0]["error_type"] == "context_fabric_rejected"
    assert "error" not in receipt["files"][0]
    assert "locator" not in receipt["files"][0]
    assert "locator_sha256" in receipt["files"][0]
    persisted = b"".join(path.read_bytes() for path in sorted((root / "_consumer").glob("*.json")))
    assert secret.encode("utf-8") not in persisted
    assert rollout.name.encode("utf-8") not in persisted
    assert str(home).encode("utf-8") not in persisted
    assert secret not in json.dumps(receipt, ensure_ascii=False)


def test_corrupt_state_persists_failed_receipt_then_recovers_only_canonical_cursors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    canonical = _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="CANONICAL-CURSOR-ROOT",
    )
    consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    noncursor = _rollout(
        home,
        session_id=SESSION_B,
        timestamp=datetime(2020, 1, 2, tzinfo=timezone.utc),
        marker="NONCURSOR-HISTORY-MUST-NOT-RECOVER",
    )
    consumer_dir = root / consumer.CONSUMER_DIR_NAME
    state_path = consumer_dir / consumer.STATE_FILE_NAME
    corrupt_secret = "sk-corrupt-state-secret-abcdefghijklmnopqrstuvwxyz"
    corrupt_body = f'{{"broken":"{corrupt_secret}","locator":"{noncursor}"'.encode()
    state_path.write_bytes(corrupt_body)

    first = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=1),
    )
    assert first["status"] == "failed"
    assert first["error_type"] == "consumer_state_invalid"
    assert first["recovery_status"] == "pending_next_run"
    persisted_first = json.loads(
        (consumer_dir / consumer.LAST_RECEIPT_FILE_NAME).read_text(encoding="utf-8")
    )
    assert persisted_first == first
    assert not state_path.exists()
    first_persisted_json = b"".join(
        path.read_bytes() for path in sorted(consumer_dir.glob("*.json"))
    )
    assert corrupt_secret.encode() not in first_persisted_json
    assert noncursor.name.encode() not in first_persisted_json

    classified: list[Path] = []
    imported: list[Path] = []
    real_classifier = consumer.classify_rollout
    real_importer = consumer.import_codex_rollout

    def observing_classifier(path: Path, **kwargs: object) -> consumer.RolloutClassification:
        classified.append(path)
        return real_classifier(path, **kwargs)

    def observing_importer(path: Path, **kwargs: object) -> dict[str, object]:
        imported.append(path)
        return real_importer(path, **kwargs)

    monkeypatch.setattr(consumer, "classify_rollout", observing_classifier)
    monkeypatch.setattr(consumer, "import_codex_rollout", observing_importer)
    second = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=2),
    )

    assert second["status"] == "completed"
    assert second["state_recovered"] is True
    assert second["counts"]["state_recovered"] == 1
    assert noncursor not in classified
    assert noncursor not in imported
    assert _raw_messages(root) == ["CANONICAL-CURSOR-ROOT"]
    recovered_state = json.loads(state_path.read_text(encoding="utf-8"))
    tracked = recovered_state["carriers"]["s-primary"]["tracked_roots"]
    canonical_hash = consumer._locator_sha256(
        str(Path("sessions") / canonical.relative_to(home / "sessions"))
    )
    noncursor_hash = consumer._locator_sha256(
        str(Path("sessions") / noncursor.relative_to(home / "sessions"))
    )
    assert set(tracked) == {canonical_hash}
    assert noncursor_hash not in tracked
    quarantine = json.loads(
        (consumer_dir / consumer.STATE_QUARANTINE_FILE_NAME).read_text(encoding="utf-8")
    )
    assert quarantine["status"] == "recovered"
    persisted = b"".join(path.read_bytes() for path in sorted(consumer_dir.glob("*.json")))
    assert corrupt_secret.encode() not in persisted
    assert noncursor.name.encode() not in persisted
    assert str(noncursor).encode() not in persisted


@pytest.mark.parametrize("retain_receipt", [True, False])
def test_missing_state_is_recovered_from_cursors_without_bootstrapping_noncursor_history(
    tmp_path: Path,
    retain_receipt: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, home, homes = _runtime(tmp_path)
    canonical = _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=2),
        marker="MISSING-STATE-CANONICAL",
    )
    consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    consumer_dir = root / consumer.CONSUMER_DIR_NAME
    state_path = consumer_dir / consumer.STATE_FILE_NAME
    receipt_path = consumer_dir / consumer.LAST_RECEIPT_FILE_NAME
    state_path.unlink()
    if not retain_receipt:
        receipt_path.unlink()
    noncursor = _rollout(
        home,
        session_id=SESSION_B,
        timestamp=BASE_NOW + timedelta(minutes=1),
        marker="MISSING-STATE-NONCURSOR-MUST-NOT-BOOTSTRAP",
    )
    classified: list[Path] = []
    imported: list[Path] = []
    real_classifier = consumer.classify_rollout
    real_importer = consumer.import_codex_rollout

    def observing_classifier(path: Path, **kwargs: object) -> consumer.RolloutClassification:
        classified.append(path)
        return real_classifier(path, **kwargs)

    def observing_importer(path: Path, **kwargs: object) -> dict[str, object]:
        imported.append(path)
        return real_importer(path, **kwargs)

    monkeypatch.setattr(consumer, "classify_rollout", observing_classifier)
    monkeypatch.setattr(consumer, "import_codex_rollout", observing_importer)
    first = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=2),
    )

    assert first["status"] == "failed"
    assert first["error_type"] == "consumer_state_invalid"
    assert first["recovery_status"] == "pending_next_run"
    assert classified == []
    assert imported == []
    assert not state_path.exists()
    marker = json.loads(
        (consumer_dir / consumer.STATE_QUARANTINE_FILE_NAME).read_text(encoding="utf-8")
    )
    assert marker["status"] == "pending_recovery"

    second = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=3),
    )

    assert second["status"] == "completed"
    assert second["bootstrap"] is False
    assert second["state_recovered"] is True
    assert second["counts"]["state_recovered"] == 1
    assert noncursor not in classified
    assert noncursor not in imported
    assert _raw_messages(root) == ["MISSING-STATE-CANONICAL"]
    recovered = json.loads(state_path.read_text(encoding="utf-8"))
    tracked = recovered["carriers"]["s-primary"]["tracked_roots"]
    canonical_hash = consumer._locator_sha256(
        str(Path("sessions") / canonical.relative_to(home / "sessions"))
    )
    noncursor_hash = consumer._locator_sha256(
        str(Path("sessions") / noncursor.relative_to(home / "sessions"))
    )
    assert set(tracked) == {canonical_hash}
    assert noncursor_hash not in tracked


def test_installer_has_exact_current_user_ignore_new_contract() -> None:
    script = (consumer.REPO_ROOT / "scripts" / "Install-SContextRolloutConsumer.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "[ValidateSet(1, 2, 5)]" in script
    assert "[int]$Minutes = 2" in script
    assert "XINAO-S-Context-Rollout-Consumer-v1" in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "-AllowStartIfOnBatteries" in script
    assert "-DontStopIfGoingOnBatteries" in script
    assert "-I -B" in script
    assert "-RunLevel Limited" in script
    assert "WindowsIdentity]::GetCurrent().Name" in script
    assert "WindowsIdentity]::GetCurrent().User.Value" in script
    assert "Resolve-IdentitySid" in script
    assert '"PT$([int]$ExpectedMinutes)M"' in script
    assert "D:\\XINAO_RESEARCH_RUNTIME\\tools\\cpython-3.13.14-official\\python.exe" in script
    assert "E:\\XINAO_RESEARCH_WORKSPACES\\S\\scripts\\context_rollout_consumer.py" in script
    assert "Get-ConsumerTaskAudit" in script
    assert "action_valid" in script
    assert "disallow_start_on_batteries" in script
    assert "contract_valid" in script
    assert "description_valid" in script
    assert "trigger_enabled" in script
    assert "start_boundary_valid" in script
    assert "repetition_duration_valid" in script
    assert "StopAtDurationEnd" in script
    assert "Settings.Enabled" in script
    assert "Settings.Hidden" in script
    assert "Settings.RunOnlyIfIdle" in script
    assert "Settings.WakeToRun" in script
    assert "-TaskPath $taskPath" in script
    assert "Principal.LogonType" in script
    assert "Refusing to remove" in script
    assert "Refusing to overwrite" in script
    assert "$createdThisInvocation = $false" in script
    assert "$createdThisInvocation = $true" in script
    assert "$rollbackCandidate.Description" in script
    assert "refusing rollback deletion" in script
    assert "apply rollback did not read back absent" in script
    assert "-ExpectedRegistrationToken $registrationToken" in script
    assert "Get-ScheduledTaskInfo" in script
    assert "LastTaskResult" in script
    assert "consumer_receipt_status" in script
    assert "consumer_health" in script
    assert "last_receipt.json" in script
    assert "Test-TrustedPathAcl" in script
    assert "payload_acl_valid" in script
    assert "S-1-5-11" not in script
    assert "content_id=" in script and "manifest_sha256=" in script
    assert "s.context_rollout_consumer.bundle.v1" in script
    assert "SContextRolloutConsumer" in script
    assert "[System.IO.Directory]::Move($stagingRoot, $finalRoot)" in script
    assert "SetAccessRuleProtection($true, $false)" in script
    assert "__pycache__" in script and "'.pyc'" in script
    assert "EF8F51028AC5329641985112F8EFB1C2D4C47C86B8011DDF7E6FAE21E2B4E5A1".lower() in script
    assert "FullControl -bor" not in script
    lock_path = consumer.REPO_ROOT / "scripts/context_rollout_consumer.bundle.lock.json"
    lock_bytes = lock_path.read_bytes()
    release_lock = json.loads(lock_bytes)
    assert hashlib.sha256(lock_bytes).hexdigest() in script
    assert release_lock.keys() == {
        "schema_version",
        "authority",
        "source_identity",
        "content_id",
        "files",
    }
    assert release_lock["schema_version"] == "s.context_rollout_consumer.bundle_lock.v1"
    assert release_lock["authority"] is False
    assert release_lock["source_identity"] == {
        "application": "xinao-s-context-rollout-consumer",
        "release": "2026-08-13",
        "python_distribution": "cpython-3.13.14-official",
    }
    assert release_lock["content_id"] == (
        "882dda531d281ac73a8ed447a438a79f511310ef1b5bd4af6ebe8b363b27f823"
    )
    assert len(release_lock["files"]) == 1332
    locked_paths = [item["relative_path"] for item in release_lock["files"]]
    assert locked_paths == sorted(locked_paths)
    assert len({path.casefold() for path in locked_paths}) == len(locked_paths)
    locked_by_path = {item["relative_path"]: item for item in release_lock["files"]}
    assert locked_by_path["app/scripts/context_rollout_consumer.py"] == {
        "relative_path": "app/scripts/context_rollout_consumer.py",
        "size": 62777,
        "sha256": "fd352a4f3f47c040f11ea2ceedd63fb41a0c80ef37123424da33aa8e42dc8764",
    }
    assert locked_by_path["app/services/agent_runtime/context_fabric.py"]["sha256"] == (
        "5d6b8cd173d85ad866d3593a68072e308faa9d636121f3d25e2a346f80a622fd"
    )
    assert (
        locked_by_path["app/services/agent_runtime/context_runtime_completion.py"]["sha256"]
        == "1d61bb13e345172650d50636d87915e8dd956c1257089075a6c59ea27f045b2f"
    )
    apply_source_plan_index = script.index("$sourcePlan = @(Get-SourceBundlePlan)")
    assert apply_source_plan_index < script.index(
        "New-ProtectedConsumerBundle", apply_source_plan_index
    )
    assert apply_source_plan_index < script.index("Register-ScheduledTask", apply_source_plan_index)
    assert "Get-FileHash" in script
    assert "if (-not $result.installation_valid)" in script
    assert "installed_pending_first_run" in script
    assert (
        "Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -InputObject $definition |"
        in script
    )
    assert (
        "Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -InputObject $definition -Force"
        not in script
    )
    assert "-Apply" in script and "-Remove" in script and "-Audit" in script
    assert "RunLevel Highest" not in script
    assert consumer.PRODUCTION_CONTEXT_FABRIC_ROOT == Path(
        r"D:\XINAO_RESEARCH_RUNTIME\state\S_Context_Fabric"
    )
    with pytest.raises(SystemExit):
        consumer._parser().parse_args(["--store-root", "elsewhere"])


def test_installer_source_release_lock_accepts_only_the_adopted_source_plan(
    tmp_path: Path,
) -> None:
    python_root, app_root, lock_path = _copy_adopted_bundle_sources(tmp_path)
    installer = _render_source_lock_installer(
        tmp_path,
        python_root=python_root,
        app_root=app_root,
        lock_path=lock_path,
    )

    exit_code, result, raw_output = _run_source_lock_probe(installer)

    assert exit_code == 0, raw_output
    assert result == {
        "status": "valid",
        "file_count": 1332,
        "total_bytes": 40_796_469,
        "content_id": "882dda531d281ac73a8ed447a438a79f511310ef1b5bd4af6ebe8b363b27f823",
    }
    assert not (tmp_path / "LocalAppData" / "XINAO").exists()


def test_bundle_release_lock_matches_fresh_head_lf_application_bytes() -> None:
    lock = json.loads(
        (consumer.REPO_ROOT / "scripts/context_rollout_consumer.bundle.lock.json").read_bytes()
    )
    locked_by_path = {item["relative_path"]: item for item in lock["files"]}
    source_paths = (
        Path("scripts/context_rollout_consumer.py"),
        Path("services/__init__.py"),
        Path("services/agent_runtime/__init__.py"),
        Path("services/agent_runtime/context_fabric.py"),
        Path("services/agent_runtime/context_runtime_completion.py"),
    )

    for source_path in source_paths:
        canonical_bytes = subprocess.check_output(
            ["git", "cat-file", "blob", f"HEAD:{source_path.as_posix()}"],
            cwd=consumer.REPO_ROOT,
        )
        assert b"\r\n" not in canonical_bytes
        locked_path = (
            f"app/{source_path.as_posix()}"
            if source_path.parts[0] != "scripts"
            else "app/scripts/context_rollout_consumer.py"
        )
        assert locked_by_path[locked_path] == {
            "relative_path": locked_path,
            "size": len(canonical_bytes),
            "sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        }
        attributes = subprocess.check_output(
            ["git", "check-attr", "text", "eol", "--", source_path.as_posix()],
            cwd=consumer.REPO_ROOT,
            text=True,
        )
        assert f"{source_path.as_posix()}: text: set" in attributes
        assert f"{source_path.as_posix()}: eol: lf" in attributes

    canonical_manifest = "".join(
        f"{item['relative_path']}\0{item['size']}\0{item['sha256']}\n" for item in lock["files"]
    ).encode()
    assert hashlib.sha256(canonical_manifest).hexdigest() == lock["content_id"]


def test_installer_apply_preflight_rejects_source_and_lock_tamper_without_residue(
    tmp_path: Path,
) -> None:
    python_root, app_root, lock_path = _copy_adopted_bundle_sources(tmp_path)
    local_app_data = tmp_path / "LocalAppData"
    task_marker = tmp_path / "task-registration.marker"
    original_lock = lock_path.read_bytes()

    def assert_apply_rejected(
        label: str,
        expected_error: str,
        *,
        repin_lock: bool = False,
    ) -> None:
        rendered_dir = tmp_path / "rendered" / label
        rendered_dir.mkdir(parents=True, exist_ok=True)
        lock_sha256 = hashlib.sha256(lock_path.read_bytes()).hexdigest() if repin_lock else None
        installer = _render_source_lock_installer(
            rendered_dir,
            python_root=python_root,
            app_root=app_root,
            lock_path=lock_path,
            expected_lock_sha256=lock_sha256,
        )
        exit_code, result, raw_output = _run_apply_source_rejection(
            installer,
            local_app_data=local_app_data,
            task_marker=task_marker,
        )
        assert exit_code == 0, raw_output
        assert result["preflight_failed"] is True
        assert expected_error in result["error_type"]
        assert result["task_registered"] is False
        assert result["bundle_residual"] is False
        assert not task_marker.exists()
        assert not (local_app_data / "XINAO" / "SContextRolloutConsumer").exists()

    consumer_path = app_root / "scripts" / "context_rollout_consumer.py"
    original_consumer = consumer_path.read_bytes()
    try:
        consumer_path.write_bytes(b"")
        assert_apply_rejected("consumer-empty", "does not match the adopted release lock")
        consumer_path.write_bytes(original_consumer + b"\n# NONEMPTY-TAMPER\n")
        assert_apply_rejected("consumer-tamper", "does not match the adopted release lock")
    finally:
        consumer_path.write_bytes(original_consumer)

    for label, relative_path in (
        ("dll-tamper", Path("python313.dll")),
        ("stdlib-tamper", Path("Lib/json/__init__.py")),
    ):
        target = python_root / relative_path
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"TAMPER")
            assert_apply_rejected(label, "does not match the adopted release lock")
        finally:
            target.write_bytes(original)

    extra_source = python_root / "unexpected-release-file.dll"
    extra_source.write_bytes(b"unexpected")
    try:
        assert_apply_rejected("source-extra", "file set does not match")
    finally:
        extra_source.unlink()
    held_source = tmp_path / "held-stdlib.py"
    missing_source = python_root / "Lib" / "json" / "scanner.py"
    missing_source.replace(held_source)
    try:
        assert_apply_rejected("source-missing", "file set does not match")
    finally:
        held_source.replace(missing_source)

    lock_path.write_bytes(original_lock + b" ")
    try:
        assert_apply_rejected("lock-hash-tamper", "bundle lock hash is invalid")
    finally:
        lock_path.write_bytes(original_lock)

    def write_structurally_tampered_lock(mutator: object) -> None:
        value = json.loads(original_lock)
        assert callable(mutator)
        mutator(value)
        lock_path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    structural_cases: tuple[tuple[str, object, str], ...] = (
        (
            "lock-extra",
            lambda value: value["files"].append(
                {"relative_path": "python/zz-extra", "size": 1, "sha256": "0" * 64}
            ),
            "bundle lock schema is invalid",
        ),
        (
            "lock-missing",
            lambda value: value["files"].pop(),
            "bundle lock schema is invalid",
        ),
        (
            "lock-unsorted",
            lambda value: value["files"].__setitem__(
                slice(0, 2), list(reversed(value["files"][:2]))
            ),
            "not strictly sorted",
        ),
        (
            "lock-duplicate",
            lambda value: value["files"].__setitem__(1, dict(value["files"][0])),
            "not strictly sorted",
        ),
        (
            "lock-unsafe-path",
            lambda value: value["files"][0].__setitem__("relative_path", "../escape"),
            "invalid file record",
        ),
        (
            "lock-record-extra-field",
            lambda value: value["files"][0].__setitem__("raw_source", "TOP-SECRET"),
            "invalid file record",
        ),
        (
            "lock-header-extra-field",
            lambda value: value.__setitem__("raw_source", "TOP-SECRET"),
            "bundle lock schema is invalid",
        ),
    )
    for label, mutator, expected_error in structural_cases:
        try:
            write_structurally_tampered_lock(mutator)
            assert_apply_rejected(label, expected_error, repin_lock=True)
        finally:
            lock_path.write_bytes(original_lock)


@pytest.mark.parametrize(
    ("last_result", "age_minutes", "extra_field", "trusted_acl", "health"),
    [
        (1, 0, "", True, "task_last_result_nonzero"),
        (0, 30, "", True, "receipt_stale"),
        (0, 0, "raw_locator", True, "receipt_invalid"),
        (0, 0, "", False, "installation_drifted"),
    ],
)
def test_installer_audit_fails_closed_for_runtime_health_and_payload_trust(
    last_result: int,
    age_minutes: int,
    extra_field: str,
    trusted_acl: bool,
    health: str,
) -> None:
    exit_code, audit, raw_output = _mock_installer_audit(
        last_task_result=last_result,
        receipt_age_minutes=age_minutes,
        extra_receipt_field=extra_field,
        trusted_acl=trusted_acl,
    )

    assert exit_code != 0
    assert audit["valid"] is False
    assert audit["consumer_health"] == health
    assert audit["status"] in {"installed_degraded", "installed_drifted"}
    assert "TOP-SECRET-RAW-BODY" not in raw_output
    assert "raw_locator" not in raw_output


def test_installer_audit_accepts_only_fresh_completed_receipt_and_zero_task_result() -> None:
    exit_code, audit, raw_output = _mock_installer_audit(
        last_task_result=0,
        receipt_age_minutes=0,
        trusted_acl=True,
    )

    assert exit_code == 0, raw_output
    assert audit["status"] == "installed_valid"
    assert audit["valid"] is True
    assert audit["installation_valid"] is True
    assert audit["health_valid"] is True
    assert audit["payload_acl_valid"] is True
    assert audit["payload_hash_valid"] is True
    assert audit["consumer_receipt_schema_valid"] is True
    assert audit["consumer_receipt_fresh"] is True
    assert audit["consumer_health"] == "healthy"


@pytest.mark.parametrize(
    ("tamper_bundle", "extra_bundle_file", "action_drift", "expected_field"),
    [
        (True, False, False, "payload_hash_valid"),
        (False, True, False, "payload_hash_valid"),
        (False, False, True, "action_valid"),
    ],
)
def test_installer_audit_rejects_bundle_tamper_extra_files_and_action_drift(
    tamper_bundle: bool,
    extra_bundle_file: bool,
    action_drift: bool,
    expected_field: str,
) -> None:
    exit_code, audit, raw_output = _mock_installer_audit(
        last_task_result=0,
        trusted_acl=True,
        tamper_bundle=tamper_bundle,
        extra_bundle_file=extra_bundle_file,
        action_drift=action_drift,
    )

    assert exit_code != 0
    assert audit["valid"] is False
    assert audit["installation_valid"] is False
    assert audit[expected_field] is False
    assert audit["status"] == "installed_drifted"
    assert "TOP-SECRET-BUNDLE-BODY" not in raw_output


@pytest.mark.parametrize(
    ("extra_file_field", "extra_count_field", "validation"),
    [
        ("raw_locator", "", "receipt_import_file_invalid"),
        ("body", "", "receipt_import_file_invalid"),
        ("", "unknown_count", "receipt_count_invalid"),
    ],
)
def test_installer_rejects_unknown_nested_receipt_fields_without_echoing_them(
    extra_file_field: str,
    extra_count_field: str,
    validation: str,
) -> None:
    exit_code, audit, raw_output = _mock_installer_audit(
        last_task_result=0,
        extra_file_field=extra_file_field,
        extra_count_field=extra_count_field,
        trusted_acl=True,
    )

    assert exit_code != 0
    assert audit["valid"] is False
    assert audit["consumer_receipt_schema_valid"] is False
    assert audit["consumer_receipt_validation"] == validation
    assert audit["consumer_health"] == "receipt_invalid"
    assert "TOP-SECRET-NESTED-BODY" not in raw_output
    assert "raw_locator" not in raw_output
    assert "unknown_count" not in raw_output


def test_installer_first_run_is_installation_valid_but_health_pending() -> None:
    exit_code, audit, _raw_output = _mock_installer_audit(
        last_task_result=0,
        task_has_run=False,
        trusted_acl=True,
    )

    assert exit_code != 0
    assert audit["status"] == "installed_pending"
    assert audit["installation_valid"] is True
    assert audit["valid"] is False
    assert audit["consumer_health"] == "pending_first_run"


def test_installer_completed_with_errors_is_degraded_not_valid() -> None:
    exit_code, audit, _raw_output = _mock_installer_audit(
        last_task_result=0,
        receipt_status="completed_with_errors",
        trusted_acl=True,
    )

    assert exit_code != 0
    assert audit["installation_valid"] is True
    assert audit["valid"] is False
    assert audit["consumer_health"] == "degraded"
