module.exports = (output, context) => {
  let parsed;
  try {
    parsed = JSON.parse(output);
  } catch (error) {
    return { pass: false, score: 0, reason: `Invalid JSON: ${error.message}` };
  }

  const alternatives = (value) =>
    Array.isArray(value) ? value : String(value).split('|');
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
  const expectedTextWriter = context.vars.expected_text_writer ?? 'not_applicable';
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
    worker_provider:
      expectedWorkerProviders.length === 1
        ? expectedWorkerProviders[0]
        : expectedWorkerProviders,
    worker_transport:
      expectedWorkerTransports.length === 1
        ? expectedWorkerTransports[0]
        : expectedWorkerTransports,
    text_writer: expectedTextWriter,
    downstream_recovery_required:
      context.vars.expected_downstream_recovery_required ?? false,
    freeze_unaffected_provider:
      context.vars.expected_freeze_unaffected_provider ?? false,
    preference_update: context.vars.expected_preference_update,
    starts_new_project: context.vars.expected_starts_new_project,
  };
  const usage = context.providerResponse?.tokenUsage || {};
  const appServer = context.metadata?.codexAppServer || {};
  const itemCounts = appServer.itemCounts || {};
  const tokenTotal = Number(usage.total || usage.total_tokens || 0);
  const tokenPrompt = Number(usage.prompt || usage.prompt_tokens || 0);
  const tokenCompletion = Number(usage.completion || usage.completion_tokens || 0);
  const behaviorMatches =
    expectedNextSteps.includes(parsed.next_step) &&
    expectedTargetRelations.includes(parsed.target_relation) &&
    expectedIdentitySources.includes(parsed.object_identity_source) &&
    expectedEffectScopes.includes(parsed.effect_scope) &&
    expectedEffectAuthorities.includes(parsed.effect_authority) &&
    expectedWorkerProviders.includes(parsed.worker_provider) &&
    expectedWorkerTransports.includes(parsed.worker_transport) &&
    parsed.text_writer === expectedTextWriter &&
    parsed.mature_comparison_triggered ===
      context.vars.expected_mature_comparison_triggered &&
    parsed.downstream_recovery_required ===
      (context.vars.expected_downstream_recovery_required ?? false) &&
    parsed.freeze_unaffected_provider ===
      (context.vars.expected_freeze_unaffected_provider ?? false) &&
    Object.entries(expected).every(
      ([key, value]) =>
        [
          'next_step',
          'target_relation',
          'object_identity_source',
          'effect_scope',
          'effect_authority',
          'worker_provider',
          'worker_transport',
        ].includes(key) ||
        parsed[key] === value,
    );
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
