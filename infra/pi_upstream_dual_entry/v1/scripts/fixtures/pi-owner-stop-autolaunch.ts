import fs from "node:fs";
import path from "node:path";

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const REQUEST_EVENT = "subagents:rpc:v1:request";
const REPLY_PREFIX = "subagents:rpc:v1:reply:";
const RECEIPT_PATH = process.env.XINAO_PI_OWNER_STOP_PROCESS_RECEIPT ?? "";
const PRIMARY_READY_PATH = process.env.XINAO_PI_OWNER_STOP_PRIMARY_READY ?? "";
const PRIMARY_EXIT_PATH = process.env.XINAO_PI_OWNER_STOP_PRIMARY_EXIT ?? "";
const RACE_READY_PATH = process.env.XINAO_PI_OWNER_STOP_RACE_READY ?? "";
const RACE_EXIT_PATH = process.env.XINAO_PI_OWNER_STOP_RACE_EXIT ?? "";
const FIXTURE_PATH = process.env.XINAO_PI_OWNER_STOP_FIXTURE ?? "";
const PRIMARY_AGENT = process.env.XINAO_PI_OWNER_STOP_PRIMARY_AGENT ?? "stop-fixture";
const RACE_AGENT = process.env.XINAO_PI_OWNER_STOP_RACE_AGENT ?? "stop-race-fixture";
const RPC_TIMEOUT_MS = 15_000;
const READY_TIMEOUT_MS = 30_000;

type JsonObject = Record<string, unknown>;

function isRecord(value: unknown): value is JsonObject {
	return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function writeJson(filePath: string, value: unknown): void {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const temporary = `${filePath}.${process.pid}.${Date.now()}.tmp`;
	fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
	fs.renameSync(temporary, filePath);
}

function delay(milliseconds: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function shellPath(value: string): string {
	return value.replaceAll("\\", "/");
}

async function waitForFile(filePath: string, timeoutMs: number): Promise<void> {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		if (fs.existsSync(filePath)) return;
		await delay(50);
	}
	throw new Error(`Timed out waiting for fixture child: ${filePath}`);
}

function rpc(pi: ExtensionAPI, method: string, params?: JsonObject): Promise<JsonObject> {
	const requestId = `owner-stop-process-${method}-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
	const replyEvent = `${REPLY_PREFIX}${requestId}`;
	return new Promise((resolve, reject) => {
		let settled = false;
		let unsubscribe: (() => void) | void;
		const finish = (error: Error | undefined, value?: JsonObject): void => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			if (typeof unsubscribe === "function") unsubscribe();
			if (error) reject(error);
			else resolve(value ?? {});
		};
		const timer = setTimeout(() => finish(new Error(`RPC ${method} timed out.`)), RPC_TIMEOUT_MS);
		unsubscribe = pi.events.on(replyEvent, (raw) => {
			finish(undefined, isRecord(raw) ? raw : { malformed_reply: raw });
		});
		pi.events.emit(REQUEST_EVENT, {
			version: 1,
			requestId,
			method,
			...(params ? { params } : {}),
			source: { extension: "xinao-owner-stop-process-acceptance" },
		});
	});
}

export default function ownerStopProcessAcceptance(pi: ExtensionAPI): void {
	let started = false;

	async function run(ctx: ExtensionContext): Promise<void> {
		const receipt: JsonObject = {
			schema: "xinao.pi_owner_stop_process_extension.v1",
			root_pid: process.pid,
			session_id: ctx.sessionManager.getSessionId(),
		};
		try {
			if (!RECEIPT_PATH || !PRIMARY_READY_PATH || !PRIMARY_EXIT_PATH || !RACE_READY_PATH || !RACE_EXIT_PATH || !FIXTURE_PATH) {
				throw new Error("Owner-stop process fixture environment is incomplete.");
			}
			const ping = await rpc(pi, "ping");
			receipt.ping = ping;
			if (ping.success !== true) throw new Error(`Subagent RPC ping failed: ${JSON.stringify(ping)}`);

			const primaryCommand = `node ${JSON.stringify(shellPath(FIXTURE_PATH))} ${JSON.stringify(shellPath(PRIMARY_READY_PATH))} ${JSON.stringify(shellPath(PRIMARY_EXIT_PATH))}`;
			const primaryTask =
				"Immediately call the bash tool exactly once with this exact command and then remain inside that tool call until it is stopped:\n" +
				primaryCommand;
			const primarySpawn = await rpc(pi, "spawn", {
				workflowScript:
					`return runs.run('hold', { agent: ${JSON.stringify(PRIMARY_AGENT)}, ` +
					`task: ${JSON.stringify(primaryTask)}, async: true })`,
				async: true,
				chatProgress: "off",
				mission: false,
			});
			receipt.primary_spawn = primarySpawn;
			if (primarySpawn.success !== true) throw new Error(`Primary spawn failed: ${JSON.stringify(primarySpawn)}`);
			await waitForFile(PRIMARY_READY_PATH, READY_TIMEOUT_MS);

			// rpc() emits synchronously. stop-session establishes the session fence
			// before its first await; the immediately following spawn therefore probes
			// the real commit boundary rather than a delayed status-file approximation.
			const stopPromise = rpc(pi, "stop-session");
			const raceCommand = `node ${JSON.stringify(shellPath(FIXTURE_PATH))} ${JSON.stringify(shellPath(RACE_READY_PATH))} ${JSON.stringify(shellPath(RACE_EXIT_PATH))}`;
			const raceTask =
				"Immediately call the bash tool exactly once with this exact command; this child must never be launched:\n" +
				raceCommand;
			const racePromise = rpc(pi, "spawn", {
				workflowScript:
					`return runs.run('race', { agent: ${JSON.stringify(RACE_AGENT)}, ` +
					`task: ${JSON.stringify(raceTask)}, async: true })`,
				async: true,
				chatProgress: "off",
				mission: false,
			});
			const [stopReply, raceSpawn] = await Promise.all([stopPromise, racePromise]);
			receipt.stop_reply = stopReply;
			receipt.race_spawn = raceSpawn;
			receipt.completed_at = new Date().toISOString();
			writeJson(RECEIPT_PATH, receipt);
		} catch (error) {
			receipt.error = error instanceof Error ? error.stack ?? error.message : String(error);
			receipt.completed_at = new Date().toISOString();
			if (RECEIPT_PATH) writeJson(RECEIPT_PATH, receipt);
		} finally {
			setTimeout(() => ctx.shutdown(), 50);
		}
	}

	pi.on("session_start", (_event, ctx) => {
		if (started) return;
		started = true;
		setTimeout(() => void run(ctx), 0);
	});
}
