#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createConnection } from "node:net";

const DEFAULT_PIPE = "\\\\.\\pipe\\xinao-pi-supervisor-prime-s-v1";
const ALLOWED = new Set(["list", "get_state", "get_events", "prompt", "steer", "follow_up", "compact", "abort", "stop", "wait"]);
const MUTATING = new Set(["prompt", "steer", "follow_up", "compact", "abort", "stop"]);
const DELIVERY = new Set(["prompt", "steer", "follow_up"]);
const WAIT_CAPABLE = new Set([...DELIVERY, "compact"]);
const WAITABLE = new Set(["runtime_accepted", "message_consumed", "agent_settled", "compact_completed", "compact_failed", "abort_requested"]);

function fail(text, code = 2) {
	process.stderr.write(`${text}\n`);
	process.exit(code);
}

function parseArgs(argv) {
	const values = {
		command: argv[0],
		pipe: process.env.XINAO_PI_SUPERVISOR_PIPE || DEFAULT_PIPE,
		profile: undefined,
		instance: undefined,
		session: undefined,
		requestId: undefined,
		contentFile: undefined,
		since: 0,
		until: undefined,
		timeout: 10_000,
	};
	const rest = argv.slice(1);
	while (rest.length > 0) {
		const key = rest.shift();
		const value = rest.shift();
		if (!key?.startsWith("--") || value === undefined) fail(`Invalid argument sequence near ${key ?? "<end>"}`);
		if (key === "--pipe") values.pipe = value;
		else if (key === "--profile") values.profile = value;
		else if (key === "--instance") values.instance = value;
		else if (key === "--session") values.session = value;
		else if (key === "--request-id") values.requestId = value;
		else if (key === "--content-file") values.contentFile = value;
		else if (key === "--since") values.since = Number(value);
		else if (key === "--until") values.until = value;
		else if (key === "--timeout") values.timeout = Number(value);
		else fail(`Unknown argument: ${key}`);
	}
	return values;
}

async function stdinText() {
	if (process.stdin.isTTY) fail("Delivery content must arrive on stdin or via --content-file; command-line content is intentionally unsupported");
	process.stdin.setEncoding("utf8");
	let body = "";
	for await (const chunk of process.stdin) body += chunk;
	return body.replace(/\r?\n$/, "");
}

async function request(pipeName, body, timeout) {
	return await new Promise((resolve, reject) => {
		const socket = createConnection(pipeName);
		let buffer = "";
		let settled = false;
		const timer = setTimeout(() => finish(new Error(`PI_SUPERVISOR_CLIENT_TIMEOUT after ${timeout} ms`)), timeout);

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
			try {
				finish(undefined, JSON.parse(buffer.slice(0, newline)));
			} catch (error) {
				finish(error);
			}
		});
		socket.once("error", (error) => finish(error));
		socket.once("end", () => {
			if (!settled) finish(new Error("PI_SUPERVISOR_CONNECTION_ENDED_WITHOUT_RESPONSE"));
		});
	});
}

function assertExactTarget(args) {
	if (!args.profile || !args.instance || !args.session) {
		fail(`${args.command} requires exact --profile, --instance, and --session values from a fresh list/get_state response`);
	}
}

function assertResponse(response) {
	if (!response || response.ok !== true) {
		const detail = response?.error ? `: ${response.error}` : "";
		fail(`Pi supervisor command was rejected${detail}`, 1);
	}
}

function sameTarget(state, args) {
	return state?.profile === args.profile && state?.instance_id === args.instance && state?.session_id === args.session;
}

async function waitForEvent(args) {
	assertExactTarget(args);
	if (!args.requestId) fail("wait requires --request-id");
	if (!WAITABLE.has(args.until)) fail(`wait requires --until <${[...WAITABLE].join("|")}>`);
	const deadline = Date.now() + args.timeout;
	let since = args.since;
	while (Date.now() < deadline) {
		const response = await request(args.pipe, { type: "get_events", since_sequence: since }, Math.min(5000, args.timeout));
		assertResponse(response);
		if (!sameTarget(response.state, args)) fail("PI_SUPERVISOR_TARGET_CHANGED_WHILE_WAITING", 1);
		for (const event of response.events ?? []) {
			since = Math.max(since, Number(event.sequence) || 0);
			if (args.until === "compact_completed" && event.request_id === args.requestId && event.kind === "compact_failed") {
				fail(`PI_SUPERVISOR_COMPACTION_FAILED request=${args.requestId}: ${event.error_text ?? "unknown error"}`, 1);
			}
			if (event.request_id === args.requestId && event.kind === args.until) {
				return { ok: true, matched_event: event, state: response.state };
			}
		}
		await new Promise((resolve) => setTimeout(resolve, 200));
	}
	fail(`PI_SUPERVISOR_WAIT_TIMEOUT request=${args.requestId} until=${args.until}`, 1);
}

const args = parseArgs(process.argv.slice(2));
if (!ALLOWED.has(args.command)) {
	fail(`Usage: pi-supervisor-command.mjs <${[...ALLOWED].join("|")}> [--pipe <name>] [--profile prime-s --instance <id> --session <id>] [--request-id <id>] [--content-file <path>] [--since <n>] [--until <phase>] [--timeout <ms>]`);
}
if (!Number.isFinite(args.timeout) || args.timeout < 100 || args.timeout > 600_000) fail("--timeout must be 100..600000 ms");
if (!Number.isSafeInteger(args.since) || args.since < 0) fail("--since must be a non-negative integer");

try {
	let response;
	if (args.command === "wait") {
		response = await waitForEvent(args);
	} else {
		const body = { type: args.command };
		if (args.command === "get_events") body.since_sequence = args.since;
		if (MUTATING.has(args.command)) {
			assertExactTarget(args);
			body.profile = args.profile;
			body.instance_id = args.instance;
			body.session_id = args.session;
			body.request_id = args.requestId || randomUUID();
		}
		if (DELIVERY.has(args.command)) {
			body.content = args.contentFile ? await readFile(args.contentFile, "utf8") : await stdinText();
			if (!body.content.trim()) fail("Delivery content is empty");
		}
		if (args.command === "compact" && args.contentFile) {
			body.content = await readFile(args.contentFile, "utf8");
			if (!body.content.trim()) fail("Compaction instructions are empty");
		}
		response = await request(args.pipe, body, args.timeout);
		assertResponse(response);
		if (WAIT_CAPABLE.has(args.command) && args.until) {
			if (!WAITABLE.has(args.until)) fail(`${args.command} --until must be <${[...WAITABLE].join("|")}>`);
			if (response.phase === args.until) {
				response = { ok: true, dispatch: response, matched_phase: args.until, state: undefined };
			} else {
				const waited = await waitForEvent({ ...args, requestId: body.request_id });
				response = { ok: true, dispatch: response, ...waited };
			}
		}
	}
	process.stdout.write(`${JSON.stringify(response, null, 2)}\n`);
} catch (error) {
	fail(`Pi supervisor client failed: ${error instanceof Error ? error.message : String(error)}`, 1);
}
