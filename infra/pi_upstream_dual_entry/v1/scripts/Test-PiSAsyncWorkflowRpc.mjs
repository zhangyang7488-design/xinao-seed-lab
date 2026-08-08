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

function findKey(value, key) {
  if (!value || typeof value !== "object") return undefined;
  if (Object.hasOwn(value, key) && typeof value[key] === "string") return value[key];
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findKey(item, key);
      if (found !== undefined) return found;
    }
    return undefined;
  }
  for (const item of Object.values(value)) {
    const found = findKey(item, key);
    if (found !== undefined) return found;
  }
  return undefined;
}

async function waitForTerminalStatus(statusPath, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastStatus;
  while (Date.now() < deadline) {
    if (fs.existsSync(statusPath)) {
      try {
        lastStatus = JSON.parse(fs.readFileSync(statusPath, "utf8"));
        if (["complete", "failed", "aborted", "timeout"].includes(lastStatus?.state)) return lastStatus;
      } catch {
        // Atomic replacement can briefly race a reader; retry the profile-local file.
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Async workflow did not settle: ${statusPath}; last=${JSON.stringify(lastStatus)}`);
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
  const receiptPath = args.receipt;
  const marker = `PIS_ASYNC_WORKFLOW_${Date.now()}_${process.pid}`;

  for (const file of [cliPath, rpcClientPath, path.join(agentDir, "PI_CONTRACT.md")]) {
    if (!fs.statSync(file).isFile()) throw new Error(`Required file is not a file: ${file}`);
  }
  for (const directory of [agentDir, sessionDir, codexHome, cwd]) {
    if (!fs.statSync(directory).isDirectory()) throw new Error(`Required directory is not a directory: ${directory}`);
  }

  const { RpcClient } = await import(pathToFileURL(rpcClientPath).href);
  const client = new RpcClient({
    cliPath,
    cwd,
    provider: "openai-codex",
    model: "gpt-5.6-sol",
    args: [
      "--no-session",
      "--thinking", "low",
      "--tools", "subagent",
      "--append-system-prompt", path.join(agentDir, "PI_CONTRACT.md"),
      "--session-dir", sessionDir,
    ],
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
    await client.prompt(
      `This is an isolated PiS Windows async workflow regression. Call subagent exactly once. ` +
      `Use workflowScript exactly equivalent to: return runs.run('portable-path', {agent:'probe', task:'Do not call tools. Reply only ${marker}.'}). ` +
      `Set chatProgress to off and mission to false. Leave async at its default; do not pass async:false. ` +
      `Do not call another tool. After the tool reports that the async workflow started, reply only ASYNC_STARTED.`,
    );
    const events = await eventsPromise;
    const extensionErrors = events.filter((event) => event?.type === "extension_error");
    if (extensionErrors.length > 0) throw new Error(`Extension errors: ${JSON.stringify(extensionErrors)}`);
    const starts = events.filter((event) => event?.type === "tool_execution_start");
    const ends = events.filter((event) => event?.type === "tool_execution_end");
    const executionStarts = starts.filter((event) => event.toolName === "subagent" && typeof event.args?.workflowScript === "string");
    const allowedDiscoveryStarts = starts.filter((event) => event.toolName === "subagent" && event.args?.action === "list");
    const unexpectedStarts = starts.filter((event) => !executionStarts.includes(event) && !allowedDiscoveryStarts.includes(event));
    if (executionStarts.length !== 1 || unexpectedStarts.length > 0 || allowedDiscoveryStarts.length > 1) {
      throw new Error(`Expected one execution and at most one read-only discovery: ${JSON.stringify(starts)}`);
    }
    const executionEnd = ends.find((event) => event.toolCallId === executionStarts[0].toolCallId);
    if (!executionEnd || executionEnd.toolName !== "subagent" || executionEnd.isError) {
      throw new Error(`Expected one successful async subagent execution: ${JSON.stringify(ends)}`);
    }
    const eventText = JSON.stringify(events);
    if (eventText.includes("ENOENT") || eventText.includes("no such file or directory")) {
      throw new Error(`Async workflow retained the Windows path failure: ${eventText}`);
    }
    const asyncId = findKey(executionEnd, "asyncId") ?? findKey(executionEnd, "runId");
    const asyncDir = findKey(executionEnd, "asyncDir");
    if (!asyncId || !asyncDir) throw new Error(`Missing async identity or directory: ${JSON.stringify(executionEnd)}`);
    if (!/^workflow-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(asyncId)) {
      throw new Error(`Async workflow ID is not provider-independent and portable: ${asyncId}`);
    }
    if (/[<>:"/\\|?*]/.test(path.basename(asyncDir)) || path.basename(asyncDir) !== asyncId) {
      throw new Error(`Async workflow directory is not a portable exact ID path: ${asyncDir}`);
    }
    const status = await waitForTerminalStatus(path.join(asyncDir, "status.json"), timeoutMs);
    if (status.state !== "complete") throw new Error(`Async workflow failed: ${JSON.stringify(status)}`);
    const tempRoot = path.dirname(path.dirname(asyncDir));
    const resultPath = path.join(tempRoot, "async-subagent-results", `${asyncId}.json`);
    if (!fs.existsSync(resultPath)) throw new Error(`Async result missing: ${resultPath}`);
    const result = JSON.parse(fs.readFileSync(resultPath, "utf8"));
    if (result.success !== true || !JSON.stringify(result).includes(marker)) {
      throw new Error(`Async child result did not carry the marker: ${JSON.stringify(result)}`);
    }

    const receipt = {
      schema: "xinao.pi_s_async_workflow_rpc_acceptance.v1",
      status: "verified",
      async_id: asyncId,
      provider_tool_id_used_as_path: false,
      windows_path_portable: true,
      child_result_consumed: true,
      profile_local: true,
      read_only_agent_discovery_used: allowedDiscoveryStarts.length === 1,
    };
    if (receiptPath) {
      fs.mkdirSync(path.dirname(receiptPath), { recursive: true });
      fs.writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
    }
    process.stdout.write(`${JSON.stringify(receipt)}\n`);
  } finally {
    await client.stop();
  }
}

main().catch((error) => {
  process.stderr.write(`PI_S_ASYNC_WORKFLOW_RPC_TEST_ERROR: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
