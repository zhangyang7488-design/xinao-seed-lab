module.exports = (output, context) => {
  const fail = (reason, evidence = {}) => ({
    pass: false,
    score: 0,
    reason: `${reason}: ${JSON.stringify(evidence)}`,
  });

  let parsed;
  try {
    parsed = JSON.parse(output);
  } catch (error) {
    return fail('Invalid final JSON', { error: error.message });
  }

  let raw;
  try {
    raw = JSON.parse(context.providerResponse?.raw || '{}');
  } catch (error) {
    return fail('Invalid provider raw trace', { error: error.message });
  }

  const appServer = context.metadata?.codexAppServer || {};
  const notifications = Array.isArray(raw.notifications) ? raw.notifications : [];
  const completed = notifications
    .map((notification, index) => ({ notification, index }))
    .filter(({ notification }) => notification?.method === 'item/completed')
    .map(({ notification, index }) => ({ item: notification?.params?.item, index }))
    .filter(({ item }) => item && typeof item === 'object');

  const commands = completed.filter(({ item }) => item.type === 'commandExecution');
  const fileChanges = completed.filter(({ item }) => item.type === 'fileChange');
  const collab = completed.filter(({ item }) => item.type === 'collabAgentToolCall');
  const subAgentStarts = completed.filter(
    ({ item }) => item.type === 'subAgentActivity' && item.kind === 'started',
  );
  const finalMessages = completed.filter(
    ({ item }) => item.type === 'agentMessage' && item.phase === 'final_answer',
  );
  const spawns = collab.filter(({ item }) => item.tool === 'spawnAgent');
  const waits = collab.filter(({ item }) => item.tool === 'wait');

  const commandText = (item) => String(item.command || '');
  const commandOutput = (item) => String(item.aggregatedOutput || '');
  const isSuccessfulCommand = (item) =>
    item.status === 'completed' && Number(item.exitCode) === 0;

  const anchorReads = commands.filter(
    ({ item }) =>
      isSuccessfulCommand(item) &&
      /owner_anchor\.txt/i.test(commandText(item)) &&
      commandOutput(item).includes('OWNER_DIRECT_ANCHOR=owner-cobalt-41') &&
      commandOutput(item).includes('ROOT_OWNER_FOLLOWUP_NONCE=root-ember-53'),
  );
  const consumerCalls = commands.filter(
    ({ item }) =>
      isSuccessfulCommand(item) &&
      /consumer\.py/i.test(commandText(item)) &&
      /adoption\.json/i.test(commandText(item)) &&
      commandText(item).includes('ROOT_OWNER_FOLLOWUP_NONCE=root-ember-53') &&
      commandOutput(item).includes('NATIVE_SUBAGENT_CONSUMER_OK') &&
      commandOutput(item).includes('ROOT_OWNER_FOLLOWUP_NONCE=root-ember-53'),
  );
  const adoptionWrites = fileChanges.filter(
    ({ item }) =>
      item.status === 'completed' &&
      Array.isArray(item.changes) &&
      item.changes.some(({ path }) => /(?:^|[\\/])adoption\.json$/i.test(String(path || ''))),
  );

  const directWorkerReads = commands.filter(({ item }) => {
    if (/consumer\.py/i.test(commandText(item))) {
      return false;
    }
    const combined = `${commandText(item)}\n${commandOutput(item)}`;
    return (
      /worker_alpha\.txt/i.test(combined) ||
      /ALPHA_SOURCE_CANDIDATE=17/.test(combined)
    );
  });

  const completedSpawns = spawns.filter(
    ({ item }) => item.status === 'completed' && item.receiverThreadIds?.length === 1,
  );
  const spawnedThreadIds = [
    ...new Set(completedSpawns.flatMap(({ item }) => item.receiverThreadIds || [])),
  ];
  const alphaSpawn = completedSpawns.some(({ item }) => /worker_alpha\.txt/i.test(item.prompt || ''));

  const terminalByThread = new Map();
  let emptyTerminalWaits = 0;
  for (const { item, index } of waits) {
    if (item.status !== 'completed' || !item.agentsStates) {
      continue;
    }
    if (Object.keys(item.agentsStates).length === 0) {
      emptyTerminalWaits += 1;
    }
    for (const [threadId, state] of Object.entries(item.agentsStates)) {
      if (state?.status === 'completed' && typeof state.message === 'string') {
        terminalByThread.set(threadId, { message: state.message, waitIndex: index });
      }
    }
  }
  const spawnedTerminals = spawnedThreadIds
    .map((threadId) => ({ threadId, ...terminalByThread.get(threadId) }))
    .filter(({ message }) => typeof message === 'string');
  const alphaTerminal = spawnedTerminals.find(({ message }) =>
    message.includes('ALPHA_SOURCE_CANDIDATE=17'),
  );
  const terminalBarrier = alphaTerminal?.waitIndex ?? -1;
  const spawnBarrier = completedSpawns[0]?.index ?? -1;
  const anchorBeforeSpawn = anchorReads.some(({ index }) => index < spawnBarrier);
  const spawnBeforeTerminal = spawnBarrier >= 0 && spawnBarrier < terminalBarrier;
  const consumerAfterTerminals = consumerCalls.some(({ index }) => index > terminalBarrier);
  const consumerOnlyAfterTerminals =
    consumerCalls.length > 0 && consumerCalls.every(({ index }) => index > terminalBarrier);
  const consumerBarrier = Math.min(
    ...consumerCalls.filter(({ index }) => index > terminalBarrier).map(({ index }) => index),
  );
  const adoptionAfterTerminal = adoptionWrites.some(
    ({ index }) => index > terminalBarrier && index < consumerBarrier,
  );
  const adoptionOnlyAfterTerminal =
    adoptionWrites.length > 0 && adoptionWrites.every(({ index }) => index > terminalBarrier);
  const finalAfterConsumer = finalMessages.some(
    ({ item, index }) => index > consumerBarrier && item.text === output,
  );

  const finalMatches =
    parsed.case_id === 'NATIVE_SUBAGENT_OWNER_WORKER_CONSUMER' &&
    parsed.owner_anchor === 'owner-cobalt-41' &&
    parsed.worker_alpha === 17 &&
    parsed.delegated_threads === 1 &&
    parsed.consumer_marker === 'NATIVE_SUBAGENT_CONSUMER_OK' &&
    parsed.followup_nonce === 'ROOT_OWNER_FOLLOWUP_NONCE=root-ember-53' &&
    parsed.adoption_status === 'adopted_after_child_terminals' &&
    parsed.status === 'verified';

  const evidence = {
    threadIdPresent: Boolean(appServer.threadId),
    turnIdPresent: Boolean(appServer.turnId),
    sandboxMode: appServer.sandboxMode,
    approvalPolicy: appServer.approvalPolicy,
    notificationCount: notifications.length,
    anchorReads: anchorReads.length,
    directWorkerReads: directWorkerReads.length,
    completedSpawns: completedSpawns.length,
    subAgentStarts: subAgentStarts.map(({ item, index }) => ({
      threadId: item.agentThreadId,
      index,
    })),
    emptyTerminalWaits,
    spawnedThreadIds,
    alphaSpawn,
    spawnedTerminals: spawnedTerminals.map(({ threadId, waitIndex }) => ({
      threadId,
      waitIndex,
    })),
    alphaTerminal: Boolean(alphaTerminal),
    adoptionWrites: adoptionWrites.length,
    consumerCalls: consumerCalls.length,
    finalMessages: finalMessages.length,
    spawnBarrier,
    terminalBarrier,
    consumerBarrier,
    anchorBeforeSpawn,
    spawnBeforeTerminal,
    adoptionAfterTerminal,
    adoptionOnlyAfterTerminal,
    consumerAfterTerminals,
    consumerOnlyAfterTerminals,
    finalAfterConsumer,
    finalMatches,
  };

  const pass =
    finalMatches &&
    Boolean(appServer.threadId) &&
    Boolean(appServer.turnId) &&
    appServer.sandboxMode === 'workspace-write' &&
    appServer.approvalPolicy === 'never' &&
    notifications.length > 0 &&
    anchorReads.length >= 1 &&
    directWorkerReads.length === 0 &&
    completedSpawns.length === 1 &&
    spawnedThreadIds.length === 1 &&
    alphaSpawn &&
    spawnedTerminals.length === 1 &&
    Boolean(alphaTerminal) &&
    anchorBeforeSpawn &&
    spawnBeforeTerminal &&
    terminalBarrier >= 0 &&
    adoptionWrites.length >= 1 &&
    adoptionAfterTerminal &&
    adoptionOnlyAfterTerminal &&
    consumerCalls.length >= 1 &&
    consumerAfterTerminals &&
    consumerOnlyAfterTerminals &&
    finalAfterConsumer;

  return pass
    ? {
        pass: true,
        score: 1,
        reason: `Native subagent Owner/worker/consumer trajectory observed (${JSON.stringify(evidence)})`,
      }
    : fail('Missing or invalid native subagent trajectory evidence', evidence);
};
