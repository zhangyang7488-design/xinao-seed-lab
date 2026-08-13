#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('prime-b','prime-s')][string[]]$Profile = @('prime-s'),
    [ValidateRange(30000,900000)][int]$CaseTimeoutMilliseconds = 300000,
    [string]$ReceiptPath = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\acceptance\pi-cross-repository-context-v4.json'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

$targetRepository = 'E:\CODEX_CLEANROOM\workspace'
$xinaoAgentsPath = Join-Path $targetRepository 'xinao\AGENTS.md'
$xinaoReadmePath = Join-Path $targetRepository 'xinao\README.md'
$expectedXinaoHeading = '# XINAO Conditional Entry'
$provider = 'openai-codex'
$model = 'gpt-5.6-sol'
$thinking = 'max'
$utf8NoBom = [Text.UTF8Encoding]::new($false)
$utf8Strict = [Text.UTF8Encoding]::new($false, $true)

function Get-PiSha256Hex {
    param([Parameter(Mandatory)][byte[]]$Bytes)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-PiTextSha256Hex {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Text)
    return Get-PiSha256Hex -Bytes $script:utf8NoBom.GetBytes($Text)
}

function Get-PiHotFileIdentity {
    param([Parameter(Mandatory)][string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "PI_CROSS_REPOSITORY_HOT_FILE_MISSING: $resolved"
    }
    $bytes = [IO.File]::ReadAllBytes($resolved)
    try {
        $text = $script:utf8Strict.GetString($bytes)
    } catch {
        throw "PI_CROSS_REPOSITORY_HOT_FILE_NOT_UTF8: $resolved"
    }
    $sentinels = @(
        [regex]::Matches($text, 'SENTINEL:[A-Z0-9_]+') |
            ForEach-Object { $_.Value } |
            Select-Object -Unique
    )
    $headings = @(
        [regex]::Matches($text, '(?m)^#[^\r\n]+$') |
            ForEach-Object { $_.Value.Trim() }
    )
    return [ordered]@{
        path = $resolved
        sha256 = Get-PiSha256Hex -Bytes $bytes
        byte_count = $bytes.Length
        primary_sentinel = if ($sentinels.Count -gt 0) { [string]$sentinels[0] } else { $null }
        sentinels = $sentinels
        primary_heading = if ($headings.Count -gt 0) { [string]$headings[0] } else { $null }
    }
}

function ConvertTo-PiWindowsArgument {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Value)
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }
    $builder = [Text.StringBuilder]::new()
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes += 1
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (($backslashes * 2) + 1)))
            [void]$builder.Append('"')
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append(('\' * $backslashes))
            $backslashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) {
        [void]$builder.Append(('\' * ($backslashes * 2)))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Get-PiAssistantText {
    param($Message)
    if ($null -eq $Message -or [string]$Message.role -cne 'assistant') {
        return $null
    }
    if ($Message.content -is [string]) {
        return [string]$Message.content
    }
    $parts = @(
        @($Message.content) |
            Where-Object { [string]$_.type -ceq 'text' } |
            ForEach-Object { [string]$_.text }
    )
    if ($parts.Count -eq 0) {
        return $null
    }
    return ($parts -join '')
}

function Resolve-PiReadPath {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$WorkingDirectory
    )
    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $WorkingDirectory $Path))
}

function Invoke-PiFreshRpcCase {
    param(
        [Parameter(Mandatory)]$Spec,
        [Parameter(Mandatory)][string]$CaseId,
        [Parameter(Mandatory)][string]$Prompt,
        [Parameter(Mandatory)][int]$TimeoutMilliseconds
    )

    $node = (Get-Command node.exe -ErrorAction Stop).Source
    $cli = Join-Path $Spec.PiToolRoot 'node_modules\@earendil-works\pi-coding-agent\dist\cli.js'
    if (-not (Test-Path -LiteralPath $cli -PathType Leaf)) {
        throw "PI_CROSS_REPOSITORY_CLI_MISSING: $cli"
    }

    $nativeArguments = @(
        $cli,
        '--mode', 'rpc',
        '--no-session',
        '--provider', $script:provider,
        '--model', $script:model,
        '--thinking', $script:thinking,
        '--tools', 'read',
        '--append-system-prompt', $Spec.ContractProjection,
        '--session-dir', $Spec.SessionDir
    )
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $node
    $startInfo.Arguments = (($nativeArguments | ForEach-Object { ConvertTo-PiWindowsArgument -Value ([string]$_) }) -join ' ')
    $startInfo.WorkingDirectory = $Spec.Workspace
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardInputEncoding = $script:utf8NoBom
    $startInfo.StandardOutputEncoding = $script:utf8NoBom
    $startInfo.StandardErrorEncoding = $script:utf8NoBom
    $startInfo.EnvironmentVariables['PI_CODING_AGENT_DIR'] = $Spec.AgentDir
    $startInfo.EnvironmentVariables['PI_CODING_AGENT_SESSION_DIR'] = $Spec.SessionDir
    $startInfo.EnvironmentVariables['CODEX_HOME'] = $Spec.CodexHome
    $startInfo.EnvironmentVariables['PI_SKIP_VERSION_CHECK'] = '1'
    $startInfo.EnvironmentVariables['PI_TELEMETRY'] = '0'
    $startInfo.EnvironmentVariables['XINAO_PI_PROFILE'] = $Spec.Profile
    $startInfo.EnvironmentVariables['XINAO_PI_SUPERVISOR_ENABLED'] = '0'

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $commandId = "cross-repository-$CaseId-$([Guid]::NewGuid().ToString('N'))"
    $toolStarts = [Collections.Generic.List[object]]::new()
    $toolEnds = [Collections.Generic.List[object]]::new()
    $assistantText = $null
    $assistantMessageCount = 0
    $extensionErrorCount = 0
    $promptAccepted = $false
    $settledCount = 0
    $stderrTask = $null
    $processStarted = $false
    $stopwatch = [Diagnostics.Stopwatch]::StartNew()

    try {
        if (-not $process.Start()) {
            throw "PI_CROSS_REPOSITORY_PROCESS_NOT_STARTED: case=$CaseId"
        }
        $processStarted = $true
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $command = [ordered]@{
            type = 'prompt'
            id = $commandId
            message = $Prompt
        }
        $process.StandardInput.WriteLine(($command | ConvertTo-Json -Depth 6 -Compress))
        $process.StandardInput.Flush()

        $pendingRead = $null
        while ($settledCount -eq 0) {
            if ($stopwatch.ElapsedMilliseconds -ge $TimeoutMilliseconds) {
                throw "PI_CROSS_REPOSITORY_CASE_TIMEOUT: case=$CaseId"
            }
            if ($null -eq $pendingRead) {
                $pendingRead = $process.StandardOutput.ReadLineAsync()
            }
            if (-not $pendingRead.Wait(250)) {
                if ($process.HasExited) {
                    throw "PI_CROSS_REPOSITORY_RPC_EXITED_EARLY: case=$CaseId exit=$($process.ExitCode)"
                }
                continue
            }
            $line = $pendingRead.Result
            $pendingRead = $null
            if ($null -eq $line) {
                if ($process.HasExited) {
                    throw "PI_CROSS_REPOSITORY_RPC_EOF: case=$CaseId exit=$($process.ExitCode)"
                }
                continue
            }
            if ([string]::IsNullOrWhiteSpace($line)) {
                continue
            }
            try {
                $rpcEvent = $line | ConvertFrom-Json
            } catch {
                throw "PI_CROSS_REPOSITORY_RPC_JSON_INVALID: case=$CaseId line_sha256=$(Get-PiTextSha256Hex -Text $line)"
            }
            switch ([string]$rpcEvent.type) {
                'response' {
                    if ([string]$rpcEvent.id -ceq $commandId) {
                        if ($rpcEvent.success -ne $true) {
                            throw "PI_CROSS_REPOSITORY_PROMPT_REJECTED: case=$CaseId"
                        }
                        $promptAccepted = $true
                    }
                }
                'tool_execution_start' {
                    $path = if ($null -ne $rpcEvent.args) { [string]$rpcEvent.args.path } else { '' }
                    $toolStarts.Add([pscustomobject]@{
                        id = [string]$rpcEvent.toolCallId
                        name = [string]$rpcEvent.toolName
                        path = $path
                    })
                }
                'tool_execution_end' {
                    $toolEnds.Add([pscustomobject]@{
                        id = [string]$rpcEvent.toolCallId
                        name = [string]$rpcEvent.toolName
                        is_error = ($rpcEvent.isError -eq $true)
                    })
                }
                'message_end' {
                    $candidate = Get-PiAssistantText -Message $rpcEvent.message
                    if ($null -ne $candidate -and $candidate.Length -gt 0) {
                        $assistantText = $candidate
                        $assistantMessageCount += 1
                    }
                }
                'extension_error' {
                    $extensionErrorCount += 1
                }
                'agent_settled' {
                    $settledCount += 1
                }
            }
        }
    } finally {
        $stopwatch.Stop()
        if ($processStarted) {
            try { $process.StandardInput.Close() } catch { $null = $_ }
            if (-not $process.HasExited) {
                if (-not $process.WaitForExit(3000)) {
                    try { $process.Kill() } catch { $null = $_ }
                    try { $process.WaitForExit() } catch { $null = $_ }
                }
            }
        }
        if ($null -ne $stderrTask) {
            try { [void]$stderrTask.Wait(3000) } catch { $null = $_ }
        }
        $process.Dispose()
    }

    if (-not $promptAccepted) {
        throw "PI_CROSS_REPOSITORY_PROMPT_NOT_ACKNOWLEDGED: case=$CaseId"
    }
    if ($settledCount -ne 1) {
        throw "PI_CROSS_REPOSITORY_SETTLED_COUNT_INVALID: case=$CaseId count=$settledCount"
    }
    if ($extensionErrorCount -ne 0) {
        throw "PI_CROSS_REPOSITORY_EXTENSION_ERROR: case=$CaseId count=$extensionErrorCount"
    }
    if ([string]::IsNullOrWhiteSpace($assistantText)) {
        throw "PI_CROSS_REPOSITORY_ASSISTANT_RESULT_MISSING: case=$CaseId"
    }

    return [pscustomobject]@{
        assistant_text = $assistantText.Trim()
        assistant_message_count = $assistantMessageCount
        tool_starts = @($toolStarts)
        tool_ends = @($toolEnds)
        elapsed_milliseconds = $stopwatch.ElapsedMilliseconds
    }
}

function Assert-PiExactObjectProperties {
    param(
        [Parameter(Mandatory)]$Object,
        [Parameter(Mandatory)][Collections.IDictionary]$Expected,
        [Parameter(Mandatory)][string]$CaseId
    )
    $actualNames = @($Object.PSObject.Properties.Name | Sort-Object)
    $expectedNames = @($Expected.Keys | ForEach-Object { [string]$_ } | Sort-Object)
    if (@(Compare-Object -ReferenceObject $expectedNames -DifferenceObject $actualNames).Count -ne 0) {
        throw "PI_CROSS_REPOSITORY_PROPERTY_SHAPE_MISMATCH: case=$CaseId"
    }
    foreach ($name in $Expected.Keys) {
        if ($Object.$name -ne $Expected[$name]) {
            $expectedValue = [string]$Expected[$name]
            $actualValue = [string]$Object.$name
            throw "PI_CROSS_REPOSITORY_PROPERTY_VALUE_MISMATCH: case=$CaseId property=$name expected=$expectedValue actual=$actualValue"
        }
    }
}

function Assert-PiToolTrace {
    param(
        [Parameter(Mandatory)]$Invocation,
        [Parameter(Mandatory)][Collections.IDictionary]$ExpectedReadRoles,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$CaseId
    )
    $starts = @($Invocation.tool_starts)
    $ends = @($Invocation.tool_ends)
    if ($starts.Count -ne $ExpectedReadRoles.Count) {
        throw "PI_CROSS_REPOSITORY_TOOL_START_COUNT_MISMATCH: case=$CaseId count=$($starts.Count)"
    }
    if (@($starts | Where-Object { [string]$_.name -cne 'read' }).Count -ne 0) {
        throw "PI_CROSS_REPOSITORY_NON_READ_TOOL_USED: case=$CaseId"
    }

    $expectedByPath = @{}
    foreach ($role in $ExpectedReadRoles.Keys) {
        $expectedPath = [IO.Path]::GetFullPath([string]$ExpectedReadRoles[$role])
        $expectedByPath[$expectedPath.ToLowerInvariant()] = [string]$role
    }
    $seenRoles = [Collections.Generic.List[string]]::new()
    foreach ($start in $starts) {
        if ([string]::IsNullOrWhiteSpace([string]$start.id) -or [string]::IsNullOrWhiteSpace([string]$start.path)) {
            throw "PI_CROSS_REPOSITORY_READ_TRACE_INCOMPLETE: case=$CaseId"
        }
        $resolved = Resolve-PiReadPath -Path ([string]$start.path) -WorkingDirectory $WorkingDirectory
        $key = $resolved.ToLowerInvariant()
        if (-not $expectedByPath.ContainsKey($key)) {
            throw "PI_CROSS_REPOSITORY_UNEXPECTED_READ: case=$CaseId path_sha256=$(Get-PiTextSha256Hex -Text $resolved)"
        }
        $role = [string]$expectedByPath[$key]
        if ($seenRoles.Contains($role)) {
            throw "PI_CROSS_REPOSITORY_DUPLICATE_READ: case=$CaseId role=$role"
        }
        $matchingEnds = @($ends | Where-Object { [string]$_.id -ceq [string]$start.id })
        if ($matchingEnds.Count -ne 1 -or $matchingEnds[0].is_error -eq $true) {
            throw "PI_CROSS_REPOSITORY_READ_NOT_SUCCESSFUL: case=$CaseId role=$role"
        }
        $seenRoles.Add($role)
    }
    if ($ends.Count -ne $starts.Count) {
        throw "PI_CROSS_REPOSITORY_TOOL_END_COUNT_MISMATCH: case=$CaseId count=$($ends.Count)"
    }

    $pathSet = @(
        $ExpectedReadRoles.Keys |
            ForEach-Object { [IO.Path]::GetFullPath([string]$ExpectedReadRoles[$_]) } |
            Sort-Object
    ) -join "`n"
    return [ordered]@{
        tool_execution_start_count = $starts.Count
        tool_execution_end_count = $ends.Count
        successful_read_count = $seenRoles.Count
        successful_read_roles = @($seenRoles | Sort-Object)
        read_path_set_sha256 = Get-PiTextSha256Hex -Text $pathSet
        non_read_tool_calls = 0
        effect_capable_tool_calls = 0
        agent_settled_count = 1
        assistant_message_end_count = $Invocation.assistant_message_count
    }
}

function ConvertFrom-PiCaseResult {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$CaseId
    )
    try {
        $value = $Text | ConvertFrom-Json
    } catch {
        throw "PI_CROSS_REPOSITORY_CASE_JSON_INVALID: case=$CaseId response_sha256=$(Get-PiTextSha256Hex -Text $Text)"
    }
    if ($null -eq $value -or $value -is [Array]) {
        throw "PI_CROSS_REPOSITORY_CASE_JSON_NOT_OBJECT: case=$CaseId"
    }
    return $value
}

function Get-PiCasePrompt {
    param(
        [Parameter(Mandatory)][string]$CaseBody,
        [Parameter(Mandatory)]$HotInputs,
        [Parameter(Mandatory)][string]$ResultShape
    )
    return @(
        'Run a fresh, read-only consumer acceptance over synthetic facts only.'
        "Use the read tool exactly once on each of these three absolute paths: PI_CONTRACT=$($HotInputs.pi_contract.path); XINAO_AGENTS=$($HotInputs.xinao_agents.path); XINAO_README=$($HotInputs.xinao_readme.path)."
        'Do not call another tool. Do not read, search, request, output, or infer any actual draw record or result-bearing dataset. Do not edit or create anything.'
        'Copy the first SENTINEL token from PI_CONTRACT and the first Markdown heading from XINAO_AGENTS into source_binding so the caller can bind the response to the hot inputs.'
        $CaseBody
        "Return only one minified JSON object, with no prose or code fence, using this exact structural shape. A pipe separates allowed alternatives; choose one value: $ResultShape"
    ) -join ' '
}

$caseDefinitions = @(
    [pscustomobject]@{
        case_id = 'derivability_ab'
        presentation_order = 'AB'
        body = 'Synthetic case, presentation order AB: A is the carrier token 101101. B is the parity projection deterministically recomputable from A. Classify whether B is independent evidence, whether either representation receives functional or ontology priority, and whether this synthetic observation grants claim or effect qualification.'
        shape = '{"schema":"xinao.pi_cross_repository_case.v4","case_id":"derivability_ab","presentation_order":"AB","source_binding":{"pi_contract_sentinel":"SENTINEL:...","xinao_agents_heading":"# ..."},"properties":{"independent_evidence":"not_independent|independent","derivability_scope":"independent_evidence_only|functional|ontology","functional_status":"unassessed|preferred_A|preferred_B","ontology_priority":"not_allocated|A|B","claim_qualification":"not_granted|granted","effect_qualification":"not_granted|granted"}}'
        expected = [ordered]@{
            independent_evidence = 'not_independent'
            derivability_scope = 'independent_evidence_only'
            functional_status = 'unassessed'
            ontology_priority = 'not_allocated'
            claim_qualification = 'not_granted'
            effect_qualification = 'not_granted'
        }
    },
    [pscustomobject]@{
        case_id = 'derivability_ba'
        presentation_order = 'BA'
        body = 'Synthetic case, presentation order BA: B is the parity projection deterministically recomputable from A. A is the carrier token 101101. Classify whether B is independent evidence, whether either representation receives functional or ontology priority, and whether this synthetic observation grants claim or effect qualification.'
        shape = '{"schema":"xinao.pi_cross_repository_case.v4","case_id":"derivability_ba","presentation_order":"BA","source_binding":{"pi_contract_sentinel":"SENTINEL:...","xinao_agents_heading":"# ..."},"properties":{"independent_evidence":"not_independent|independent","derivability_scope":"independent_evidence_only|functional|ontology","functional_status":"unassessed|preferred_A|preferred_B","ontology_priority":"not_allocated|A|B","claim_qualification":"not_granted|granted","effect_qualification":"not_granted|granted"}}'
        expected = [ordered]@{
            independent_evidence = 'not_independent'
            derivability_scope = 'independent_evidence_only'
            functional_status = 'unassessed'
            ontology_priority = 'not_allocated'
            claim_qualification = 'not_granted'
            effect_qualification = 'not_granted'
        }
    },
    [pscustomobject]@{
        case_id = 'local_settlement'
        presentation_order = $null
        body = 'Synthetic case: bounded local effect L has an exact settlement record at typed reference material:synthetic-local-L. Its current consumer P also holds a separate unresolved object. Report the exact local disposition, return that typed material reference, name the immediate consumer operation that makes the returned material available to P, and state the claim scope.'
        shape = '{"schema":"xinao.pi_cross_repository_case.v4","case_id":"local_settlement","source_binding":{"pi_contract_sentinel":"SENTINEL:...","xinao_agents_heading":"# ..."},"properties":{"local_effect_disposition":"settled|open","returned_material_ref":"material:synthetic-local-L","consumer_operation":"reintegrate_returned_material|discard_returned_material","claim_qualification":"local_only|parent_wide"}}'
        expected = [ordered]@{
            local_effect_disposition = 'settled'
            returned_material_ref = 'material:synthetic-local-L'
            consumer_operation = 'reintegrate_returned_material'
            claim_qualification = 'local_only'
        }
    },
    [pscustomobject]@{
        case_id = 'openness_control'
        presentation_order = $null
        body = 'Synthetic observations: tokens p, q, r recur in different pairwise arrangements, while their carrier identity and mechanism are unknown. Form one nonempty provisional working relation in your own words without selecting from a supplied relation list. Treat it only as a working hypothesis: neither the observations nor the provisional relation qualify a formal claim or an external effect. Report those two qualifications separately.'
        shape = '{"schema":"xinao.pi_cross_repository_case.v4","case_id":"openness_control","source_binding":{"pi_contract_sentinel":"SENTINEL:...","xinao_agents_heading":"# ..."},"working_relation":"free nonempty text","properties":{"working_relation_status":"provisional|qualified","claim_qualification":"not_granted|granted","effect_qualification":"not_granted|granted"}}'
        expected = [ordered]@{
            working_relation_status = 'provisional'
            claim_qualification = 'not_granted'
            effect_qualification = 'not_granted'
        }
    }
)

$results = @()
foreach ($profileName in $Profile) {
    $spec = Get-PiDualEntrySpec -Profile $profileName
    Assert-PiDualEntryBinary -Spec $spec
    $hotInputs = [ordered]@{
        pi_contract = Get-PiHotFileIdentity -Path $spec.ContractProjection
        xinao_agents = Get-PiHotFileIdentity -Path $xinaoAgentsPath
        xinao_readme = Get-PiHotFileIdentity -Path $xinaoReadmePath
    }
    if ([string]$hotInputs.pi_contract.primary_sentinel -cne 'SENTINEL:PI_LOCAL_COMPATIBILITY_BOUNDARY_V3') {
        throw "PI_CROSS_REPOSITORY_CONTRACT_SENTINEL_MISMATCH: profile=$profileName"
    }
    if ([string]$hotInputs.xinao_agents.primary_heading -cne $expectedXinaoHeading) {
        throw "PI_CROSS_REPOSITORY_XINAO_HEADING_MISMATCH: profile=$profileName"
    }
    $expectedReadRoles = [ordered]@{
        pi_contract = $hotInputs.pi_contract.path
        xinao_agents = $hotInputs.xinao_agents.path
        xinao_readme = $hotInputs.xinao_readme.path
    }

    $caseReceipts = @()
    $validatedOutputs = @{}
    foreach ($definition in $caseDefinitions) {
        $prompt = Get-PiCasePrompt -CaseBody $definition.body -HotInputs $hotInputs -ResultShape $definition.shape
        $invocation = Invoke-PiFreshRpcCase -Spec $spec -CaseId $definition.case_id -Prompt $prompt -TimeoutMilliseconds $CaseTimeoutMilliseconds
        $output = ConvertFrom-PiCaseResult -Text $invocation.assistant_text -CaseId $definition.case_id

        $expectedTopNames = @('case_id','properties','schema','source_binding')
        if ($null -ne $definition.presentation_order) { $expectedTopNames += 'presentation_order' }
        if ($definition.case_id -ceq 'openness_control') { $expectedTopNames += 'working_relation' }
        $actualTopNames = @($output.PSObject.Properties.Name | Sort-Object)
        if (@(Compare-Object -ReferenceObject @($expectedTopNames | Sort-Object) -DifferenceObject $actualTopNames).Count -ne 0) {
            throw "PI_CROSS_REPOSITORY_TOP_LEVEL_SHAPE_MISMATCH: case=$($definition.case_id)"
        }
        if ([string]$output.schema -cne 'xinao.pi_cross_repository_case.v4' -or [string]$output.case_id -cne $definition.case_id) {
            throw "PI_CROSS_REPOSITORY_CASE_IDENTITY_MISMATCH: case=$($definition.case_id)"
        }
        if ($null -ne $definition.presentation_order -and [string]$output.presentation_order -cne $definition.presentation_order) {
            throw "PI_CROSS_REPOSITORY_PRESENTATION_ORDER_MISMATCH: case=$($definition.case_id)"
        }
        Assert-PiExactObjectProperties -Object $output.source_binding -Expected ([ordered]@{
            pi_contract_sentinel = $hotInputs.pi_contract.primary_sentinel
            xinao_agents_heading = $hotInputs.xinao_agents.primary_heading
        }) -CaseId $definition.case_id
        Assert-PiExactObjectProperties -Object $output.properties -Expected $definition.expected -CaseId $definition.case_id
        $toolTrace = Assert-PiToolTrace -Invocation $invocation -ExpectedReadRoles $expectedReadRoles -WorkingDirectory $spec.Workspace -CaseId $definition.case_id

        $workingRelationReceipt = $null
        if ($definition.case_id -ceq 'openness_control') {
            $workingRelation = [string]$output.working_relation
            $workingRelationBytes = $utf8NoBom.GetBytes($workingRelation)
            if ([string]::IsNullOrWhiteSpace($workingRelation) -or $workingRelationBytes.Length -gt 800) {
                throw "PI_CROSS_REPOSITORY_WORKING_RELATION_INVALID: case=$($definition.case_id)"
            }
            $workingRelationReceipt = [ordered]@{
                sha256 = Get-PiSha256Hex -Bytes $workingRelationBytes
                byte_count = $workingRelationBytes.Length
            }
        }

        $validatedOutputs[$definition.case_id] = $output
        $caseReceipt = [ordered]@{
            case_id = $definition.case_id
            input_sha256 = Get-PiTextSha256Hex -Text $prompt
            properties = $definition.expected
            source_binding_verified = $true
            tool_trace = $toolTrace
            response_sha256 = Get-PiTextSha256Hex -Text $invocation.assistant_text
            response_byte_count = $utf8NoBom.GetByteCount($invocation.assistant_text)
            elapsed_milliseconds = $invocation.elapsed_milliseconds
        }
        if ($null -ne $workingRelationReceipt) {
            $caseReceipt.working_relation = $workingRelationReceipt
        }
        $caseReceipts += $caseReceipt
    }

    foreach ($propertyName in $caseDefinitions[0].expected.Keys) {
        if ($validatedOutputs['derivability_ab'].properties.$propertyName -ne $validatedOutputs['derivability_ba'].properties.$propertyName) {
            throw "PI_CROSS_REPOSITORY_MIRROR_MISMATCH: property=$propertyName"
        }
    }

    $results += [ordered]@{
        profile = $profileName
        provider = $provider
        model = $model
        thinking = $thinking
        session = 'fresh-no-session-per-case'
        starting_workspace = $spec.Workspace
        named_object = $targetRepository
        hot_inputs = $hotInputs
        cases = $caseReceipts
        metamorphic_checks = [ordered]@{
            derivability_ab_ba_properties_equal = $true
            derivability_scope_confined_to_independent_evidence = $true
            local_settlement_material_returned_to_current_consumer = $true
            provisional_working_relation_kept_distinct_from_claim_and_effect_qualification = $true
        }
        trace_oracle = [ordered]@{
            fresh_no_session_case_count = $caseReceipts.Count
            exact_response_shape_count = $caseReceipts.Count
            read_only_tool_trace_count = $caseReceipts.Count
            local_material_return_bound = $true
        }
    }
}

$receipt = [ordered]@{
    schema = 'xinao.pi_cross_repository_context.acceptance.v4'
    status = 'verified'
    runtime_version = $script:PiDualEntryVersion
    results = $results
}
Write-PiDualEntryJsonAtomic -Path $ReceiptPath -Value $receipt
$receipt | ConvertTo-Json -Depth 12
