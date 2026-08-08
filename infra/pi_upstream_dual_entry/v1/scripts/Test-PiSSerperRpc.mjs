import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) throw new Error(`Unexpected argument: ${token}`);
    const name = token.slice(2);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for --${name}`);
    result[name] = value;
    index += 1;
  }
  return result;
}

function required(args, name) {
  const value = args[name];
  if (!value) throw new Error(`Missing --${name}`);
  return value;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cliPath = required(args, "cli");
  const rpcClientPath = required(args, "rpc-client");
  const agentDir = required(args, "agent-dir");
  const sessionDir = required(args, "session-dir");
  const codexHome = required(args, "codex-home");
  const cwd = required(args, "cwd");
  const expect = args.expect ?? "auth_rejected";
  const receiptPath = args.receipt;
  const timeoutMs = Number(args["timeout-ms"] ?? "120000");
  if (!new Set(["accepted", "auth_rejected", "quota_rejected"]).has(expect)) {
    throw new Error(`Unsupported --expect value: ${expect}`);
  }
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
      "--thinking",
      "low",
      "--tools",
      "web_search",
      "--append-system-prompt",
      path.join(agentDir, "PI_CONTRACT.md"),
      "--session-dir",
      sessionDir,
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
      'This is an isolated provider regression. Call web_search exactly once with query "OpenAI official", num 1. Do not call any other tool and do not retry. Then report the exact provider result or error.',
    );
    const events = await eventsPromise;
    const extensionErrors = events.filter((event) => event?.type === "extension_error");
    if (extensionErrors.length > 0) throw new Error(`Extension errors: ${JSON.stringify(extensionErrors)}`);
    const starts = events.filter((event) => event?.type === "tool_execution_start");
    const ends = events.filter((event) => event?.type === "tool_execution_end");
    if (starts.length !== 1 || starts[0].toolName !== "web_search") {
      throw new Error(`Expected exactly one web_search start, got: ${JSON.stringify(starts)}`);
    }
    if (ends.length !== 1 || ends[0].toolName !== "web_search") {
      throw new Error(`Expected exactly one web_search end, got: ${JSON.stringify(ends)}`);
    }
    const end = ends[0];
    const rendered = JSON.stringify(end.result ?? {});
    if (expect === "accepted") {
      if (end.isError || end.result?.details?.provider !== "serper") {
        throw new Error(`Expected accepted Serper result: ${JSON.stringify(end)}`);
      }
    } else {
      const expectedToken = expect === "auth_rejected" ? "SERPER_AUTH_REJECTED" : "SERPER_QUOTA_REJECTED";
      if (!end.isError || !rendered.includes(expectedToken)) {
        throw new Error(`Expected ${expectedToken}: ${JSON.stringify(end)}`);
      }
    }
    const receipt = {
      schema: "xinao.pi_serper_rpc_acceptance.v1",
      status: "verified",
      expected_provider_state: expect,
      tool_name: "web_search",
      tool_calls: 1,
      strict_provider: true,
      provider: "serper",
      no_other_tool_called: true,
      no_session: true,
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
  process.stderr.write(`PI_SERPER_RPC_TEST_ERROR: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
