module.exports = (output, context) => {
  let parsed;
  try {
    parsed = JSON.parse(output);
  } catch (error) {
    return { pass: false, score: 0, reason: `Invalid JSON: ${error.message}` };
  }

  const asBool = (value) => {
    if (typeof value === "boolean") return value;
    if (value === "true") return true;
    if (value === "false") return false;
    return value;
  };
  const expected = {
    case_id: context.vars.case_id,
    research_mode: context.vars.expected_research_mode,
    scope_source: context.vars.expected_scope_source,
    utterance_is_automatic_task_boundary: false,
    local_baseline_required: asBool(context.vars.expected_local_baseline_required),
    coverage_expansion_required: asBool(
      context.vars.expected_coverage_expansion_required,
    ),
    local_collision_required: asBool(context.vars.expected_local_collision_required),
    external_classification: context.vars.expected_external_classification,
    next_action: context.vars.expected_next_action,
    stop_basis: context.vars.expected_stop_basis,
    fixed_search_quota: false,
    automatic_external_adoption: false,
    second_research_owner: false,
  };

  const usage = context.providerResponse?.tokenUsage || {};
  const appServer = context.metadata?.codexAppServer || {};
  const itemCounts = appServer.itemCounts || {};
  const tokenPrompt = Number(usage.prompt || usage.prompt_tokens || 0);
  const tokenCompletion = Number(usage.completion || usage.completion_tokens || 0);
  const tokenTotal = Number(usage.total || usage.total_tokens || 0);
  const behaviorMatches = Object.entries(expected).every(
    ([key, value]) => parsed[key] === value,
  );
  const traceIsReal =
    Boolean(appServer.threadId) &&
    Boolean(appServer.turnId) &&
    appServer.sandboxMode === "read-only" &&
    appServer.approvalPolicy === "never" &&
    (Number(itemCounts.commandExecution || 0) >= 1 ||
      Number(itemCounts.agentMessage || 0) >= 1) &&
    tokenPrompt > 0 &&
    tokenCompletion > 0 &&
    tokenTotal >= tokenPrompt + tokenCompletion;
  const pass = behaviorMatches && traceIsReal && Boolean(parsed.reason?.trim());
  const evidence = {
    caseId: context.vars.case_id,
    expected,
    actual: parsed,
    threadIdPresent: Boolean(appServer.threadId),
    turnIdPresent: Boolean(appServer.turnId),
    sandboxMode: appServer.sandboxMode,
    approvalPolicy: appServer.approvalPolicy,
    commandExecutions: Number(itemCounts.commandExecution || 0),
    agentMessages: Number(itemCounts.agentMessage || 0),
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
      ? `Parent-grounded external-reality behavior passed (${JSON.stringify(evidence)})`
      : `Behavior mismatch or missing real trace: ${JSON.stringify(evidence)}`,
  };
};
