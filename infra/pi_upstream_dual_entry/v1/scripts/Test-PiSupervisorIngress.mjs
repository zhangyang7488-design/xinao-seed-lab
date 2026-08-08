#!/usr/bin/env node

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { dirname, join } from "node:path";
import { createConnection } from "node:net";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const sourceRoot = dirname(scriptDir);
const extensionPath = join(sourceRoot, "surface-overlays", "prime-s", "extensions", "supervisor-ingress.ts");
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
	isIdle: () => idle,
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
	shutdown: () => {},
};

const pi = {
	on,
	getActiveTools: () => new Set(["read"]),
	getAllTools: () => [{ name: "read" }, { name: "edit" }],
	sendUserMessage: (content, options) => {
		const delivery = options?.deliverAs ?? "prompt";
		if (delivery === "steer") queue.steer.push(content);
		else if (delivery === "followUp") queue.followUp.push(content);
		void fire("input", {
			source: "extension",
			text: content,
			streamingBehavior: options?.deliverAs,
		}, context);
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
	}, null, 2)}\n`);
} finally {
	if (started) await fire("session_shutdown", { reason: "test-complete" }, context);
}
