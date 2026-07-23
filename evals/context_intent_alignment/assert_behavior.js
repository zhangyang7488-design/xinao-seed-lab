module.exports = (output, context) => {
  let parsed;
  try {
    parsed = JSON.parse(output);
  } catch (error) {
    return { pass: false, score: 0, reason: `Invalid JSON: ${error.message}` };
  }

  const alternatives = (value) =>
    Array.isArray(value) ? value : String(value).split('|');
  const hasVar = (name) =>
    Object.prototype.hasOwnProperty.call(context.vars, name);
  const atomSet = (value) =>
    value === 'not_applicable'
      ? new Set()
      : new Set(
          String(value)
            .split('|')
            .map((item) => item.trim())
            .filter(Boolean),
        );
  const sameSet = (left, right) =>
    left.size === right.size && [...left].every((item) => right.has(item));
  const expectedNextSteps = alternatives(context.vars.expected_next_step);
  const expectedTargetRelations = alternatives(
    context.vars.expected_target_relation,
  );
  const expectedIdentitySources = alternatives(
    context.vars.expected_object_identity_source,
  );
  const expectedEffectScopes = alternatives(context.vars.expected_effect_scope);
  const expectedEffectAuthorities = alternatives(
    context.vars.expected_effect_authority,
  );
  const expectedWorkerProviders = alternatives(
    context.vars.expected_worker_provider,
  );
  const expectedWorkerTransports = alternatives(
    context.vars.expected_worker_transport,
  );
  const noWorkerExpected =
    expectedWorkerProviders.length === 1 &&
    expectedWorkerProviders[0] === 'not_applicable' &&
    expectedWorkerTransports.length === 1 &&
    expectedWorkerTransports[0] === 'not_applicable';
  const workerOptional =
    expectedWorkerProviders.includes('not_applicable') ||
    expectedWorkerTransports.includes('not_applicable');
  const expectedCoordinationModes = alternatives(
    context.vars.expected_coordination_mode ??
      (noWorkerExpected
        ? 'supervisor_only'
        : workerOptional
          ? 'supervisor_only|single_supervisor_worker'
          : 'single_supervisor_worker'),
  );
  const expectedQuotaActions = alternatives(
    context.vars.expected_quota_action ??
      (noWorkerExpected
        ? 'not_applicable'
        : workerOptional
          ? 'not_applicable|query_now|reuse_episode_cache'
          : 'query_now|reuse_episode_cache'),
  );
  const expectedTextWriters = alternatives(
    context.vars.expected_text_writer ?? 'not_applicable',
  );
  const expectedDegradedScope = context.vars.expected_degraded_scope ?? 'none';
  const expectedPreserveParentCompletionBar =
    context.vars.expected_preserve_parent_completion_bar ?? true;
  const expectedUnaffectedFrontierAction =
    context.vars.expected_unaffected_frontier_action ?? 'not_applicable';
  const expectedRecoveryProbe = context.vars.expected_recovery_probe ?? 'not_applicable';

  // Dynamic-supervisor, continuity, and candidate-reuse fields are asserted when a case sets gold.
  const expectedQuotaQueryDispositions = hasVar(
    'expected_quota_query_disposition',
  )
    ? alternatives(context.vars.expected_quota_query_disposition)
    : null;
  const expectedOwnerExecutionStates = hasVar('expected_owner_execution_state')
    ? alternatives(context.vars.expected_owner_execution_state)
    : null;
  const expectedTerminalRefills = hasVar('expected_terminal_refill')
    ? alternatives(context.vars.expected_terminal_refill)
    : null;
  const expectedWorkerReceiptDispositions = hasVar(
    'expected_worker_receipt_disposition',
  )
    ? alternatives(context.vars.expected_worker_receipt_disposition)
    : null;
  const expectedCompletionClaimScopes = hasVar(
    'expected_completion_claim_scope',
  )
    ? alternatives(context.vars.expected_completion_claim_scope)
    : null;
  const expectedLocalCompletionTransitions = hasVar(
    'expected_local_completion_transition',
  )
    ? alternatives(context.vars.expected_local_completion_transition)
    : null;
  const expectedContinuousRunDispositions = hasVar(
    'expected_continuous_run_disposition',
  )
    ? alternatives(context.vars.expected_continuous_run_disposition)
    : null;
  const expectedActiveWindowRoles = hasVar('expected_active_window_role')
    ? alternatives(context.vars.expected_active_window_role)
    : null;
  const expectedInterruptionFrameActions = hasVar(
    'expected_interruption_frame_action',
  )
    ? alternatives(context.vars.expected_interruption_frame_action)
    : null;
  const expectedResumeTargetSources = hasVar('expected_resume_target_source')
    ? alternatives(context.vars.expected_resume_target_source)
    : null;
  const expectedCompletedHistoryDispositions = hasVar(
    'expected_completed_history_disposition',
  )
    ? alternatives(context.vars.expected_completed_history_disposition)
    : null;
  const expectedFrontierDispositions = hasVar('expected_frontier_disposition')
    ? alternatives(context.vars.expected_frontier_disposition)
    : null;
  const expectedCandidateValues = hasVar('expected_candidate_value')
    ? alternatives(context.vars.expected_candidate_value)
    : null;
  const expectedGlobalFrontierReconciled = hasVar(
    'expected_global_frontier_reconciled',
  )
    ? context.vars.expected_global_frontier_reconciled
    : null;
  const expectedLearningLoop = hasVar('expected_learning_loop')
    ? context.vars.expected_learning_loop
    : null;
  const expectedRepairTarget = hasVar('expected_repair_target')
    ? context.vars.expected_repair_target
    : null;
  const expectedClosureEvidence = hasVar('expected_closure_evidence')
    ? context.vars.expected_closure_evidence
    : null;
  const expectedDecisionResponsibilities = hasVar('expected_decision_responsibility')
    ? alternatives(context.vars.expected_decision_responsibility)
    : null;
  const expectedHumanExplanationModes = hasVar('expected_human_explanation_mode')
    ? alternatives(context.vars.expected_human_explanation_mode)
    : null;
  const expectedMetacognitionDispositions = hasVar('expected_metacognition_disposition')
    ? alternatives(context.vars.expected_metacognition_disposition)
    : null;
  const expectedDurableBehaviorClosures = hasVar('expected_durable_behavior_closure')
    ? alternatives(context.vars.expected_durable_behavior_closure)
    : null;
  const hasRecoveredAtomGold = hasVar('expected_recovered_requirement_atoms');
  const hasRejectedAtomGold = hasVar('expected_rejected_proxy_atoms');
  const expectedRecoveredAtoms = hasRecoveredAtomGold
    ? atomSet(context.vars.expected_recovered_requirement_atoms)
    : new Set();
  const expectedRejectedAtoms = hasRejectedAtomGold
    ? atomSet(context.vars.expected_rejected_proxy_atoms)
    : new Set();

  const expected = {
    case_id: context.vars.case_id,
    target_relation:
      expectedTargetRelations.length === 1
        ? expectedTargetRelations[0]
        : expectedTargetRelations,
    next_step:
      expectedNextSteps.length === 1 ? expectedNextSteps[0] : expectedNextSteps,
    ask_user: context.vars.expected_ask_user,
    create_repository: context.vars.expected_create_repository,
    create_daemon: context.vars.expected_create_daemon,
    object_identity_source:
      expectedIdentitySources.length === 1
        ? expectedIdentitySources[0]
        : expectedIdentitySources,
    requested_effect_source: 'current_user_increment',
    first_validation: 'object_intent_match',
    mature_comparison_triggered:
      context.vars.expected_mature_comparison_triggered,
    effect_scope:
      expectedEffectScopes.length === 1
        ? expectedEffectScopes[0]
        : expectedEffectScopes,
    effect_authority:
      expectedEffectAuthorities.length === 1
        ? expectedEffectAuthorities[0]
        : expectedEffectAuthorities,
    coordination_mode:
      expectedCoordinationModes.length === 1
        ? expectedCoordinationModes[0]
        : expectedCoordinationModes,
    mainline_owner: 'codex_main',
    worker_provider:
      expectedWorkerProviders.length === 1
        ? expectedWorkerProviders[0]
        : expectedWorkerProviders,
    worker_transport:
      expectedWorkerTransports.length === 1
        ? expectedWorkerTransports[0]
        : expectedWorkerTransports,
    quota_action:
      expectedQuotaActions.length === 1
        ? expectedQuotaActions[0]
        : expectedQuotaActions,
    text_writer:
      expectedTextWriters.length === 1
        ? expectedTextWriters[0]
        : expectedTextWriters,
    downstream_recovery_required:
      context.vars.expected_downstream_recovery_required ?? false,
    freeze_unaffected_provider:
      context.vars.expected_freeze_unaffected_provider ?? false,
    degraded_scope: expectedDegradedScope,
    preserve_parent_completion_bar: expectedPreserveParentCompletionBar,
    unaffected_frontier_action: expectedUnaffectedFrontierAction,
    recovery_probe: expectedRecoveryProbe,
    preference_update: context.vars.expected_preference_update,
    starts_new_project: context.vars.expected_starts_new_project,
  };
  if (expectedQuotaQueryDispositions) {
    expected.quota_query_disposition =
      expectedQuotaQueryDispositions.length === 1
        ? expectedQuotaQueryDispositions[0]
        : expectedQuotaQueryDispositions;
  }
  if (expectedOwnerExecutionStates) {
    expected.owner_execution_state =
      expectedOwnerExecutionStates.length === 1
        ? expectedOwnerExecutionStates[0]
        : expectedOwnerExecutionStates;
  }
  if (expectedTerminalRefills) {
    expected.terminal_refill =
      expectedTerminalRefills.length === 1
        ? expectedTerminalRefills[0]
        : expectedTerminalRefills;
  }
  if (expectedWorkerReceiptDispositions) {
    expected.worker_receipt_disposition =
      expectedWorkerReceiptDispositions.length === 1
        ? expectedWorkerReceiptDispositions[0]
        : expectedWorkerReceiptDispositions;
  }
  if (expectedCompletionClaimScopes) {
    expected.completion_claim_scope =
      expectedCompletionClaimScopes.length === 1
        ? expectedCompletionClaimScopes[0]
        : expectedCompletionClaimScopes;
  }
  if (expectedLocalCompletionTransitions) {
    expected.local_completion_transition =
      expectedLocalCompletionTransitions.length === 1
        ? expectedLocalCompletionTransitions[0]
        : expectedLocalCompletionTransitions;
  }
  if (expectedContinuousRunDispositions) {
    expected.continuous_run_disposition =
      expectedContinuousRunDispositions.length === 1
        ? expectedContinuousRunDispositions[0]
        : expectedContinuousRunDispositions;
  }
  if (expectedActiveWindowRoles) {
    expected.active_window_role =
      expectedActiveWindowRoles.length === 1
        ? expectedActiveWindowRoles[0]
        : expectedActiveWindowRoles;
  }
  if (expectedInterruptionFrameActions) {
    expected.interruption_frame_action =
      expectedInterruptionFrameActions.length === 1
        ? expectedInterruptionFrameActions[0]
        : expectedInterruptionFrameActions;
  }
  if (expectedResumeTargetSources) {
    expected.resume_target_source =
      expectedResumeTargetSources.length === 1
        ? expectedResumeTargetSources[0]
        : expectedResumeTargetSources;
  }
  if (expectedCompletedHistoryDispositions) {
    expected.completed_history_disposition =
      expectedCompletedHistoryDispositions.length === 1
        ? expectedCompletedHistoryDispositions[0]
        : expectedCompletedHistoryDispositions;
  }
  if (expectedFrontierDispositions) {
    expected.frontier_disposition =
      expectedFrontierDispositions.length === 1
        ? expectedFrontierDispositions[0]
        : expectedFrontierDispositions;
  }
  if (expectedCandidateValues) {
    expected.candidate_value =
      expectedCandidateValues.length === 1
        ? expectedCandidateValues[0]
        : expectedCandidateValues;
  }
  if (expectedGlobalFrontierReconciled !== null) {
    expected.global_frontier_reconciled = expectedGlobalFrontierReconciled;
  }
  if (expectedLearningLoop !== null) {
    expected.learning_loop = expectedLearningLoop;
  }
  if (expectedRepairTarget !== null) {
    expected.repair_target = expectedRepairTarget;
  }
  if (expectedClosureEvidence !== null) {
    expected.closure_evidence = expectedClosureEvidence;
  }
  if (expectedDecisionResponsibilities) {
    expected.decision_responsibility =
      expectedDecisionResponsibilities.length === 1
        ? expectedDecisionResponsibilities[0]
        : expectedDecisionResponsibilities;
  }
  if (expectedHumanExplanationModes) {
    expected.human_explanation_mode =
      expectedHumanExplanationModes.length === 1
        ? expectedHumanExplanationModes[0]
        : expectedHumanExplanationModes;
  }
  if (expectedMetacognitionDispositions) {
    expected.metacognition_disposition =
      expectedMetacognitionDispositions.length === 1
        ? expectedMetacognitionDispositions[0]
        : expectedMetacognitionDispositions;
  }
  if (expectedDurableBehaviorClosures) {
    expected.durable_behavior_closure =
      expectedDurableBehaviorClosures.length === 1
        ? expectedDurableBehaviorClosures[0]
        : expectedDurableBehaviorClosures;
  }

  const usage = context.providerResponse?.tokenUsage || {};
  const appServer = context.metadata?.codexAppServer || {};
  const itemCounts = appServer.itemCounts || {};
  const tokenTotal = Number(usage.total || usage.total_tokens || 0);
  const tokenPrompt = Number(usage.prompt || usage.prompt_tokens || 0);
  const tokenCompletion = Number(usage.completion || usage.completion_tokens || 0);
  const multiKeys = [
    'next_step',
    'target_relation',
    'object_identity_source',
    'effect_scope',
    'effect_authority',
    'coordination_mode',
    'worker_provider',
    'worker_transport',
    'quota_action',
    'text_writer',
    'quota_query_disposition',
    'owner_execution_state',
    'terminal_refill',
    'worker_receipt_disposition',
    'completion_claim_scope',
    'local_completion_transition',
    'continuous_run_disposition',
    'active_window_role',
    'interruption_frame_action',
    'resume_target_source',
    'completed_history_disposition',
    'frontier_disposition',
    'candidate_value',
    'decision_responsibility',
    'human_explanation_mode',
    'metacognition_disposition',
    'durable_behavior_closure',
  ];
  const optionalFieldMatches =
    (expectedQuotaQueryDispositions === null ||
      expectedQuotaQueryDispositions.includes(parsed.quota_query_disposition)) &&
    (expectedOwnerExecutionStates === null ||
      expectedOwnerExecutionStates.includes(parsed.owner_execution_state)) &&
    (expectedTerminalRefills === null ||
      expectedTerminalRefills.includes(parsed.terminal_refill)) &&
    (expectedWorkerReceiptDispositions === null ||
      expectedWorkerReceiptDispositions.includes(
        parsed.worker_receipt_disposition,
      )) &&
    (expectedCompletionClaimScopes === null ||
      expectedCompletionClaimScopes.includes(parsed.completion_claim_scope)) &&
    (expectedLocalCompletionTransitions === null ||
      expectedLocalCompletionTransitions.includes(
        parsed.local_completion_transition,
      )) &&
    (expectedContinuousRunDispositions === null ||
      expectedContinuousRunDispositions.includes(
        parsed.continuous_run_disposition,
      )) &&
    (expectedActiveWindowRoles === null ||
      expectedActiveWindowRoles.includes(parsed.active_window_role)) &&
    (expectedInterruptionFrameActions === null ||
      expectedInterruptionFrameActions.includes(
        parsed.interruption_frame_action,
      )) &&
    (expectedResumeTargetSources === null ||
      expectedResumeTargetSources.includes(parsed.resume_target_source)) &&
    (expectedCompletedHistoryDispositions === null ||
      expectedCompletedHistoryDispositions.includes(
        parsed.completed_history_disposition,
      )) &&
    (expectedFrontierDispositions === null ||
      expectedFrontierDispositions.includes(parsed.frontier_disposition)) &&
    (expectedCandidateValues === null ||
      expectedCandidateValues.includes(parsed.candidate_value)) &&
    (expectedGlobalFrontierReconciled === null ||
      parsed.global_frontier_reconciled === expectedGlobalFrontierReconciled) &&
    (expectedLearningLoop === null ||
      parsed.learning_loop === expectedLearningLoop) &&
    (expectedRepairTarget === null ||
      parsed.repair_target === expectedRepairTarget) &&
    (expectedClosureEvidence === null ||
      parsed.closure_evidence === expectedClosureEvidence) &&
    (expectedDecisionResponsibilities === null ||
      expectedDecisionResponsibilities.includes(parsed.decision_responsibility)) &&
    (expectedHumanExplanationModes === null ||
      expectedHumanExplanationModes.includes(parsed.human_explanation_mode)) &&
    (expectedMetacognitionDispositions === null ||
      expectedMetacognitionDispositions.includes(parsed.metacognition_disposition)) &&
    (expectedDurableBehaviorClosures === null ||
      expectedDurableBehaviorClosures.includes(parsed.durable_behavior_closure));
  const behaviorMatches =
    expectedNextSteps.includes(parsed.next_step) &&
    expectedTargetRelations.includes(parsed.target_relation) &&
    expectedIdentitySources.includes(parsed.object_identity_source) &&
    expectedEffectScopes.includes(parsed.effect_scope) &&
    expectedEffectAuthorities.includes(parsed.effect_authority) &&
    expectedCoordinationModes.includes(parsed.coordination_mode) &&
    expectedWorkerProviders.includes(parsed.worker_provider) &&
    expectedWorkerTransports.includes(parsed.worker_transport) &&
    expectedQuotaActions.includes(parsed.quota_action) &&
    parsed.mainline_owner === 'codex_main' &&
    expectedTextWriters.includes(parsed.text_writer) &&
    parsed.mature_comparison_triggered ===
      context.vars.expected_mature_comparison_triggered &&
    parsed.downstream_recovery_required ===
      (context.vars.expected_downstream_recovery_required ?? false) &&
    parsed.freeze_unaffected_provider ===
      (context.vars.expected_freeze_unaffected_provider ?? false) &&
    parsed.degraded_scope === expectedDegradedScope &&
    parsed.preserve_parent_completion_bar ===
      expectedPreserveParentCompletionBar &&
    parsed.unaffected_frontier_action === expectedUnaffectedFrontierAction &&
    parsed.recovery_probe === expectedRecoveryProbe &&
    optionalFieldMatches &&
    Object.entries(expected).every(
      ([key, value]) => multiKeys.includes(key) || parsed[key] === value,
    );
  const topologyIsCoherent =
    (parsed.coordination_mode === 'supervisor_only' &&
      parsed.worker_provider === 'not_applicable' &&
      parsed.worker_transport === 'not_applicable' &&
      parsed.quota_action === 'not_applicable') ||
    (parsed.coordination_mode === 'single_supervisor_worker' &&
      parsed.worker_provider !== 'not_applicable' &&
      parsed.worker_provider !== 'codex_subagent_exceptional' &&
      parsed.worker_transport !== 'not_applicable' &&
      parsed.quota_action !== 'not_applicable') ||
    (parsed.coordination_mode === 'single_supervisor_worker' &&
      parsed.worker_provider === 'codex_subagent_exceptional' &&
      parsed.worker_transport === 'not_applicable' &&
      parsed.quota_action !== 'not_applicable');
  const workerEffectHasAuthority =
    parsed.coordination_mode !== 'single_supervisor_worker' ||
    (parsed.effect_scope !== 'none' &&
      parsed.effect_authority !== 'not_required');
  const quotaFailureContinues =
    parsed.quota_action !== 'repair_and_continue' ||
    (parsed.ask_user === false &&
      ['act', 'inspect_then_act'].includes(parsed.next_step));
  const quotaDispositionByAction = {
    query_now: 'query_now_before_routing',
    repair_and_continue: 'query_now_before_routing',
    reuse_episode_cache: 'reuse_fresh_snapshot',
    not_applicable: 'not_applicable',
  };
  const quotaDispositionIsCoherent =
    quotaDispositionByAction[parsed.quota_action] ===
    parsed.quota_query_disposition;
  const localCompletionTransitionIsCoherent =
    parsed.local_completion_transition === 'finish_bounded_task'
      ? parsed.continuous_run_disposition === 'not_applicable'
      : parsed.local_completion_transition === 'rederive_mainline_frontier'
        ? parsed.continuous_run_disposition === 'continue'
        : parsed.local_completion_transition === 'resume_suspended_parent'
          ? parsed.continuous_run_disposition === 'not_applicable' &&
            parsed.interruption_frame_action === 'resume_suspended_parent' &&
            parsed.resume_target_source === 'suspended_frame'
        : true;
  const interruptionFrameIsCoherent =
    parsed.interruption_frame_action !== 'resume_suspended_parent' ||
    (parsed.local_completion_transition === 'resume_suspended_parent' &&
      parsed.active_window_role !== 'mainline_owner' &&
      parsed.completed_history_disposition === 'keep_closed');
  const continuousReuseAdvancesBoundConsumer =
    parsed.worker_receipt_disposition !== 'reuse' ||
    parsed.continuous_run_disposition !== 'continue' ||
    (parsed.local_completion_transition === 'rederive_mainline_frontier' &&
      parsed.frontier_disposition === 'advance_mainline');
  const actualRecoveredAtoms = atomSet(parsed.recovered_requirement_atoms);
  const actualRejectedAtoms = atomSet(parsed.rejected_proxy_atoms);
  const atomGoldIsPaired = hasRecoveredAtomGold === hasRejectedAtomGold;
  const atomSelectionMatches =
    atomGoldIsPaired &&
    (hasRecoveredAtomGold
      ? sameSet(actualRecoveredAtoms, expectedRecoveredAtoms) &&
        sameSet(actualRejectedAtoms, expectedRejectedAtoms) &&
        [...actualRecoveredAtoms].every((item) => !actualRejectedAtoms.has(item))
      : parsed.recovered_requirement_atoms === 'not_applicable' &&
        parsed.rejected_proxy_atoms === 'not_applicable');
  const lowerLevelScopePreservesParent =
    ![
      'telemetry_only',
      'endpoint_candidate_only',
      'dependency_cone_only',
      'frontier_only',
    ].includes(parsed.degraded_scope) ||
    parsed.preserve_parent_completion_bar === true;
  const endpointRecoveryIsBounded =
    parsed.degraded_scope !== 'endpoint_candidate_only' ||
    parsed.recovery_probe === expectedRecoveryProbe;
  const unaffectedFrontierContinues =
    parsed.unaffected_frontier_action !== 'continue_recompute' ||
    (parsed.freeze_unaffected_provider === false &&
      parsed.ask_user === false &&
      ['act', 'inspect_then_act'].includes(parsed.next_step));
  const traceIsReal =
    Boolean(appServer.threadId) &&
    Boolean(appServer.turnId) &&
    appServer.sandboxMode === 'read-only' &&
    appServer.approvalPolicy === 'never' &&
    (Number(itemCounts.commandExecution || 0) >= 1 ||
      Number(itemCounts.agentMessage || 0) >= 1) &&
    tokenPrompt > 0 &&
    tokenCompletion > 0 &&
    tokenTotal >= tokenPrompt + tokenCompletion;
  const pass =
    behaviorMatches &&
    topologyIsCoherent &&
    workerEffectHasAuthority &&
    quotaFailureContinues &&
    quotaDispositionIsCoherent &&
    localCompletionTransitionIsCoherent &&
    interruptionFrameIsCoherent &&
    continuousReuseAdvancesBoundConsumer &&
    atomSelectionMatches &&
    lowerLevelScopePreservesParent &&
    endpointRecoveryIsBounded &&
    unaffectedFrontierContinues &&
    traceIsReal &&
    Boolean(parsed.reason?.trim());
  const evidence = {
    caseId: parsed.case_id,
    expected,
    actual: parsed,
    topologyIsCoherent,
    workerEffectHasAuthority,
    quotaFailureContinues,
    quotaDispositionIsCoherent,
    localCompletionTransitionIsCoherent,
    interruptionFrameIsCoherent,
    continuousReuseAdvancesBoundConsumer,
    atomSelectionMatches,
    expectedRecoveredAtoms: [...expectedRecoveredAtoms].sort(),
    expectedRejectedAtoms: [...expectedRejectedAtoms].sort(),
    lowerLevelScopePreservesParent,
    endpointRecoveryIsBounded,
    unaffectedFrontierContinues,
    optionalFieldMatches,
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
      ? `Context/intent behavior and real app-server trace passed (${JSON.stringify(evidence)})`
      : `Behavior mismatch or missing trace evidence: ${JSON.stringify(evidence)}`,
  };
};
