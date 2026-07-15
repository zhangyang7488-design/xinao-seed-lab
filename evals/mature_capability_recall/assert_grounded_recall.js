const parseEnvelope = (text) => {
  const raw = String(text || "").trim();
  const start = raw.indexOf("{");
  const end = raw.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  try {
    return JSON.parse(raw.slice(start, end + 1));
  } catch {
    return null;
  }
};

const normalizePath = (value) => String(value || "").replaceAll("\\", "/").toLowerCase();

module.exports = (output, context) => {
  const decodeExpectedSha = (value) => {
    const encoded = String(value);
    return /^[0-9a-f]{32}:[0-9a-f]{32}$/i.test(encoded) ? encoded.replace(":", "") : "";
  };
  let parsed;
  try {
    parsed = JSON.parse(output);
  } catch (error) {
    return { pass: false, score: 0, reason: `Invalid JSON: ${error.message}` };
  }

  const bool = (value) => value === true || value === "true";
  const expectedKinds = String(context.vars.expected_source_kinds).split("|").filter(Boolean);
  const reportedKinds = Array.isArray(parsed.candidate_sources_considered)
    ? parsed.candidate_sources_considered
    : [];
  const actualKinds = new Set(reportedKinds);
  const appServer =
    context.metadata?.codexAppServer ||
    context.providerResponse?.metadata?.codexAppServer ||
    {};
  const items = Array.isArray(appServer.items) ? appServer.items : [];
  const commands = items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.type === "commandExecution");
  const caseToken = `--case ${context.vars.case_id}`.toLowerCase();
  const localCommands = commands.filter(({ item }) => {
    const command = String(item.command || "").toLowerCase();
    return command.includes("read_local_evidence.py") && command.includes(caseToken);
  });
  const replayCommands = commands.filter(({ item }) => {
    const command = String(item.command || "").toLowerCase();
    return command.includes("replay_candidate_search.py") && command.includes(caseToken);
  });
  const local = localCommands.length === 1 ? localCommands[0] : null;
  const replay = replayCommands.length === 1 ? replayCommands[0] : null;
  const localEnvelope = local ? parseEnvelope(local.item.aggregatedOutput) : null;
  const replayEnvelope = replay ? parseEnvelope(replay.item.aggregatedOutput) : null;
  const finalIndex = items.reduce(
    (last, item, index) => (item.type === "agentMessage" ? index : last),
    -1,
  );
  const mutationPattern =
    /apply_patch|set-content|add-content|out-file|new-item|remove-item|move-item|copy-item|git\s+(add|commit|push)/i;
  const mutatingTrace = items.some(
    (item) =>
      item.type === "fileChange" ||
      (item.type === "commandExecution" && mutationPattern.test(String(item.command || ""))),
  );
  const liveFallbackTrace = items.some((item) => {
    const type = String(item.type || "").toLowerCase();
    const descriptor = `${item.server || ""} ${item.tool || ""} ${item.name || ""}`.toLowerCase();
    const command = String(item.command || "").toLowerCase();
    return (
      type.includes("websearch") ||
      (type.includes("mcptoolcall") && /\b(web|search)\b/.test(descriptor)) ||
      (item.type === "commandExecution" &&
        /(^|[\s'";&|])(gh|curl|wget|invoke-restmethod)(\.exe)?\s/.test(command))
    );
  });

  const expectedLocalSha = decodeExpectedSha(
    context.vars.expected_local_fixture_digest,
  ).toLowerCase();
  const expectedSearchSha = decodeExpectedSha(
    context.vars.expected_search_fixture_digest,
  ).toLowerCase();
  const localEvidence = localEnvelope?.evidence || {};
  const searchEvidence = replayEnvelope?.search || {};
  const observedLocalSha = decodeExpectedSha(
    localEnvelope?.fixture_sha256_parts,
  ).toLowerCase();
  const observedSearchSha = decodeExpectedSha(
    replayEnvelope?.fixture_sha256_parts,
  ).toLowerCase();
  const fixtureContract =
    observedLocalSha === expectedLocalSha &&
    observedSearchSha === expectedSearchSha &&
    localEvidence.evidence_nonce === context.vars.expected_local_evidence_nonce &&
    searchEvidence.search_evidence_nonce === context.vars.expected_search_evidence_nonce &&
    parsed.local_evidence_nonce === context.vars.expected_local_evidence_nonce &&
    parsed.search_evidence_nonce === context.vars.expected_search_evidence_nonce &&
    String(parsed.local_fixture_sha256 || "").toLowerCase() === expectedLocalSha &&
    String(parsed.search_fixture_sha256 || "").toLowerCase() === expectedSearchSha;

  const allowedCandidates = [
    ...(Array.isArray(localEvidence.capabilities) ? localEvidence.capabilities : []),
    ...(Array.isArray(searchEvidence.candidates) ? searchEvidence.candidates : []),
  ];
  const reportedCandidates = Array.isArray(parsed.candidates_considered)
    ? parsed.candidates_considered
    : [];
  const candidateKey = (candidate) =>
    `${candidate.candidate_id}|${candidate.source_kind}|${candidate.url || candidate.source_url}`;
  const allowedKeys = new Set(allowedCandidates.map(candidateKey));
  const reportedKeys = new Set(reportedCandidates.map(candidateKey));
  const candidatesGrounded =
    allowedCandidates.length >= 2 &&
    reportedCandidates.length === allowedCandidates.length &&
    reportedCandidates.every(
      (candidate) => allowedKeys.has(candidateKey(candidate)) && Boolean(candidate.fit?.trim()),
    ) &&
    allowedCandidates.every((candidate) => reportedKeys.has(candidateKey(candidate)));
  const selectedKey = `${parsed.selected_candidate_id}|${parsed.selected_source_kind}|${parsed.selected_candidate_url}`;
  const selectedGrounded = reportedKeys.has(selectedKey);
  const groundedKinds = new Set(allowedCandidates.map((candidate) => candidate.source_kind));
  const sourceCoverage =
    reportedKinds.length === actualKinds.size &&
    actualKinds.size === groundedKinds.size &&
    [...actualKinds].every((kind) => groundedKinds.has(kind)) &&
    [...groundedKinds].every((kind) => actualKinds.has(kind)) &&
    expectedKinds.every((kind) => actualKinds.has(kind));
  const expectedMatches =
    parsed.case_id === context.vars.case_id &&
    parsed.parent_outcome === context.vars.parent_outcome &&
    parsed.selected_candidate_id === context.vars.expected_selected_candidate_id &&
    parsed.selected_candidate_url === context.vars.expected_selected_candidate_url &&
    parsed.selected_source_kind === context.vars.expected_selected_source_kind &&
    parsed.selected_route === context.vars.expected_selected_route &&
    parsed.binding_recommended === bool(context.vars.expected_binding_recommended) &&
    parsed.mutation_performed === bool(context.vars.expected_mutation_performed) &&
    parsed.new_runtime === bool(context.vars.expected_new_runtime) &&
    parsed.status === context.vars.expected_status;

  const localCwd = normalizePath(local?.item.cwd);
  const replayCwd = normalizePath(replay?.item.cwd);
  const appCwd = normalizePath(appServer.cwd);
  const traceContract =
    Boolean(appServer.threadId) &&
    Boolean(appServer.turnId) &&
    Boolean(appCwd) &&
    appServer.sandboxMode === "read-only" &&
    appServer.approvalPolicy === "never" &&
    localCommands.length === 1 &&
    replayCommands.length === 1 &&
    local?.item.exitCode === 0 &&
    replay?.item.exitCode === 0 &&
    localCwd === appCwd &&
    replayCwd === appCwd &&
    local.index < replay.index &&
    replay.index < finalIndex &&
    !mutatingTrace &&
    !liveFallbackTrace;
  const pass =
    fixtureContract &&
    candidatesGrounded &&
    selectedGrounded &&
    sourceCoverage &&
    expectedMatches &&
    traceContract &&
    Boolean(parsed.reason?.trim());
  const evidence = {
    fixtureContract,
    candidatesGrounded,
    selectedGrounded,
    sourceCoverage,
    expectedMatches,
    traceContract,
    localCommandCount: localCommands.length,
    replayCommandCount: replayCommands.length,
    localIndex: local?.index ?? -1,
    replayIndex: replay?.index ?? -1,
    finalIndex,
    mutatingTrace,
    liveFallbackTrace,
    selectedCandidate: parsed.selected_candidate_id,
  };
  return {
    pass,
    score: pass ? 1 : 0,
    reason: pass
      ? `Grounded candidate recall passed: ${JSON.stringify(evidence)}`
      : `Grounded candidate recall failed: ${JSON.stringify(evidence)}`,
  };
};
