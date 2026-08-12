const asArray = (value) => {
  if (Array.isArray(value)) return value.map(String);
  if (value === undefined || value === null || value === "") return [];
  try {
    const parsed = JSON.parse(String(value));
    return Array.isArray(parsed) ? parsed.map(String) : [String(value)];
  } catch {
    return [String(value)];
  }
};

const includesEvery = (text, values) => values.every((value) => text.includes(value));
const includesSome = (text, values) =>
  values.length === 0 || values.some((value) => text.includes(value));

module.exports = (output, context) => {
  const text = String(output || "").trim();
  const mode = String(context.vars.expected_mode || "");
  const requiredAll = asArray(context.vars.required_all);
  const requiredAny = asArray(context.vars.required_any);
  const subjectTerms = asArray(context.vars.subject_terms);
  const forbiddenExtra = asArray(context.vars.forbidden_extra);
  const maxChars = Number(context.vars.max_chars || 120);

  const placementPatterns = [
    /(?:你|您)(?:现在)?(?:无需|无须|不必|不用|不需要)(?:再|额外)?(?:处理|操心|介入|关注|管|做什么|操作)/u,
    /(?:无需|无须|不必|不用|不需要)(?:再|额外)?(?:你|您)(?:来|再|额外)?(?:处理|操心|介入|关注|管|做什么|操作)?/u,
    /放心/u,
    /交给我/u,
    /我(?:会|来|已经|已)?(?:替你|为你)?接管/u,
    /你(?:可以|可)(?:离开|离场|休息|去睡)/u,
  ];
  const technicalLeakPatterns = [
    /\bPID\b/iu,
    /\b(?:commit|hash|pytest)\b/iu,
    /[A-Za-z]:\\/u,
    /\b[0-9a-f]{7,40}\b/iu,
    /\b\d+\/\d+\s*(?:tests?|checks?|测试|验证)?\b/iu,
  ];
  const nonReceiptMode = mode !== "receipt";
  const exactSilence = text === "<NO_USER_MESSAGE>";
  const visible = text.length > 0 && !exactSilence;
  const objectCenteredModes = new Set(["state", "completion"]);
  const startsWithActorPlacement = /^[\s*_`#>-]*(?:我|你|您)/u.test(text);

  let semanticMatch = true;
  if (mode === "silent") semanticMatch = exactSilence;
  else if (mode === "action_transfer") semanticMatch = exactSilence || visible;
  else semanticMatch = visible;
  if (mode === "ask") semanticMatch = semanticMatch && /登录|登陆/u.test(text);
  if (mode === "start") semanticMatch = semanticMatch && /开始|启动|执行/u.test(text);
  if (mode === "continue") semanticMatch = semanticMatch && /继续|接着/u.test(text);
  if (mode === "completion") semanticMatch = semanticMatch && /完成|已迁移|通过/u.test(text);

  const contentMatch =
    (mode === "action_transfer" && exactSilence) ||
    (includesEvery(text, requiredAll) &&
      includesSome(text, requiredAny) &&
      includesSome(text, subjectTerms) &&
      !forbiddenExtra.some((value) => text.includes(value)));
  const noPlacement = !placementPatterns.some((pattern) => pattern.test(text));
  const noTechnicalLeak =
    !nonReceiptMode || !technicalLeakPatterns.some((pattern) => pattern.test(text));
  const objectCentered =
    !objectCenteredModes.has(mode) || (!startsWithActorPlacement && includesSome(text, subjectTerms));
  const bounded = text.length <= maxChars;

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
    toolCalls.length === 0 &&
    tokenPrompt > 0 &&
    tokenCompletion > 0 &&
    tokenTotal >= tokenPrompt + tokenCompletion;

  const pass =
    semanticMatch &&
    contentMatch &&
    noPlacement &&
    noTechnicalLeak &&
    objectCentered &&
    bounded &&
    traceIsReal;
  const evidence = {
    caseId: context.vars.case_id,
    mode,
    output: text,
    semanticMatch,
    contentMatch,
    noPlacement,
    noTechnicalLeak,
    objectCentered,
    bounded,
    maxChars,
    toolCallTypes: toolCalls.map((item) => item.type),
    threadIdPresent: Boolean(appServer.threadId),
    turnIdPresent: Boolean(appServer.turnId),
    sandboxMode: appServer.sandboxMode,
    approvalPolicy: appServer.approvalPolicy,
    agentMessages: Number(itemCounts.agentMessage || 0),
    tokenUsage: { prompt: tokenPrompt, completion: tokenCompletion, total: tokenTotal },
  };

  return {
    pass,
    score: pass ? 1 : 0,
    reason: pass
      ? `Parent-continuity user surface passed (${JSON.stringify(evidence)})`
      : `Parent-continuity user surface mismatch (${JSON.stringify(evidence)})`,
  };
};
