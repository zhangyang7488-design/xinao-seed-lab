#!/usr/bin/env node

import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs";
import { registerHooks, stripTypeScriptTypes } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

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
	const value = args[name];
	if (!value) throw new Error(`Missing --${name}`);
	return path.resolve(value);
}

function sha256File(filePath) {
	return createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function resultText(result) {
	return (result.content ?? [])
		.filter((item) => item?.type === "text")
		.map((item) => item.text ?? "")
		.join("\n");
}

function makeState(cwd, sessionId) {
	return {
		baseCwd: cwd,
		currentSessionId: sessionId,
		asyncJobs: new Map(),
		foregroundControls: new Map(),
		lastForegroundControlId: null,
	};
}

function makeContext(cwd, sessionId, sessionFile) {
	return {
		cwd,
		hasUI: false,
		ui: {},
		sessionManager: {
			getSessionId: () => sessionId,
			getSessionFile: () => sessionFile,
			getEntries: () => [],
		},
		modelRegistry: { getAvailable: () => [] },
	};
}

function createEventBus() {
	const listeners = new Map();
	return {
		on(channel, handler) {
			const current = listeners.get(channel) ?? new Set();
			current.add(handler);
			listeners.set(channel, current);
			return () => current.delete(handler);
		},
		emit(channel, payload) {
			for (const handler of listeners.get(channel) ?? []) handler(payload);
		},
	};
}

function tasks(count, prefix) {
	return Array.from({ length: count }, (_, index) => ({
		agent: "recursive-peer",
		task: `Do not call tools. Reply only ${prefix}_${index + 1}.`,
	}));
}

async function waitForAsyncState(asyncDir, wanted, timeoutMs) {
	const statusPath = path.join(asyncDir, "status.json");
	const deadline = Date.now() + timeoutMs;
	let last;
	while (Date.now() < deadline) {
		if (fs.existsSync(statusPath)) {
			try {
				last = JSON.parse(fs.readFileSync(statusPath, "utf8"));
				if (wanted.has(last?.state)) return last;
			} catch {
				// Atomic replacement can briefly race this read.
			}
		}
		await new Promise((resolve) => setTimeout(resolve, 200));
	}
	throw new Error(`Timed out waiting for async state ${[...wanted]}: ${statusPath}; last=${JSON.stringify(last)}`);
}

async function main() {
	const args = parseArgs(process.argv.slice(2));
	const agentDir = required(args, "agent-dir");
	const piToolRoot = required(args, "pi-tool-root");
	const codexHome = required(args, "codex-home");
	const cwd = required(args, "cwd");
	const testRoot = required(args, "test-root");
	const receiptPath = required(args, "receipt");
	const timeoutMs = Number(args["timeout-ms"] ?? "600000");
	const resumeRoot = args["resume-root"] === "true";
	const skipWidth10 = args["skip-width10"] === "true";
	const subagentsRoot = path.join(agentDir, "npm", "node_modules", "pi-subagents");
	const coreRoot = path.join(piToolRoot, "node_modules", "@earendil-works", "pi-coding-agent");
	const cliPath = path.join(coreRoot, "dist", "cli.js");
	const coreAnchor = pathToFileURL(path.join(coreRoot, "dist", "index.js")).href;

	for (const file of [cliPath, path.join(subagentsRoot, "package.json"), path.join(agentDir, "PI_CONTRACT.md")]) {
		assert.equal(fs.statSync(file).isFile(), true, `Required file is not a file: ${file}`);
	}
	for (const directory of [agentDir, piToolRoot, codexHome, cwd, testRoot]) {
		assert.equal(fs.statSync(directory).isDirectory(), true, `Required directory is not a directory: ${directory}`);
	}
	for (const key of ["XINAO_PI_SUBAGENT_CAPACITY_V1", "XINAO_PI_SUBAGENT_CAPACITY_SHA256_V1"]) {
		assert.equal(typeof process.env[key] === "string" && process.env[key].length > 0, true, `Missing capacity handshake: ${key}`);
	}
	assert.equal(process.env.PI_SUBAGENT_MAX_DEPTH, "3");

	process.env.PI_CODING_AGENT_DIR = agentDir;
	process.env.PI_CODING_AGENT_SESSION_DIR = path.join(testRoot, "sessions");
	process.env.PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT = coreRoot;
	process.env.CODEX_HOME = codexHome;
	process.env.XINAO_ACCOUNT_SLOT = "account-b";
	process.env.XINAO_PI_PROFILE = "prime-s";
	process.env.XINAO_PI_ROLE = "main-prime";
	process.env.XINAO_PI_SUPERVISOR_ENABLED = "0";
	process.env.XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE = "1";
	process.env.PI_SKIP_VERSION_CHECK = "1";
	process.env.PI_TELEMETRY = "0";
	process.env.NODE_PATH = [path.join(agentDir, "npm", "node_modules"), path.join(piToolRoot, "node_modules"), path.join(coreRoot, "node_modules")].join(path.delimiter);
	process.argv[1] = cliPath;

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
						source: stripTypeScriptTypes(fs.readFileSync(filename, "utf8"), { mode: "transform" }),
						shortCircuit: true,
					};
				}
			}
			return nextLoad(url, context);
		},
	});

	const runtime = await import(pathToFileURL(path.join(subagentsRoot, "src", "runs", "shared", "xinao-pi-subagent-capacity-runtime.js")).href);
	const { createSubagentExecutor } = await import(pathToFileURL(path.join(subagentsRoot, "src", "runs", "foreground", "subagent-executor.ts")).href);
	const { discoverAgents } = await import(pathToFileURL(path.join(subagentsRoot, "src", "agents", "agents.ts")).href);

	const sessionDir = path.join(testRoot, "sessions");
	fs.mkdirSync(sessionDir, { recursive: true });
	let sessionId;
	let sessionFile;
	if (resumeRoot) {
		const roots = fs.readdirSync(sessionDir, { withFileTypes: true })
			.filter((entry) => entry.isFile() && entry.name.endsWith(".jsonl"));
		assert.equal(roots.length, 1, `resume-root requires exactly one root session file: ${JSON.stringify(roots.map((entry) => entry.name))}`);
		sessionFile = path.join(sessionDir, roots[0].name);
		const header = JSON.parse(fs.readFileSync(sessionFile, "utf8").split(/\r?\n/, 1)[0]);
		assert.equal(header.type, "session");
		sessionId = header.id;
	} else {
		sessionId = randomUUID();
		sessionFile = path.join(sessionDir, `${new Date().toISOString().replace(/[:.]/g, "-")}_${sessionId}.jsonl`);
		fs.writeFileSync(sessionFile, `${JSON.stringify({ type: "session", version: 3, id: sessionId, timestamp: new Date().toISOString(), cwd })}\n`, "utf8");
	}

	const activation = await runtime.activateRootCapacity({
		env: process.env,
		agentDir,
		profile: "prime-s",
		sessionId,
		sessionFile,
	});
	Object.assign(process.env, activation.envProjection);

	const discovered = discoverAgents(cwd, "both");
	const wantedAgents = discovered.agents.filter((agent) => agent.name === "recursive-peer" || agent.name === "peer");
	assert.deepEqual(new Set(wantedAgents.map((agent) => agent.name)), new Set(["recursive-peer", "peer"]));
	const state = makeState(cwd, sessionId);
	const executorBase = createSubagentExecutor({
		pi: { events: createEventBus(), getSessionName: () => "high-capacity-live-acceptance" },
		state,
		config: {
			maxSubagentDepth: 3,
			maxSubagentSpawnsPerSession: 40,
			globalConcurrencyLimit: 6,
			parallel: { maxTasks: 10, concurrency: 6 },
			chain: { dynamicFanout: { maxItems: 10 } },
			turnBudget: { maxTurns: 30, graceTurns: 0 },
		},
		asyncByDefault: false,
		tempArtifactsDir: testRoot,
		getSubagentSessionRoot: () => sessionDir,
		expandTilde: (value) => value,
		discoverAgents: () => ({ agents: wantedAgents }),
	});
	const executor = {
		executePublic(id, params, signal, onUpdate, ctx) {
			return executorBase.executePublic(id, params, signal, onUpdate, ctx, {
				allowCapacityTasks: true,
				allowCapacityRestrictedFilesystemPolicy: false,
			});
		},
	};
	const context = makeContext(cwd, sessionId, sessionFile);
	const execute = (params) => executor.executePublic(randomUUID(), params, new AbortController().signal, undefined, context);
	const checks = {};
	const startedAt = new Date().toISOString();

	try {
		if (skipWidth10) {
			const retainedSessions = [];
			for (const entry of fs.readdirSync(sessionDir, { withFileTypes: true })) {
				if (!entry.isDirectory()) continue;
				for (const run of fs.readdirSync(path.join(sessionDir, entry.name), { withFileTypes: true })) {
					const candidate = path.join(sessionDir, entry.name, run.name, "session.jsonl");
					if (run.isDirectory() && fs.existsSync(candidate)) retainedSessions.push(candidate);
				}
			}
			assert.equal(retainedSessions.length, 10, `skip-width10 expected ten retained live child sessions: ${JSON.stringify(retainedSessions)}`);
			const retainedText = retainedSessions.map((file) => fs.readFileSync(file, "utf8")).join("\n");
			for (let index = 1; index <= 10; index += 1) assert.match(retainedText, new RegExp(`LIVE_WIDTH10_${index}`));
			checks.width10 = { child_results: 10, resumed_verified_child_sessions: 10 };
		} else {
			const width10 = await execute({ tasks: tasks(10, "LIVE_WIDTH10"), turnBudget: { maxTurns: 10, graceTurns: 0 }, async: false });
			assert.notEqual(width10.isError, true, resultText(width10));
			assert.equal(width10.details?.results?.length, 10, `width10 result count mismatch: ${JSON.stringify(width10.details)}`);
			for (let index = 1; index <= 10; index += 1) assert.match(resultText(width10), new RegExp(`LIVE_WIDTH10_${index}`));
			checks.width10 = { child_results: 10 };
		}

		const beforeWidth11 = await runtime.inspectRootCapacityLedger({ env: process.env, binding: activation.binding });
		const width11 = await execute({ tasks: tasks(11, "LIVE_WIDTH11_MUST_NOT_RUN"), turnBudget: { maxTurns: 10, graceTurns: 0 }, async: false });
		assert.equal(width11.isError, true, `width11 unexpectedly succeeded: ${resultText(width11)}`);
		assert.match(resultText(width11), /(fanout|width|10|maximum)/i);
		const afterWidth11 = await runtime.inspectRootCapacityLedger({ env: process.env, binding: activation.binding });
		assert.equal(afterWidth11.spawnCount, beforeWidth11.spawnCount);
		checks.width11_prelaunch_rejected = true;

		for (const hard of [10, 30]) {
			const marker = `LIVE_TURN_${hard}`;
			const result = await execute({ tasks: tasks(1, marker), turnBudget: { maxTurns: hard, graceTurns: 0 }, async: false });
			assert.notEqual(result.isError, true, resultText(result));
			assert.equal(result.details?.results?.length, 1);
			assert.match(resultText(result), new RegExp(`${marker}_1`));
			checks[`turn_${hard}_accepted`] = true;
		}

		const beforeTurn31 = await runtime.inspectRootCapacityLedger({ env: process.env, binding: activation.binding });
		const turn31 = await execute({ tasks: tasks(1, "LIVE_TURN31_MUST_NOT_RUN"), turnBudget: { maxTurns: 31, graceTurns: 0 }, async: false });
		assert.equal(turn31.isError, true, `turn31 unexpectedly succeeded: ${resultText(turn31)}`);
		assert.match(resultText(turn31), /(turn|31|30|hard)/i);
		const afterTurn31 = await runtime.inspectRootCapacityLedger({ env: process.env, binding: activation.binding });
		assert.equal(afterTurn31.spawnCount, beforeTurn31.spawnCount);
		checks.turn_31_prelaunch_rejected = true;

		const recursiveTask = [
			"This is a bounded recursion-depth acceptance. If subagent execution is still permitted at your current depth,",
			"call subagent exactly once with tasks containing one recursive-peer whose task is this same instruction,",
			"turnBudget maxTurns 10 graceTurns 0, and async false. After it settles, reply DEPTH_RETURNED plus its terminal text.",
			"If that one call is rejected by the depth ceiling, reply only DEPTH_CEILING_REACHED.",
		].join(" ");
		const depth = await execute({ tasks: [{ agent: "recursive-peer", task: recursiveTask }], turnBudget: { maxTurns: 10, graceTurns: 0 }, async: false });
		assert.notEqual(depth.isError, true, resultText(depth));
		assert.match(resultText(depth), /DEPTH_(RETURNED|CEILING_REACHED)/);
		checks.depth3_recursive_provider_path = true;

		const stopTask = "Use your bash tool exactly once to run powershell.exe -NoProfile -Command Start-Sleep -Seconds 90. After the sleep, reply only SHOULD_HAVE_BEEN_STOPPED.";
		const started = await execute({ tasks: [{ agent: "peer", task: stopTask }], turnBudget: { maxTurns: 10, graceTurns: 0 }, async: true });
		assert.notEqual(started.isError, true, resultText(started));
		const asyncId = started.details?.asyncId;
		const asyncDir = started.details?.asyncDir;
		assert.equal(typeof asyncId, "string");
		assert.equal(typeof asyncDir, "string");
		await waitForAsyncState(asyncDir, new Set(["running"]), timeoutMs);
		const stopped = await execute({ action: "stop", id: asyncId });
		assert.match(resultText(stopped), /(stop|abort|terminal|verified)/i);
		const terminal = await waitForAsyncState(asyncDir, new Set(["failed", "aborted", "stopped", "timeout"]), timeoutMs);
		checks.owner_stop = { async_id: asyncId, terminal_state: terminal.state };

		const ledger = await runtime.inspectRootCapacityLedger({ env: process.env, binding: activation.binding });
		assert.equal(ledger.pendingSpawns, 0);
		assert.equal(ledger.spawnCount > 0 && ledger.spawnCount <= 40, true);
		const receipt = {
			schema: "xinao.pi_s_high_capacity_live_executor.v1",
			status: "verified",
			started_at: startedAt,
			completed_at: new Date().toISOString(),
			profile: "prime-s",
			account_slot: "account-b",
			provider: "openai-codex",
			root_model: "gpt-5.6-sol",
			capacity_static_sha256: process.env.XINAO_PI_SUBAGENT_CAPACITY_SHA256_V1,
			root_key: activation.binding.rootKey,
			ledger: { committed_spawns: ledger.spawnCount, pending_spawns: ledger.pendingSpawns },
			checks,
			active_hashes: {
				async_execution_sha256: sha256File(path.join(subagentsRoot, "src", "runs", "background", "async-execution.ts")),
				async_resume_sha256: sha256File(path.join(subagentsRoot, "src", "runs", "background", "async-resume.ts")),
				capacity_runtime_sha256: sha256File(path.join(subagentsRoot, "src", "runs", "shared", "xinao-pi-subagent-capacity-runtime.js")),
			},
		};
		fs.mkdirSync(path.dirname(receiptPath), { recursive: true });
		fs.writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
		process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
	} finally {
		await activation.release();
	}
}

main().catch((error) => {
	process.stderr.write(`PI_S_HIGH_CAPACITY_LIVE_EXECUTOR_ERROR: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
	process.exitCode = 1;
});
