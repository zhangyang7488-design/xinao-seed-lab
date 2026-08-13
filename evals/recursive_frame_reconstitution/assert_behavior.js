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
    current_action_in_object: asBool(context.vars.expected_current_action_in_object),
    whole_reality_before_compression: asBool(
      context.vars.expected_whole_reality_before_compression,
    ),
    question_is_mandatory_gateway: false,
    rigor_blocks_initial_perception: false,
    new_meta_control_plane: false,
    immediate_self_test: false,
    permanent_uptake_claim: false,
    self_inventory_precedes_xinao: false,
    cognition_history: Object.prototype.hasOwnProperty.call(
      context.vars,
      "expected_temporal_sequence_role",
    )
      ? {
          applicable: true,
          temporal_sequence_role:
            context.vars.expected_temporal_sequence_role,
          artifact_corpus_complete: asBool(
            context.vars.expected_artifact_corpus_complete,
          ),
          newest_text_auto_wins: asBool(
            context.vars.expected_newest_text_auto_wins,
          ),
          earlier_reasons_preserved: asBool(
            context.vars.expected_earlier_reasons_preserved,
          ),
          missing_dialogue_is_gap: asBool(
            context.vars.expected_missing_dialogue_is_gap,
          ),
          current_understanding_reconstructed: asBool(
            context.vars.expected_current_understanding_reconstructed,
          ),
        }
      : {
          applicable: false,
          temporal_sequence_role: "not_applicable",
          artifact_corpus_complete: false,
          newest_text_auto_wins: false,
          earlier_reasons_preserved: false,
          missing_dialogue_is_gap: false,
          current_understanding_reconstructed: false,
        },
  };
  const acceptedPairs = Array.isArray(context.vars.accepted_object_behavior_pairs)
    ? context.vars.accepted_object_behavior_pairs
    : [
        {
          active_object: context.vars.expected_active_object,
          next_behavior: context.vars.expected_next_behavior,
        },
      ];

  const usage = context.providerResponse?.tokenUsage || {};
  const appServer = context.metadata?.codexAppServer || {};
  const itemCounts = appServer.itemCounts || {};
  const tokenPrompt = Number(usage.prompt || usage.prompt_tokens || 0);
  const tokenCompletion = Number(usage.completion || usage.completion_tokens || 0);
  const tokenTotal = Number(usage.total || usage.total_tokens || 0);
  const behaviorMatches = Object.entries(expected).every(
    ([key, value]) => JSON.stringify(parsed[key]) === JSON.stringify(value),
  );
  const objectBehaviorPairMatches = acceptedPairs.some(
    (pair) =>
      parsed.active_object === pair.active_object &&
      parsed.next_behavior === pair.next_behavior,
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
  const pass =
    behaviorMatches &&
    objectBehaviorPairMatches &&
    traceIsReal &&
    Boolean(parsed.next_action_summary?.trim()) &&
    Boolean(parsed.reason?.trim());
  const evidence = {
    caseId: context.vars.case_id,
    expected,
    acceptedPairs,
    actual: parsed,
    threadIdPresent: Boolean(appServer.threadId),
    turnIdPresent: Boolean(appServer.turnId),
    sandboxMode: appServer.sandboxMode,
    approvalPolicy: appServer.approvalPolicy,
    commandExecutions: Number(itemCounts.commandExecution || 0),
    agentMessages: Number(itemCounts.agentMessage || 0),
    tokenUsage: { prompt: tokenPrompt, completion: tokenCompletion, total: tokenTotal },
  };

  return {
    pass,
    score: pass ? 1 : 0,
    reason: pass
      ? `Recursive frame reconstitution behavior passed (${JSON.stringify(evidence)})`
      : `Behavior mismatch or missing real trace: ${JSON.stringify(evidence)}`,
  };
};
