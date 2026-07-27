#Requires -Version 5.1

function Set-XinaoProcessArguments {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [Diagnostics.ProcessStartInfo]$StartInfo,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [AllowEmptyString()]
        [string[]]$Arguments
    )

    $argumentListProperty = $StartInfo.PSObject.Properties['ArgumentList']
    if ($null -eq $argumentListProperty) {
        throw 'GROK_PROCESS_ARGUMENT_LIST_UNAVAILABLE: PowerShell 7 / modern .NET required'
    }
    foreach ($argument in $Arguments) {
        [void]$StartInfo.ArgumentList.Add([string]$argument)
    }
    return 'process_start_info_argument_list'
}

function Set-XinaoUtf8ProcessStreams {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [Diagnostics.ProcessStartInfo]$StartInfo
    )

    # Docker and the Linux Grok worker emit UTF-8 bytes regardless of the
    # active Windows console code page.  Keep decoding deterministic and
    # fail closed on invalid bytes instead of silently corrupting JSON.
    $strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
    $StartInfo.StandardOutputEncoding = $strictUtf8
    $StartInfo.StandardErrorEncoding = $strictUtf8
}
