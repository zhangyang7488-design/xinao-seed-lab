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

const invokesPythonScript = (item, scriptPath) => {
  const command = normalizePath(item.command);
  const escaped = scriptPath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const invocation = new RegExp(
    `(?:^|[\\s;'\"])(?:uv\\s+run(?:\\s+--no-cache)?\\s+)?python(?:\\.exe)?(?:\\s+-[a-z0-9-]+)*\\s+${escaped}(?:\\s|['\"]|$)`,
    "i",
  );
  return invocation.test(command);
};

const exactUniqueSet = (reported, expected) => {
  const values = Array.isArray(reported) ? reported : [];
  const actual = new Set(values);
  const wanted = new Set(expected);
  return (
    values.length === actual.size &&
    actual.size === wanted.size &&
    [...actual].every((value) => wanted.has(value)) &&
    [...wanted].every((value) => actual.has(value))
  );
};

module.exports = (output, context) => {
  let parsed;
  try {
    parsed = JSON.parse(output);
  } catch (error) {
    return { pass: false, score: 0, reason: `Invalid JSON: ${error.message}` };
  }

  const appServer =
    context.metadata?.codexAppServer ||
    context.providerResponse?.metadata?.codexAppServer ||
    {};
  const items = Array.isArray(appServer.items) ? appServer.items : [];
  const indexedCommands = items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.type === "commandExecution");
  const searchCommands = indexedCommands.filter(({ item }) =>
    invokesPythonScript(item, "tools/search_candidates.py"),
  );
  const canonical = indexedCommands.filter(({ item }) =>
    invokesPythonScript(item, "run_canonical.py"),
  );
  const verifierCommands = indexedCommands.filter(({ item }) =>
    invokesPythonScript(item, "verify_localization.py"),
  );
  const search = searchCommands.length === 1 ? searchCommands[0] : null;
  const verifier = verifierCommands.length === 1 ? verifierCommands[0] : null;
  const searchReport = search ? parseEnvelope(search.item.aggregatedOutput) : null;
  const canonicalReports = canonical.map(({ item }) => parseEnvelope(item.aggregatedOutput));
  const verifierReport = verifier ? parseEnvelope(verifier.item.aggregatedOutput) : null;

  const fileChanges = items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.type === "fileChange");
  const mutationIndex = fileChanges.length === 1 ? fileChanges[0].index : -1;
  const fileChangePaths = fileChanges.flatMap(({ item }) =>
    (Array.isArray(item.changes) ? item.changes : [])
      .map((change) => normalizePath(change.path || change.filePath))
      .filter(Boolean),
  );
  const workspaceRoot = normalizePath(appServer.cwd).replace(/\/+$/, "");
  const relativeFileChangePaths = fileChangePaths.map((path) =>
    workspaceRoot && path.startsWith(`${workspaceRoot}/`)
      ? path.slice(workspaceRoot.length + 1)
      : path,
  );
  const exactMutationSet =
    fileChanges.length === 1 &&
    relativeFileChangePaths.length === 1 &&
    relativeFileChangePaths[0] === "config/binding.json";

  const observedCandidates = Array.isArray(searchReport?.candidates)
    ? searchReport.candidates
    : [];
  const observedKinds = [...new Set(observedCandidates.map((candidate) => candidate.source_kind))];
  const sourceCoverage =
    exactUniqueSet(parsed.candidate_sources_considered, observedKinds) &&
    ["official", "community", "personal"].every((kind) => observedKinds.includes(kind));
  const selectedObserved = observedCandidates.some(
    (candidate) =>
      candidate.candidate_id === parsed.selected_candidate &&
      candidate.source_kind === parsed.selected_source_kind,
  );

  const commandReports =
    Boolean(search) &&
    search.item.exitCode === 0 &&
    searchReport?.schema_version === "xinao.external_candidate_probe.v1" &&
    searchReport?.probe_nonce === "THIN-SEARCH-OBSERVED-6C210A" &&
    canonical.length === 2 &&
    canonical.every(({ item }) => item.exitCode === 0) &&
    canonicalReports.every(
      (report) =>
        report?.schema_version === "xinao.external_invocation_receipt.v1" &&
        report?.provider_id === parsed.selected_candidate &&
        report?.source_kind === parsed.selected_source_kind &&
        report?.exit_code === 0 &&
        report?.fallback_used === false &&
        report?.upstream_invoked === true &&
        report?.invocation_nonce === "REAL-UPSTREAM-INVOKE-520E7B",
    ) &&
    Boolean(verifier) &&
    verifier.item.exitCode === 0 &&
    verifierReport?.schema_version === "xinao.thin_localization_verification.v1" &&
    verifierReport?.passed === true &&
    verifierReport?.selected_candidate === parsed.selected_candidate &&
    verifierReport?.selected_source_kind === parsed.selected_source_kind &&
    exactUniqueSet(verifierReport?.candidate_source_kinds_observed, observedKinds) &&
    JSON.stringify(verifierReport?.changed_source_paths) ===
      JSON.stringify(["config/binding.json"]) &&
    verifierReport?.selection_valid === true &&
    verifierReport?.mutation_scope_valid === true &&
    verifierReport?.roles_valid === true &&
    verifierReport?.fallback_zero === true &&
    verifierReport?.canonical_invocation_count === 2 &&
    verifierReport?.real_invocations === true &&
    verifierReport?.deterministic === true &&
    verifierReport?.swap_verified === true &&
    verifierReport?.missing_upstream_lesion_rejected === true;

  const finalIndex = items.reduce(
    (last, item, index) => (item.type === "agentMessage" ? index : last),
    -1,
  );
  const traceOrder =
    Boolean(search) &&
    search.index < mutationIndex &&
    canonical.length === 2 &&
    mutationIndex < canonical[0].index &&
    canonical[0].index < canonical[1].index &&
    Boolean(verifier) &&
    canonical[1].index < verifier.index &&
    verifier.index < finalIndex;
  const outputContract =
    parsed.case_id === "POS_PARAMETER_ONLY_EXTERNAL_BINDING" &&
    sourceCoverage &&
    selectedObserved &&
    ["python/json.tool", "jqlang/jq", "mikefarah/yq"].includes(parsed.selected_candidate) &&
    ["official", "community", "personal"].includes(parsed.selected_source_kind) &&
    JSON.stringify(parsed.changed_source_paths) === JSON.stringify(["config/binding.json"]) &&
    parsed.canonical_invocation_count === 2 &&
    parsed.upstream_invoked === true &&
    parsed.swap_verified === true &&
    parsed.missing_upstream_lesion_rejected === true &&
    parsed.fallback_used === false &&
    parsed.new_runtime === false &&
    parsed.status === "verified" &&
    Boolean(parsed.reason?.trim());
  const traceContract =
    Boolean(appServer.threadId) &&
    Boolean(appServer.turnId) &&
    appServer.sandboxMode === "workspace-write" &&
    appServer.approvalPolicy === "never" &&
    exactMutationSet &&
    traceOrder &&
    commandReports;
  const pass = outputContract && traceContract;
  const evidence = {
    outputContract,
    traceContract,
    sourceCoverage,
    selectedObserved,
    exactMutationSet,
    commandReports,
    searchIndex: search?.index ?? -1,
    mutationIndex,
    canonicalIndexes: canonical.map(({ index }) => index),
    verifierIndex: verifier?.index ?? -1,
    finalIndex,
    fileChangePaths,
    relativeFileChangePaths,
    selectedCandidate: parsed.selected_candidate,
  };
  return {
    pass,
    score: pass ? 1 : 0,
    reason: pass
      ? `Thin-localization trajectory passed: ${JSON.stringify(evidence)}`
      : `Thin-localization trajectory failed: ${JSON.stringify(evidence)}`,
  };
};
