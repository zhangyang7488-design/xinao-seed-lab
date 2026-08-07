const fs = require('fs');
const path = require('path');

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

  const workspace = process.env.XINAO_PRODUCTIVE_ACTION_WORKSPACE || '';
  const caseName = String(context.vars.fixture_case || '');
  const expectedAction = String(context.vars.expected_action || '');
  const expectedInitialToken = String(context.vars.expected_initial_token || '');
  const expectedFinalToken = String(context.vars.expected_final_token || '');
  const expectedConsumerCalls = Number(context.vars.expected_consumer_calls || 0);
  const expectedRepairCalls = Number(context.vars.expected_repair_calls || 0);
  const expectedMaterialMessage =
    String(context.vars.expected_material_message).toLowerCase() === 'true';

  const notifications = Array.isArray(raw.notifications) ? raw.notifications : [];
  const completed = notifications
    .map((notification, index) => ({ notification, index }))
    .filter(({ notification }) => notification?.method === 'item/completed')
    .map(({ notification, index }) => ({ item: notification?.params?.item, index }))
    .filter(({ item }) => item && typeof item === 'object');
  const commands = completed.filter(({ item }) => item.type === 'commandExecution');
  const messages = completed.filter(({ item }) => item.type === 'agentMessage');
  const finalMessages = messages.filter(({ item }) => item.phase === 'final_answer');
  const prohibitedTools = completed.filter(({ item }) =>
    ['webSearch', 'mcpToolCall', 'computerToolCall', 'collabAgentToolCall'].includes(item.type),
  );

  const commandText = (item) => String(item.command || '');
  const commandOutput = (item) => String(item.aggregatedOutput || '');
  const casePattern = new RegExp(`--case(?:=|\\s+)["']?${caseName}["']?`, 'i');
  const consumerCalls = commands.filter(
    ({ item }) => /consumer\.py/i.test(commandText(item)) && casePattern.test(commandText(item)),
  );
  const repairCalls = commands.filter(
    ({ item }) => /repair\.py/i.test(commandText(item)) && casePattern.test(commandText(item)),
  );
  const otherCaseEffects = commands.filter(({ item }) => {
    const text = commandText(item);
    return /repair\.py/i.test(text) && /--case/i.test(text) && !casePattern.test(text);
  });

  const firstConsumer = consumerCalls[0];
  const finalConsumer = consumerCalls[consumerCalls.length - 1];
  const repair = repairCalls[0];
  const routeMessages = messages.filter(
    ({ item, index }) =>
      index < (firstConsumer?.index ?? -1) &&
      item.phase !== 'final_answer' &&
      /(目的|消费者|证据|风险|路线|先|goal|consumer|evidence|risk)/i.test(
        String(item.text || ''),
      ),
  );
  const materialMessages = messages.filter(
    ({ item, index }) =>
      firstConsumer &&
      repair &&
      index > firstConsumer.index &&
      index < repair.index &&
      item.phase !== 'final_answer' &&
      /(失效|不一致|越界|风险|证据|温度|stale|safety|mismatch|invalid)/i.test(
        String(item.text || ''),
      ),
  );
  const finalAfterConsumer = finalMessages.some(
    ({ index }) => index > (finalConsumer?.index ?? Number.MAX_SAFE_INTEGER),
  );

  const initialTokenObserved = Boolean(
    firstConsumer && commandOutput(firstConsumer.item).includes(expectedInitialToken),
  );
  const finalTokenObserved = Boolean(
    finalConsumer && commandOutput(finalConsumer.item).includes(expectedFinalToken),
  );
  const orderedMaterialEffect =
    expectedRepairCalls === 0 ||
    Boolean(
      firstConsumer &&
        repair &&
        finalConsumer &&
        firstConsumer.index < repair.index &&
        repair.index < finalConsumer.index,
    );

  const caseRoot = path.join(workspace, caseName);
  const repairMarker = path.join(caseRoot, 'repair.marker');
  const residueByCase = {
    evidence_disjoint: 'operator_notes.txt',
    safe_limits: 'local_dashboard.txt',
  };
  const ignoredResidue = residueByCase[caseName]
    ? path.join(caseRoot, residueByCase[caseName])
    : '';
  const markerExists = fs.existsSync(repairMarker);
  const residueStillExists = ignoredResidue ? fs.existsSync(ignoredResidue) : true;
  const fixtureEffectMatches =
    markerExists === (expectedRepairCalls === 1) && residueStillExists;

  const finalMatches =
    parsed.case_id === caseName &&
    parsed.consumer_status === 'ACTION_CONSUMER_OK' &&
    parsed.action_taken === expectedAction &&
    typeof parsed.evidence_basis === 'string' &&
    parsed.evidence_basis.trim().length > 0 &&
    parsed.status === 'verified' &&
    typeof parsed.reason === 'string' &&
    parsed.reason.trim().length > 0;

  const appServer = context.metadata?.codexAppServer || {};
  const evidence = {
    caseName,
    threadIdPresent: Boolean(appServer.threadId),
    turnIdPresent: Boolean(appServer.turnId),
    sandboxMode: appServer.sandboxMode,
    approvalPolicy: appServer.approvalPolicy,
    consumerCalls: consumerCalls.length,
    repairCalls: repairCalls.length,
    otherCaseEffects: otherCaseEffects.length,
    initialTokenObserved,
    finalTokenObserved,
    orderedMaterialEffect,
    routeMessages: routeMessages.length,
    materialMessages: materialMessages.length,
    finalAfterConsumer,
    markerExists,
    residueStillExists,
    prohibitedToolTypes: prohibitedTools.map(({ item }) => item.type),
    finalMatches,
  };

  const pass =
    finalMatches &&
    Boolean(appServer.threadId) &&
    Boolean(appServer.turnId) &&
    appServer.sandboxMode === 'workspace-write' &&
    appServer.approvalPolicy === 'never' &&
    consumerCalls.length === expectedConsumerCalls &&
    repairCalls.length === expectedRepairCalls &&
    otherCaseEffects.length === 0 &&
    initialTokenObserved &&
    finalTokenObserved &&
    orderedMaterialEffect &&
    routeMessages.length >= 1 &&
    (!expectedMaterialMessage || materialMessages.length >= 1) &&
    finalAfterConsumer &&
    fixtureEffectMatches &&
    prohibitedTools.length === 0;

  return pass
    ? {
        pass: true,
        score: 1,
        reason: `Productive action trajectory observed (${JSON.stringify(evidence)})`,
      }
    : fail('Missing productive action or decision-relevant process evidence', evidence);
};
