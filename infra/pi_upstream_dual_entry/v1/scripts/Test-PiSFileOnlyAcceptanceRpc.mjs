import assert from "node:assert/strict";
import crypto from "node:crypto";
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

function findKeyValues(value, key, found = []) {
  if (!value || typeof value !== "object") return found;
  if (Object.hasOwn(value, key) && typeof value[key] === "string") found.push(value[key]);
  if (Array.isArray(value)) {
    for (const item of value) findKeyValues(item, key, found);
    return found;
  }
  for (const item of Object.values(value)) findKeyValues(item, key, found);
  return found;
}

function toMsysDrivePath(filePath) {
  const normalized = path.resolve(filePath);
  const match = normalized.match(/^([a-z]):\\(.*)$/i);
  if (!match) throw new Error(`Configured output is not a Windows drive path: ${filePath}`);
  return `/${match[1].toLowerCase()}/${match[2].replaceAll("\\", "/")}`;
}

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function sessionMessages(filePath) {
  return fs.readFileSync(filePath, "utf8")
    .trim()
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line))
    .filter((entry) => entry.type === "message")
    .map((entry) => entry.message);
}

function toolCalls(messages) {
  const calls = [];
  for (let messageIndex = 0; messageIndex < messages.length; messageIndex += 1) {
    const message = messages[messageIndex];
    if (message?.role !== "assistant" || !Array.isArray(message.content)) continue;
    for (const part of message.content) {
      if (part?.type === "toolCall") calls.push({ ...part, messageIndex });
    }
  }
  return calls;
}

function successfulToolResult(messages, call) {
  return messages.some((message, messageIndex) =>
    messageIndex > call.messageIndex
    && message?.role === "toolResult"
    && message.toolCallId === call.id
    && message.isError !== true,
  );
}

async function waitForStructuredOutput(filePath, marker, platformCommand, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  let lastState = "missing";
  while (Date.now() < deadline) {
    if (fs.existsSync(filePath)) {
      const output = fs.readFileSync(filePath, "utf8");
      const match = output.match(/```acceptance-report\r?\n([\s\S]*?)\r?\n```/);
      if (output.includes(marker) && match?.[1]) {
        try {
          const report = JSON.parse(match[1]);
          const commandRecorded = Array.isArray(report.commandsRun)
            && report.commandsRun.some((item) => item?.command === platformCommand && item?.result === "passed");
          if (commandRecorded) return { output, report };
          lastState = "structured report lacks the exact passed platform command";
        } catch (error) {
          lastState = `structured report JSON not yet parseable: ${error instanceof Error ? error.message : String(error)}`;
        }
      } else {
        lastState = `bytes=${Buffer.byteLength(output, "utf8")} marker=${output.includes(marker)} report=${Boolean(match?.[1])}`;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Configured output did not settle with the structured marker: ${filePath}; last=${lastState}`);
}

async function verifyNegativeBoundaries(sourcePath, jitiPath, configured, msysPath, cwd) {
  const { createJiti } = await import(pathToFileURL(jitiPath).href);
  const jiti = createJiti(import.meta.url, { moduleCache: false });
  const { extractChildWrittenOutput } = await jiti.import(sourcePath);
  const content = "authored\n```acceptance-report\n{}\n```";
  const call = (id, authoredPath, tool = "write") => ({
    role: "assistant",
    content: [{ type: "toolCall", id, name: tool, arguments: { path: authoredPath, content } }],
  });
  const result = (id, tool = "write", isError = false) => ({
    role: "toolResult",
    toolCallId: id,
    toolName: tool,
    content: [{ type: "text", text: isError ? "failed" : "ok" }],
    isError,
  });
  const completed = (id, authoredPath) => [call(id, authoredPath), result(id)];
  const sibling = msysPath.replace(/\/terminal\.md$/, "/sibling.md");
  const wrongDrive = msysPath.replace(/^\/[a-z]\//i, "/z/");

  assert.equal(extractChildWrittenOutput(completed("positive-msys", msysPath), configured, cwd), content);
  assert.equal(extractChildWrittenOutput(completed("wrong-drive", wrongDrive), configured, cwd), undefined);
  assert.equal(extractChildWrittenOutput(completed("sibling", sibling), configured, cwd), undefined);
  assert.equal(extractChildWrittenOutput([call("failed", msysPath), result("failed", "write", true)], configured, cwd), undefined);
  assert.equal(extractChildWrittenOutput([call("unanswered", msysPath)], configured, cwd), undefined);
  assert.equal(extractChildWrittenOutput([call("edit", msysPath, "edit"), result("edit", "edit")], configured, cwd), undefined);
  assert.equal(
    extractChildWrittenOutput([{ role: "assistant", content: [{ type: "text", text: `Existing output: ${configured}` }] }], configured, cwd),
    undefined,
  );
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cliPath = required(args, "cli");
  const rpcClientPath = required(args, "rpc-client");
  const agentDir = required(args, "agent-dir");
  const sessionDir = required(args, "session-dir");
  const codexHome = required(args, "codex-home");
  const cwd = required(args, "cwd");
  const bodyLab = required(args, "body-lab");
  const outputRoot = required(args, "output-root");
  const timeoutMs = Number(args["timeout-ms"] ?? "600000");
  const receiptPath = args.receipt;
  const unique = `${Date.now()}-${process.pid}`;
  const marker = `FRESH_PIS_MSYS_FILE_ONLY_STRUCTURED_${unique}`;
  const runKey = `fresh-msys-file-only-${unique}`;
  const outputDir = path.join(outputRoot, `prime-s-msys-file-only-${unique}`);
  const configured = path.join(outputDir, "terminal.md");
  const msysPath = toMsysDrivePath(configured);
  const platformCommand = 'node -e "process.stdout.write(process.platform)"';
  const singleOutputSource = path.join(agentDir, "npm", "node_modules", "pi-subagents", "src", "runs", "shared", "single-output.ts");
  const jitiPath = path.join(agentDir, "npm", "node_modules", "jiti", "lib", "jiti.mjs");

  for (const file of [cliPath, rpcClientPath, path.join(agentDir, "PI_CONTRACT.md"), singleOutputSource, jitiPath]) {
    if (!fs.statSync(file).isFile()) throw new Error(`Required file is not a file: ${file}`);
  }
  for (const directory of [agentDir, sessionDir, codexHome, cwd, bodyLab, outputRoot]) {
    if (!fs.statSync(directory).isDirectory()) throw new Error(`Required directory is not a directory: ${directory}`);
  }
  if (fs.existsSync(outputDir)) throw new Error(`Fresh output directory already exists: ${outputDir}`);

  const report = [
    "# Fresh PiS native child MSYS-path acceptance",
    `marker: ${marker}`,
    `configured-path: ${configured}`,
    `authored-path: ${msysPath}`,
    "transport: pi-subagents operator child",
    "```acceptance-report",
    JSON.stringify({
      criteriaSatisfied: [{
        id: "criterion-1",
        status: "satisfied",
        evidence: `After observing Node platform win32, the child authored ${marker} through one successful write call using ${msysPath}.`,
      }],
      changedFiles: [configured],
      testsAddedOrUpdated: [],
      commandsRun: [{ command: platformCommand, result: "passed", summary: "stdout was exactly win32" }],
      validationOutput: ["Node reported win32 before the exact MSYS-path write; the artifact contains the marker and structured report."],
      residualRisks: [],
      noStagedFiles: true,
    }),
    "```",
    "",
  ].join("\n");
  const task = [
    "Perform one bounded body-consumer acceptance action only.",
    `First run exactly this harmless command with bash: ${platformCommand}. If stdout is not exactly win32, stop and do not write.`,
    `If and only if it is win32, invoke the native write tool exactly once using ${msysPath}, the MSYS spelling of runtime-configured output ${configured}; do not use the Windows spelling in the write call.`,
    "Write exactly the payload between BEGIN_PAYLOAD and END_PAYLOAD, including the fenced acceptance-report. The output file is your only writable target. Do not use bash or edit to construct it; do not touch a repository, a wrong drive, or any sibling path.",
    "BEGIN_PAYLOAD",
    report,
    "END_PAYLOAD",
    "After the successful write, return only MSYS_CHILD_WRITE_DONE and stop.",
  ].join("\n\n");
  const workflowScript = [
    `return runs.run(${JSON.stringify(runKey)}, {`,
    '  agent: "operator",',
    `  cwd: ${JSON.stringify(bodyLab)},`,
    `  task: ${JSON.stringify(task)},`,
    `  output: ${JSON.stringify(configured)},`,
    '  outputMode: "file-only",',
    '  acceptance: { level: "checked", criteria: [',
    `    ${JSON.stringify(`The exact configured output is child-authored through one successful /d MSYS-alias write after Node reports win32 and contains marker ${marker}.`)},`,
    "  ] },",
    "});",
  ].join("\n");

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
    await client.prompt([
      "This is an isolated PiS file-only structured-acceptance regression. Call subagent exactly once for execution.",
      "You may first call subagent action:list once if required by the installed contract. Do not call models or any other tool.",
      "Use this workflowScript exactly, byte for byte:",
      "BEGIN_WORKFLOW_SCRIPT",
      workflowScript,
      "END_WORKFLOW_SCRIPT",
      "Set top-level async:false, context:fresh, chatProgress:off, mission:false, artifacts:true, includeProgress:false, timeoutMs:600000, and cwd to the current cwd.",
      "After the workflow succeeds, reply only FILE_ONLY_ACCEPTED.",
    ].join("\n"));
    const events = await eventsPromise;
    const extensionErrors = events.filter((event) => event?.type === "extension_error");
    if (extensionErrors.length > 0) throw new Error(`Extension errors: ${JSON.stringify(extensionErrors)}`);
    const starts = events.filter((event) => event?.type === "tool_execution_start");
    const ends = events.filter((event) => event?.type === "tool_execution_end");
    const executionStarts = starts.filter((event) => event.toolName === "subagent" && typeof event.args?.workflowScript === "string");
    const discoveryStarts = starts.filter((event) => event.toolName === "subagent" && event.args?.action === "list");
    const unexpectedStarts = starts.filter((event) => !executionStarts.includes(event) && !discoveryStarts.includes(event));
    if (executionStarts.length !== 1 || discoveryStarts.length > 1 || unexpectedStarts.length > 0) {
      throw new Error(`Unexpected root tool trajectory: ${JSON.stringify(starts)}`);
    }
    if (executionStarts[0].args.workflowScript !== workflowScript) {
      throw new Error("Root did not consume the exact workflowScript");
    }
    const executionEnd = ends.find((event) => event.toolCallId === executionStarts[0].toolCallId);
    const executionText = JSON.stringify(executionEnd);
    if (!executionEnd || executionEnd.isError || /Workflow failed|Acceptance rejected/.test(executionText)) {
      throw new Error(`Native workflow did not pass: ${executionText}`);
    }

    const runId = findKeyValues(executionEnd, "runId").find((value) => /^[0-9a-f]{8}$/i.test(value));
    if (!runId) throw new Error(`Native workflow runId missing: ${executionText}`);
    const childSession = path.join(sessionDir, "children", runId, "run-0", "session.jsonl");
    if (!fs.existsSync(childSession)) throw new Error(`Native child session missing: ${childSession}`);
    const { output } = await waitForStructuredOutput(configured, marker, platformCommand);

    const messages = sessionMessages(childSession);
    const calls = toolCalls(messages);
    const bashCalls = calls.filter((call) => call.name === "bash");
    const writeCalls = calls.filter((call) => call.name === "write");
    if (bashCalls.length !== 1 || bashCalls[0].arguments?.command !== platformCommand || !successfulToolResult(messages, bashCalls[0])) {
      throw new Error(`Child platform probe trajectory invalid: ${JSON.stringify(bashCalls)}`);
    }
    if (
      writeCalls.length !== 1
      || writeCalls[0].arguments?.path !== msysPath
      || !String(writeCalls[0].arguments?.content ?? "").includes(marker)
      || !successfulToolResult(messages, writeCalls[0])
      || bashCalls[0].messageIndex >= writeCalls[0].messageIndex
    ) {
      throw new Error(`Child MSYS write trajectory invalid: ${JSON.stringify(writeCalls)}`);
    }

    await verifyNegativeBoundaries(singleOutputSource, jitiPath, configured, msysPath, bodyLab);
    const receipt = {
      schema: "xinao.pi_s_file_only_acceptance_rpc.v1",
      status: "verified",
      profile: "prime-s",
      root_model: "openai-codex/gpt-5.6-sol",
      native_child_run_id: runId,
      native_child_session: childSession,
      configured_output: configured,
      configured_output_sha256: sha256(configured),
      msys_write_call_verified: true,
      structured_acceptance_consumed: true,
      negative_boundaries: ["wrong-drive", "sibling", "failed-write", "unanswered-write", "edit", "non-authored-prose"],
      profile_local: true,
      read_only_agent_discovery_used: discoveryStarts.length === 1,
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
  process.stderr.write(`PI_S_FILE_ONLY_ACCEPTANCE_RPC_TEST_ERROR: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
