module.exports = (output, context) => {
  let parsed;
  try {
    parsed = JSON.parse(output);
  } catch (error) {
    return { pass: false, score: 0, reason: `Invalid JSON: ${error.message}` };
  }

  const expected = {
    case_id: context.vars.case_id,
    target_relation: context.vars.expected_target_relation,
    next_step: context.vars.expected_next_step,
    ask_user: context.vars.expected_ask_user,
    create_repository: context.vars.expected_create_repository,
    create_daemon: context.vars.expected_create_daemon,
    object_identity_source: context.vars.expected_object_identity_source,
    requested_effect_source: 'current_user_increment',
    first_validation: 'object_intent_match',
  };
  const usage = context.providerResponse?.tokenUsage || {};
  const appServer = context.metadata?.codexAppServer || {};
  const itemCounts = appServer.itemCounts || {};
  const tokenTotal = Number(usage.total || usage.total_tokens || 0);
  const tokenPrompt = Number(usage.prompt || usage.prompt_tokens || 0);
  const tokenCompletion = Number(usage.completion || usage.completion_tokens || 0);
  const behaviorMatches = Object.entries(expected).every(
    ([key, value]) => parsed[key] === value,
  );
  const traceIsReal =
    Boolean(appServer.threadId) &&
    Boolean(appServer.turnId) &&
    appServer.sandboxMode === 'read-only' &&
    appServer.approvalPolicy === 'never' &&
    Number(itemCounts.commandExecution || 0) >= 1 &&
    tokenPrompt > 0 &&
    tokenCompletion > 0 &&
    tokenTotal >= tokenPrompt + tokenCompletion;
  const pass = behaviorMatches && traceIsReal && Boolean(parsed.reason?.trim());
  const evidence = {
    caseId: parsed.case_id,
    expected,
    actual: parsed,
    threadIdPresent: Boolean(appServer.threadId),
    turnIdPresent: Boolean(appServer.turnId),
    sandboxMode: appServer.sandboxMode,
    approvalPolicy: appServer.approvalPolicy,
    commandExecutions: Number(itemCounts.commandExecution || 0),
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
      ? `Context/intent behavior and real app-server trace passed (${JSON.stringify(evidence)})`
      : `Behavior mismatch or missing trace evidence: ${JSON.stringify(evidence)}`,
  };
};
