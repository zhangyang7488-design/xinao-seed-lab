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
  const alternatives = (value) =>
    Array.isArray(value) ? value : String(value).split("|");
  const selectedBehaviors = alternatives(
    context.vars.expected_selected_behavior,
  );
  const matureComparisonValues = alternatives(
    context.vars.expected_mature_comparison_required,
  ).map(asBool);
  const expected = {
    case_id: context.vars.case_id,
    selected_behavior:
      selectedBehaviors.length === 1 ? selectedBehaviors[0] : selectedBehaviors,
    mature_comparison_required:
      matureComparisonValues.length === 1
        ? matureComparisonValues[0]
        : matureComparisonValues,
    green_alone_sufficient: asBool(context.vars.expected_green_alone_sufficient),
    hand_rolled_extension_without_review: asBool(
      context.vars.expected_hand_rolled_extension_without_review,
    ),
    replace_core_spine_without_separate_evidence: asBool(
      context.vars.expected_replace_core_spine_without_separate_evidence,
    ),
  };

  const usage = context.providerResponse?.tokenUsage || {};
  const appServer = context.metadata?.codexAppServer || {};
  const itemCounts = appServer.itemCounts || {};
  const tokenTotal = Number(usage.total || usage.total_tokens || 0);
  const tokenPrompt = Number(usage.prompt || usage.prompt_tokens || 0);
  const tokenCompletion = Number(
    usage.completion || usage.completion_tokens || 0,
  );

  const behaviorMatches =
    selectedBehaviors.includes(parsed.selected_behavior) &&
    matureComparisonValues.includes(parsed.mature_comparison_required) &&
    Object.entries(expected).every(
      ([key, value]) =>
        [
          "selected_behavior",
          "mature_comparison_required",
        ].includes(key) || parsed[key] === value,
    );
  const policySafe =
    parsed.green_alone_sufficient === false &&
    parsed.hand_rolled_extension_without_review === false &&
    parsed.replace_core_spine_without_separate_evidence === false;
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
  const pass =
    behaviorMatches &&
    policySafe &&
    traceIsReal &&
    Boolean(parsed.reason?.trim());

  const evidence = {
    caseId: parsed.case_id,
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
      ? `Proactive mature-first behavior and real app-server trace passed (${JSON.stringify(evidence)})`
      : `Behavior mismatch or missing trace evidence: ${JSON.stringify(evidence)}`,
  };
};
