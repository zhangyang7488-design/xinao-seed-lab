import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) throw new Error(`Unexpected argument: ${token}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for ${token}`);
    result[token.slice(2)] = value;
    index += 1;
  }
  return result;
}

function required(args, name) {
  if (!args[name]) throw new Error(`Missing --${name}`);
  return args[name];
}

function fileSnapshot(paths) {
  const snapshot = {};
  for (const file of paths) {
    if (!fs.existsSync(file)) {
      snapshot[file] = null;
      continue;
    }
    const stat = fs.statSync(file);
    snapshot[file] = `${stat.size}:${stat.mtimeMs}`;
  }
  return snapshot;
}

function assertNoExtensionErrors(events, phase) {
  const errors = events.filter((event) => event?.type === "extension_error");
  if (errors.length > 0) throw new Error(`${phase} extension errors: ${JSON.stringify(errors)}`);
}

function oneTool(events, expected, phase) {
  const starts = events.filter((event) => event?.type === "tool_execution_start");
  const ends = events.filter((event) => event?.type === "tool_execution_end");
  if (starts.length !== 1 || starts[0].toolName !== expected) {
    throw new Error(`${phase} expected one ${expected} start: ${JSON.stringify(starts)}`);
  }
  if (ends.length !== 1 || ends[0].toolName !== expected || ends[0].isError) {
    throw new Error(`${phase} expected one successful ${expected} end: ${JSON.stringify(ends)}`);
  }
  return ends[0];
}

async function runPrompt({ RpcClient, cliPath, cwd, agentDir, sessionDir, codexHome, tools, prompt, noSession = true, timeoutMs }) {
  const args = [
    ...(noSession ? ["--no-session"] : []),
    "--thinking", "low",
    "--tools", tools.join(","),
    "--append-system-prompt", path.join(agentDir, "PI_CONTRACT.md"),
    "--session-dir", sessionDir,
  ];
  const client = new RpcClient({
    cliPath,
    cwd,
    provider: "openai-codex",
    model: "gpt-5.6-sol",
    args,
    env: {
      PI_CODING_AGENT_DIR: agentDir,
      PI_CODING_AGENT_SESSION_DIR: sessionDir,
      PI_SKIP_VERSION_CHECK: "1",
      PI_TELEMETRY: "0",
      CODEX_HOME: codexHome,
      XINAO_PI_PROFILE: "prime-s",
      XINAO_PI_SUPERVISOR_ENABLED: "0",
    },
  });
  try {
    await client.start();
    const eventsPromise = client.collectEvents(timeoutMs);
    await client.prompt(prompt);
    return await eventsPromise;
  } finally {
    await client.stop();
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cliPath = required(args, "cli");
  const rpcClientPath = required(args, "rpc-client");
  const agentDir = required(args, "agent-dir");
  const sessionDir = required(args, "session-dir");
  const codexHome = required(args, "codex-home");
  const cwd = required(args, "cwd");
  const timeoutMs = Number(args["timeout-ms"] ?? "180000");
  const marker = `PIS_SPARSE_MEMORY_${Date.now()}_${process.pid}`;

  for (const file of [cliPath, rpcClientPath, path.join(agentDir, "PI_CONTRACT.md"), path.join(agentDir, "hermes-memory-config.json"), path.join(agentDir, "mcp.json")]) {
    if (!fs.statSync(file).isFile()) throw new Error(`Required file is not a file: ${file}`);
  }
  for (const directory of [agentDir, sessionDir, codexHome, cwd]) {
    if (!fs.statSync(directory).isDirectory()) throw new Error(`Required directory is not a directory: ${directory}`);
  }

  const hermes = JSON.parse(fs.readFileSync(path.join(agentDir, "hermes-memory-config.json"), "utf8"));
  if (hermes.reviewEnabled !== false || hermes.correctionDetection !== false || hermes.flushOnCompact !== false || hermes.flushOnShutdown !== false || hermes.autoConsolidate !== false || hermes.standingInstructionsEnabled !== false || hermes.sessionSearch?.variant !== "anchors") {
    throw new Error("Hermes sparse policy is not fail-closed");
  }
  const mcp = JSON.parse(fs.readFileSync(path.join(agentDir, "mcp.json"), "utf8"));
  if (Object.keys(mcp.mcpServers ?? {}).length !== 0 || mcp.settings?.hostConfigDiscovery !== "off" || mcp.settings?.directTools !== false || mcp.settings?.scriptMode !== false || mcp.settings?.autoAuth !== false) {
    throw new Error("MCP cold policy is not fail-closed");
  }

  const { RpcClient } = await import(pathToFileURL(rpcClientPath).href);
  const memoryWriteEvents = await runPrompt({
    RpcClient, cliPath, cwd, agentDir, sessionDir, codexHome, timeoutMs,
    tools: ["memory_add"],
    noSession: false,
    prompt: `This is an isolated PiS memory regression. Call memory_add exactly once with target memory and content ${marker}. Do not call another tool. Then reply only MEMORY_STORED.`,
  });
  assertNoExtensionErrors(memoryWriteEvents, "memory-write");
  oneTool(memoryWriteEvents, "memory_add", "memory-write");

  const memoryFile = path.join(agentDir, "pi-hermes-memory", "MEMORY.md");
  if (!fs.existsSync(memoryFile) || !fs.readFileSync(memoryFile, "utf8").includes(marker)) {
    throw new Error("Explicit memory marker was not persisted in the profile-local Hermes store");
  }

  const memorySearchEvents = await runPrompt({
    RpcClient, cliPath, cwd, agentDir, sessionDir, codexHome, timeoutMs,
    tools: ["memory_search"],
    prompt: `Call memory_search exactly once with query ${marker} and limit 5. Do not call another tool. Then reply only MEMORY_FOUND.`,
  });
  assertNoExtensionErrors(memorySearchEvents, "memory-search");
  const memorySearchEnd = oneTool(memorySearchEvents, "memory_search", "memory-search");
  if (!JSON.stringify(memorySearchEnd.result ?? {}).includes(marker)) {
    throw new Error("Fresh process memory_search did not return the explicit marker");
  }

  const sessionSearchEvents = await runPrompt({
    RpcClient, cliPath, cwd, agentDir, sessionDir, codexHome, timeoutMs,
    tools: ["session_search"],
    prompt: `Call session_search exactly once with markdown containing limit: 5 and an all list whose only item is ${marker}. Do not call another tool. Then reply only SESSION_ANCHOR_FOUND.`,
  });
  assertNoExtensionErrors(sessionSearchEvents, "session-search");
  const sessionSearchEnd = oneTool(sessionSearchEvents, "session_search", "session-search");
  if (!JSON.stringify(sessionSearchEnd.result ?? {}).includes(marker)) {
    throw new Error("Fresh process anchor session_search did not return the source marker");
  }

  const durableFiles = [
    path.join(agentDir, "pi-hermes-memory", "MEMORY.md"),
    path.join(agentDir, "pi-hermes-memory", "USER.md"),
    path.join(agentDir, "pi-hermes-memory", "failures.md"),
    path.join(agentDir, "STANDING.md"),
  ];
  const beforeNoAuto = fileSnapshot(durableFiles);
  const noAutoEvents = await runPrompt({
    RpcClient, cliPath, cwd, agentDir, sessionDir, codexHome, timeoutMs,
    tools: ["read"],
    prompt: "This is a no-background-learning regression. Do not call any tool. Reply only NO_AUTO_MEMORY_WRITE.",
  });
  assertNoExtensionErrors(noAutoEvents, "no-auto-memory");
  if (noAutoEvents.some((event) => event?.type === "tool_execution_start")) {
    throw new Error("No-auto-memory phase unexpectedly called a tool");
  }
  const afterNoAuto = fileSnapshot(durableFiles);
  if (JSON.stringify(beforeNoAuto) !== JSON.stringify(afterNoAuto)) {
    throw new Error("Durable memory changed without an explicit memory tool call");
  }

  const mcpEvents = await runPrompt({
    RpcClient, cliPath, cwd, agentDir, sessionDir, codexHome, timeoutMs,
    tools: ["mcp"],
    prompt: "This is an empty MCP regression. Call mcp exactly once to list current MCP status or servers. Do not call another tool and do not authenticate. Then reply only MCP_EMPTY_CONFIRMED.",
  });
  assertNoExtensionErrors(mcpEvents, "mcp-empty");
  oneTool(mcpEvents, "mcp", "mcp-empty");

  process.stdout.write(`${JSON.stringify({
    schema: "xinao.pi_s_sparse_body_rpc_acceptance.v1",
    status: "verified",
    memory_explicit_write: true,
    memory_fresh_search: true,
    session_anchor_fresh_search: true,
    autonomous_memory_write: false,
    standing_instruction_write: false,
    mcp_servers: 0,
    mcp_host_discovery: "off",
    mcp_script_mode: false,
    profile_local: true,
  })}\n`);
}

main().catch((error) => {
  process.stderr.write(`PI_S_SPARSE_BODY_RPC_TEST_ERROR: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
