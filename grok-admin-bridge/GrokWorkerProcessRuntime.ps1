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
