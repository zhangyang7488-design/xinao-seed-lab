import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, realpathSync, rmSync, mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { registerHooks, stripTypeScriptTypes } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
	createEventBus,
	createMockPi,
	getHighCapacityReplayPaths,
	makeAgent,
	makeMinimalCtx,
} from "./Test-PiSHighCapacitySupport.mjs";

const replay = getHighCapacityReplayPaths();
const candidateRoot = replay.tempRoot;
const subagentsRoot = replay.subagentsRoot;
const coreAnchor = pathToFileURL(replay.coreAnchor).href;
const capacityRuntimeUrl = pathToFileURL(path.join(
	subagentsRoot,
	"src",
	"runs",
	"shared",
	"xinao-pi-subagent-capacity-runtime.js",
)).href;

registerHooks({
	resolve(specifier, context, nextResolve) {
		if (specifier.startsWith("@earendil-works/")) {
			return nextResolve(specifier, { ...context, parentURL: coreAnchor });
		}
		return nextResolve(specifier, context);
	},
	load(url, context, nextLoad) {
		if (url.endsWith(".ts")) {
			const filename = fileURLToPath(url);
			if (filename.startsWith(subagentsRoot)) {
				return {
					format: "module",
					source: stripTypeScriptTypes(readFileSync(filename, "utf8"), { mode: "transform" }),
					shortCircuit: true,
				};
			}
		}
		return nextLoad(url, context);
	},
});

const runtime = await import(capacityRuntimeUrl);
const { createSubagentExecutor } = await import(pathToFileURL(path.join(
	subagentsRoot,
	"src",
	"runs",
	"foreground",
	"subagent-executor.ts",
)).href);
const { normalizePublicSubagentExecution } = await import(pathToFileURL(path.join(
	subagentsRoot,
	"src",
	"extension",
	"public-execution.ts",
)).href);
const { discoverAgentsAll, EXTRA_AGENT_DIRS_ENV } = await import(pathToFileURL(path.join(
	subagentsRoot,
	"src",
	"agents",
	"agents.ts",
)).href);
const filesystemPolicyRuntime = await import(pathToFileURL(path.join(
	subagentsRoot,
	"src",
	"runs",
	"shared",
	"filesystem-policy.ts",
)).href);
const { deliverStopRequest } = await import(pathToFileURL(path.join(
	subagentsRoot,
	"src",
	"runs",
	"background",
	"control-channel.ts",
)).href);
const { DIRS } = await import(pathToFileURL(path.join(
	subagentsRoot,
	"src",
	"shared",
	"types.ts",
)).href);

const capacityEnvKeys = [
	runtime.CAPACITY_STATIC_ENV_KEY,
	runtime.CAPACITY_STATIC_SHA_ENV_KEY,
	runtime.ROOT_BINDING_ENV_KEY,
	runtime.ROOT_BINDING_SHA_ENV_KEY,
];
const filesystemPolicyEnvKeys = [
	filesystemPolicyRuntime.FILESYSTEM_POLICY_REQUIRED_ENV,
	filesystemPolicyRuntime.FILESYSTEM_POLICY_ENV,
	filesystemPolicyRuntime.FILESYSTEM_POLICY_SHA256_ENV,
	filesystemPolicyRuntime.FILESYSTEM_POLICY_RUNTIME_PATH_ENV,
	filesystemPolicyRuntime.FILESYSTEM_POLICY_RUNTIME_SHA256_ENV,
	filesystemPolicyRuntime.FILESYSTEM_POLICY_GATE_PATH_ENV,
	filesystemPolicyRuntime.FILESYSTEM_POLICY_GATE_SHA256_ENV,
	"PI_SUBAGENT_CHILD",
	"PI_SUBAGENT_FANOUT_CHILD",
	"PI_SUBAGENT_INHERIT_PROJECT_CONTEXT",
	"PI_SUBAGENT_INHERIT_SKILLS",
	"PI_SUBAGENT_DEPTH",
	"PI_SUBAGENT_MAX_DEPTH",
];

function snapshotEnv(keys) {
	return new Map(keys.map((key) => [key, process.env[key]]));
}

function restoreEnv(snapshot) {
	for (const [key, value] of snapshot) {
		if (value === undefined) delete process.env[key];
		else process.env[key] = value;
	}
}

function assertUnregisteredIsolatedPayloadFailsClosed(env) {
	const probeSource = [
		"import * as runtime from " + JSON.stringify(capacityRuntimeUrl) + ";",
		"try {",
		"  runtime.parseStaticCapacityEnv(process.env);",
		"  console.error(\"UNEXPECTED_ACCEPT\");",
		"  process.exitCode = 41;",
		"} catch (error) {",
		"  if (error?.code !== \"XINAO_PI_CAPACITY_POLICY_DRIFT\") {",
		"    console.error(error?.code ?? error?.stack ?? String(error));",
		"    process.exitCode = 42;",
		"  } else {",
		"    process.stdout.write(error.code);",
		"  }",
		"}",
	].join("\n");
	const childEnv = { ...env };
	delete childEnv.NODE_OPTIONS;
	const probe = spawnSync(process.execPath, ["--input-type=module", "--eval", probeSource], {
		env: childEnv,
		encoding: "utf8",
		windowsHide: true,
	});
	assert.equal(probe.status, 0, `unregistered isolated payload probe failed: ${probe.stderr || probe.stdout}`);
	assert.equal(probe.stdout, "XINAO_PI_CAPACITY_POLICY_DRIFT");
}

function writeIsolatedRegistryPreload(testRoot) {
	const preloadPath = path.join(testRoot, "capacity-isolated-registry-preload.mjs");
	const source = [
		"import * as runtime from " + JSON.stringify(capacityRuntimeUrl) + ";",
		"import { readFileSync } from \"node:fs\";",
		"let raw = process.env[runtime.CAPACITY_STATIC_ENV_KEY];",
		"let sha = process.env[runtime.CAPACITY_STATIC_SHA_ENV_KEY];",
		"if (raw === undefined && sha === undefined) {",
		"  try {",
		"    const config = JSON.parse(readFileSync(process.argv.at(-1), \"utf8\"));",
		"    const rootContext = config?.capacityRootContext ?? config?.capacitySpawnReservation?.rootContext;",
		"    raw = rootContext?.staticPayload;",
		"    sha = rootContext?.staticSha256;",
		"  } catch {}",
		"}",
		"if (raw === undefined && sha === undefined) {",
		"  // Ordinary, non-capacity children retain their original no-handshake path.",
		"} else {",
		"  if (typeof raw !== \"string\" || typeof sha !== \"string\" || runtime.sha256Hex(raw) !== sha) {",
		"    throw new Error(\"Isolated capacity preload received a malformed static raw+sha pair.\");",
		"  }",
		"  const payload = JSON.parse(raw);",
		"  const isolated = runtime.__testing.createIsolatedHarness({ registryRoot: payload.registryRoot });",
		"  if (isolated.staticEncoded.raw !== raw || isolated.staticEncoded.sha !== sha) {",
		"    throw new Error(\"Isolated capacity preload refused an unregistered or noncanonical static payload.\");",
		"  }",
		"  isolated.registerEnv(process.env);",
		"}",
	].join("\n");
	writeFileSync(preloadPath, source, "utf8");
	return {
		preloadPath,
		nodeOption: `--import=${pathToFileURL(preloadPath).href}`,
	};
}

function resultText(result) {
	return result.content
		.filter((item) => item.type === "text")
		.map((item) => item.text)
		.join("\n");
}

function snapshotNonRegistryTree(root) {
	const snapshot = [];
	const walk = (directory, relativeDirectory = "") => {
		for (const entry of readdirSync(directory, { withFileTypes: true }).sort((left, right) => left.name.localeCompare(right.name))) {
			if (!relativeDirectory && entry.name === "registry") continue;
			const relativePath = relativeDirectory ? path.join(relativeDirectory, entry.name) : entry.name;
			const absolutePath = path.join(directory, entry.name);
			if (entry.isDirectory()) {
				snapshot.push(`directory:${relativePath}`);
				walk(absolutePath, relativePath);
			} else if (entry.isFile()) {
				const content = readFileSync(absolutePath);
				snapshot.push(`file:${relativePath}:${content.length}:${createHash("sha256").update(content).digest("hex")}`);
			} else {
				snapshot.push(`other:${relativePath}`);
			}
		}
	};
	walk(root);
	return snapshot;
}

function makeState(cwd) {
	return {
		baseCwd: cwd,
		currentSessionId: null,
		asyncJobs: new Map(),
		foregroundControls: new Map(),
		lastForegroundControlId: null,
	};
}

function makeExecutor(cwd, allowPublicCapacityTasks, agent = makeAgent("recursive-peer"), allowCapacityRestrictedFilesystemPolicy = false) {
	const agents = [agent];
	const executor = createSubagentExecutor({
		pi: { events: createEventBus(), getSessionName: () => undefined },
		state: makeState(cwd),
		config: {
			maxSubagentDepth: 3,
			maxSubagentSpawnsPerSession: 40,
			globalConcurrencyLimit: 6,
			parallel: { maxTasks: 10, concurrency: 6 },
			chain: { dynamicFanout: { maxItems: 10 } },
		},
		asyncByDefault: false,
		tempArtifactsDir: cwd,
		getSubagentSessionRoot: () => path.join(cwd, "sessions"),
		expandTilde: (value) => value,
		discoverAgents: () => ({ agents }),
	});
	return {
		...executor,
		executePublic(id, params, signal, onUpdate, ctx) {
			return executor.executePublic(id, params, signal, onUpdate, ctx, {
				allowCapacityTasks: allowPublicCapacityTasks,
				allowCapacityRestrictedFilesystemPolicy,
			});
		},
	};
}

function makeContext(cwd, sessionId) {
	const ctx = makeMinimalCtx(cwd);
	ctx.sessionManager.getSessionId = () => sessionId;
	ctx.sessionManager.getSessionFile = () => null;
	return ctx;
}

function tasks(count) {
	return Array.from({ length: count }, (_, index) => ({
		agent: "recursive-peer",
		task: `capacity public task ${index}`,
	}));
}

function peerTasks(count) {
	return Array.from({ length: count }, (_, index) => ({
		agent: "peer",
		task: `capacity restricted peer task ${index}`,
	}));
}

async function executePublic(executor, cwd, sessionId, params) {
	return executor.executePublic(
		`capacity-public-${Math.random().toString(16).slice(2)}`,
		params,
		new AbortController().signal,
		undefined,
		makeContext(cwd, sessionId),
	);
}

async function waitForPendingZero(harness, timeoutMs = 5000) {
	const deadline = Date.now() + timeoutMs;
	let snapshot;
	do {
		snapshot = await harness.inspect();
		if (snapshot.pendingSpawns === 0) return snapshot;
		await new Promise((resolve) => setTimeout(resolve, 20));
	} while (Date.now() < deadline);
	assert.equal(snapshot?.pendingSpawns, 0, "capacity reservation did not close after every foreground child settled");
	return snapshot;
}

async function waitForAsyncRunning(asyncDir, mockPi, expectedCallCount, timeoutMs = 10000) {
	const statusPath = path.join(asyncDir, "status.json");
	const deadline = Date.now() + timeoutMs;
	let status;
	do {
		if (existsSync(statusPath)) {
			status = JSON.parse(readFileSync(statusPath, "utf8"));
			if (status.state !== "running") assert.fail(`async run became ${status.state} before Stop: ${JSON.stringify(status)}`);
			if (Number.isInteger(status.pid) && mockPi.callCount() >= expectedCallCount) return status;
		}
		await new Promise((resolve) => setTimeout(resolve, 20));
	} while (Date.now() < deadline);
	assert.fail(`async run did not reach a launched running child before Stop: ${JSON.stringify(status)}`);
}

function mockCallFiles(mockPi) {
	return new Set(readdirSync(mockPi.dir).filter((name) => name.startsWith("call-") && name.endsWith(".json")));
}

function readSingleNewMockCall(mockPi, before) {
	const created = [...mockCallFiles(mockPi)].filter((name) => !before.has(name));
	assert.equal(created.length, 1, `expected one new mock Pi call record, got ${created.length}`);
	return JSON.parse(readFileSync(path.join(mockPi.dir, created[0]), "utf8"));
}

function parseEchoedEnvironment(output) {
	const firstLine = output.split(/\r?\n/, 1)[0];
	return JSON.parse(firstLine);
}

function assertRestrictedFilesystemGate(childEnv, allowedReadPath, outsideReadPath) {
	assert.equal(childEnv.PI_SUBAGENT_CHILD, "1");
	assert.equal(childEnv.PI_SUBAGENT_FANOUT_CHILD, "0");
	assert.equal(childEnv.PI_SUBAGENT_INHERIT_PROJECT_CONTEXT, "0");
	assert.equal(childEnv.PI_SUBAGENT_INHERIT_SKILLS, "0");
	assert.equal(childEnv.PI_SUBAGENT_DEPTH, "1");
	assert.equal(childEnv.PI_SUBAGENT_MAX_DEPTH, "0");
	let filesystemGate;
	const decodedRestrictedPolicy = filesystemPolicyRuntime.registerFilesystemPolicyGate(
		{
			on(event, handler) {
				assert.equal(event, "tool_call");
				filesystemGate = handler;
			},
		},
		childEnv,
		childEnv[filesystemPolicyRuntime.FILESYSTEM_POLICY_RUNTIME_PATH_ENV],
	);
	assert.ok(decodedRestrictedPolicy);
	assert.equal(filesystemGate({ toolName: "read", input: { path: allowedReadPath } }), undefined);
	assert.equal(readFileSync(allowedReadPath, "utf8"), "safe read evidence");
	const outsideDecision = filesystemGate({ toolName: "read", input: { path: outsideReadPath } });
	assert.equal(outsideDecision.block, true);
	assert.match(outsideDecision.reason, /outside allowedRoots/i);
	const bashDecision = filesystemGate({ toolName: "bash", input: { command: "Get-Content safe.txt" } });
	assert.equal(bashDecision.block, true);
	assert.match(bashDecision.reason, /bash is always denied/i);
}

async function waitForAsyncTerminal(asyncDir, timeoutMs = 10000) {
	const statusPath = path.join(asyncDir, "status.json");
	const deadline = Date.now() + timeoutMs;
	let status;
	do {
		if (existsSync(statusPath)) {
			status = JSON.parse(readFileSync(statusPath, "utf8"));
			if (["complete", "failed", "stopped"].includes(status.state)) return status;
		}
		await new Promise((resolve) => setTimeout(resolve, 20));
	} while (Date.now() < deadline);
	assert.fail(`async run did not become terminal: ${JSON.stringify(status)}`);
}

function registerAsyncCleanup(t, started) {
	const asyncId = started.details.asyncId;
	const asyncDir = started.details.asyncDir;
	assert.equal(typeof asyncId, "string", "detached workflow must return asyncId");
	assert.equal(typeof asyncDir, "string", "detached workflow must return asyncDir");
	t.after(() => {
		rmSync(asyncDir, { recursive: true, force: true });
		rmSync(path.join(DIRS.results, `${asyncId}.json`), { force: true });
	});
	return { asyncId, asyncDir, resultPath: path.join(DIRS.results, `${asyncId}.json`) };
}

test("executePublic enforces the canonical typed-tasks capacity boundary before durable effects", { concurrency: false }, async (t) => {
	const testRoot = mkdtempSync(path.join(candidateRoot, "_capacity-public-tasks-"));
	const registryRoot = path.join(testRoot, "registry");
	const harness = runtime.__testing.createIsolatedHarness({ registryRoot });
	const agentDir = replay.piToolRoot;
	const sessionFile = replay.sessionFile;
	const sessionId = `capacity-public-tasks-${process.pid}`;
	const activation = await harness.activate({ agentDir, profile: "prime-s", sessionId, sessionFile });
	const priorExecutionEnv = snapshotEnv([...capacityEnvKeys, "NODE_OPTIONS"]);
	const mockPi = createMockPi(testRoot);
	t.after(async () => {
		mockPi.uninstall();
		restoreEnv(priorExecutionEnv);
		await activation.release();
		rmSync(testRoot, { recursive: true, force: true });
	});

	Object.assign(process.env, harness.env);
	assertUnregisteredIsolatedPayloadFailsClosed(process.env);
	const isolatedPreload = writeIsolatedRegistryPreload(testRoot);
	process.env.NODE_OPTIONS = isolatedPreload.nodeOption;
	// The isolated runtime owns this exact D:-local registry. Registering the
	// ambient object is required because the production default remains fixed.
	harness.registerEnv(process.env);
	mockPi.install();
	mockPi.onCall({ output: "capacity child complete" });

	const allowedRoot = path.join(testRoot, "restricted-safe-root");
	const outsideRoot = path.join(testRoot, "restricted-outside-root");
	mkdirSync(allowedRoot);
	mkdirSync(outsideRoot);
	const allowedReadPath = path.join(allowedRoot, "safe.txt");
	const outsideReadPath = path.join(outsideRoot, "outside.txt");
	writeFileSync(allowedReadPath, "safe read evidence", "utf8");
	writeFileSync(outsideReadPath, "must remain outside the policy root", "utf8");
	const restrictedFilesystemPolicy = {
		allowedRoots: [allowedRoot],
		bash: "deny",
	};
	const peerFrontmatterPath = replay.peerPath;
	const priorExtraAgentDirs = snapshotEnv([EXTRA_AGENT_DIRS_ENV]);
	let peerAgent;
	try {
		process.env[EXTRA_AGENT_DIRS_ENV] = path.dirname(peerFrontmatterPath);
		peerAgent = discoverAgentsAll(testRoot).user.find((agent) => {
			if (!agent.filePath || !existsSync(agent.filePath)) return false;
			return realpathSync(agent.filePath) === peerFrontmatterPath;
		});
	} finally {
		restoreEnv(priorExtraAgentDirs);
	}
	assert.ok(peerAgent, `real prime-s peer frontmatter was not discovered at ${peerFrontmatterPath}`);
	assert.equal(
		createHash("sha256").update(readFileSync(peerFrontmatterPath)).digest("hex").toUpperCase(),
		"E9B0F62714C2AEC4C2A9061A04F79C67D2547D190EDFF59D54FB3D5AD2D9EA89",
		"the restricted fixture must remain bound to the reviewed prime-s peer frontmatter bytes",
	);
	assert.deepEqual(
		{
			name: peerAgent.name,
			description: peerAgent.description,
			model: peerAgent.model,
			thinking: peerAgent.thinking,
			tools: peerAgent.tools,
			extensions: peerAgent.extensions,
			systemPromptMode: peerAgent.systemPromptMode,
			inheritProjectContext: peerAgent.inheritProjectContext,
			inheritSkills: peerAgent.inheritSkills,
			defaultContext: peerAgent.defaultContext,
			acceptanceRole: peerAgent.acceptanceRole,
			completionGuard: peerAgent.completionGuard,
			maxSubagentDepth: peerAgent.maxSubagentDepth,
			runner: peerAgent.runner,
			filePath: realpathSync(peerAgent.filePath),
		},
		{
			name: "peer",
			description: "Fresh independent cognition over the inherited live object without a fixed profession or preselected local question",
			model: "openai-codex/gpt-5.6-terra",
			thinking: "max",
			tools: ["read", "grep", "find", "ls", "bash"],
			extensions: [],
			systemPromptMode: "append",
			inheritProjectContext: true,
			inheritSkills: false,
			defaultContext: "fresh",
			acceptanceRole: "read-only",
			completionGuard: false,
			maxSubagentDepth: 0,
			runner: undefined,
			filePath: peerFrontmatterPath,
		},
		"restricted capacity tests must consume the real native Pi peer contract, not a recursive-peer read surrogate",
	);
	const restrictedToolList = peerAgent.tools.filter((tool) => filesystemPolicyRuntime.FILESYSTEM_POLICY_ALLOWED_TOOLS.includes(tool));
	assert.deepEqual(restrictedToolList, ["read", "grep", "find", "ls"]);

	const capacityExecutor = makeExecutor(testRoot, true);
	const restrictedCapacityExecutor = makeExecutor(testRoot, true, peerAgent, true);
	const beforeTen = await harness.inspect();
	const callsBeforeTen = mockPi.callCount();
	const ten = await executePublic(capacityExecutor, testRoot, sessionId, {
		tasks: tasks(10),
		concurrency: 6,
		turnBudget: { maxTurns: 30, graceTurns: 0 },
	});
	assert.equal(ten.isError, undefined, resultText(ten));
	assert.equal(ten.details.results.length, 10);
	assert.equal(mockPi.callCount() - callsBeforeTen, 10, "the real foreground executor must start all ten native child processes");
	const afterTen = await waitForPendingZero(harness);
	assert.equal(afterTen.spawnCount, beforeTen.spawnCount, "mock children never acquire a provider slot, so their unclaimed tickets are refunded");

	const beforeEleven = await harness.inspect();
	const callsBeforeEleven = mockPi.callCount();
	const eleven = await executePublic(capacityExecutor, testRoot, sessionId, {
		tasks: tasks(11),
		turnBudget: { maxTurns: 30, graceTurns: 0 },
	});
	assert.equal(eleven.isError, true);
	assert.match(resultText(eleven), /fanout width 10 exceeded.*11/i);
	assert.equal(mockPi.callCount(), callsBeforeEleven, "width 11 must not reach a child/provider process");
	assert.deepEqual(await harness.inspect(), beforeEleven, "width 11 must not reserve durable tickets");

	for (const [label, turnBudget] of [
		["minimum", { maxTurns: 10, graceTurns: 0 }],
		["maximum", { maxTurns: 30, graceTurns: 0 }],
		["default", undefined],
	]) {
		const callsBefore = mockPi.callCount();
		const result = await executePublic(capacityExecutor, testRoot, sessionId, {
			tasks: tasks(1),
			...(turnBudget === undefined ? {} : { turnBudget }),
		});
		assert.equal(result.isError, undefined, `${label}: ${resultText(result)}`);
		assert.equal(mockPi.callCount(), callsBefore + 1, `${label} capacity turn budget must launch exactly one child`);
		await waitForPendingZero(harness);
	}

	const beforeThirtyOne = await harness.inspect();
	const callsBeforeThirtyOne = mockPi.callCount();
	const thirtyOne = await executePublic(capacityExecutor, testRoot, sessionId, {
		tasks: tasks(1),
		turnBudget: { maxTurns: 31, graceTurns: 0 },
	});
	assert.equal(thirtyOne.isError, true);
	assert.match(resultText(thirtyOne), /between 10 and 30/i);
	assert.equal(mockPi.callCount(), callsBeforeThirtyOne);
	assert.deepEqual(await harness.inspect(), beforeThirtyOne, "turn 31 must fail before durable reservation");

	const foregroundRestrictedTaskText = "capacity restricted foreground single must stay native and bounded";
	mockPi.onCall({
		matchArgIncludes: [
			foregroundRestrictedTaskText,
			"--tools",
			"--no-context-files",
			"--no-skills",
			"subagent-prompt-runtime",
		],
		echoEnv: filesystemPolicyEnvKeys,
	});
	const foregroundRestrictedCallsBefore = mockPi.callCount();
	const foregroundRestrictedCallFilesBefore = mockCallFiles(mockPi);
	const foregroundRestricted = await executePublic(restrictedCapacityExecutor, testRoot, sessionId, {
		tasks: [{ agent: "peer", task: foregroundRestrictedTaskText }],
		filesystemPolicy: restrictedFilesystemPolicy,
	});
	assert.equal(foregroundRestricted.isError, undefined, resultText(foregroundRestricted));
	assert.equal(foregroundRestricted.details.mode, "single");
	assert.equal(foregroundRestricted.details.asyncId, undefined);
	assert.equal(foregroundRestricted.details.asyncDir, undefined);
	assert.equal(foregroundRestricted.details.results?.length, 1);
	assert.equal(foregroundRestricted.details.results[0].exitCode, 0);
	assert.equal(mockPi.callCount(), foregroundRestrictedCallsBefore + 1, "foreground restricted single must launch one native Pi child");
	const foregroundRestrictedCall = readSingleNewMockCall(mockPi, foregroundRestrictedCallFilesBefore);
	const foregroundToolsIndex = foregroundRestrictedCall.args.indexOf("--tools");
	assert.notEqual(foregroundToolsIndex, -1);
	assert.equal(foregroundRestrictedCall.args[foregroundToolsIndex + 1], restrictedToolList.join(","));
	assert.equal(foregroundRestrictedCall.args[foregroundToolsIndex + 1].split(",").includes("subagent"), false);
	assert.equal(foregroundRestrictedCall.args[foregroundToolsIndex + 1].split(",").includes("bash"), false);
	assert.equal(foregroundRestrictedCall.args.includes("--no-context-files"), true);
	assert.equal(foregroundRestrictedCall.args.includes("--no-skills"), true);
	const foregroundRestrictedChildEnv = parseEchoedEnvironment(foregroundRestricted.details.results[0].finalOutput);
	assert.equal(foregroundRestrictedChildEnv.PI_SUBAGENT_DEPTH, "1");
	assert.equal(foregroundRestrictedChildEnv.PI_SUBAGENT_MAX_DEPTH, "0");
	await waitForPendingZero(harness);

	const restrictedTaskText = "capacity restricted single must expose only the safe read surface";
	mockPi.onCall({
		matchArgIncludes: [
			restrictedTaskText,
			"--tools",
			"--no-context-files",
			"--no-skills",
			"subagent-prompt-runtime",
		],
		echoEnv: filesystemPolicyEnvKeys,
	});
	const restrictedCallsBefore = mockPi.callCount();
	const restrictedCallFilesBefore = mockCallFiles(mockPi);
	const restrictedStarted = await executePublic(restrictedCapacityExecutor, testRoot, sessionId, {
		tasks: [{ agent: "peer", task: restrictedTaskText }],
		filesystemPolicy: restrictedFilesystemPolicy,
		async: true,
	});
	assert.equal(restrictedStarted.isError, undefined, resultText(restrictedStarted));
	assert.equal(restrictedStarted.details.mode, "single");
	const restrictedRun = registerAsyncCleanup(t, restrictedStarted);
	const restrictedStatus = await waitForAsyncTerminal(restrictedRun.asyncDir);
	assert.equal(restrictedStatus.state, "complete", JSON.stringify(restrictedStatus));
	assert.equal(mockPi.callCount(), restrictedCallsBefore + 1, "restricted typed single must launch exactly one Pi child");
	assert.equal(restrictedStatus.steps?.[0]?.context, "fresh", "filesystem-restricted child context must be fresh");
	const restrictedRecovery = JSON.parse(readFileSync(path.join(restrictedRun.asyncDir, "recovery-descriptor.json"), "utf8"));
	assert.equal(restrictedRecovery.maxSubagentDepth, 0, "filesystem-restricted child must have recursion depth zero");
	assert.equal(restrictedRecovery.inheritProjectContext, false);
	assert.equal(restrictedRecovery.inheritSkills, false);
	assert.equal(Object.hasOwn(restrictedRecovery, "skills"), false, "filesystem-restricted recovery must not retain skills");
	assert.deepEqual(restrictedRecovery.filesystemPolicy?.allowedRoots, [realpathSync(allowedRoot)]);

	const restrictedCall = readSingleNewMockCall(mockPi, restrictedCallFilesBefore);
	const restrictedToolsIndex = restrictedCall.args.indexOf("--tools");
	assert.notEqual(restrictedToolsIndex, -1, "restricted Pi launch must use an explicit tool allowlist");
	assert.equal(restrictedCall.args[restrictedToolsIndex + 1], restrictedToolList.join(","), "policy must intersect the real peer's tools without widening them");
	assert.equal(restrictedCall.args.includes("--no-context-files"), true);
	assert.equal(restrictedCall.args.includes("--no-skills"), true);
	assert.equal(restrictedCall.args[restrictedToolsIndex + 1].split(",").includes("subagent"), false);

	assert.equal(existsSync(restrictedRun.resultPath), true);
	const restrictedResult = JSON.parse(readFileSync(restrictedRun.resultPath, "utf8"));
	assert.equal(restrictedResult.success, true);
	assert.equal(restrictedResult.results?.length, 1);
	const restrictedChildEnv = parseEchoedEnvironment(restrictedResult.results[0].output);
	assertRestrictedFilesystemGate(restrictedChildEnv, allowedReadPath, outsideReadPath);
	await waitForPendingZero(harness);

	const stopTaskText = "capacity restricted stop must terminate the live child";
	const neverReleasePath = path.join(testRoot, "restricted-stop-never-release");
	mockPi.onCall({ matchArgIncludes: stopTaskText, waitForPath: neverReleasePath });
	const callsBeforeRestrictedStop = mockPi.callCount();
	const stopStarted = await executePublic(restrictedCapacityExecutor, testRoot, sessionId, {
		tasks: [{ agent: "peer", task: stopTaskText }],
		filesystemPolicy: restrictedFilesystemPolicy,
		async: true,
	});
	assert.equal(stopStarted.isError, undefined, resultText(stopStarted));
	const stopRun = registerAsyncCleanup(t, stopStarted);
	const stopRunning = await waitForAsyncRunning(stopRun.asyncDir, mockPi, callsBeforeRestrictedStop + 1);
	deliverStopRequest({ asyncDir: stopRun.asyncDir, pid: stopRunning.pid, source: "capacity-public-tasks-test" });
	const stoppedStatus = await waitForAsyncTerminal(stopRun.asyncDir);
	assert.equal(stoppedStatus.state, "stopped", JSON.stringify(stoppedStatus));
	await waitForPendingZero(harness);

	const standaloneTask = tasks(1);
	for (const mixed of [
		{ tasks: standaloneTask, workflowScript: "return 'not allowed'" },
		{ tasks: standaloneTask, action: "status" },
		{ tasks: standaloneTask, agent: "recursive-peer" },
	]) {
		const before = await harness.inspect();
		const treeBefore = snapshotNonRegistryTree(testRoot);
		const callsBefore = mockPi.callCount();
		const result = await executePublic(capacityExecutor, testRoot, sessionId, mixed);
		assert.equal(result.isError, true);
		assert.match(resultText(result), /(?:standalone typed fanout batch.*cannot be combined|capacity v1.*does not expose workflowScript)/i);
		assert.equal(mockPi.callCount(), callsBefore);
		assert.deepEqual(await harness.inspect(), before, "mixed public modes must fail before durable reservation");
		assert.deepEqual(snapshotNonRegistryTree(testRoot), treeBefore, "mixed public modes must not create session or mission state");
	}

	for (const [label, invalidRestricted] of [
		[
			"multi-child filesystem policy",
			{ tasks: peerTasks(2), filesystemPolicy: restrictedFilesystemPolicy, async: true },
		],
		[
			"filesystem policy plus workflow",
			{ tasks: peerTasks(1), filesystemPolicy: restrictedFilesystemPolicy, workflowScript: "return 'never run'" },
		],
		[
			"filesystem policy plus action",
			{ tasks: peerTasks(1), filesystemPolicy: restrictedFilesystemPolicy, action: "status" },
		],
		[
			"filesystem policy plus legacy agent",
			{ tasks: peerTasks(1), filesystemPolicy: restrictedFilesystemPolicy, agent: "peer" },
		],
		[
			"management list plus filesystem policy",
			{ action: "list", filesystemPolicy: restrictedFilesystemPolicy },
		],
		[
			"management status plus filesystem policy",
			{ action: "status", filesystemPolicy: restrictedFilesystemPolicy },
		],
	]) {
		const ledgerBefore = await harness.inspect();
		const treeBefore = snapshotNonRegistryTree(testRoot);
		const callsBefore = mockPi.callCount();
		const rejected = await executePublic(restrictedCapacityExecutor, testRoot, sessionId, invalidRestricted);
		assert.equal(rejected.isError, true, `${label}: ${resultText(rejected)}`);
		assert.match(resultText(rejected), /filesystemPolicy|standalone typed fanout batch|does not expose workflowScript/i);
		assert.equal(mockPi.callCount(), callsBefore, `${label} must reject before child/provider launch`);
		assert.deepEqual(await harness.inspect(), ledgerBefore, `${label} must reject before durable reservation`);
		assert.deepEqual(snapshotNonRegistryTree(testRoot), treeBefore, `${label} must reject before session or mission state`);
	}

	const filesystemTask = peerTasks(1);
	filesystemTask[0].filesystemPolicy = {
		allowedRoots: [testRoot],
		bash: "deny",
	};
	for (const [label, itemPolicyParams] of [
		["item filesystemPolicy", { tasks: filesystemTask }],
		[
			"top-level plus item filesystemPolicy",
			{ tasks: filesystemTask, filesystemPolicy: restrictedFilesystemPolicy, async: true },
		],
	]) {
		const ledgerBefore = await harness.inspect();
		const treeBefore = snapshotNonRegistryTree(testRoot);
		const callsBefore = mockPi.callCount();
		const rejected = await executePublic(restrictedCapacityExecutor, testRoot, sessionId, itemPolicyParams);
		assert.equal(rejected.isError, true, `${label}: ${resultText(rejected)}`);
		assert.match(resultText(rejected), /never accept item-level filesystemPolicy/i);
		assert.equal(rejected.details.asyncId, undefined);
		assert.equal(mockPi.callCount(), callsBefore, `${label} must not reach a child\/provider process`);
		assert.deepEqual(await harness.inspect(), ledgerBefore, `${label} must fail before durable reservation`);
		assert.deepEqual(snapshotNonRegistryTree(testRoot), treeBefore, `${label} must fail before session or mission state`);
	}

	for (const [label, workflowParams] of [
		[
			"sequential runs.run",
			{ workflowScript: "return await runs.run('single', { agent: 'recursive-peer', task: 'capacity workflow must be retired' })" },
		],
		[
			"partial sequential work before runs.all",
			{
				workflowScript: "await runs.run('first', { agent: 'recursive-peer', task: 'must never launch first' }); return runs.all([{ key: 'second', agent: 'recursive-peer', task: 'must never launch second' }])",
				async: true,
			},
		],
		[
			"scheduled workflow",
			{
				action: "schedule.create",
				id: "capacity-schedule-must-be-retired",
				every: "1h",
				workflowScript: "return await runs.run('scheduled', { agent: 'recursive-peer', task: 'must never schedule or launch' })",
			},
		],
	]) {
		const ledgerBefore = await harness.inspect();
		const treeBefore = snapshotNonRegistryTree(testRoot);
		const callsBefore = mockPi.callCount();
		const rejected = await executePublic(capacityExecutor, testRoot, sessionId, workflowParams);
		assert.equal(rejected.isError, true, `${label}: ${resultText(rejected)}`);
		assert.ok(["workflow", "management"].includes(rejected.details.mode), `${label} must return a typed public-mode rejection`);
		assert.equal(rejected.details.asyncId, undefined, `${label} must not create a workflow session`);
		assert.deepEqual(rejected.details.results, []);
		assert.match(resultText(rejected), /capacity v1.*(?:does not expose workflowScript|workflowScript.*(?:retired|unavailable|not supported|disabled))/i);
		assert.equal(mockPi.callCount(), callsBefore, `${label} must not reach child/provider launch`);
		assert.deepEqual(await harness.inspect(), ledgerBefore, `${label} must reject before durable reservation`);
		assert.deepEqual(snapshotNonRegistryTree(testRoot), treeBefore, `${label} must reject before session or mission state`);
	}

	const ordinaryExecutor = makeExecutor(testRoot, false);
	for (const count of [1, 10]) {
		const ledgerBefore = await harness.inspect();
		const callsBefore = mockPi.callCount();
		const denied = await executePublic(ordinaryExecutor, testRoot, sessionId, { tasks: tasks(count) });
		assert.equal(denied.isError, true);
		assert.match(resultText(denied), /Legacy top-level chain and parallel inputs were removed/i);
		assert.equal(mockPi.callCount(), callsBefore, `allowCapacityTasks=false must hide typed tasks width ${count}`);
		assert.deepEqual(await harness.inspect(), ledgerBefore);
	}

	for (const key of capacityEnvKeys) delete process.env[key];
	for (const count of [1, 10]) {
		const callsBefore = mockPi.callCount();
		const denied = await executePublic(ordinaryExecutor, testRoot, sessionId, { tasks: tasks(count) });
		assert.equal(denied.isError, true);
		assert.match(resultText(denied), /Legacy top-level chain and parallel inputs were removed/i);
		assert.equal(mockPi.callCount(), callsBefore, `no-handshake allow=false must hide typed tasks width ${count}`);
	}
	const ordinarySchedule = normalizePublicSubagentExecution({
		action: "schedule.create",
		id: "ordinary-schedule-remains-supported",
		every: "1h",
		workflowScript: "return await runs.run('ordinary-scheduled', { agent: 'recursive-peer', task: 'ordinary schedule' })",
	});
	assert.equal(ordinarySchedule.ok, true, ordinarySchedule.ok ? undefined : ordinarySchedule.error);

	const callsBeforeOrdinaryWorkflow = mockPi.callCount();
	const ordinaryWorkflow = await executePublic(ordinaryExecutor, testRoot, sessionId, {
		workflowScript: "return await runs.run('ordinary-detached', { agent: 'recursive-peer', task: 'ordinary default async workflow child' })",
	});
	assert.equal(ordinaryWorkflow.isError, undefined, resultText(ordinaryWorkflow));
	const ordinaryAsync = registerAsyncCleanup(t, ordinaryWorkflow);
	const ordinaryAsyncStatus = await waitForAsyncTerminal(ordinaryAsync.asyncDir);
	assert.equal(ordinaryAsyncStatus.state, "complete");
	assert.equal(mockPi.callCount(), callsBeforeOrdinaryWorkflow + 1);
	assert.equal(existsSync(ordinaryAsync.resultPath), true, "ordinary default-detached workflow must persist its terminal result");
	const ordinaryAsyncResult = JSON.parse(readFileSync(ordinaryAsync.resultPath, "utf8"));
	assert.equal(ordinaryAsyncResult.success, true);
	assert.equal(ordinaryAsyncResult.results?.length, 1);

	Object.assign(process.env, harness.env);
	harness.registerEnv(process.env);
	mockPi.onCall({ echoEnv: ["NODE_OPTIONS"] });
	const callsBeforeCapacityAsyncTasks = mockPi.callCount();
	const capacityAsyncTasks = await executePublic(capacityExecutor, testRoot, sessionId, {
		tasks: tasks(1),
		async: true,
	});
	assert.equal(capacityAsyncTasks.isError, undefined, resultText(capacityAsyncTasks));
	const capacityAsyncTaskRun = registerAsyncCleanup(t, capacityAsyncTasks);
	const capacityAsyncTaskStatus = await waitForAsyncTerminal(capacityAsyncTaskRun.asyncDir);
	assert.equal(capacityAsyncTaskStatus.state, "complete", JSON.stringify(capacityAsyncTaskStatus));
	assert.equal(mockPi.callCount(), callsBeforeCapacityAsyncTasks + 1, "detached typed tasks must reach exactly one child/provider process");
	assert.equal(existsSync(capacityAsyncTaskRun.resultPath), true, "detached typed tasks must persist their terminal result");
	const capacityAsyncTaskResult = JSON.parse(readFileSync(capacityAsyncTaskRun.resultPath, "utf8"));
	assert.equal(capacityAsyncTaskResult.success, true);
	assert.equal(capacityAsyncTaskResult.results?.length, 1);
	assert.match(
		capacityAsyncTaskResult.results[0].output,
		/--import=.*capacity-isolated-registry-preload\.mjs/i,
		"detached mock Pi child must inherit the isolated registry preload through NODE_OPTIONS",
	);
	await waitForPendingZero(harness);
});
