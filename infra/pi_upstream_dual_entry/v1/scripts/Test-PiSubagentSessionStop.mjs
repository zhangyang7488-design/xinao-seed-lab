#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = process.env.XINAO_PI_SUBAGENTS_PACKAGE_ROOT
	|| "D:\\XINAO_RESEARCH_RUNTIME\\state\\pi\\0.84.1\\profiles\\prime-s\\npm\\node_modules\\pi-subagents";
const piPackageRoot = process.env.XINAO_PI_AGENT_PACKAGE_ROOT
	|| "D:\\XINAO_RESEARCH_RUNTIME\\tools\\pi\\0.84.1\\node_modules\\@earendil-works\\pi-coding-agent";
const rpcSource = path.join(packageRoot, "src", "extension", "rpc.ts");
const executorSource = path.join(packageRoot, "src", "runs", "foreground", "subagent-executor.ts");
const processGuardSource = path.join(packageRoot, "src", "shared", "post-exit-stdio-guard.ts");
const runnerSource = path.join(packageRoot, "src", "runs", "background", "subagent-runner.ts");
const jitiPath = path.join(piPackageRoot, "node_modules", "jiti", "lib", "jiti.mjs");

for (const required of [rpcSource, executorSource, processGuardSource, runnerSource, jitiPath]) {
	assert.equal(fs.statSync(required).isFile(), true, `missing required file: ${required}`);
}

const { createJiti } = await import(new URL(`file:///${jitiPath.replaceAll("\\", "/")}`).href);
const jiti = createJiti(import.meta.url);
const rpc = await jiti.import(rpcSource);

class EventBus {
	#handlers = new Map();

	on(name, handler) {
		const handlers = this.#handlers.get(name) ?? new Set();
		handlers.add(handler);
		this.#handlers.set(name, handlers);
		return () => handlers.delete(handler);
	}

	emit(name, data) {
		for (const handler of this.#handlers.get(name) ?? []) handler(data);
	}
}

function writeJson(file, value) {
	fs.mkdirSync(path.dirname(file), { recursive: true });
	fs.writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function writeStatus(asyncRoot, { runId, sessionId, state = "running", mode = "single" }) {
	const asyncDir = path.join(asyncRoot, runId);
	writeJson(path.join(asyncDir, "status.json"), {
		runId,
		sessionId,
		state,
		mode,
		startedAt: Date.now() - 100,
		lastUpdate: Date.now(),
		steps: [],
	});
	return asyncDir;
}

function observeTerminal(asyncDir, runId, state = "stopped") {
	const statusPath = path.join(asyncDir, "status.json");
	const status = JSON.parse(fs.readFileSync(statusPath, "utf8"));
	writeJson(statusPath, { ...status, state, stopped: state === "stopped", endedAt: Date.now(), lastUpdate: Date.now() });
	const runnerProcessInstanceId = `runner-${runId}`;
	writeJson(path.join(asyncDir, "process-terminal.json"), {
		version: 1,
		state: "observed",
		runId,
		runnerProcessInstanceId,
		observedAt: Date.now(),
		instances: [{
			processInstanceId: runnerProcessInstanceId,
			kind: "runner",
			closeObservedAt: Date.now(),
			exitCode: state === "complete" ? 0 : 1,
			signal: null,
		}],
		resumeDisposition: state === "stopped" ? "non-resumable" : "resumable",
	});
}

function stateFor(sessionId) {
	return {
		baseCwd: scriptDir,
		currentSessionId: sessionId,
		sessionStopFences: new Set(),
		asyncJobs: new Map(),
		fleetJobs: new Map(),
		foregroundRuns: new Map(),
		foregroundControls: new Map(),
		lastForegroundControlId: null,
		cleanupTimers: new Map(),
		lastUiContext: null,
		poller: null,
		completionSeen: new Map(),
		watcher: null,
		watcherRestartTimer: null,
		workflowControllers: new Map(),
		resultFileCoalescer: { schedule: () => false, clear: () => {} },
	};
}

function contextFor(sessionId) {
	return {
		cwd: scriptDir,
		sessionManager: {
			getSessionFile: () => sessionId,
			getSessionId: () => path.basename(sessionId, ".jsonl"),
		},
	};
}

function rpcRequest(events, method, requestId, params) {
	return new Promise((resolve, reject) => {
		const replyEvent = `${rpc.SUBAGENT_RPC_REPLY_EVENT_PREFIX}${requestId}`;
		const timeout = setTimeout(() => {
			unsubscribe();
			reject(new Error(`RPC timeout for ${method}`));
		}, 2_000);
		const unsubscribe = events.on(replyEvent, (reply) => {
			clearTimeout(timeout);
			unsubscribe();
			resolve(reply);
		});
		events.emit(rpc.SUBAGENT_RPC_REQUEST_EVENT, {
			version: 1,
			requestId,
			method,
			...(params === undefined ? {} : { params }),
		});
	});
}

function installBridge({ asyncRoot, resultsRoot, sessionId, state, waitMs = 500 }) {
	const events = new EventBus();
	const ctx = contextFor(sessionId);
	const bridge = rpc.registerSubagentRpcBridge({
		events,
		getContext: () => ctx,
		execute: async () => ({ content: [{ type: "text", text: "unused" }], details: { mode: "management", results: [] } }),
		state,
		asyncDirRoot: asyncRoot,
		resultsDir: resultsRoot,
		ownerSessionStopWaitMs: waitMs,
		ownerSessionStopPollMs: 10,
	});
	return { bridge, ctx, events };
}

const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "xinao-pi-session-stop-test-"));
try {
	const asyncRoot = path.join(tempRoot, "async");
	const resultsRoot = path.join(tempRoot, "results");
	const ownerSession = path.join(tempRoot, "owner-session.jsonl");
	const foreignSession = path.join(tempRoot, "foreign-session.jsonl");
	const state = stateFor(ownerSession);

	const memoryDir = writeStatus(asyncRoot, { runId: "memory-run", sessionId: ownerSession });
	state.asyncJobs.set("memory-run", { asyncId: "memory-run", asyncDir: memoryDir, status: "running", sessionId: ownerSession, mode: "single" });
	const diskDir = writeStatus(asyncRoot, { runId: "disk-run", sessionId: ownerSession });
	const workflowDir = writeStatus(asyncRoot, { runId: "workflow-run", sessionId: ownerSession, mode: "workflow" });
	const workflowController = new AbortController();
	workflowController.signal.addEventListener("abort", () => {
		const current = JSON.parse(fs.readFileSync(path.join(workflowDir, "status.json"), "utf8"));
		writeJson(path.join(workflowDir, "status.json"), { ...current, state: "stopped", stopped: true, endedAt: Date.now() });
	}, { once: true });
	state.asyncJobs.set("workflow-run", { asyncId: "workflow-run", asyncDir: workflowDir, status: "running", sessionId: ownerSession, mode: "workflow" });
	state.workflowControllers.set("workflow-run", workflowController);
	const foreignDir = writeStatus(asyncRoot, { runId: "foreign-run", sessionId: foreignSession });

	const simulator = setInterval(() => {
		for (const [runId, asyncDir] of [["memory-run", memoryDir], ["disk-run", diskDir]]) {
			if (fs.existsSync(path.join(asyncDir, "control", "stop.json")) && !fs.existsSync(path.join(asyncDir, "process-terminal.json"))) {
				observeTerminal(asyncDir, runId);
			}
		}
	}, 5);

	const { bridge, events } = installBridge({ asyncRoot, resultsRoot, sessionId: ownerSession, state });
	const first = await rpcRequest(events, "stop-session", "stop-owner-1");
	clearInterval(simulator);
	assert.equal(first.success, true);
	assert.equal(first.data.status, "verified");
	assert.equal(first.data.stopFence, true);
	assert.equal(first.data.targetCount, 3);
	assert.deepEqual(new Set(first.data.results.map((result) => result.runId)), new Set(["memory-run", "disk-run", "workflow-run"]));
	assert.equal(first.data.results.find((result) => result.runId === "workflow-run")?.disposition, "in_process_stopped");
	assert.equal(first.data.results.filter((result) => result.kind === "detached").every((result) => result.disposition === "stopped_observed"), true);
	assert.equal(state.sessionStopFences.has(ownerSession), true);
	assert.equal(workflowController.signal.aborted, true);
	assert.equal(fs.existsSync(path.join(memoryDir, "control", "stop.json")), true);
	assert.equal(fs.existsSync(path.join(diskDir, "control", "stop.json")), true);
	assert.equal(fs.existsSync(path.join(foreignDir, "control", "stop.json")), false);

	const duplicate = await rpcRequest(events, "stop-session", "stop-owner-2");
	assert.deepEqual(duplicate.data, first.data);
	bridge.dispose();

	const pendingSession = path.join(tempRoot, "pending-session.jsonl");
	const pendingState = stateFor(pendingSession);
	const pendingDir = writeStatus(asyncRoot, { runId: "pending-run", sessionId: pendingSession });
	pendingState.asyncJobs.set("pending-run", { asyncId: "pending-run", asyncDir: pendingDir, status: "running", sessionId: pendingSession, mode: "single" });
	const pendingBridge = installBridge({ asyncRoot, resultsRoot, sessionId: pendingSession, state: pendingState, waitMs: 60 });
	const pending = await rpcRequest(pendingBridge.events, "stop-session", "stop-pending");
	assert.equal(pending.success, true);
	assert.equal(pending.data.status, "partial");
	assert.equal(pending.data.results[0].disposition, "stop_unverified");
	assert.equal(pendingState.sessionStopFences.has(pendingSession), true);
	pendingBridge.bridge.dispose();

	const mismatchSession = path.join(tempRoot, "mismatch-session.jsonl");
	const mismatchState = stateFor(path.join(tempRoot, "wrong-owner.jsonl"));
	const mismatchBridge = installBridge({ asyncRoot, resultsRoot, sessionId: mismatchSession, state: mismatchState, waitMs: 20 });
	const mismatch = await rpcRequest(mismatchBridge.events, "stop-session", "stop-owner-mismatch");
	assert.equal(mismatch.success, false);
	assert.match(mismatch.error?.message ?? "", /owner mismatch/);
	assert.equal(mismatchState.sessionStopFences.size, 0);
	await new Promise((resolve) => setImmediate(resolve));
	mismatchState.currentSessionId = mismatchSession;
	const mismatchRetry = await rpcRequest(mismatchBridge.events, "stop-session", "stop-owner-mismatch-retry");
	assert.equal(mismatchRetry.success, true);
	assert.equal(mismatchRetry.data.status, "verified");
	assert.equal(mismatchRetry.data.targetCount, 0);
	mismatchBridge.bridge.dispose();

	const executorText = fs.readFileSync(executorSource, "utf8");
	const processGuardText = fs.readFileSync(processGuardSource, "utf8");
	const runnerText = fs.readFileSync(runnerSource, "utf8");
	assert.equal((executorText.match(/sessionStopFenced\(\)/g) ?? []).length >= 3, true);
	assert.equal(executorText.includes("Subagent launch rejected: the owning Pi session is stopping."), true);
	assert.equal(executorText.includes("This is the async launch commit fence."), true);
	assert.match(executorText, /if \(effectiveAsync && sessionStopFenced\(\)\)[\s\S]{0,400}const asyncResult = runAsyncPath/);
	assert.match(processGuardText, /spawnSync\("taskkill", \["\/F", "\/T", "\/PID"/);
	assert.match(processGuardText, /export function tryStopChildTree/);
	assert.match(runnerText, /registerStop\?\.\(\(\) => \{[\s\S]{0,400}tryStopChildTree\(child\)/);

	process.stdout.write(`${JSON.stringify({
		schema: "xinao.pi_subagent_owner_session_stop.v2",
		status: "module_mechanically_verified",
		exact_owner_union: true,
		foreign_session_untouched: true,
		in_process_workflow_aborted: true,
		detached_terminal_proof_required: true,
		pending_proof_is_partial: true,
		duplicate_stop_idempotent: true,
		owner_mismatch_fails_closed_and_retry_recovers: true,
		launch_fence_present_at_entry_and_commit: true,
		windows_stop_owns_child_process_tree: true,
		detached_terminal_sidecar_simulated: true,
		real_process_termination_status: "pending_isolated_process",
		launch_fence_race_status: "pending_isolated_process",
	}, null, 2)}\n`);
} finally {
	const resolvedTemp = path.resolve(tempRoot);
	const resolvedOsTemp = `${path.resolve(os.tmpdir())}${path.sep}`;
	assert.equal(resolvedTemp.startsWith(resolvedOsTemp), true, "refusing to clean a non-temp test root");
	fs.rmSync(resolvedTemp, { recursive: true, force: true });
}
