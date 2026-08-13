[CmdletBinding()]
param(
    [string]$ReceiptRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\S_Context_Fabric\_consumer\presentation_delivery_receipts'
)

$ErrorActionPreference = 'Stop'
$requestSchema = 's.presentation_notify_icon.request.v1'
$receiptSchema = 's.presentation_notify_icon.receipt.v1'
$adapterId = 'windows_notify_icon.v1'

function Get-Sha256Hex {
    param([byte[]]$Bytes)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-Utf8Sha256 {
    param([string]$Text)
    return Get-Sha256Hex ([System.Text.UTF8Encoding]::new($false).GetBytes($Text))
}

function Test-ExactPropertySet {
    param([object]$Value, [string[]]$Names)
    if ($null -eq $Value) { return $false }
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($Names | Sort-Object)
    return [string]::Equals(
        ($actual -join "`n"),
        ($expected -join "`n"),
        [System.StringComparison]::Ordinal
    )
}

function Test-ReparsePoint {
    param([string]$LiteralPath)
    if (-not (Test-Path -LiteralPath $LiteralPath)) { return $false }
    $item = Get-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop
    return (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
}

function Read-ExistingReceipt {
    param(
        [string]$LiteralPath,
        [string]$DeliveryKey,
        [string]$BodySha256,
        [string]$TitleSha256
    )
    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) { return $null }
    if (Test-ReparsePoint $LiteralPath) { throw 'Presentation receipt cannot be a reparse point.' }
    $item = Get-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop
    if ($item.Length -lt 2 -or $item.Length -gt 16KB) {
        throw 'Presentation receipt size is invalid.'
    }
    $receipt = Get-Content -LiteralPath $LiteralPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
    if (-not (Test-ExactPropertySet $receipt @(
                'schema_version', 'adapter_id', 'delivery_key', 'receipt_id',
                'title_sha256', 'body_sha256', 'delivered_at', 'ui_interception_claimed',
                'authority'
            )) -or
        -not [string]::Equals([string]$receipt.schema_version, $receiptSchema, [System.StringComparison]::Ordinal) -or
        -not [string]::Equals([string]$receipt.adapter_id, $adapterId, [System.StringComparison]::Ordinal) -or
        -not [string]::Equals([string]$receipt.delivery_key, $DeliveryKey, [System.StringComparison]::Ordinal) -or
        -not [string]::Equals([string]$receipt.body_sha256, $BodySha256, [System.StringComparison]::Ordinal) -or
        -not [string]::Equals([string]$receipt.title_sha256, $TitleSha256, [System.StringComparison]::Ordinal) -or
        [string]$receipt.receipt_id -notmatch '^presentation_toast_[0-9a-f]{64}$' -or
        $receipt.ui_interception_claimed -isnot [bool] -or $receipt.ui_interception_claimed -ne $false -or
        $receipt.authority -isnot [bool] -or $receipt.authority -ne $false) {
        throw 'Presentation receipt identity is invalid.'
    }
    return [string]$receipt.receipt_id
}

try {
    $requestText = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($requestText) -or $requestText.Length -gt 16KB) {
        throw 'Presentation notification request is absent or oversized.'
    }
    $request = $requestText | ConvertFrom-Json -ErrorAction Stop
    if (-not (Test-ExactPropertySet $request @('schema_version', 'delivery_key', 'title', 'body')) -or
        -not [string]::Equals([string]$request.schema_version, $requestSchema, [System.StringComparison]::Ordinal) -or
        [string]$request.delivery_key -notmatch '^delivery_[0-9a-f]{64}$') {
        throw 'Presentation notification request identity is invalid.'
    }
    $deliveryKey = [string]$request.delivery_key
    $title = ([string]$request.title).Trim()
    $body = ([string]$request.body).Trim()
    if ([string]::IsNullOrWhiteSpace($title) -or $title.Length -gt 96 -or
        [string]::IsNullOrWhiteSpace($body) -or $body.Length -gt 8192) {
        throw 'Presentation notification text is invalid.'
    }
    if (-not [System.IO.Path]::IsPathRooted($ReceiptRoot)) {
        throw 'Presentation receipt root must be absolute.'
    }
    if (Test-ReparsePoint $ReceiptRoot) {
        throw 'Presentation receipt root cannot be a reparse point.'
    }
    if (-not (Test-Path -LiteralPath $ReceiptRoot -PathType Container)) {
        [void][System.IO.Directory]::CreateDirectory($ReceiptRoot)
    }
    $resolvedReceiptRoot = (Get-Item -LiteralPath $ReceiptRoot -Force -ErrorAction Stop).FullName
    if (Test-ReparsePoint $resolvedReceiptRoot) {
        throw 'Presentation receipt root cannot be a reparse point.'
    }
    $receiptPath = Join-Path $resolvedReceiptRoot ($deliveryKey + '.json')
    $bodySha256 = Get-Utf8Sha256 $body
    $titleSha256 = Get-Utf8Sha256 $title
    $receiptId = 'presentation_toast_' + $deliveryKey.Substring('delivery_'.Length)

    $mutexName = 'Local\XINAO.S.PresentationDelivery.' + $deliveryKey.Substring('delivery_'.Length)
    $mutex = [System.Threading.Mutex]::new($false, $mutexName)
    $acquired = $false
    try {
        $acquired = $mutex.WaitOne([TimeSpan]::FromSeconds(5))
        if (-not $acquired) { throw 'Presentation notification delivery is busy.' }
        $existing = Read-ExistingReceipt $receiptPath $deliveryKey $bodySha256 $titleSha256
        if ($null -ne $existing) {
            [Console]::Out.WriteLine($existing)
            exit 0
        }

        if (-not [Environment]::UserInteractive) {
            throw 'Presentation notification has no interactive desktop.'
        }
        $sessionId = (Get-Process -Id $PID -ErrorAction Stop).SessionId
        $hasExplorer = @(Get-Process -Name explorer -ErrorAction SilentlyContinue | Where-Object {
                $_.SessionId -eq $sessionId
            }).Count -gt 0
        if (-not $hasExplorer) {
            throw 'Presentation notification has no Explorer desktop in this session.'
        }

        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        Add-Type -AssemblyName System.Drawing -ErrorAction Stop
        $notifyIcon = New-Object System.Windows.Forms.NotifyIcon
        try {
            $notifyIcon.Icon = [System.Drawing.SystemIcons]::Information
            $notifyIcon.Visible = $true
            $notifyIcon.BalloonTipTitle = $title.Substring(0, [Math]::Min($title.Length, 63))
            $notifyIcon.BalloonTipText = $body.Substring(0, [Math]::Min($body.Length, 240))
            $notifyIcon.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
            $notifyIcon.ShowBalloonTip(6000)
            Start-Sleep -Milliseconds 1000
        }
        finally {
            $notifyIcon.Visible = $false
            $notifyIcon.Dispose()
        }

        $receipt = [ordered]@{
            schema_version = $receiptSchema
            adapter_id = $adapterId
            delivery_key = $deliveryKey
            receipt_id = $receiptId
            title_sha256 = $titleSha256
            body_sha256 = $bodySha256
            delivered_at = [DateTimeOffset]::UtcNow.ToString('o')
            ui_interception_claimed = $false
            authority = $false
        }
        $json = ($receipt | ConvertTo-Json -Depth 4 -Compress) + "`n"
        $temporary = Join-Path $resolvedReceiptRoot ('.' + $deliveryKey + '.' + $PID + '.tmp')
        if (Test-Path -LiteralPath $temporary) {
            throw 'Presentation receipt temporary path already exists.'
        }
        try {
            [System.IO.File]::WriteAllText($temporary, $json, [System.Text.UTF8Encoding]::new($false))
            [System.IO.File]::Move($temporary, $receiptPath)
        }
        finally {
            if (Test-Path -LiteralPath $temporary) {
                Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
            }
        }
        $readback = Read-ExistingReceipt $receiptPath $deliveryKey $bodySha256 $titleSha256
        if (-not [string]::Equals($readback, $receiptId, [System.StringComparison]::Ordinal)) {
            throw 'Presentation receipt readback changed.'
        }
        [Console]::Out.WriteLine($receiptId)
        exit 0
    }
    finally {
        if ($acquired) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 2
}
