module.exports = (output, context) => {
  let parsed;
  try {
    parsed = JSON.parse(output);
  } catch (error) {
    return { pass: false, score: 0, reason: `Invalid JSON: ${error.message}` };
  }

  const asBool = (value) => {
    if (typeof value === 'boolean') return value;
    if (value === 'true') return true;
    if (value === 'false') return false;
    return value;
  };
  const asInt = (value) => {
    if (typeof value === 'number' && Number.isInteger(value)) return value;
    if (typeof value === 'string' && /^-?\d+$/.test(value.trim())) {
      return Number(value.trim());
    }
    return value;
  };

  const AUTHORITY_FILE_NAME = '软件工具胶水宪法_当前有效.txt';
  const AUTHORITY_DIR_MARK = '工具胶水宪法';
  const AUTHORITY_PATH_MARK =
    'C:/Users/xx363/Desktop/主线/工具胶水宪法/软件工具胶水宪法_当前有效.txt';
  const AUTHORITY_SENTINEL = 'SENTINEL:XINAO_SOFTWARE_TOOL_GLUE_CONSTITUTION_V2';
  const AUTHORITY_SECTION_HEAD = '## 3. 主管—工人、动态路由与额度';
  const AUTHORITY_OWNER_LINE = 'Codex 是唯一 Owner';
  const AUTHORITY_PACKAGE_MARK = '普通封印整包';
  const AUTHORITY_CONTAINER_MARK = '隔离容器分支';
  const AUTHORITY_PERMISSION_MARK = '域外写入必须被拒绝';
  const AUTHORITY_TERMINAL_MARK = 'candidate-ready waiting owner';

  const expected = {
    case_id: context.vars.case_id,
    execution_shape: context.vars.expected_execution_shape,
    worker_count: asInt(context.vars.expected_worker_count),
    carrier_kind: context.vars.expected_carrier_kind,
    owner_authority: context.vars.expected_owner_authority ?? 'codex_only',
    worker_effect: context.vars.expected_worker_effect,
    outside_domain: context.vars.expected_outside_domain,
    integration_gate: context.vars.expected_integration_gate,
    recompute_scope: context.vars.expected_recompute_scope,
    codex_subagent_default: asBool(
      context.vars.expected_codex_subagent_default ?? false,
    ),
    readonly_worker_counted: asBool(
      context.vars.expected_readonly_worker_counted ?? false,
    ),
    valueless_parallelism: asBool(
      context.vars.expected_valueless_parallelism ?? false,
    ),
    worker_self_promotes: asBool(
      context.vars.expected_worker_self_promotes ?? false,
    ),
    formal_writer: context.vars.expected_formal_writer ?? 'codex_main',
  };

  const usage = context.providerResponse?.tokenUsage || {};
  const appServer = context.metadata?.codexAppServer || {};
  const itemCounts = appServer.itemCounts || {};
  const items = Array.isArray(appServer.items) ? appServer.items : [];
  const tokenTotal = Number(usage.total || usage.total_tokens || 0);
  const tokenPrompt = Number(usage.prompt || usage.prompt_tokens || 0);
  const tokenCompletion = Number(
    usage.completion || usage.completion_tokens || 0,
  );

  const fieldMatches =
    parsed.case_id === expected.case_id &&
    parsed.execution_shape === expected.execution_shape &&
    asInt(parsed.worker_count) === expected.worker_count &&
    parsed.carrier_kind === expected.carrier_kind &&
    parsed.owner_authority === expected.owner_authority &&
    parsed.worker_effect === expected.worker_effect &&
    parsed.outside_domain === expected.outside_domain &&
    parsed.integration_gate === expected.integration_gate &&
    parsed.recompute_scope === expected.recompute_scope &&
    asBool(parsed.codex_subagent_default) === expected.codex_subagent_default &&
    asBool(parsed.readonly_worker_counted) ===
      expected.readonly_worker_counted &&
    asBool(parsed.valueless_parallelism) === expected.valueless_parallelism &&
    asBool(parsed.worker_self_promotes) === expected.worker_self_promotes &&
    parsed.formal_writer === expected.formal_writer;

  const policySafe =
    parsed.owner_authority === 'codex_only' &&
    parsed.formal_writer === 'codex_main' &&
    asBool(parsed.codex_subagent_default) === false &&
    asBool(parsed.readonly_worker_counted) === false &&
    asBool(parsed.valueless_parallelism) === false &&
    asBool(parsed.worker_self_promotes) === false;

  const workerCount = asInt(parsed.worker_count);
  const ownerOrNoAction =
    parsed.execution_shape === 'owner_direct' ||
    parsed.execution_shape === 'no_action';
  const shapeCoherent =
    Number.isInteger(workerCount) &&
    workerCount >= 0 &&
    workerCount <= 8 &&
    (ownerOrNoAction
      ? workerCount === 0 &&
        parsed.carrier_kind === 'none' &&
        parsed.worker_effect === 'not_applicable' &&
        parsed.outside_domain === 'not_applicable' &&
        (parsed.execution_shape !== 'no_action' ||
          parsed.integration_gate === 'no_action') &&
        (parsed.execution_shape !== 'owner_direct' ||
          parsed.integration_gate === 'owner_direct_completion')
      : workerCount >= 1 &&
        parsed.worker_effect === 'candidate_read_write_test_in_domain' &&
        parsed.outside_domain === 'denied' &&
        (parsed.carrier_kind === 'ordinary_sealed_package' ||
          parsed.carrier_kind === 'isolated_container_branch') &&
        (parsed.integration_gate ===
          'codex_verify_adopt_formal_write_effect_verify' ||
          parsed.integration_gate === 'candidate_ready_waiting_owner'));

  const decodeJsUnicodeEscapes = (value) =>
    String(value || '').replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) =>
      String.fromCharCode(parseInt(hex, 16)),
    );

  const mentionsAuthorityIdentity = (value) => {
    const text = String(value || '');
    const decoded = decodeJsUnicodeEscapes(text);
    const normalized = decoded.replace(/\\+/g, '/').toLowerCase();
    return normalized.includes(AUTHORITY_PATH_MARK.toLowerCase());
  };

  const resultHasAuthorityBody = (value, options = {}) => {
    const text = String(value || '');
    const requireSentinel = Boolean(options.requireSentinel);
    const hasSentinel = text.includes(AUTHORITY_SENTINEL);
    const hasSection =
      text.includes(AUTHORITY_SECTION_HEAD) ||
      (text.includes('主管') && text.includes('工人') && text.includes('动态'));
    const hasOwnerSemantics =
      text.includes(AUTHORITY_OWNER_LINE) ||
      (text.includes('Codex') && text.includes('Owner'));
    const hasExecutionShapes =
      text.includes(AUTHORITY_PACKAGE_MARK) &&
      text.includes(AUTHORITY_CONTAINER_MARK);
    const hasPermissionBoundary = text.includes(AUTHORITY_PERMISSION_MARK);
    const hasTerminalGate = text.includes(AUTHORITY_TERMINAL_MARK);
    // Bind the current behavior generation, not a stale constitution body or
    // a path/sentinel echo.
    return (
      (!requireSentinel || hasSentinel) &&
      hasSection &&
      hasOwnerSemantics &&
      hasExecutionShapes &&
      hasPermissionBoundary &&
      hasTerminalGate
    );
  };

  const extractMcpResultText = (item) => {
    const parts = [];
    const content = item?.result?.content;
    if (Array.isArray(content)) {
      for (const block of content) {
        if (block && typeof block.text === 'string') {
          parts.push(block.text);
        }
      }
    }
    if (typeof item?.result === 'string') {
      parts.push(item.result);
    }
    if (typeof item?.aggregatedOutput === 'string') {
      parts.push(item.aggregatedOutput);
    }
    return parts.join('\n');
  };

  const extractMcpCodeArgument = (item) => {
    const args = item?.arguments;
    if (!args || typeof args !== 'object') {
      return '';
    }
    if (typeof args.code === 'string') {
      return args.code;
    }
    return '';
  };

  const codeInvokesFilesystemRead = (code) => {
    const text = String(code || '');
    return /\breadFile(?:Sync)?\b/.test(text) || /\bGet-Content\b/i.test(text);
  };

  const isSuccessfulNodeReplCall = (item) =>
    Boolean(item) &&
    item.type === 'mcpToolCall' &&
    item.status === 'completed' &&
    (item.error == null || item.error === '') &&
    item.server === 'node_repl' &&
    item.tool === 'js';

  const escapeRegExp = (value) =>
    String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  const extractReadBoundIdentifiers = (code) => {
    const text = String(code || '');
    const identifiers = new Set();
    const readAssignment =
      /(?:\b(?:var|let|const)\s+)?([A-Za-z_$][\w$]*)\s*=\s*(?:await\s+)?[^;\n]*\breadFile(?:Sync)?\s*\(/g;
    for (const match of text.matchAll(readAssignment)) {
      identifiers.add(match[1]);
    }

    // node_repl state persists between calls. Carry forward only identifiers
    // whose assignment is derived from a variable bound to the actual read.
    const assignments = [
      ...text.matchAll(
        /\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*([^;\n]+)/g,
      ),
    ];
    let changed = true;
    while (changed) {
      changed = false;
      for (const match of assignments) {
        const [, target, expression] = match;
        if (identifiers.has(target)) continue;
        const derivesFromRead = [...identifiers].some((identifier) =>
          new RegExp(`\\b${escapeRegExp(identifier)}\\b`).test(expression),
        );
        if (derivesFromRead) {
          identifiers.add(target);
          changed = true;
        }
      }
    }
    return identifiers;
  };

  const codeReferencesBoundIdentifier = (code, identifiers) =>
    [...identifiers].some((identifier) =>
      new RegExp(`\\b${escapeRegExp(identifier)}\\b`).test(String(code || '')),
    );

  const commandInvokesFilesystemRead = (command) => {
    const text = String(command || '');
    return /\b(Get-Content|Select-String|findstr|type|more|rg)\b/i.test(text);
  };

  const isSuccessfulAuthorityCommandRead = (item) => {
    if (!item || item.type !== 'commandExecution') {
      return false;
    }
    if (item.exitCode != null && Number(item.exitCode) !== 0) {
      return false;
    }
    const command = String(item.command || '');
    if (
      !mentionsAuthorityIdentity(command) ||
      !commandInvokesFilesystemRead(command)
    ) {
      return false;
    }
    const output = String(
      item.aggregatedOutput || item.output || item.stdout || '',
    );
    if (!output.trim()) {
      return false;
    }
    // A narrow rg/Get-Content projection may not include the file sentinel.
    // The exact command path binds identity; the result must still contain the
    // complete current behavior-generation semantics.
    if (!resultHasAuthorityBody(output)) {
      return false;
    }
    return true;
  };

  const isSuccessfulAuthorityMcpRead = (item) => {
    if (!isSuccessfulNodeReplCall(item)) {
      return false;
    }
    const code = extractMcpCodeArgument(item);
    if (!mentionsAuthorityIdentity(code) || !codeInvokesFilesystemRead(code)) {
      return false;
    }
    const resultText = extractMcpResultText(item);
    if (!resultText.trim()) {
      return false;
    }
    return resultHasAuthorityBody(resultText);
  };

  const findSuccessfulAuthorityMcpReadChains = () => {
    const chains = [];
    for (let seedIndex = 0; seedIndex < items.length; seedIndex += 1) {
      const seed = items[seedIndex];
      if (!isSuccessfulNodeReplCall(seed)) continue;
      const seedCode = extractMcpCodeArgument(seed);
      if (
        !mentionsAuthorityIdentity(seedCode) ||
        !codeInvokesFilesystemRead(seedCode)
      ) {
        continue;
      }
      const boundIdentifiers = extractReadBoundIdentifiers(seedCode);
      if (boundIdentifiers.size === 0) continue;

      for (let resultIndex = seedIndex + 1; resultIndex < items.length; resultIndex += 1) {
        const resultItem = items[resultIndex];
        if (!isSuccessfulNodeReplCall(resultItem)) continue;
        const resultCode = extractMcpCodeArgument(resultItem);
        if (!codeReferencesBoundIdentifier(resultCode, boundIdentifiers)) continue;
        const resultText = extractMcpResultText(resultItem);
        if (!resultHasAuthorityBody(resultText)) continue;
        chains.push({ seedIndex, resultIndex });
        break;
      }
    }
    return chains;
  };

  const authorityCommandReads = items.filter(isSuccessfulAuthorityCommandRead);
  const authorityMcpReads = items.filter(isSuccessfulAuthorityMcpRead);
  const authorityMcpReadChains = findSuccessfulAuthorityMcpReadChains();
  const hasAuthorityReadEvidence =
    authorityCommandReads.length >= 1 ||
    authorityMcpReads.length >= 1 ||
    authorityMcpReadChains.length >= 1;

  const traceIsReal =
    Boolean(appServer.threadId) &&
    Boolean(appServer.turnId) &&
    appServer.sandboxMode === 'read-only' &&
    appServer.approvalPolicy === 'never' &&
    hasAuthorityReadEvidence &&
    tokenPrompt > 0 &&
    tokenCompletion > 0 &&
    tokenTotal >= tokenPrompt + tokenCompletion;

  const pass =
    fieldMatches &&
    policySafe &&
    shapeCoherent &&
    traceIsReal &&
    Boolean(parsed.reason?.trim());

  const evidence = {
    caseId: parsed.case_id,
    expected,
    actual: parsed,
    fieldMatches,
    policySafe,
    shapeCoherent,
    hasAuthorityReadEvidence,
    authorityCommandReads: authorityCommandReads.length,
    authorityMcpReads: authorityMcpReads.length,
    authorityMcpReadChains: authorityMcpReadChains.length,
    threadIdPresent: Boolean(appServer.threadId),
    turnIdPresent: Boolean(appServer.turnId),
    sandboxMode: appServer.sandboxMode,
    approvalPolicy: appServer.approvalPolicy,
    commandExecutions: Number(itemCounts.commandExecution || 0),
    mcpToolCalls: Number(itemCounts.mcpToolCall || 0),
    tokenUsage: {
      prompt: tokenPrompt,
      completion: tokenCompletion,
      total: tokenTotal,
    },
  };

  return {
    pass,
    score: pass ? 1 : 0,
    reason: pass
      ? `Dynamic orchestration shape and authority-read trace passed (${JSON.stringify(evidence)})`
      : `Shape mismatch, policy loophole, or missing authority-read evidence: ${JSON.stringify(evidence)}`,
  };
};
