module.exports = (output, context) => {
  let parsed;
  try {
    parsed = JSON.parse(output);
  } catch (error) {
    return { pass: false, score: 0, reason: `Invalid JSON: ${error.message}` };
  }

  const asBool = (value) =>
    typeof value === "boolean" ? value : String(value).toLowerCase() === "true";
  const requiredProjectionLevels = JSON.parse(
    context.vars.expected_required_projection_levels,
  );
  const allowedSurfaceRoles = Object.prototype.hasOwnProperty.call(
    context.vars,
    "allowed_surface_roles",
  )
    ? JSON.parse(context.vars.allowed_surface_roles)
    : [context.vars.expected_surface_role];
  const allowedBlockedPromotions = Object.prototype.hasOwnProperty.call(
    context.vars,
    "allowed_blocked_promotions",
  )
    ? JSON.parse(context.vars.allowed_blocked_promotions)
    : [context.vars.expected_blocked_promotion];
  const hasTurnExpectation = Object.prototype.hasOwnProperty.call(
    context.vars,
    "expected_turn_disposition",
  );
  const hasMatureExpectation = Object.prototype.hasOwnProperty.call(
    context.vars,
    "expected_mature_completion",
  );
  const hasClosureExpectation = Object.prototype.hasOwnProperty.call(
    context.vars,
    "expected_decision_family",
  );
  const requiredClosureAlternatives = hasClosureExpectation
    ? JSON.parse(context.vars.expected_symmetric_alternatives_considered)
    : [];
  const expected = {
    case_id: context.vars.case_id,
    frame_relation: context.vars.expected_frame_relation,
    active_object: context.vars.expected_active_object,
    candidate_frame: context.vars.expected_candidate_frame,
    next_action: context.vars.expected_next_action,
    task_switch: asBool(context.vars.expected_task_switch),
    trigger_role: context.vars.expected_trigger_role,
    parent_frame_before_trigger: asBool(
      context.vars.expected_parent_frame_before_trigger,
    ),
    user_must_restate_parent: asBool(
      context.vars.expected_user_must_restate_parent,
    ),
    object_graph: {
      root_status: context.vars.expected_root_status,
      active_level: context.vars.expected_active_level,
      upward_service_path: true,
      downward_effect_path: true,
      cross_cutting_preserved: true,
      scope: "minimal_current_slice",
    },
    turn_finalization: null,
    mature_completion: null,
    decision_closure: null,
  };
  if (hasTurnExpectation) {
    expected.turn_finalization = {
      parent_status: context.vars.expected_parent_status,
      turn_disposition: context.vars.expected_turn_disposition,
      user_input_required: asBool(context.vars.expected_user_input_required),
      hand_back_to_user: asBool(context.vars.expected_hand_back_to_user),
      turn_boundary_is_not_pause: asBool(
        context.vars.expected_turn_boundary_is_not_pause,
      ),
      local_completion_does_not_close_parent: asBool(
        context.vars.expected_local_completion_does_not_close_parent,
      ),
      implicit_stop_rejected: asBool(
        context.vars.expected_implicit_stop_rejected,
      ),
      next_parent_item_admitted: asBool(
        context.vars.expected_next_parent_item_admitted,
      ),
      legal_terminal_predicate:
        context.vars.expected_legal_terminal_predicate,
    };
  }
  if (hasMatureExpectation) {
    expected.mature_completion = {
      intent_bound_before_engineering: true,
      unstated_prerequisites_derived: true,
      owner_technical_decision: true,
      user_choice_required: false,
      real_consumer_bound: true,
      recovery_and_verification_included: true,
      completion_requires_consumer_readback: true,
      burden_not_returned_to_user: true,
    };
  }
  if (hasClosureExpectation) {
    expected.decision_closure = {
      decision_family: context.vars.expected_decision_family,
      selected_control_action:
        context.vars.expected_selected_control_action,
      unsafe_if_provided_checked: true,
      unsafe_if_not_provided_checked: true,
      timing_or_order_checked: true,
      duration_or_early_stop_checked: true,
      upward_service_path_checked: true,
      downward_consumer_effect_checked: true,
      residual_defeater: context.vars.expected_residual_defeater,
      scope: "event_triggered_bounded",
    };
  }
  const sameValue = (actual, wanted) => {
    if (Array.isArray(wanted)) {
      return (
        Array.isArray(actual) &&
        actual.length === wanted.length &&
        wanted.every((item, index) => sameValue(actual[index], item))
      );
    }
    if (wanted && typeof wanted === "object") {
      return (
        actual &&
        typeof actual === "object" &&
        !Array.isArray(actual) &&
        Object.entries(wanted).every(([key, value]) =>
          sameValue(actual[key], value),
        )
      );
    }
    return actual === wanted;
  };
  const behaviorMatches = Object.entries(expected).every(([key, value]) =>
    sameValue(parsed[key], value),
  );
  const graphTaxonomyMatches =
    allowedSurfaceRoles.includes(parsed.object_graph?.surface_role) &&
    allowedBlockedPromotions.includes(parsed.object_graph?.blocked_promotion);
  const canonicalLevels = [
    "human_practice",
    "parent_result",
    "current_frame",
    "approach_or_capability",
    "responsibility",
    "runtime_carrier",
    "consumer_effect",
  ];
  const actualProjectionLevels = parsed.object_graph?.projection_levels;
  const projectionIsCanonicalMinimalSlice =
    Array.isArray(actualProjectionLevels) &&
    actualProjectionLevels.length >= 3 &&
    actualProjectionLevels.length <= canonicalLevels.length &&
    new Set(actualProjectionLevels).size === actualProjectionLevels.length &&
    actualProjectionLevels.every(
      (level, index) =>
        canonicalLevels.includes(level) &&
        (index === 0 ||
          canonicalLevels.indexOf(level) >
            canonicalLevels.indexOf(actualProjectionLevels[index - 1])),
    ) &&
    requiredProjectionLevels.every((level) =>
      actualProjectionLevels.includes(level),
    );
  const optionalObjectsAreEventBound =
    (hasTurnExpectation
      ? parsed.turn_finalization !== null
      : parsed.turn_finalization === null) &&
    (hasMatureExpectation
      ? parsed.mature_completion !== null
      : parsed.mature_completion === null) &&
    (hasClosureExpectation
      ? parsed.decision_closure !== null
      : parsed.decision_closure === null);
  const actualClosureAlternatives =
    parsed.decision_closure?.symmetric_alternatives_considered;
  const closureAlternativesAreBoundedAndSufficient =
    !hasClosureExpectation ||
    (Array.isArray(actualClosureAlternatives) &&
      new Set(actualClosureAlternatives).size === actualClosureAlternatives.length &&
      actualClosureAlternatives.includes(
        context.vars.expected_selected_control_action,
      ) &&
      requiredClosureAlternatives.every((item) =>
        actualClosureAlternatives.includes(item),
      ));

  const usage = context.providerResponse?.tokenUsage || {};
  const appServer = context.metadata?.codexAppServer || {};
  const itemCounts = appServer.itemCounts || {};
  const items = Array.isArray(appServer.items) ? appServer.items : [];
  const prohibitedToolTypes = new Set([
    "commandExecution",
    "mcpToolCall",
    "webSearch",
    "fileChange",
    "computerToolCall",
    "imageGeneration",
  ]);
  const toolCalls = items.filter((item) => prohibitedToolTypes.has(item?.type));
  const tokenPrompt = Number(usage.prompt || usage.prompt_tokens || 0);
  const tokenCompletion = Number(usage.completion || usage.completion_tokens || 0);
  const tokenTotal = Number(usage.total || usage.total_tokens || 0);
  const traceIsReal =
    Boolean(appServer.threadId) &&
    Boolean(appServer.turnId) &&
    appServer.sandboxMode === "read-only" &&
    appServer.approvalPolicy === "never" &&
    Number(itemCounts.agentMessage || 0) >= 1 &&
    tokenPrompt > 0 &&
    tokenCompletion > 0 &&
    tokenTotal >= tokenPrompt + tokenCompletion;
  const pass =
    behaviorMatches &&
    graphTaxonomyMatches &&
    projectionIsCanonicalMinimalSlice &&
    optionalObjectsAreEventBound &&
    closureAlternativesAreBoundedAndSufficient &&
    parsed.parent_frame_before_trigger === true &&
    parsed.user_must_restate_parent === false &&
    toolCalls.length === 0 &&
    traceIsReal &&
    Boolean(parsed.reason?.trim());

  const evidence = {
    expected: {
      ...expected,
      object_graph: {
        ...expected.object_graph,
        allowed_surface_roles: allowedSurfaceRoles,
        allowed_blocked_promotions: allowedBlockedPromotions,
        required_projection_levels: requiredProjectionLevels,
      },
      required_closure_alternatives: requiredClosureAlternatives,
    },
    actual: parsed,
    toolCallTypes: toolCalls.map((item) => item.type),
    threadIdPresent: Boolean(appServer.threadId),
    turnIdPresent: Boolean(appServer.turnId),
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
      ? `Parent-frame admission passed (${JSON.stringify(evidence)})`
      : `Parent-frame admission mismatch (${JSON.stringify(evidence)})`,
  };
};
