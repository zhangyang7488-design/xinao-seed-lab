module.exports = (output, context) => {
  let parsed;
  try {
    parsed = JSON.parse(output);
  } catch (error) {
    return { pass: false, score: 0, reason: `Invalid JSON: ${error.message}` };
  }

  const usage = context.providerResponse?.tokenUsage || {};
  const appServer = context.metadata?.codexAppServer || {};
  const itemCounts = appServer.itemCounts || {};
  const items = Array.isArray(appServer.items) ? appServer.items : [];
  const tokenTotal = Number(usage.total || usage.total_tokens || 0);
  const tokenPrompt = Number(usage.prompt || usage.prompt_tokens || 0);
  const tokenCompletion = Number(usage.completion || usage.completion_tokens || 0);
  const commandExecutions = Number(itemCounts.commandExecution || 0);

  const FIXTURE_MARKER = 'HUMAN_CAPABILITY_EVAL_OK';
  const FIXTURE_SECOND_LINE = 'This fixture has exactly two non-empty lines.';

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
    return parts.join('\n');
  };

  const mentionsFixturePath = (value) => {
    const text = String(value || '').toLowerCase();
    return (
      text.includes('fixture.txt') ||
      text.includes('codex_capability/fixture') ||
      text.includes('codex_capability\\fixture')
    );
  };

  const codeInvokesFilesystemRead = (code) => {
    const text = String(code || '');
    // Bind actual observed read primitives used by node_repl/js fixture reads.
    return /\breadFile(?:Sync)?\b/.test(text);
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

  const resultContainsBothFixtureLines = (resultText) => {
    return (
      resultText.includes(FIXTURE_MARKER) &&
      resultText.includes(FIXTURE_SECOND_LINE)
    );
  };

  const isSuccessfulFixtureReadMcp = (item) => {
    if (!item || item.type !== 'mcpToolCall') {
      return false;
    }
    if (item.status !== 'completed') {
      return false;
    }
    if (item.error != null && item.error !== '') {
      return false;
    }
    // Qualifying MCP read must use the observed mechanism: node_repl / js.
    if (item.server !== 'node_repl' || item.tool !== 'js') {
      return false;
    }
    const code = extractMcpCodeArgument(item);
    if (!mentionsFixturePath(code) || !codeInvokesFilesystemRead(code)) {
      return false;
    }
    const resultText = extractMcpResultText(item);
    if (!resultText.trim()) {
      return false;
    }
    // Result must carry both fixture body lines, not a marker-only echo.
    return resultContainsBothFixtureLines(resultText);
  };

  const mcpFixtureReads = items.filter(isSuccessfulFixtureReadMcp);
  const hasLocalReadEvidence =
    commandExecutions >= 1 || mcpFixtureReads.length >= 1;

  const pass =
    parsed.marker === FIXTURE_MARKER &&
    parsed.non_empty_line_count === 2 &&
    parsed.mode === 'read-only' &&
    Boolean(appServer.threadId) &&
    Boolean(appServer.turnId) &&
    appServer.sandboxMode === 'read-only' &&
    appServer.approvalPolicy === 'never' &&
    hasLocalReadEvidence &&
    tokenPrompt > 0 &&
    tokenCompletion > 0 &&
    tokenTotal >= tokenPrompt + tokenCompletion;

  const evidence = {
    parsed,
    threadIdPresent: Boolean(appServer.threadId),
    turnIdPresent: Boolean(appServer.turnId),
    sandboxMode: appServer.sandboxMode,
    approvalPolicy: appServer.approvalPolicy,
    commandExecutions,
    mcpFixtureReads: mcpFixtureReads.length,
    hasLocalReadEvidence,
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
      ? `Codex app-server read-only trace and token ledger present (${JSON.stringify(evidence)})`
      : `Unexpected result or missing capability evidence: ${JSON.stringify(evidence)}`,
  };
};
