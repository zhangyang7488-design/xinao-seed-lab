#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`Expected --name value pairs, got: ${argv.join(" ")}`);
    }
    values[key.slice(2)] = value;
  }
  return values;
}

function required(values, key) {
  const value = values[key];
  if (!value) throw new Error(`Missing --${key}`);
  return value;
}

function findSlashMessages(value, found = []) {
  if (!value || typeof value !== "object") return found;
  if (value.customType === "subagent-slash-result") found.push(value);
  if (Array.isArray(value)) {
    for (const item of value) findSlashMessages(item, found);
    return found;
  }
  for (const item of Object.values(value)) findSlashMessages(item, found);
  return found;
}

function resultDetails(message) {
  return message?.details?.result?.details ?? message?.details?.details ?? message?.details;
}

function messageText(message) {
  const content = message?.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part) => part?.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("\n");
}

function resultStatus(result) {
  const explicit = String(result?.progress?.status ?? result?.status ?? "").toLowerCase();
  if (explicit) return explicit;
  if (typeof result?.exitCode === "number" && result.exitCode !== 0) return "failed";
  return "";
}

function isTerminalStatus(status) {
  const normalized = String(status ?? "").toLowerCase();
  return normalized.length > 0 && !["queued", "pending", "running"].includes(normalized);
}

function terminalResult(message) {
  const details = resultDetails(message);
  const results = Array.isArray(details?.results) ? details.results : [];
  if (results.length === 0 || !results.every((result) => isTerminalStatus(resultStatus(result)))) return null;
  return { details, results, text: messageText(message) };
}

function assistantTextFromResult(result) {
  const parts = [];
  if (typeof result?.finalOutput === "string") parts.push(result.finalOutput);
  if (typeof result?.error === "string") parts.push(result.error);
  for (const message of Array.isArray(result?.messages) ? result.messages : []) {
    if (message?.role !== "assistant" || !Array.isArray(message.content)) continue;
    for (const content of message.content) {
      if (content?.type === "text" && typeof content.text === "string") parts.push(content.text);
    }
  }
  return parts.join("\n");
}

function messagePartsText(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part) => part?.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("\n");
}

function inspectChildSession(file, marker) {
  let assistantText = "";
  let cleanStop = false;
  try {
    for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
      if (!line.trim()) continue;
      const entry = JSON.parse(line);
      const message = entry?.type === "message" ? entry.message : undefined;
      if (message?.role !== "assistant") continue;
      const text = messagePartsText(message.content);
      if (text) assistantText = assistantText ? `${assistantText}\n${text}` : text;
      if (message.stopReason === "stop") cleanStop = true;
    }
  } catch {
    return null;
  }
  if (!cleanStop || !assistantText.includes(marker)) return null;
  return { assistantText };
}

function recentSuccessfulRun(historyPath, startedAt, agent) {
  if (!fs.existsSync(historyPath)) return false;
  try {
    return fs.readFileSync(historyPath, "utf8").split(/\r?\n/).some((line) => {
      if (!line.trim()) return false;
      const item = JSON.parse(line);
      return item?.agent === agent && item?.status === "ok" && Number(item?.ts ?? 0) * 1000 >= startedAt - 2000;
    });
  } catch {
    return false;
  }
}

function findCompletedChild(sessionRoot, marker, startedAt, historyPath, agent) {
  if (!fs.existsSync(sessionRoot) || !recentSuccessfulRun(historyPath, startedAt, agent)) return null;
  const candidates = [];
  const visit = (directory, depth) => {
    if (depth > 4) return;
    let entries;
    try { entries = fs.readdirSync(directory, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      const fullPath = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(fullPath, depth + 1);
      if (!entry.isFile() || entry.name !== "session.jsonl") continue;
      let mtimeMs = 0;
      try { mtimeMs = fs.statSync(fullPath).mtimeMs; } catch { continue; }
      if (mtimeMs >= startedAt - 2000) candidates.push({ fullPath, mtimeMs });
    }
  };
  visit(sessionRoot, 0);
  candidates.sort((left, right) => right.mtimeMs - left.mtimeMs);
  for (const candidate of candidates) {
    const inspected = inspectChildSession(candidate.fullPath, marker);
    if (inspected) return { ...inspected, sessionFile: candidate.fullPath };
  }
  return null;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cliPath = required(args, "cli");
  const rpcClientPath = required(args, "rpc-client");
  const cwd = required(args, "cwd");
  const agentDir = required(args, "agent-dir");
  const sessionDir = required(args, "session-dir");
  const codexHome = required(args, "codex-home");
  const rolePrompt = required(args, "role-prompt");
  const role = required(args, "role");
  const accountSlot = args["account-slot"] ?? "main";
  const marker = required(args, "marker");
  const task = required(args, "task");
  const agent = args.agent ?? "probe";
  const timeoutMs = Number(args["timeout-ms"] ?? "240000");
  const receiptPath = args.receipt;

  for (const file of [cliPath, rpcClientPath, rolePrompt]) {
    if (!fs.statSync(file).isFile()) throw new Error(`Required file is not a file: ${file}`);
  }
  for (const directory of [cwd, agentDir, sessionDir, codexHome]) {
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
      "max",
      "--append-system-prompt",
      rolePrompt,
      "--session-dir",
      sessionDir,
    ],
    env: {
      PI_CODING_AGENT_DIR: agentDir,
      PI_CODING_AGENT_SESSION_DIR: sessionDir,
      PI_SKIP_VERSION_CHECK: "1",
      PI_TELEMETRY: "0",
      PI_SUBAGENT_MAX_DEPTH: "2",
      CODEX_HOME: codexHome,
      XINAO_ACCOUNT_SLOT: accountSlot,
      XINAO_PI_ROLE: role,
      XINAO_REPO: cwd,
      XINAO_RUNTIME: "D:\\XINAO_RESEARCH_RUNTIME",
    },
  });

  let runningSeen = false;
  const startedAt = Date.now();
  let resolveTerminal;
  let rejectTerminal;
  const terminalPromise = new Promise((resolve, reject) => {
    resolveTerminal = resolve;
    rejectTerminal = reject;
  });
  const timer = setTimeout(() => rejectTerminal(new Error(`Timed out after ${timeoutMs}ms`)), timeoutMs);
  let filesystemPoll;

  const unsubscribe = client.onEvent((event) => {
    if (event?.type === "extension_ui_request" && ["select", "confirm", "input", "editor"].includes(event.method)) {
      rejectTerminal(new Error(`Unexpected blocking extension UI request: ${event.method}`));
      return;
    }
    for (const message of findSlashMessages(event)) {
      const details = resultDetails(message);
      const statuses = Array.isArray(details?.results)
        ? details.results.map(resultStatus)
        : [];
      if (statuses.some((status) => ["queued", "pending", "running"].includes(status.toLowerCase()))) runningSeen = true;
      const terminal = terminalResult(message);
      if (terminal) resolveTerminal(terminal);
    }
  });

  try {
    await client.start();
    const commands = await client.getCommands();
    if (!commands.some((command) => command.name === "run")) {
      throw new Error("pi-subagents /run command is not loaded");
    }
    await client.prompt(`/run ${agent} ${task}`);
    const historyPath = path.join(agentDir, "run-history.jsonl");
    filesystemPoll = setInterval(() => {
      const completed = findCompletedChild(sessionDir, marker, startedAt, historyPath, agent);
      if (!completed) return;
      runningSeen = true;
      resolveTerminal({
        details: { mode: "single", results: [{ agent, exitCode: 0, progress: { status: "completed" }, sessionFile: completed.sessionFile }] },
        results: [{ agent, exitCode: 0, progress: { status: "completed" }, sessionFile: completed.sessionFile }],
        text: completed.assistantText,
        observationSource: "native-run-history-and-child-session",
      });
    }, 400);
    const terminal = await terminalPromise;
    const combinedText = [terminal.text, ...terminal.results.map(assistantTextFromResult)].join("\n");
    if (!combinedText.includes(marker)) throw new Error(`Terminal child result did not contain marker ${marker}`);
    if (!terminal.results.every((result) => resultStatus(result) === "completed" && Number(result.exitCode) === 0)) {
      throw new Error(`Child did not complete successfully: ${terminal.results.map(resultStatus).join(",")}`);
    }
    const normalizedSessionRoot = `${path.resolve(sessionDir)}${path.sep}`.toLowerCase();
    const childSessions = terminal.results.map((result) => result.sessionFile).filter(Boolean);
    if (childSessions.length === 0 || childSessions.some((file) => !path.resolve(file).toLowerCase().startsWith(normalizedSessionRoot))) {
      throw new Error(`Child session escaped profile session root: ${childSessions.join(",")}`);
    }
    const receipt = {
      schema: "xinao.pi_subagent_rpc_acceptance.v1",
      status: "verified",
      role,
      agent,
      marker,
      running_seen: runningSeen,
      terminal_statuses: terminal.results.map(resultStatus),
      child_agents: terminal.results.map((result) => result.agent),
      child_sessions: childSessions,
      child_sessions_under_profile_root: true,
      observation_source: terminal.observationSource ?? "rpc-custom-message",
      duration_ms: Date.now() - startedAt,
    };
    if (receiptPath) {
      fs.mkdirSync(path.dirname(receiptPath), { recursive: true });
      fs.writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
    }
    process.stdout.write(`${JSON.stringify(receipt)}\n`);
  } finally {
    clearTimeout(timer);
    if (filesystemPoll) clearInterval(filesystemPoll);
    unsubscribe();
    await client.stop();
  }
}

main().catch((error) => {
  process.stderr.write(`PI_SUBAGENT_RPC_TEST_ERROR: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
