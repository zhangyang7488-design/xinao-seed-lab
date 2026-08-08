#!/usr/bin/env node

import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";

const MARKER = "PIS_MIDTURN_COMPACTION_REGRESSION_V1";
const FINAL_MARKER = "PIS_MIDTURN_COMPACT_RESUMED_V1";

function parseArgs(argv) {
  const parsed = { expect: "patched", gate: "on", fault: "none" };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (key === "--pi-root") parsed.piRoot = argv[++index];
    else if (key === "--agent-dir") parsed.agentDir = argv[++index];
    else if (key === "--expect") parsed.expect = argv[++index];
    else if (key === "--gate") parsed.gate = argv[++index];
    else if (key === "--fault") parsed.fault = argv[++index];
    else throw new Error(`Unknown argument: ${key}`);
  }
  if (!parsed.piRoot || !parsed.agentDir) {
    throw new Error("Usage: Test-PiSMidTurnCompaction.mjs --pi-root <isolated-root> --agent-dir <body-lab> [--expect upstream-gap|patched] [--gate on|off]");
  }
  if (!new Set(["upstream-gap", "patched"]).has(parsed.expect)) {
    throw new Error(`Invalid --expect value: ${parsed.expect}`);
  }
  if (!new Set(["on", "off"]).has(parsed.gate)) {
    throw new Error(`Invalid --gate value: ${parsed.gate}`);
  }
  if (!new Set(["none", "cancel-with-steer"]).has(parsed.fault)) {
    throw new Error(`Invalid --fault value: ${parsed.fault}`);
  }
  if (parsed.fault !== "none" && (parsed.expect !== "patched" || parsed.gate !== "on")) {
    throw new Error("Fault regression requires --expect patched --gate on");
  }
  return parsed;
}

function textFromMessage(message) {
  const content = message?.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => (typeof part?.text === "string" ? part.text : ""))
    .join("\n");
}

function requestStage(body) {
  const messages = Array.isArray(body?.messages) ? body.messages : [];
  const serialized = JSON.stringify(messages);
  // Resume payloads can retain a split-turn compaction summary string. A real
  // tool-role message is therefore the stronger classifier and must win.
  if (messages.some((message) => message?.role === "tool")) return "resume-after-tool";
  if (
    serialized.includes("context summarization assistant") ||
    serialized.includes("<conversation>") ||
    serialized.includes("Turn Context (split turn)")
  ) {
    return "compact";
  }
  const userText = messages
    .filter((message) => message?.role === "user")
    .map(textFromMessage)
    .join("\n");
  if (userText.includes("PIS_MIDTURN_TRIGGER")) return "tool-call";
  if (userText.includes("PIS_MIDTURN_WARMUP")) return "warmup";
  return "unexpected";
}

function writeSse(response, chunks) {
  response.writeHead(200, {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-cache",
    connection: "keep-alive",
  });
  for (const chunk of chunks) response.write(`data: ${JSON.stringify(chunk)}\n\n`);
  response.write("data: [DONE]\n\n");
  response.end();
}

function baseChunk(id, delta, finishReason = null) {
  return {
    id,
    object: "chat.completion.chunk",
    created: 1,
    model: "mock-midturn",
    choices: [{ index: 0, delta, finish_reason: finishReason }],
  };
}

function textResponse(stage, text, totalTokens) {
  const id = `chatcmpl-${stage}`;
  return [
    baseChunk(id, { role: "assistant" }),
    baseChunk(id, { content: text }),
    baseChunk(id, {}, "stop"),
    {
      id,
      object: "chat.completion.chunk",
      created: 1,
      model: "mock-midturn",
      choices: [],
      usage: {
        prompt_tokens: Math.max(1, totalTokens - 20),
        completion_tokens: 20,
        total_tokens: totalTokens,
      },
    },
  ];
}

function toolResponse(readTarget) {
  const id = "chatcmpl-tool-call";
  return [
    baseChunk(id, { role: "assistant" }),
    baseChunk(id, {
      tool_calls: [
        {
          index: 0,
          id: "call-midturn-read",
          type: "function",
          function: {
            name: "read",
            arguments: JSON.stringify({ path: readTarget }),
          },
        },
      ],
    }),
    baseChunk(id, {}, "tool_calls"),
    {
      id,
      object: "chat.completion.chunk",
      created: 1,
      model: "mock-midturn",
      choices: [],
      usage: {
        prompt_tokens: 580,
        completion_tokens: 20,
        total_tokens: 600,
      },
    },
  ];
}

async function runPi({ cliPath, args, env }) {
  return await new Promise((resolveRun, rejectRun) => {
    const child = spawn(process.execPath, [cliPath, ...args], {
      cwd: env.PI_MIDTURN_TEST_CWD,
      env,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.once("error", rejectRun);
    child.once("exit", (code, signal) => resolveRun({ code, signal, stdout, stderr }));
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const piRoot = resolve(args.piRoot);
  const agentDir = resolve(args.agentDir);
  const cliPath = join(piRoot, "node_modules", "@earendil-works", "pi-coding-agent", "dist", "cli.js");
  const packagePath = join(piRoot, "node_modules", "@earendil-works", "pi-coding-agent", "package.json");
  const packageInfo = JSON.parse(await readFile(packagePath, "utf8"));
  if (packageInfo.name !== "@earendil-works/pi-coding-agent" || packageInfo.version !== "0.84.1") {
    throw new Error(`Unexpected Pi package: ${packageInfo.name}@${packageInfo.version}`);
  }

  const testRoot = join(agentDir, `midturn-compaction-regression-${args.expect}-${args.gate}-${args.fault}`);
  const sessionDir = join(testRoot, "sessions");
  await rm(testRoot, { recursive: true, force: true });
  await mkdir(sessionDir, { recursive: true });
  const testAgentDir = join(testRoot, "agent");
  await mkdir(testAgentDir, { recursive: true });
  const readTarget = join(testRoot, "bounded-tool-result.txt");
  await writeFile(readTarget, `${"x".repeat(1200)}\nMIDTURN_TOOL_RESULT_END\n`, "utf8");
  let faultExtensionPath = null;
  if (args.fault === "cancel-with-steer") {
    faultExtensionPath = join(testRoot, "cancel-compaction-with-queued-steer.mjs");
    await writeFile(
      faultExtensionPath,
      `export default function (pi) {
  let queued = false;
  pi.on("tool_result", async (event) => {
    if (!queued && event.toolName === "read") {
      queued = true;
      pi.sendUserMessage("PIS_FAILCLOSED_QUEUED_STEER", { deliverAs: "steer" });
    }
  });
  pi.on("session_before_compact", async () => ({ cancel: true }));
}
`,
      "utf8",
    );
  }

  const stages = [];
  let resumeSawCompletedToolResult = false;
  const server = createServer(async (request, response) => {
    try {
      if (request.method !== "POST" || !request.url?.endsWith("/chat/completions")) {
        response.writeHead(404).end();
        return;
      }
      let raw = "";
      request.setEncoding("utf8");
      for await (const chunk of request) raw += chunk;
      const body = JSON.parse(raw);
      const stage = requestStage(body);
      stages.push(stage);
      if (stage === "resume-after-tool") {
        resumeSawCompletedToolResult = JSON.stringify(body.messages ?? []).includes("MIDTURN_TOOL_RESULT_END");
      }
      if (stage === "warmup") writeSse(response, textResponse(stage, "WARMUP_COMPLETE", 500));
      else if (stage === "tool-call") writeSse(response, toolResponse(readTarget));
      else if (stage === "compact") {
        writeSse(
          response,
          textResponse(
            stage,
            "The warmup history was compacted. The active turn called read and its completed tool result must be consumed before answering.",
            100,
          ),
        );
      } else if (stage === "resume-after-tool") {
        writeSse(response, textResponse(stage, FINAL_MARKER, 650));
      } else {
        writeSse(response, textResponse(stage, "UNEXPECTED_REQUEST", 100));
      }
    } catch (error) {
      response.writeHead(500, { "content-type": "text/plain" });
      response.end(error instanceof Error ? error.stack : String(error));
    }
  });
  await new Promise((resolveListen) => server.listen(0, "127.0.0.1", resolveListen));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Mock provider did not bind a TCP port");

  // Each regression owns its agent configuration. Mutating the body lab's
  // shared settings/models made otherwise independent fault cases race when a
  // test runner executed them in parallel.
  const modelsPath = join(testAgentDir, "models.json");
  const settingsPath = join(testAgentDir, "settings.json");
  const settings = JSON.parse(await readFile(join(agentDir, "settings.json"), "utf8"));
  // Keep the current tool turn intact while making the prior warmup turn eligible
  // for compaction. The tool result alone stays below this keep budget.
  settings.sessionDir = sessionDir.replaceAll("\\", "/");
  settings.compaction = { enabled: true, reserveTokens: 400, keepRecentTokens: 350 };
  await writeFile(settingsPath, `${JSON.stringify(settings, null, 2)}\n`, "utf8");
  await writeFile(
    modelsPath,
    `${JSON.stringify(
      {
        providers: {
          "xinao-midturn-test": {
            baseUrl: `http://127.0.0.1:${address.port}/v1`,
            api: "openai-completions",
            apiKey: "local-test-only",
            compat: {
              supportsDeveloperRole: false,
              supportsReasoningEffort: false,
              supportsUsageInStreaming: true,
            },
            models: [
              {
                id: "mock-midturn",
                name: "PiS mid-turn deterministic mock",
                reasoning: false,
                input: ["text"],
                contextWindow: 1200,
                maxTokens: 256,
                cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
              },
            ],
          },
        },
      },
      null,
      2,
    )}\n`,
    "utf8",
  );

  const env = {
    ...process.env,
    PI_CODING_AGENT_DIR: testAgentDir,
    PI_CODING_AGENT_SESSION_DIR: sessionDir,
    PI_SKIP_VERSION_CHECK: "1",
    PI_TELEMETRY: "0",
    PI_OFFLINE: "1",
    PI_MIDTURN_TEST_CWD: testRoot,
    XINAO_PI_PROFILE: args.gate === "on" ? "prime-s" : "prime-b",
    XINAO_PI_MIDTURN_COMPACTION_BACKPRESSURE: args.gate === "on" ? "1" : "0",
  };
  const common = [
    "--provider",
    "xinao-midturn-test",
    "--model",
    "mock-midturn",
    "--thinking",
    "off",
    "--mode",
    "json",
    "--print",
    "--session-dir",
    sessionDir,
    "--no-extensions",
    "--no-skills",
    "--no-prompt-templates",
    "--no-context-files",
    "--no-approve",
  ];
  if (faultExtensionPath) common.push("--extension", faultExtensionPath);

  let warmup;
  let trigger;
  try {
    warmup = await runPi({
      cliPath,
      env,
      args: [...common, "--no-tools", "PIS_MIDTURN_WARMUP: establish prior history without tools."],
    });
    if (warmup.code !== 0) {
      throw new Error(`Warmup failed (${warmup.code}): ${warmup.stderr || warmup.stdout}`);
    }
    const sessions = (await readdir(sessionDir)).filter((name) => name.endsWith(".jsonl"));
    if (sessions.length !== 1) throw new Error(`Expected one warmup session, found ${sessions.length}`);
    trigger = await runPi({
      cliPath,
      env,
      args: [
        ...common,
        "--tools",
        "read",
        "--session",
        join(sessionDir, sessions[0]),
        "PIS_MIDTURN_TRIGGER: call read once, consume the result, then return the requested marker.",
      ],
    });
    if (trigger.code !== 0) {
      throw new Error(`Trigger failed (${trigger.code}): ${trigger.stderr || trigger.stdout}`);
    }
  } finally {
    await new Promise((resolveClose) => server.close(resolveClose));
  }

  const compactIndex = stages.indexOf("compact");
  const resumeIndex = stages.indexOf("resume-after-tool");
  const compactionBeforeResume = compactIndex >= 0 && resumeIndex > compactIndex;
  const finalMarkerConsumed = trigger.stdout.includes(FINAL_MARKER);
  const sessionFiles = (await readdir(sessionDir)).filter((name) => name.endsWith(".jsonl"));
  if (sessionFiles.length !== 1) throw new Error(`Expected one durable session, found ${sessionFiles.length}`);
  const sessionText = await readFile(join(sessionDir, sessionFiles[0]), "utf8");
  const compactionPersisted = sessionText.split(/\r?\n/).some((line) => {
    if (!line.trim()) return false;
    try {
      return JSON.parse(line).type === "compaction";
    } catch {
      return false;
    }
  });

  let providerRequestBlockedAfterFault = false;
  if (args.fault === "cancel-with-steer") {
    providerRequestBlockedAfterFault =
      JSON.stringify(stages) === JSON.stringify(["warmup", "tool-call"]) &&
      !compactionPersisted &&
      !finalMarkerConsumed;
    if (!providerRequestBlockedAfterFault) {
      throw new Error(
        `Compaction cancel with queued steer did not fail closed: stages=${JSON.stringify(stages)} persisted=${compactionPersisted} marker=${finalMarkerConsumed}`,
      );
    }
  } else if (args.expect === "patched") {
    const compactStages = stages.slice(2, -1);
    const expectedShape =
      stages[0] === "warmup" &&
      stages[1] === "tool-call" &&
      stages.at(-1) === "resume-after-tool" &&
      compactStages.length >= 1 &&
      compactStages.every((stage) => stage === "compact");
    if (
      !expectedShape ||
      !compactionBeforeResume ||
      !compactionPersisted ||
      !resumeSawCompletedToolResult ||
      !finalMarkerConsumed
    ) {
      throw new Error(
        `Patched lifecycle failed: stages=${JSON.stringify(stages)} persisted=${compactionPersisted} toolResult=${resumeSawCompletedToolResult} marker=${finalMarkerConsumed}`,
      );
    }
  } else {
    const expectedStages = ["warmup", "tool-call", "resume-after-tool"];
    if (
      JSON.stringify(stages) !== JSON.stringify(expectedStages) ||
      compactionBeforeResume ||
      compactionPersisted ||
      !resumeSawCompletedToolResult ||
      !finalMarkerConsumed
    ) {
      throw new Error(
        `Upstream gap was not reproduced exactly: stages=${JSON.stringify(stages)} persisted=${compactionPersisted} toolResult=${resumeSawCompletedToolResult} marker=${finalMarkerConsumed}`,
      );
    }
  }

  const receipt = {
    schema: "xinao.pi_s_midturn_compaction_regression.v1",
    marker: MARKER,
    expected_surface: args.expect,
    prime_s_runtime_gate: args.gate,
    fault_injection: args.fault,
    pi_version: packageInfo.version,
    provider_request_stages: stages,
    compaction_before_resume: compactionBeforeResume,
    compaction_persisted: compactionPersisted,
    completed_tool_result_present_in_resume_request: resumeSawCompletedToolResult,
    completed_tool_result_consumed_after_compaction: finalMarkerConsumed,
    provider_request_blocked_after_compaction_cancel_with_queued_steer: providerRequestBlockedAfterFault,
    same_session_file: true,
    external_provider_used: false,
  };
  const receiptPath = join(testRoot, "receipt.json");
  await writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify({ ...receipt, receipt_path: receiptPath }, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
  process.exitCode = 1;
});
