#!/usr/bin/env node

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const SCRIPT_PATH = fileURLToPath(import.meta.url);
const EXPECTED_PACKAGE = "pi-hermes-memory";
const EXPECTED_VERSION = "0.9.4";
const MAIN_LIMITS = Object.freeze({ memoryCharLimit: 10000, userCharLimit: 5000, projectCharLimit: 5000 });
const DEFAULT_LIMITS = Object.freeze({ memoryCharLimit: 5000, userCharLimit: 5000, projectCharLimit: 5000 });
const SPARSE_POLICY = Object.freeze({
  memoryMode: "policy-only",
  memoryPolicyStyle: "custom",
  reviewEnabled: false,
  reviewTransport: "direct",
  reviewRecentMessages: 0,
  flushOnCompact: false,
  flushOnShutdown: false,
  flushRecentMessages: 0,
  memoryOverflowStrategy: "reject",
  autoConsolidate: false,
  correctionDetection: false,
  failureInjectionEnabled: false,
  nudgeInterval: 0,
  nudgeToolCalls: 0,
  standingInstructionsEnabled: false,
});
const PROVIDER = "xinao-hermes-memory-capacity-test";
const MODEL = "mock-hermes-memory-capacity";

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`Expected --name value pairs: ${argv.join(" ")}`);
    }
    result[key.slice(2)] = value;
  }
  return result;
}

function required(args, name) {
  if (!args[name]) throw new Error(`Missing --${name}`);
  return path.resolve(args[name]);
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function strictJson(file, label) {
  let raw;
  try {
    raw = fs.readFileSync(file, "utf8");
  } catch (error) {
    throw new Error(`PI_HERMES_MEMORY_CONFIG_READ_FAILED: label=${label} path=${file} cause=${error instanceof Error ? error.message : String(error)}`);
  }
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("root must be a JSON object");
    }
    return { raw, parsed };
  } catch (error) {
    throw new Error(`PI_HERMES_MEMORY_CONFIG_INVALID: label=${label} path=${file} cause=${error instanceof Error ? error.message : String(error)}`);
  }
}

function assertExactLimits(actual, expected, label) {
  for (const [name, value] of Object.entries(expected)) {
    if (actual[name] !== value) {
      throw new Error(`${label} ${name} mismatch: expected=${value} actual=${actual[name]}`);
    }
  }
}

function assertNoExplicitLimits(actual, label) {
  for (const name of Object.keys(DEFAULT_LIMITS)) {
    if (Object.prototype.hasOwnProperty.call(actual, name)) {
      throw new Error(`${label} unexpectedly contains main-only ${name}`);
    }
  }
}

function assertSparsePolicy(actual, label) {
  for (const [name, value] of Object.entries(SPARSE_POLICY)) {
    if (actual[name] !== value) {
      throw new Error(`${label} sparse policy drift: ${name} expected=${value} actual=${actual[name]}`);
    }
  }
  if (actual.sessionSearch?.variant !== "anchors") {
    throw new Error(`${label} sparse policy drift: sessionSearch.variant=${actual.sessionSearch?.variant}`);
  }
}

async function importHermes(args) {
  const packageRoot = required(args, "hermes-package-root");
  const jitiPath = required(args, "jiti");
  const packageJson = strictJson(path.join(packageRoot, "package.json"), "package").parsed;
  if (packageJson.name !== EXPECTED_PACKAGE || packageJson.version !== EXPECTED_VERSION) {
    throw new Error(`PI_HERMES_MEMORY_PACKAGE_IDENTITY_MISMATCH: ${packageJson.name}@${packageJson.version}`);
  }
  const { createJiti } = await import(pathToFileURL(jitiPath).href);
  const jiti = createJiti(import.meta.url, { moduleCache: false });
  return { packageRoot, jiti };
}

async function runMemoryChild(args) {
  const mode = args["child-mode"];
  const agentDir = required(args, "agent-dir");
  const marker = args.marker ?? "";
  const configPath = path.join(agentDir, "hermes-memory-config.json");
  strictJson(configPath, `child-${mode}`);
  const { packageRoot, jiti } = await importHermes(args);
  const configModule = await jiti.import(path.join(packageRoot, "src", "config.ts"));
  const storeModule = await jiti.import(path.join(packageRoot, "src", "store", "memory-store.ts"));
  const dbModule = await jiti.import(path.join(packageRoot, "src", "store", "db.ts"));
  const sqliteModule = await jiti.import(path.join(packageRoot, "src", "store", "sqlite-memory-store.ts"));
  const config = configModule.loadConfig(configPath);
  assertExactLimits(config, MAIN_LIMITS, `child-${mode}-effective`);
  const memoryDir = path.join(agentDir, "pi-hermes-memory");
  const dbManager = new dbModule.DatabaseManager(memoryDir);
  try {
    if (mode === "db-snapshot") {
      const rows = dbManager.getDb().prepare(`
        SELECT project, target, category, content, failure_reason, tool_state, corrected_to, created, last_referenced
        FROM memories ORDER BY id
      `).all();
      process.stdout.write(`${JSON.stringify({ mode, rows, logical_sha256: sha256(JSON.stringify(rows)) })}\n`);
      return;
    }
    if (mode === "memory-search") {
      const results = sqliteModule.searchMemories(dbManager, marker, { target: "failure", limit: 5 });
      if (!results.some((entry) => typeof entry.content === "string" && entry.content.includes(marker))) {
        throw new Error("Fresh process memory_search backend did not return the marker");
      }
      process.stdout.write(`${JSON.stringify({ mode, found: true, count: results.length })}\n`);
      return;
    }

    const store = new storeModule.MemoryStore({ ...config, memoryDir });
    await store.loadFromDisk();
    store.setMutationObserver((target, entries) => {
      if (target === "failure") sqliteModule.reconcileMarkdownFailureScopes(dbManager, entries);
      return Promise.resolve(null);
    });
    const content = mode === "memory-reject" ? `${marker}${"R".repeat(10500)}` : marker;
    const details = await store.addFailure(content, {
      category: "tool-quirk",
      failureReason: "bounded capacity regression",
    });
    if (mode === "memory-write") {
      if (details.success !== true || !String(details.usage ?? "").includes("/20000 chars")) {
        throw new Error(`Expected old-10k-crossing write to succeed at /20000: ${JSON.stringify(details)}`);
      }
    } else if (mode === "memory-reject") {
      if (details.success !== false || !String(details.error ?? "").includes("/20000 chars")) {
        throw new Error(`Expected >20k write rejection: ${JSON.stringify(details)}`);
      }
    } else {
      throw new Error(`Unknown child mode: ${mode}`);
    }
    process.stdout.write(`${JSON.stringify({ mode, details })}\n`);
  } finally {
    dbManager.close();
  }
}

function runNodeChild(args, mode, agentDir, marker) {
  const childArgs = [
    SCRIPT_PATH,
    "--child-mode", mode,
    "--agent-dir", agentDir,
    "--hermes-package-root", args["hermes-package-root"],
    "--jiti", args.jiti,
    "--marker", marker,
  ];
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, childArgs, {
      cwd: args["work-dir"],
      env: {
        ...process.env,
        PI_CODING_AGENT_DIR: agentDir,
        PI_CODING_AGENT_SESSION_DIR: path.join(agentDir, "sessions"),
        PI_SKIP_VERSION_CHECK: "1",
        PI_TELEMETRY: "0",
      },
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code !== 0) {
        reject(new Error(`Child ${mode} failed: code=${code} signal=${signal} stderr=${stderr} stdout=${stdout}`));
        return;
      }
      const lines = stdout.trim().split(/\r?\n/).filter(Boolean);
      try {
        resolve(JSON.parse(lines.at(-1) ?? "{}"));
      } catch (error) {
        reject(new Error(`Child ${mode} returned invalid JSON: ${stdout}; ${error instanceof Error ? error.message : String(error)}`));
      }
    });
  });
}

function writeSse(response, text) {
  const id = "chatcmpl-hermes-capacity";
  const base = (delta, finishReason = null) => ({
    id,
    object: "chat.completion.chunk",
    created: 1,
    model: MODEL,
    choices: [{ index: 0, delta, finish_reason: finishReason }],
  });
  const chunks = [
    base({ role: "assistant" }),
    base({ content: text }),
    base({}, "stop"),
    {
      id,
      object: "chat.completion.chunk",
      created: 1,
      model: MODEL,
      choices: [],
      usage: { prompt_tokens: 50, completion_tokens: 2, total_tokens: 52 },
    },
  ];
  response.writeHead(200, {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-cache",
    connection: "keep-alive",
  });
  for (const chunk of chunks) response.write(`data: ${JSON.stringify(chunk)}\n\n`);
  response.write("data: [DONE]\n\n");
  response.end();
}

async function startProvider() {
  const requests = [];
  const server = http.createServer(async (request, response) => {
    try {
      if (request.method !== "POST" || !request.url?.endsWith("/chat/completions")) {
        response.writeHead(404).end();
        return;
      }
      let raw = "";
      request.setEncoding("utf8");
      for await (const chunk of request) raw += chunk;
      requests.push({ raw, body: JSON.parse(raw) });
      writeSse(response, "PROMPT_CAPTURED");
    } catch (error) {
      response.writeHead(500, { "content-type": "text/plain" });
      // This loopback-only mock returns diagnostics only to its regression client.
      // codeql[js/stack-trace-exposure]
      response.end(error instanceof Error ? error.stack : String(error));
    }
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Mock provider did not bind a TCP port");
  return {
    baseUrl: `http://127.0.0.1:${address.port}/v1`,
    requests,
    close: () => new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve())),
  };
}

function preparePromptAgent(sourceConfig, agentDir, baseUrl, failureMarker) {
  fs.mkdirSync(path.join(agentDir, "sessions"), { recursive: true });
  fs.mkdirSync(path.join(agentDir, "pi-hermes-memory"), { recursive: true });
  fs.copyFileSync(sourceConfig, path.join(agentDir, "hermes-memory-config.json"));
  fs.writeFileSync(path.join(agentDir, "pi-hermes-memory", "failures.md"), failureMarker, "utf8");
  fs.writeFileSync(path.join(agentDir, "models.json"), `${JSON.stringify({
    providers: {
      [PROVIDER]: {
        baseUrl,
        api: "openai-completions",
        apiKey: "local-test-only",
        compat: {
          supportsDeveloperRole: false,
          supportsReasoningEffort: false,
          supportsUsageInStreaming: true,
        },
        models: [{
          id: MODEL,
          name: "Hermes capacity prompt capture",
          reasoning: false,
          input: ["text"],
          contextWindow: 32000,
          maxTokens: 64,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        }],
      },
    },
  }, null, 2)}\n`, "utf8");
}

function runPi(args, agentDir, prompt) {
  const cliJs = required(args, "cli-js");
  const extensionPath = path.join(required(args, "hermes-package-root"), "src", "index.ts");
  const argv = [
    cliJs,
    "--provider", PROVIDER,
    "--model", MODEL,
    "--api-key", "local-test-only",
    "--thinking", "off",
    "--mode", "json",
    "--print",
    "--no-session",
    "--session-dir", path.join(agentDir, "sessions"),
    "--no-extensions",
    "--no-skills",
    "--no-prompt-templates",
    "--no-context-files",
    "--no-tools",
    "--extension", extensionPath,
    prompt,
  ];
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, argv, {
      cwd: args["work-dir"],
      env: {
        ...process.env,
        PI_CODING_AGENT_DIR: agentDir,
        PI_CODING_AGENT_SESSION_DIR: path.join(agentDir, "sessions"),
        PI_SKIP_VERSION_CHECK: "1",
        PI_TELEMETRY: "0",
        PI_OFFLINE: "1",
      },
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code !== 0) reject(new Error(`Pi prompt capture failed: code=${code} signal=${signal} stderr=${stderr} stdout=${stdout}`));
      else resolve({ stdout, stderr });
    });
  });
}

function bodyMessages(body, role) {
  return (Array.isArray(body?.messages) ? body.messages : []).filter((message) => message?.role === role);
}

function snapshotFile(file) {
  const bytes = fs.readFileSync(file);
  return { bytes: bytes.length, sha256: sha256(bytes) };
}

async function main(args) {
  args["work-dir"] = required(args, "work-dir");
  const mainDir = required(args, "main-agent-dir");
  const mainLabDir = required(args, "main-lab-agent-dir");
  const primeBDir = required(args, "prime-b-agent-dir");
  const primeBLabDir = required(args, "prime-b-lab-agent-dir");
  const primeBReference = required(args, "prime-b-reference-config");
  const { packageRoot, jiti } = await importHermes(args);
  const configModule = await jiti.import(path.join(packageRoot, "src", "config.ts"));

  const paths = {
    main: path.join(mainDir, "hermes-memory-config.json"),
    mainLab: path.join(mainLabDir, "hermes-memory-config.json"),
    primeB: path.join(primeBDir, "hermes-memory-config.json"),
    primeBLab: path.join(primeBLabDir, "hermes-memory-config.json"),
  };
  const raw = Object.fromEntries(Object.entries(paths).map(([name, file]) => [name, strictJson(file, name)]));
  assertExactLimits(raw.main.parsed, MAIN_LIMITS, "main raw");
  assertExactLimits(raw.mainLab.parsed, MAIN_LIMITS, "main lab raw");
  assertNoExplicitLimits(raw.primeB.parsed, "PrimeB raw");
  assertNoExplicitLimits(raw.primeBLab.parsed, "PrimeB lab raw");
  const loaded = Object.fromEntries(Object.entries(paths).map(([name, file]) => [name, configModule.loadConfig(file)]));
  assertExactLimits(loaded.main, MAIN_LIMITS, "main loaded");
  assertExactLimits(loaded.mainLab, MAIN_LIMITS, "main lab loaded");
  assertExactLimits(loaded.primeB, DEFAULT_LIMITS, "PrimeB loaded");
  assertExactLimits(loaded.primeBLab, DEFAULT_LIMITS, "PrimeB lab loaded");
  for (const [name, config] of Object.entries(loaded)) {
    assertSparsePolicy(config, name);
  }
  if (!fs.readFileSync(paths.primeB).equals(fs.readFileSync(primeBReference))) {
    throw new Error("PrimeB generated config changed from the active cold-snapshot reference");
  }
  if (raw.primeB.raw !== raw.primeBLab.raw) throw new Error("PrimeB lab config differs from PrimeB profile config");
  if (raw.main.raw !== raw.mainLab.raw) throw new Error("Main lab config differs from main profile config");

  const invalidPath = path.join(args["work-dir"], "invalid-hermes-memory-config.json");
  fs.writeFileSync(invalidPath, '{"memoryCharLimit":', "utf8");
  const upstreamFallback = configModule.loadConfig(invalidPath);
  assertExactLimits(upstreamFallback, DEFAULT_LIMITS, "observed upstream invalid fallback");
  let invalidRejected = false;
  try { strictJson(invalidPath, "invalid-negative"); } catch (error) {
    invalidRejected = String(error).includes("PI_HERMES_MEMORY_CONFIG_INVALID");
  }
  if (!invalidRejected) throw new Error("Acceptance loader silently accepted invalid config");

  const mutationDir = path.join(args["work-dir"], "mutation-main");
  fs.rmSync(mutationDir, { recursive: true, force: true });
  fs.mkdirSync(path.join(mutationDir, "pi-hermes-memory"), { recursive: true });
  fs.mkdirSync(path.join(mutationDir, "sessions"), { recursive: true });
  fs.copyFileSync(paths.main, path.join(mutationDir, "hermes-memory-config.json"));
  const failuresPath = path.join(mutationDir, "pi-hermes-memory", "failures.md");
  const oldLimitCrossingSeedChars = 10050;
  fs.writeFileSync(failuresPath, "L".repeat(oldLimitCrossingSeedChars), "utf8");
  const marker = `PISHERMESCAPACITY${Date.now()}${process.pid}`;
  const writeResult = await runNodeChild(args, "memory-write", mutationDir, marker);
  const afterWriteFile = snapshotFile(failuresPath);
  const afterWriteDb = await runNodeChild(args, "db-snapshot", mutationDir, marker);
  if (!afterWriteDb.rows.some((row) => typeof row.content === "string" && row.content.includes(marker))) {
    throw new Error("Successful Markdown write was not mirrored into SQLite");
  }
  const searchResult = await runNodeChild(args, "memory-search", mutationDir, marker);
  const rejectResult = await runNodeChild(args, "memory-reject", mutationDir, marker);
  const afterRejectFile = snapshotFile(failuresPath);
  const afterRejectDb = await runNodeChild(args, "db-snapshot", mutationDir, marker);
  if (JSON.stringify(afterWriteFile) !== JSON.stringify(afterRejectFile)) {
    throw new Error("Rejected >20k write changed failures.md");
  }
  if (afterWriteDb.logical_sha256 !== afterRejectDb.logical_sha256) {
    throw new Error("Rejected >20k write changed SQLite logical rows");
  }

  const provider = await startProvider();
  const promptRoot = path.join(args["work-dir"], "provider-prompt");
  const baselineDir = path.join(promptRoot, "baseline");
  const candidateDir = path.join(promptRoot, "candidate");
  const baselineConfig = path.join(promptRoot, "baseline-config.json");
  fs.rmSync(promptRoot, { recursive: true, force: true });
  fs.mkdirSync(promptRoot, { recursive: true });
  const baselineRaw = structuredClone(raw.main.parsed);
  baselineRaw.memoryCharLimit = 5000;
  fs.writeFileSync(baselineConfig, `${JSON.stringify(baselineRaw, null, 2)}\n`, "utf8");
  const failureInjectionMarker = `PISHERMESNOINJECT${Date.now()}${process.pid}`;
  preparePromptAgent(baselineConfig, baselineDir, provider.baseUrl, failureInjectionMarker);
  preparePromptAgent(paths.main, candidateDir, provider.baseUrl, failureInjectionMarker);
  try {
    await runPi(args, baselineDir, "PISHERMESPROMPTCASEA");
    await runPi(args, candidateDir, "PISHERMESPROMPTCASEB");
  } finally {
    await provider.close();
  }
  if (provider.requests.length !== 2) throw new Error(`Expected two provider requests, got ${provider.requests.length}`);
  const baselineRequest = provider.requests.find((request) => request.raw.includes("PISHERMESPROMPTCASEA"));
  const candidateRequest = provider.requests.find((request) => request.raw.includes("PISHERMESPROMPTCASEB"));
  if (!baselineRequest || !candidateRequest) throw new Error("Could not classify prompt-capture requests");
  const baselineSystem = JSON.stringify([
    ...bodyMessages(baselineRequest.body, "system"),
    ...bodyMessages(baselineRequest.body, "developer"),
  ]);
  const candidateSystem = JSON.stringify([
    ...bodyMessages(candidateRequest.body, "system"),
    ...bodyMessages(candidateRequest.body, "developer"),
  ]);
  if (baselineSystem !== candidateSystem) throw new Error("Main memory limit changed the first provider system prompt");
  if (!candidateSystem.includes(raw.main.parsed.memoryPolicyCustomText)) {
    throw new Error("Custom policy-only prompt is absent from the first provider request");
  }
  if (candidateSystem.includes(failureInjectionMarker) || candidateRequest.raw.includes(failureInjectionMarker)) {
    throw new Error("Policy-only first provider request injected failure memory content");
  }
  const normalizedBaselineRequest = baselineRequest.raw.replaceAll("PISHERMESPROMPTCASEA", "PISHERMESPROMPTCASEX");
  const normalizedCandidateRequest = candidateRequest.raw.replaceAll("PISHERMESPROMPTCASEB", "PISHERMESPROMPTCASEX");
  if (normalizedBaselineRequest.length !== normalizedCandidateRequest.length) {
    throw new Error("Main memory limit changed first provider request size");
  }

  const receipt = {
    schema: "xinao.pi_s_hermes_memory_capacity_acceptance.v1",
    status: "verified",
    package: `${EXPECTED_PACKAGE}@${EXPECTED_VERSION}`,
    scope: {
      main_profile: "prime-s",
      main_body_labs: true,
      prime_b_unchanged: true,
      prime_b_reference_sha256: sha256(fs.readFileSync(primeBReference)),
    },
    generated_raw_limits: {
      main: MAIN_LIMITS,
      main_lab: MAIN_LIMITS,
      prime_b_explicit_limits: false,
      prime_b_lab_explicit_limits: false,
    },
    loaded_effective_limits: {
      main: { ...MAIN_LIMITS, failureCharLimit: 20000 },
      main_lab: { ...MAIN_LIMITS, failureCharLimit: 20000 },
      prime_b: { ...DEFAULT_LIMITS, failureCharLimit: 10000 },
      prime_b_lab: { ...DEFAULT_LIMITS, failureCharLimit: 10000 },
    },
    unchanged_sparse_policy: {
      memoryMode: "policy-only",
      memoryOverflowStrategy: "reject",
      failureInjectionEnabled: false,
      reviewEnabled: false,
      flushOnCompact: false,
      flushOnShutdown: false,
      autoConsolidate: false,
      correctionDetection: false,
      standingInstructionsEnabled: false,
    },
    old_10k_crossing_write: {
      seed_chars: oldLimitCrossingSeedChars,
      success: writeResult.details.success === true,
      usage: writeResult.details.usage,
      markdown_sqlite_mirror: true,
    },
    over_20k_rejection: {
      rejected: rejectResult.details.success === false,
      explicit_limit: String(rejectResult.details.error ?? "").includes("/20000 chars"),
      markdown_unchanged: true,
      sqlite_logical_rows_unchanged: true,
    },
    fresh_process_memory_search: {
      found: searchResult.found === true,
      count: searchResult.count,
    },
    policy_only_first_provider_request: {
      provider_posts: provider.requests.length,
      system_prompt_chars: candidateSystem.length,
      system_prompt_sha256: sha256(candidateSystem),
      same_system_prompt_as_5k_baseline: true,
      same_request_size_as_5k_baseline: true,
      failure_content_injected: false,
    },
    invalid_config: {
      upstream_default_fallback_observed: true,
      acceptance_strict_parse_rejected: invalidRejected,
      false_green_prevented: true,
    },
  };
  const receiptPath = args.receipt ? path.resolve(args.receipt) : null;
  if (receiptPath) {
    fs.mkdirSync(path.dirname(receiptPath), { recursive: true });
    fs.writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
  }
  process.stdout.write(`${JSON.stringify(receipt)}\n`);
}

const args = parseArgs(process.argv.slice(2));
const run = args["child-mode"] ? runMemoryChild(args) : main(args);
run.catch((error) => {
  process.stderr.write(`PI_S_HERMES_MEMORY_CAPACITY_TEST_ERROR: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
