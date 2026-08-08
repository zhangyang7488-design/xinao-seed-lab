#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { dirname, join } from "node:path";
import { createConnection } from "node:net";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const sourceRoot = dirname(scriptDir);
const extensionPath = join(sourceRoot, "surface-overlays", "prime-s", "extensions", "supervisor-ingress.ts");
const clientPath = join(sourceRoot, "surface-overlays", "prime-s", "skills", "understand-and-steer-prime", "scripts", "pi-supervisor-command.mjs");
const piPackageRoot = process.env.XINAO_PI_AGENT_PACKAGE_ROOT
	|| "D:\\XINAO_RESEARCH_RUNTIME\\tools\\pi\\0.84.1\\node_modules\\@earendil-works\\pi-coding-agent";
const jitiPath = join(piPackageRoot, "node_modules", "jiti", "lib", "jiti.mjs");
const pipeName = `\\\\.\\pipe\\xinao-pi-supervisor-test-${process.pid}-${randomUUID()}`;

process.env.XINAO_PI_PROFILE = "prime-s";
process.env.XINAO_PI_SUPERVISOR_ENABLED = "1";
process.env.XINAO_PI_SUPERVISOR_PIPE = pipeName;

const { createJiti } = await import(pathToFileURL(jitiPath).href);
const jiti = createJiti(import.meta.url);
const loaded = await jiti.import(extensionPath);
const installExtension = loaded.default ?? loaded;

const handlers = new Map();
const queue = { steer: [], followUp: [] };
let editorText = "USER_DRAFT_SENTINEL";
let idle = false;
let compactCalls = 0;
let compactInstructions;
let idlePromptSettlementGuard = false;
let idlePromptMayStart = true;
let promptDispatchCount = 0;
let abortCalls = 0;
let shutdownCalls = 0;
let becomeBusyAfterNextIdleRead = false;

function on(name, handler) {
	const items = handlers.get(name) ?? [];
	items.push(handler);
	handlers.set(name, items);
}

async function fire(name, event, ctx) {
	for (const handler of handlers.get(name) ?? []) await handler(event, ctx);
}

const context = {
	mode: "tui",
	hasUI: true,
	cwd: "E:\\XINAO_RESEARCH_WORKSPACES\\S",
	isIdle: () => {
		const current = idle;
		if (current && becomeBusyAfterNextIdleRead) {
			becomeBusyAfterNextIdleRead = false;
			idle = false;
		}
		return current;
	},
	hasPendingMessages: () => queue.steer.length + queue.followUp.length > 0,
	sessionManager: {
		getSessionId: () => "test-session",
		getSessionFile: () => "D:\\test-session.jsonl",
	},
	ui: {
		getEditorText: () => editorText,
		setEditorText: (text) => { editorText = text; },
	},
	abort: () => {
		abortCalls += 1;
		const restored = [...queue.steer, ...queue.followUp];
		queue.steer.length = 0;
		queue.followUp.length = 0;
		const queuedText = restored.join("\n\n");
		editorText = [queuedText, editorText].filter((text) => text.trim().length > 0).join("\n\n");
	},
	getContextUsage: () => ({ tokens: 260000, contextWindow: 272000, percent: 95.6 }),
	compact: (options) => {
		compactCalls += 1;
		compactInstructions = options?.customInstructions;
		queueMicrotask(() => options?.onComplete?.({ summary: "test" }));
	},
	shutdown: () => { shutdownCalls += 1; },
};

const pi = {
	on,
	getActiveTools: () => new Set(["read"]),
	getAllTools: () => [{ name: "read" }, { name: "edit" }],
	sendUserMessage: (content, options) => {
		const delivery = options?.deliverAs ?? "prompt";
		if (delivery === "steer") queue.steer.push(content);
		else if (delivery === "followUp") queue.followUp.push(content);
		else promptDispatchCount += 1;
		void (async () => {
			await fire("input", {
				source: "extension",
				text: content,
				streamingBehavior: options?.deliverAs,
			}, context);
			// Reproduce the real TUI settlement race: isIdle is already true while
			// the preceding agent_settled stack is still unwinding. A synchronous
			// prompt is accepted by the input hook but never reaches message_start.
			if (delivery === "prompt" && idlePromptSettlementGuard && !idlePromptMayStart) return;
			if (delivery === "prompt") {
				await fire("message_start", {
					message: { role: "user", content: [{ type: "text", text: content }] },
				}, context);
			}
		})();
	},
};

function request(body, timeout = 5000) {
	return new Promise((resolve, reject) => {
		const socket = createConnection(pipeName);
		let buffer = "";
		let settled = false;
		const timer = setTimeout(() => finish(new Error("test pipe timeout")), timeout);
		function finish(error, value) {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			socket.destroy();
			if (error) reject(error);
			else resolve(value);
		}
		socket.setEncoding("utf8");
		socket.once("connect", () => socket.write(`${JSON.stringify(body)}\n`));
		socket.on("data", (chunk) => {
			buffer += chunk;
			const newline = buffer.indexOf("\n");
			if (newline < 0) return;
			try { finish(undefined, JSON.parse(buffer.slice(0, newline))); }
			catch (error) { finish(error); }
		});
		socket.once("error", (error) => finish(error));
	});
}

function runClient(args, stdin = "") {
	return new Promise((resolve, reject) => {
		const child = spawn(process.execPath, [clientPath, ...args], {
			env: process.env,
			windowsHide: true,
			stdio: ["pipe", "pipe", "pipe"],
		});
		let stdout = "";
		let stderr = "";
		child.stdout.setEncoding("utf8");
		child.stderr.setEncoding("utf8");
		child.stdout.on("data", (chunk) => { stdout += chunk; });
		child.stderr.on("data", (chunk) => { stderr += chunk; });
		child.once("error", reject);
		child.once("exit", (code, signal) => resolve({ code, signal, stdout, stderr }));
		child.stdin.end(stdin);
	});
}

async function waitUntilListening() {
	let lastError;
	for (let attempt = 0; attempt < 50; attempt += 1) {
		try { return await request({ type: "get_state" }, 500); }
		catch (error) {
			lastError = error;
			await new Promise((resolve) => setTimeout(resolve, 20));
		}
	}
	throw lastError;
}

function target(type, requestId, content) {
	return {
		type,
		profile: "prime-s",
		instance_id: liveState.state.instance_id,
		session_id: "test-session",
		request_id: requestId,
		...(content === undefined ? {} : { content }),
	};
}

installExtension(pi);
let started = false;
let liveState;
try {
	await fire("session_start", { reason: "startup" }, context);
	started = true;
	liveState = await waitUntilListening();
	assert.equal(liveState.ok, true);
	assert.equal(liveState.state.editor_text_present, true);
	assert.equal(liveState.state.editor_text_length, Buffer.byteLength(editorText, "utf8"));
	assert.equal("editor_text" in liveState.state, false);

	const first = await request(target("steer", "req-owned", "SUPERVISOR_STEER_SENTINEL"));
	assert.equal(first.ok, true);
	assert.equal(first.delivery, "steer");
	assert.equal(queue.steer.length, 1);

	const duplicate = await request(target("steer", "req-owned", "SUPERVISOR_STEER_SENTINEL"));
	assert.equal(duplicate.ok, true);
	assert.equal(duplicate.deduplicated, true);
	assert.equal(duplicate.phase, "runtime_accepted");
	assert.equal(queue.steer.length, 1);

	const conflict = await request(target("steer", "req-owned", "DIFFERENT_CONTENT"));
	assert.equal(conflict.ok, false);
	assert.equal(conflict.error, "PI_SUPERVISOR_REQUEST_ID_CONFLICT");
	assert.equal(queue.steer.length, 1);

	const aborted = await request(target("abort", "abort-owned"));
	assert.equal(aborted.ok, true);
	assert.equal(aborted.editor_reconciled, true);
	assert.equal(aborted.owned_delivery_count, 1);
	assert.equal(editorText, "USER_DRAFT_SENTINEL");
	assert.equal(queue.steer.length + queue.followUp.length, 0);

	const events = await request({ type: "get_events", since_sequence: 0 });
	assert.equal(events.ok, true);
	assert.equal(events.events.some((event) => event.kind === "owned_editor_residue_removed"), true);
	assert.equal(JSON.stringify(events).includes("SUPERVISOR_STEER_SENTINEL"), false);

	const freshSameContent = await request(target("steer", "req-owned-fresh", "SUPERVISOR_STEER_SENTINEL"));
	assert.equal(freshSameContent.ok, true);
	assert.equal(queue.steer.length, 1);
	const sameContentEvents = await request({ type: "get_events", since_sequence: 0 });
	assert.equal(sameContentEvents.events.some((event) =>
		event.kind === "runtime_accepted" && event.request_id === "req-owned-fresh"), true);
	const freshAbort = await request(target("abort", "abort-owned-fresh"));
	assert.equal(freshAbort.editor_reconciled, true);
	assert.equal(editorText, "USER_DRAFT_SENTINEL");

	queue.steer.push("UNOWNED_QUEUED_SENTINEL");
	const second = await request(target("follow_up", "req-mixed", "SUPERVISOR_FOLLOW_UP_SENTINEL"));
	assert.equal(second.ok, true);
	const mixedAbort = await request(target("abort", "abort-mixed"));
	assert.equal(mixedAbort.ok, true);
	assert.equal(mixedAbort.editor_reconciled, false);
	assert.equal(editorText.includes("UNOWNED_QUEUED_SENTINEL"), true);
	assert.equal(editorText.includes("SUPERVISOR_FOLLOW_UP_SENTINEL"), true);

	const finalEvents = await request({ type: "get_events", since_sequence: 0 });
	assert.equal(finalEvents.events.some((event) => event.kind === "owned_editor_reconcile_skipped"), true);

	idle = true;
	const compacted = await request(target("compact", "compact-once", "PRESERVE_PARENT_AND_RETURN_POINT"));
	assert.equal(compacted.ok, true);
	assert.equal(compacted.phase, "compact_requested");
	assert.equal(compactCalls, 1);
	assert.equal(compactInstructions, "PRESERVE_PARENT_AND_RETURN_POINT");
	await new Promise((resolve) => setImmediate(resolve));
	const compactDuplicate = await request(target("compact", "compact-once", "PRESERVE_PARENT_AND_RETURN_POINT"));
	assert.equal(compactDuplicate.deduplicated, true);
	assert.equal(compactDuplicate.phase, "compact_completed");
	assert.equal(compactCalls, 1);
	const compactConflict = await request(target("compact", "compact-once", "DIFFERENT_INSTRUCTIONS"));
	assert.equal(compactConflict.ok, false);
	assert.equal(compactConflict.error, "PI_SUPERVISOR_REQUEST_ID_CONFLICT");
	idle = false;
	const compactBusy = await request(target("compact", "compact-busy"));
	assert.equal(compactBusy.ok, false);
	assert.equal(compactBusy.error, "PI_SUPERVISOR_BUSY_CANNOT_COMPACT");
	const compactionEvents = await request({ type: "get_events", since_sequence: 0 });
	assert.equal(compactionEvents.events.some((event) => event.kind === "compact_completed" && event.request_id === "compact-once"), true);

	// A pipe request can arrive after AgentSession flipped isIdle=true but before
	// the prior agent_settled event has returned. The extension must not call
	// sendUserMessage synchronously inside that settlement window.
	idle = true;
	idlePromptSettlementGuard = true;
	idlePromptMayStart = false;
	const settlementPrompt = await request(target("prompt", "settlement-race", "SETTLEMENT_RACE_PROMPT_SENTINEL"));
	assert.equal(settlementPrompt.ok, true);
	idlePromptMayStart = true;
	await new Promise((resolve) => setTimeout(resolve, 40));
	const settlementDuplicate = await request(target("prompt", "settlement-race", "SETTLEMENT_RACE_PROMPT_SENTINEL"));
	assert.equal(settlementDuplicate.deduplicated, true);
	assert.equal(settlementDuplicate.phase, "message_consumed");
	assert.equal(promptDispatchCount, 1);

	// A prompt accepted while apparently idle must not silently become a steer
	// if another user turn starts during the bounded settlement delay.
	idle = true;
	const dispatchesBeforeBusyRace = promptDispatchCount;
	const becameBusy = await request(target("prompt", "became-busy", "BECAME_BUSY_PROMPT_SENTINEL"));
	assert.equal(becameBusy.ok, true);
	idle = false;
	await new Promise((resolve) => setTimeout(resolve, 40));
	const becameBusyDuplicate = await request(target("prompt", "became-busy", "BECAME_BUSY_PROMPT_SENTINEL"));
	assert.equal(becameBusyDuplicate.deduplicated, true);
	assert.equal(becameBusyDuplicate.phase, "dispatch_failed");
	assert.equal(becameBusyDuplicate.failure_reason, "TARGET_BECAME_BUSY_BEFORE_PROMPT");
	assert.equal(promptDispatchCount, dispatchesBeforeBusyRace);

	// The real client must surface typed asynchronous delivery failure instead
	// of waiting until a generic timeout and inviting an unsafe blind resend.
	idle = true;
	becomeBusyAfterNextIdleRead = true;
	const clientFailure = await runClient([
		"prompt",
		"--profile", "prime-s",
		"--instance", liveState.state.instance_id,
		"--session", "test-session",
		"--request-id", "client-became-busy",
		"--until", "message_consumed",
		"--timeout", "3000",
	], "CLIENT_BECAME_BUSY_PROMPT_SENTINEL\n");
	assert.equal(clientFailure.code, 1);
	assert.equal(clientFailure.stderr.includes("PI_SUPERVISOR_DELIVERY_FAILED"), true);
	assert.equal(clientFailure.stderr.includes("TARGET_BECAME_BUSY_BEFORE_PROMPT"), true);

	// stop is only an accepted shutdown request until the owning process really
	// exits; it must not claim process_shutdown in the pipe response. It also
	// cancels any unconsumed owned delivery before requesting shutdown.
	idle = false;
	const abortCallsBeforeStop = abortCalls;
	const ownedBeforeStop = await request(target("follow_up", "stop-owned-delivery", "STOP_OWNED_QUEUE_SENTINEL"));
	assert.equal(ownedBeforeStop.ok, true);
	const stopResponse = await request(target("stop", "stop-busy"));
	assert.equal(stopResponse.ok, true);
	assert.equal(stopResponse.phase, "stop_requested");
	assert.equal(stopResponse.process_shutdown, false);
	assert.equal(stopResponse.shutdown_requested, true);
	assert.equal(stopResponse.owned_delivery_count >= 1, true);
	await new Promise((resolve) => setTimeout(resolve, 80));
	assert.equal(abortCalls, abortCallsBeforeStop + 1);
	assert.equal(shutdownCalls, 1);

	process.stdout.write(`${JSON.stringify({
		schema: "xinao.pi_supervisor_ingress_regression.v1",
		status: "verified",
		request_id_idempotency: true,
		conflicting_request_rejected: true,
		aborted_hash_reuse_targets_fresh_request: true,
		owned_abort_residue_removed: true,
		preexisting_draft_preserved: true,
		mismatch_preserved: true,
		plaintext_absent_from_events: true,
		native_compaction_exactly_once: true,
		busy_compaction_rejected: true,
		idle_settlement_race_deferred: true,
		message_consumption_proven: true,
		prompt_never_silently_becomes_steer: true,
		client_fails_fast_on_typed_delivery_failure: true,
		stop_cancels_unconsumed_owned_delivery: true,
		stop_request_not_misreported_as_process_exit: true,
	}, null, 2)}\n`);
} finally {
	if (started) await fire("session_shutdown", { reason: "test-complete" }, context);
}
