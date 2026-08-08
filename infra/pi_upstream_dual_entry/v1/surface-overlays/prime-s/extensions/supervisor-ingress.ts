import { createHash, randomUUID } from "node:crypto";
import { createServer, type Server, type Socket } from "node:net";

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const PROTOCOL = "xinao.pi_supervisor.v1";
const PROFILE = process.env.XINAO_PI_PROFILE ?? "";
const PIPE = process.env.XINAO_PI_SUPERVISOR_PIPE ?? "";
const ENABLED = process.env.XINAO_PI_SUPERVISOR_ENABLED === "1" && PROFILE === "prime-s" && PIPE.length > 0;
const MAX_REQUEST_BYTES = 1024 * 1024;
const MAX_EVENTS = 512;
const INSTANCE_ID = randomUUID();

type JsonObject = Record<string, unknown>;
type SupervisorRequest = {
	type?: unknown;
	request_id?: unknown;
	profile?: unknown;
	instance_id?: unknown;
	session_id?: unknown;
	content?: unknown;
	since_sequence?: unknown;
};

type PendingDelivery = {
	request_id: string;
	command: "prompt" | "steer" | "follow_up";
	message_sha256: string;
	runtime_accepted: boolean;
	message_consumed: boolean;
};

type SupervisorEvent = JsonObject & {
	protocol: string;
	instance_id: string;
	profile: string;
	sequence: number;
	timestamp: string;
	kind: string;
};

function sha256(value: string): string {
	return createHash("sha256").update(value, "utf8").digest("hex");
}

function userText(value: unknown): string | undefined {
	if (!value || typeof value !== "object") return undefined;
	const candidate = value as { role?: unknown; content?: unknown };
	if (candidate.role !== "user") return undefined;
	if (typeof candidate.content === "string") return candidate.content;
	if (!Array.isArray(candidate.content)) return undefined;
	const parts = candidate.content
		.filter((part): part is { type: string; text: string } => {
			return Boolean(part && typeof part === "object" && (part as JsonObject).type === "text" && typeof (part as JsonObject).text === "string");
		})
		.map((part) => part.text);
	return parts.length > 0 ? parts.join("\n") : undefined;
}

export default function supervisorIngress(pi: ExtensionAPI): void {
	let currentContext: ExtensionContext | undefined;
	let server: Server | undefined;
	let sequence = 0;
	let activeRequestId: string | undefined;
	const events: SupervisorEvent[] = [];
	const pending: PendingDelivery[] = [];

	function emit(kind: string, detail: JsonObject = {}): SupervisorEvent {
		const event: SupervisorEvent = {
			protocol: PROTOCOL,
			instance_id: INSTANCE_ID,
			profile: PROFILE,
			sequence: ++sequence,
			timestamp: new Date().toISOString(),
			kind,
			...detail,
		};
		events.push(event);
		if (events.length > MAX_EVENTS) events.splice(0, events.length - MAX_EVENTS);
		return event;
	}

	function state(ctx = currentContext): JsonObject {
		if (!ctx) {
			return {
				protocol: PROTOCOL,
				profile: PROFILE,
				instance_id: INSTANCE_ID,
				ready: false,
				last_sequence: sequence,
			};
		}
		return {
			protocol: PROTOCOL,
			profile: PROFILE,
			instance_id: INSTANCE_ID,
			ready: true,
			mode: ctx.mode,
			session_id: ctx.sessionManager.getSessionId(),
			session_file: ctx.sessionManager.getSessionFile(),
			cwd: ctx.cwd,
			idle: ctx.isIdle(),
			pending_messages: ctx.hasPendingMessages(),
			active_tools: [...pi.getActiveTools()].sort(),
			available_tools: pi.getAllTools().map((tool) => tool.name).sort(),
			last_sequence: sequence,
		};
	}

	function requireTarget(request: SupervisorRequest, ctx: ExtensionContext): void {
		const actualSession = ctx.sessionManager.getSessionId();
		if (request.profile !== PROFILE || request.instance_id !== INSTANCE_ID || request.session_id !== actualSession) {
			throw new Error("PI_SUPERVISOR_TARGET_MISMATCH");
		}
	}

	function requireContent(request: SupervisorRequest): string {
		if (typeof request.content !== "string" || request.content.trim().length === 0) {
			throw new Error("PI_SUPERVISOR_CONTENT_REQUIRED");
		}
		if (Buffer.byteLength(request.content, "utf8") > MAX_REQUEST_BYTES) {
			throw new Error("PI_SUPERVISOR_CONTENT_TOO_LARGE");
		}
		return request.content;
	}

	function requireRequestId(request: SupervisorRequest): string {
		if (typeof request.request_id !== "string" || request.request_id.trim().length === 0) {
			throw new Error("PI_SUPERVISOR_REQUEST_ID_REQUIRED");
		}
		return request.request_id;
	}

	function rememberDelivery(requestId: string, command: PendingDelivery["command"], content: string): PendingDelivery {
		const item: PendingDelivery = {
			request_id: requestId,
			command,
			message_sha256: sha256(content),
			runtime_accepted: false,
			message_consumed: false,
		};
		pending.push(item);
		if (pending.length > 128) pending.splice(0, pending.length - 128);
		return item;
	}

	async function processRequest(request: SupervisorRequest): Promise<JsonObject> {
		const command = typeof request.type === "string" ? request.type : "";
		const ctx = currentContext;
		if (!ctx) throw new Error("PI_SUPERVISOR_NOT_READY");

		if (command === "list") {
			return { ok: true, protocol: PROTOCOL, targets: [state(ctx)] };
		}
		if (command === "get_state") {
			return { ok: true, state: state(ctx) };
		}
		if (command === "get_events") {
			const since = typeof request.since_sequence === "number" && Number.isSafeInteger(request.since_sequence)
				? request.since_sequence
				: 0;
			return {
				ok: true,
				state: state(ctx),
				events: events.filter((event) => event.sequence > since),
			};
		}

		requireTarget(request, ctx);
		const requestId = requireRequestId(request);

		if (command === "abort") {
			const wasIdle = ctx.isIdle();
			emit("abort_requested", { request_id: requestId, was_idle: wasIdle, pending_messages: ctx.hasPendingMessages() });
			ctx.abort();
			return { ok: true, phase: "abort_requested", request_id: requestId, was_idle: wasIdle };
		}
		if (command === "stop") {
			emit("stop_requested", { request_id: requestId, pending_messages: ctx.hasPendingMessages() });
			setTimeout(() => ctx.shutdown(), 50);
			return { ok: true, phase: "stop_requested", request_id: requestId, process_shutdown: true };
		}
		if (command !== "prompt" && command !== "steer" && command !== "follow_up") {
			throw new Error("PI_SUPERVISOR_COMMAND_UNKNOWN");
		}

		const content = requireContent(request);
		if (command === "prompt" && !ctx.isIdle()) {
			throw new Error("PI_SUPERVISOR_BUSY_USE_STEER_OR_FOLLOW_UP");
		}
		const item = rememberDelivery(requestId, command, content);
		let delivery: "prompt" | "steer" | "followUp" = "prompt";
		emit("dispatch_requested", {
			request_id: requestId,
			command,
			message_sha256: item.message_sha256,
			was_idle: ctx.isIdle(),
		});
		if (ctx.isIdle()) {
			pi.sendUserMessage(content);
		} else if (command === "follow_up") {
			delivery = "followUp";
			pi.sendUserMessage(content, { deliverAs: "followUp" });
		} else {
			delivery = "steer";
			pi.sendUserMessage(content, { deliverAs: "steer" });
		}
		return {
			ok: true,
			phase: "dispatch_requested",
			request_id: requestId,
			command,
			delivery,
			message_sha256: item.message_sha256,
		};
	}

	function writeResponse(socket: Socket, body: JsonObject): void {
		if (!socket.destroyed) socket.end(`${JSON.stringify(body)}\n`);
	}

	function acceptConnection(socket: Socket): void {
		let buffer = "";
		let complete = false;
		socket.setEncoding("utf8");
		socket.setTimeout(15_000, () => socket.destroy(new Error("PI_SUPERVISOR_REQUEST_TIMEOUT")));
		socket.on("data", (chunk: string) => {
			if (complete) return;
			buffer += chunk;
			if (Buffer.byteLength(buffer, "utf8") > MAX_REQUEST_BYTES) {
				complete = true;
				writeResponse(socket, { ok: false, error: "PI_SUPERVISOR_REQUEST_TOO_LARGE" });
				return;
			}
			const newline = buffer.indexOf("\n");
			if (newline < 0) return;
			complete = true;
			const line = buffer.slice(0, newline).trim();
			void (async () => {
				try {
					const request = JSON.parse(line) as SupervisorRequest;
					writeResponse(socket, await processRequest(request));
				} catch (error) {
					writeResponse(socket, {
						ok: false,
						error: error instanceof Error ? error.message : String(error),
						state: state(),
					});
				}
			})();
		});
	}

	function startServer(ctx: ExtensionContext): void {
		if (!ENABLED || ctx.mode !== "tui" || server) return;
		server = createServer(acceptConnection);
		server.on("error", (error: NodeJS.ErrnoException) => {
			emit("transport_error", { code: error.code ?? "UNKNOWN", error_text: error.message });
		});
		server.listen(PIPE, () => emit("transport_listening", { pipe_name: PIPE }));
	}

	async function stopServer(): Promise<void> {
		const active = server;
		server = undefined;
		if (!active) return;
		await new Promise<void>((resolve) => active.close(() => resolve()));
	}

	function capture(ctx: ExtensionContext): void {
		currentContext = ctx;
	}

	pi.on("session_start", (event, ctx) => {
		capture(ctx);
		emit("session_start", { reason: event.reason, session_id: ctx.sessionManager.getSessionId() });
		startServer(ctx);
	});

	pi.on("session_shutdown", async (event, ctx) => {
		capture(ctx);
		emit("session_shutdown", { reason: event.reason, session_id: ctx.sessionManager.getSessionId() });
		await stopServer();
		currentContext = undefined;
	});

	pi.on("input", (event, ctx) => {
		capture(ctx);
		if (event.source !== "extension") return;
		const digest = sha256(event.text);
		const item = pending.find((candidate) => candidate.message_sha256 === digest && !candidate.runtime_accepted);
		if (!item) {
			emit("unmatched_extension_input", { message_sha256: digest });
			return;
		}
		item.runtime_accepted = true;
		emit("runtime_accepted", {
			request_id: item.request_id,
			command: item.command,
			message_sha256: item.message_sha256,
			streaming_behavior: event.streamingBehavior,
		});
	});

	pi.on("message_start", (event, ctx) => {
		capture(ctx);
		const text = userText(event.message);
		if (text === undefined) return;
		const digest = sha256(text);
		const item = pending.find((candidate) => candidate.message_sha256 === digest && !candidate.message_consumed);
		if (!item) return;
		item.message_consumed = true;
		activeRequestId = item.request_id;
		emit("message_consumed", {
			request_id: item.request_id,
			command: item.command,
			message_sha256: item.message_sha256,
		});
	});

	pi.on("agent_start", (_event, ctx) => {
		capture(ctx);
		emit("agent_start", { request_id: activeRequestId });
	});

	pi.on("tool_execution_start", (event, ctx) => {
		capture(ctx);
		emit("tool_execution_start", { request_id: activeRequestId, tool_name: event.toolName });
	});

	pi.on("tool_execution_end", (event, ctx) => {
		capture(ctx);
		emit("tool_execution_end", { request_id: activeRequestId, tool_name: event.toolName, is_error: event.isError });
	});

	pi.on("turn_end", (event, ctx) => {
		capture(ctx);
		emit("turn_end", { request_id: activeRequestId, turn_index: event.turnIndex, tool_result_count: event.toolResults.length });
	});

	pi.on("agent_settled", (_event, ctx) => {
		capture(ctx);
		emit("agent_settled", { request_id: activeRequestId });
		activeRequestId = undefined;
	});

	pi.on("session_compact", (event, ctx) => {
		capture(ctx);
		emit("session_compact", { reason: event.reason, will_retry: event.willRetry });
	});
}
