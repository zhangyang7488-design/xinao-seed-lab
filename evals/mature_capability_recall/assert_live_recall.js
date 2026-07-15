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
  const appServer =
    context.metadata?.codexAppServer ||
    context.providerResponse?.metadata?.codexAppServer ||
    {};
  const items = Array.isArray(appServer.items) ? appServer.items : [];
  const expectedSha = decodeExpectedSha(
    context.vars.expected_discovery_cache_digest,
  ).toUpperCase();
  const expectedTraceDigest = String(
    context.vars.expected_discovery_cache_digest,
  ).toUpperCase();
  const cacheName = "github_external_mature_all_repos.json";
  const hashCommands = items
    .map((item, index) => ({ item, index }))
    .filter(
      ({ item }) =>
        item.type === "commandExecution" &&
        item.exitCode === 0 &&
        /get-filehash/i.test(String(item.command || "")) &&
        /-algorithm\s+sha256/i.test(String(item.command || "")) &&
        /write-output/i.test(String(item.command || "")) &&
        /substring\(0,\s*32\)/i.test(String(item.command || "")) &&
        /substring\(32,\s*32\)/i.test(String(item.command || "")) &&
        String(item.command || "").toLowerCase().includes(cacheName),
    );
  const hashOutputObserved = hashCommands.some(({ item }) =>
    String(item.aggregatedOutput || "").toUpperCase().includes(expectedTraceDigest),
  );
  const hashOutputSuppressed =
    hashCommands.length === 1 &&
    !String(hashCommands[0].item.aggregatedOutput || "").trim();
  const searchItems = items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => {
      const type = String(item.type || "").toLowerCase();
      const command = String(item.command || "").toLowerCase();
      const server = String(item.server || "").toLowerCase();
      const tool = String(item.tool || "").toLowerCase();
      const mcpSearch =
        type.includes("mcptoolcall") &&
        server.includes("web") &&
        /search|open|run|fetch/.test(tool);
      return (
        type.includes("websearch") ||
        mcpSearch ||
        (item.type === "commandExecution" &&
          item.exitCode === 0 &&
          (command.includes("gh ") ||
            command.includes("invoke-restmethod") ||
            command.includes("curl ")))
      );
    });
  const searchText = JSON.stringify(searchItems).toLowerCase();
  const capabilityTerms = ["git", "release", "http", "image", "lock"];
  const capabilityBearingSearch = capabilityTerms.every((term) => searchText.includes(term));
  const finalIndex = items.reduce(
    (last, item, index) => (item.type === "agentMessage" ? index : last),
    -1,
  );
  const candidates = Array.isArray(parsed.candidates_considered)
    ? parsed.candidates_considered
    : [];
  const reportedKinds = Array.isArray(parsed.candidate_sources_considered)
    ? parsed.candidate_sources_considered
    : [];
  const sourceKinds = new Set(reportedKinds);
  const candidateKinds = new Set(candidates.map((candidate) => candidate.source_kind));
  const sourceKindsExact =
    reportedKinds.length === sourceKinds.size &&
    sourceKinds.size === candidateKinds.size &&
    [...sourceKinds].every((kind) => candidateKinds.has(kind)) &&
    [...candidateKinds].every((kind) => sourceKinds.has(kind)) &&
    ["official", "community", "personal"].every((kind) => sourceKinds.has(kind));
  const selected = candidates.find(
    (candidate) =>
      candidate.candidate_id === parsed.selected_candidate_id &&
      candidate.source_kind === parsed.selected_source_kind &&
      candidate.url === parsed.selected_candidate_url,
  );
  const selectedEvidence = `${selected?.fit || ""} ${selected?.evidence || ""}`.toLowerCase();
  const selectedCapabilityCoverage = capabilityTerms.every((term) =>
    selectedEvidence.includes(term),
  );
  const toolEvidence = JSON.stringify(
    items.filter((item) => !["agentMessage", "userMessage", "reasoning"].includes(item.type)),
  ).toLowerCase();
  const selectedObserved =
    String(parsed.selected_candidate_url || "").startsWith("https://github.com/") &&
    toolEvidence.includes(String(parsed.selected_candidate_url || "").toLowerCase());
  const noMutation = !items.some(
    (item) =>
      item.type === "fileChange" ||
      (item.type === "commandExecution" &&
        /apply_patch|set-content|add-content|out-file|new-item|remove-item|move-item|copy-item|git\s+(add|commit|push)/i.test(
          String(item.command || ""),
        )),
  );
  const outputMatches =
    parsed.case_id === context.vars.case_id &&
    parsed.parent_outcome === context.vars.parent_outcome &&
    String(parsed.discovery_cache_sha256).toUpperCase() === expectedSha &&
    candidates.length >= 3 &&
    sourceKindsExact &&
    Boolean(selected) &&
    selectedCapabilityCoverage &&
    parsed.selected_route === "bind_external" &&
    parsed.binding_recommended === true &&
    parsed.mutation_performed === false &&
    parsed.new_runtime === false &&
    parsed.status === "select_external";
  const hashEvidenceBound =
    hashOutputObserved ||
    (hashOutputSuppressed &&
      String(parsed.discovery_cache_sha256).toUpperCase() === expectedSha);
  const hashIndex = hashCommands[0]?.index ?? -1;
  const searchIndex = searchItems[0]?.index ?? -1;
  const traceMatches =
    Boolean(appServer.threadId) &&
    Boolean(appServer.turnId) &&
    appServer.sandboxMode === "read-only" &&
    appServer.approvalPolicy === "never" &&
    hashCommands.length === 1 &&
    hashEvidenceBound &&
    searchItems.length > 0 &&
    capabilityBearingSearch &&
    selectedObserved &&
    hashIndex < searchIndex &&
    searchIndex < finalIndex &&
    noMutation;
  const pass = outputMatches && traceMatches && Boolean(parsed.reason?.trim());
  const evidence = {
    outputMatches,
    traceMatches,
    hashCommandCount: hashCommands.length,
    hashOutputObserved,
    hashOutputSuppressed,
    hashEvidenceBound,
    searchItemCount: searchItems.length,
    capabilityBearingSearch,
    selectedObserved,
    selectedCapabilityCoverage,
    sourceKindsExact,
    hashIndex,
    searchIndex,
    finalIndex,
    noMutation,
    selectedCandidate: parsed.selected_candidate_id,
    sourceKinds: [...sourceKinds],
  };
  return {
    pass,
    score: pass ? 1 : 0,
    reason: pass
      ? `Live public-repository recall passed: ${JSON.stringify(evidence)}`
      : `Live public-repository recall failed: ${JSON.stringify(evidence)}`,
  };
};
