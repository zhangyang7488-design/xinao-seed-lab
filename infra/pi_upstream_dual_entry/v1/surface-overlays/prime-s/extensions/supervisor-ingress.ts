import { createHash, randomUUID } from "node:crypto";
import { createServer, type Server, type Socket } from "node:net";

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const PROTOCOL = "xinao.pi_supervisor.v1";
const PROFILE = process.env.XINAO_PI_PROFILE ?? "";
const PIPE = process.env.XINAO_PI_SUPERVISOR_PIPE ?? "";
const ENABLED = process.env.XINAO_PI_SUPERVISOR_ENABLED === "1" && ["prime-s", "prime-b"].includes(PROFILE) && PIPE.length > 0;
const MAX_REQUEST_BYTES = 1024 * 1024;
const MAX_EVENTS = 512;
const IDLE_DISPATCH_SETTLE_MS = 25;
const RUNTIME_ACCEPTANCE_WATCHDOG_MS = 2_000;
const SUBAGENT_RPC_REQUEST_EVENT = "subagents:rpc:v1:request";
const SUBAGENT_RPC_REPLY_EVENT_PREFIX = "subagents:rpc:v1:reply:";
const SUBAGENT_STOP_RPC_TIMEOUT_MS = 8_000;
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
	delivery: "prompt" | "steer" | "followUp";
	content: string;
	message_sha256: string;
	dispatch_attempted: boolean;
	runtime_accepted: boolean;
	message_consumed: boolean;
	aborted: boolean;
	failure_reason?: string;
};

type PendingCompaction = {
	request_id: string;
	instructions_sha256: string;
	phase: "compact_requested" | "compact_completed" | "compact_failed";
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

function jsonObject(value: unknown): JsonObject | undefined {
	return value && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : undefined;
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
	let stopping = false;
	let stopOperation: Promise<JsonObject> | undefined;
	let stopOperationRequestId: string | undefined;
	const events: SupervisorEvent[] = [];
	const pending: PendingDelivery[] = [];
	const compactions: PendingCompaction[] = [];

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
				stopping,
			};
		}
		const editorText = ctx.mode === "tui" && ctx.hasUI ? ctx.ui.getEditorText() : "";
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
			editor_text_present: editorText.length > 0,
			editor_text_length: Buffer.byteLength(editorText, "utf8"),
			editor_text_sha256: sha256(editorText),
			active_tools: [...pi.getActiveTools()].sort(),
			available_tools: pi.getAllTools().map((tool) => tool.name).sort(),
			last_sequence: sequence,
			stopping,
		};
	}

	function requestOwnerSessionStop(requestId: string): Promise<JsonObject> {
		const rpcRequestId = `supervisor-stop-${randomUUID()}`;
		const replyEvent = `${SUBAGENT_RPC_REPLY_EVENT_PREFIX}${rpcRequestId}`;
		return new Promise((resolve) => {
			let settled = false;
			let unsubscribe: (() => void) | void;
			const finish = (value: JsonObject): void => {
				if (settled) return;
				settled = true;
				clearTimeout(timer);
				if (typeof unsubscribe === "function") unsubscribe();
				resolve(value);
			};
			const timer = setTimeout(() => finish({
				status: "partial",
				verified: false,
				error: "PI_SUBAGENT_OWNER_STOP_RPC_TIMEOUT",
			}), SUBAGENT_STOP_RPC_TIMEOUT_MS);
			unsubscribe = pi.events.on(replyEvent, (raw) => {
				const reply = jsonObject(raw);
				if (!reply || reply.success !== true) {
					const error = jsonObject(reply?.error);
					finish({
						status: "partial",
						verified: false,
						error: typeof error?.message === "string" ? error.message : "PI_SUBAGENT_OWNER_STOP_RPC_FAILED",
					});
					return;
				}
				const data = jsonObject(reply.data);
				finish({
					status: data?.status === "verified" ? "verified" : "partial",
					verified: data?.status === "verified",
					stop_fence: data?.stopFence === true,
					target_count: typeof data?.targetCount === "number" ? data.targetCount : 0,
					results: Array.isArray(data?.results) ? data.results : [],
					enumeration_errors: Array.isArray(data?.enumerationErrors) ? data.enumerationErrors : [],
				});
			});
			try {
				pi.events.emit(SUBAGENT_RPC_REQUEST_EVENT, {
					version: 1,
					requestId: rpcRequestId,
					method: "stop-session",
					source: { extension: "xinao-supervisor-ingress", requestId },
				});
			} catch (error) {
				finish({
					status: "partial",
					verified: false,
					error: error instanceof Error ? error.message : String(error),
				});
			}
		});
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

	function optionalContent(request: SupervisorRequest): string | undefined {
		if (request.content === undefined) return undefined;
		if (typeof request.content !== "string") throw new Error("PI_SUPERVISOR_CONTENT_INVALID");
		if (Buffer.byteLength(request.content, "utf8") > MAX_REQUEST_BYTES) {
			throw new Error("PI_SUPERVISOR_CONTENT_TOO_LARGE");
		}
		return request.content.trim().length > 0 ? request.content : undefined;
	}

	function requireRequestId(request: SupervisorRequest): string {
		if (typeof request.request_id !== "string" || request.request_id.trim().length === 0) {
			throw new Error("PI_SUPERVISOR_REQUEST_ID_REQUIRED");
		}
		return request.request_id;
	}

	function rememberDelivery(
		requestId: string,
		command: PendingDelivery["command"],
		delivery: PendingDelivery["delivery"],
		content: string,
	): PendingDelivery {
		const item: PendingDelivery = {
			request_id: requestId,
			command,
			delivery,
			content,
			message_sha256: sha256(content),
			dispatch_attempted: false,
			runtime_accepted: false,
			message_consumed: false,
			aborted: false,
		};
		pending.push(item);
		if (pending.length > 128) pending.splice(0, pending.length - 128);
		return item;
	}

	function deliveryPhase(item: PendingDelivery): string {
		if (item.failure_reason) return "dispatch_failed";
		if (item.aborted) return "aborted";
		if (item.message_consumed) return "message_consumed";
		if (item.runtime_accepted) return "runtime_accepted";
		if (item.dispatch_attempted) return "dispatch_attempted";
		return "dispatch_requested";
	}

	function reconcileOwnedAbortResidue(
		ctx: ExtensionContext,
		abortRequestId: string,
		editorBefore: string,
		candidates: PendingDelivery[],
	): JsonObject {
		if (ctx.mode !== "tui" || !ctx.hasUI || candidates.length === 0) {
			return { owned_delivery_count: candidates.length, editor_reconciled: false };
		}
		const ordered = [
			...candidates.filter((item) => item.delivery === "steer"),
			...candidates.filter((item) => item.delivery === "followUp"),
		];
		if (ordered.length === 0) {
			return { owned_delivery_count: 0, editor_reconciled: false };
		}
		const ownedQueueText = ordered.map((item) => item.content).join("\n\n");
		const expectedAfterAbort = [ownedQueueText, editorBefore]
			.filter((text) => text.trim().length > 0)
			.join("\n\n");
		const editorAfterAbort = ctx.ui.getEditorText();
		if (editorAfterAbort !== expectedAfterAbort) {
			emit("owned_editor_reconcile_skipped", {
				request_id: abortRequestId,
				owned_delivery_count: ordered.length,
				editor_before_sha256: sha256(editorBefore),
				editor_after_sha256: sha256(editorAfterAbort),
				reason: "EDITOR_CONTENT_DID_NOT_MATCH_OWNED_ABORT_RESTORE",
			});
			return { owned_delivery_count: ordered.length, editor_reconciled: false };
		}
		ctx.ui.setEditorText(editorBefore);
		emit("owned_editor_residue_removed", {
			request_id: abortRequestId,
			owned_delivery_count: ordered.length,
			editor_before_sha256: sha256(editorBefore),
			editor_after_sha256: sha256(editorBefore),
		});
		return { owned_delivery_count: ordered.length, editor_reconciled: true };
	}

	function scheduleDelivery(item: PendingDelivery, sessionId: string, deferPastIdleSettlement: boolean): void {
		const attempt = () => {
			if (item.aborted || item.dispatch_attempted) return;
			const ctx = currentContext;
			if (!ctx || ctx.sessionManager.getSessionId() !== sessionId) {
				item.aborted = true;
				item.failure_reason = "TARGET_SESSION_CHANGED_BEFORE_DISPATCH";
				item.content = "";
				emit("dispatch_failed", {
					request_id: item.request_id,
					command: item.command,
					message_sha256: item.message_sha256,
					reason: "TARGET_SESSION_CHANGED_BEFORE_DISPATCH",
				});
				return;
			}

			const nowIdle = ctx.isIdle();
			if (item.command === "prompt" && !nowIdle) {
				item.aborted = true;
				item.failure_reason = "TARGET_BECAME_BUSY_BEFORE_PROMPT";
				item.content = "";
				emit("dispatch_failed", {
					request_id: item.request_id,
					command: item.command,
					message_sha256: item.message_sha256,
					reason: item.failure_reason,
				});
				return;
			}
			if (nowIdle) item.delivery = "prompt";
			else if (item.command === "follow_up") item.delivery = "followUp";
			else item.delivery = "steer";
			item.dispatch_attempted = true;
			emit("dispatch_attempted", {
				request_id: item.request_id,
				command: item.command,
				delivery: item.delivery,
				message_sha256: item.message_sha256,
				deferred_past_idle_settlement: deferPastIdleSettlement,
			});
			if (item.delivery === "prompt") pi.sendUserMessage(item.content);
			else pi.sendUserMessage(item.content, { deliverAs: item.delivery });

			const watchdog = setTimeout(() => {
				if (item.aborted || item.message_consumed) return;
				if (!item.runtime_accepted) {
					emit("runtime_acceptance_missing", {
						request_id: item.request_id,
						command: item.command,
						delivery: item.delivery,
						message_sha256: item.message_sha256,
					});
				} else if (item.delivery === "prompt") {
					emit("message_consumption_missing", {
						request_id: item.request_id,
						command: item.command,
						delivery: item.delivery,
						message_sha256: item.message_sha256,
					});
				}
			}, RUNTIME_ACCEPTANCE_WATCHDOG_MS);
			watchdog.unref();
		};

		// AgentSession sets isIdle=true immediately before it emits agent_settled.
		// A pipe request can therefore observe idle while the previous settled
		// stack is still unwinding. Starting a prompt synchronously in that window
		// races the old run's finally block and can accept input without ever
		// appending the user message. Cross one macrotask boundary first.
		if (deferPastIdleSettlement) setTimeout(attempt, IDLE_DISPATCH_SETTLE_MS);
		else attempt();
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
		if (stopping && command !== "stop") throw new Error("PI_SUPERVISOR_STOP_IN_PROGRESS");

		requireTarget(request, ctx);
		const requestId = requireRequestId(request);

		if (command === "abort") {
			const wasIdle = ctx.isIdle();
			const editorBefore = ctx.mode === "tui" && ctx.hasUI ? ctx.ui.getEditorText() : "";
			const ownedUnconsumed = pending.filter((item) => !item.message_consumed && !item.aborted);
			emit("abort_requested", {
				request_id: requestId,
				was_idle: wasIdle,
				pending_messages: ctx.hasPendingMessages(),
				owned_unconsumed_count: ownedUnconsumed.length,
			});
			ctx.abort();
			const reconciliation = reconcileOwnedAbortResidue(ctx, requestId, editorBefore, ownedUnconsumed);
			for (const item of ownedUnconsumed) {
				item.aborted = true;
				item.content = "";
			}
			return { ok: true, phase: "abort_requested", request_id: requestId, was_idle: wasIdle, ...reconciliation };
		}
		if (command === "stop") {
			if (stopOperation) {
				const receipt = await stopOperation;
				return {
					...receipt,
					request_id: requestId,
					original_request_id: stopOperationRequestId,
					deduplicated: true,
				};
			}
			stopping = true;
			stopOperationRequestId = requestId;
			stopOperation = (async (): Promise<JsonObject> => {
				const cleanupErrors: string[] = [];
				let wasIdle = false;
				let editorBefore = "";
				let ownedUnconsumed: PendingDelivery[] = [];
				let reconciliation: JsonObject = { owned_delivery_count: 0, editor_reconciled: false };
				try {
					wasIdle = ctx.isIdle();
					editorBefore = ctx.mode === "tui" && ctx.hasUI ? ctx.ui.getEditorText() : "";
					ownedUnconsumed = pending.filter((item) => !item.message_consumed && !item.aborted);
					emit("stop_requested", {
						request_id: requestId,
						was_idle: wasIdle,
						pending_messages: ctx.hasPendingMessages(),
						owned_unconsumed_count: ownedUnconsumed.length,
					});
				} catch (error) {
					cleanupErrors.push(`stop_setup:${error instanceof Error ? error.message : String(error)}`);
				}

				let childStopPromise: Promise<JsonObject>;
				try {
					childStopPromise = requestOwnerSessionStop(requestId);
				} catch (error) {
					childStopPromise = Promise.resolve({
						status: "partial",
						verified: false,
						error: error instanceof Error ? error.message : String(error),
					});
				}
				try {
					ctx.abort();
				} catch (error) {
					cleanupErrors.push(`root_abort:${error instanceof Error ? error.message : String(error)}`);
				}
				try {
					reconciliation = reconcileOwnedAbortResidue(ctx, requestId, editorBefore, ownedUnconsumed);
				} catch (error) {
					cleanupErrors.push(`residue_reconciliation:${error instanceof Error ? error.message : String(error)}`);
				}
				for (const item of ownedUnconsumed) {
					item.aborted = true;
					item.content = "";
				}

				let childStop: JsonObject;
				try {
					childStop = await childStopPromise;
				} catch (error) {
					childStop = {
						status: "partial",
						verified: false,
						error: error instanceof Error ? error.message : String(error),
					};
				}
				try {
					emit("child_stop_settled", {
						request_id: requestId,
						status: childStop.status,
						target_count: childStop.target_count,
						cleanup_error_count: cleanupErrors.length,
					});
				} catch (error) {
					cleanupErrors.push(`stop_event:${error instanceof Error ? error.message : String(error)}`);
				}
				return {
					ok: true,
					phase: "stop_requested",
					request_id: requestId,
					shutdown_requested: true,
					process_shutdown: false,
					was_idle: wasIdle,
					status: childStop.status === "verified" && cleanupErrors.length === 0 ? "verified" : "partial",
					child_stop: childStop,
					cleanup_errors: cleanupErrors,
					...reconciliation,
				};
			})().catch((error): JsonObject => ({
				ok: true,
				phase: "stop_requested",
				request_id: requestId,
				shutdown_requested: true,
				process_shutdown: false,
				status: "partial",
				child_stop: { status: "partial", verified: false },
				cleanup_errors: [`stop_operation:${error instanceof Error ? error.message : String(error)}`],
			})).finally(() => {
				setTimeout(() => {
					try {
						emit("shutdown_dispatched", { request_id: requestId });
					} catch (error) {
						console.error("Failed to record Pi supervisor shutdown dispatch:", error);
					}
					try {
						ctx.shutdown();
					} catch (error) {
						console.error("Failed to dispatch Pi supervisor shutdown:", error);
					}
				}, 50);
			});
			return await stopOperation;
		}
		if (command === "compact") {
			const customInstructions = optionalContent(request);
			const instructionsDigest = sha256(customInstructions ?? "");
			const existing = compactions.find((item) => item.request_id === requestId);
			if (existing) {
				if (existing.instructions_sha256 !== instructionsDigest) {
					throw new Error("PI_SUPERVISOR_REQUEST_ID_CONFLICT");
				}
				return {
					ok: true,
					phase: existing.phase,
					request_id: requestId,
					instructions_sha256: instructionsDigest,
					deduplicated: true,
				};
			}
			if (!ctx.isIdle()) throw new Error("PI_SUPERVISOR_BUSY_CANNOT_COMPACT");
			const item: PendingCompaction = {
				request_id: requestId,
				instructions_sha256: instructionsDigest,
				phase: "compact_requested",
			};
			compactions.push(item);
			if (compactions.length > 64) compactions.splice(0, compactions.length - 64);
			const usageBefore = ctx.getContextUsage();
			emit("compact_requested", {
				request_id: requestId,
				instructions_sha256: instructionsDigest,
				context_tokens_before: usageBefore?.tokens ?? null,
				context_window: usageBefore?.contextWindow ?? null,
			});
			try {
				ctx.compact({
					customInstructions,
					onComplete: () => {
						item.phase = "compact_completed";
						const usageAfter = currentContext?.getContextUsage();
						emit("compact_completed", {
							request_id: requestId,
							instructions_sha256: instructionsDigest,
							context_tokens_after: usageAfter?.tokens ?? null,
							context_window: usageAfter?.contextWindow ?? null,
						});
					},
					onError: (error) => {
						item.phase = "compact_failed";
						emit("compact_failed", {
							request_id: requestId,
							instructions_sha256: instructionsDigest,
							error_text: error.message,
						});
					},
				});
			} catch (error) {
				item.phase = "compact_failed";
				const errorText = error instanceof Error ? error.message : String(error);
				emit("compact_failed", {
					request_id: requestId,
					instructions_sha256: instructionsDigest,
					error_text: errorText,
				});
				throw error;
			}
			return {
				ok: true,
				phase: item.phase,
				request_id: requestId,
				instructions_sha256: instructionsDigest,
			};
		}
		if (command !== "prompt" && command !== "steer" && command !== "follow_up") {
			throw new Error("PI_SUPERVISOR_COMMAND_UNKNOWN");
		}

		const content = requireContent(request);
		const digest = sha256(content);
		const existing = pending.find((item) => item.request_id === requestId);
		if (existing) {
			if (existing.command !== command || existing.message_sha256 !== digest) {
				throw new Error("PI_SUPERVISOR_REQUEST_ID_CONFLICT");
			}
			return {
				ok: true,
				phase: deliveryPhase(existing),
				request_id: existing.request_id,
				command: existing.command,
				delivery: existing.delivery,
				message_sha256: existing.message_sha256,
				failure_reason: existing.failure_reason,
				deduplicated: true,
			};
		}
		const wasIdle = ctx.isIdle();
		if (command === "prompt" && !wasIdle) {
			throw new Error("PI_SUPERVISOR_BUSY_USE_STEER_OR_FOLLOW_UP");
		}
		let delivery: "prompt" | "steer" | "followUp" = "prompt";
		if (!wasIdle && command === "follow_up") delivery = "followUp";
		else if (!wasIdle) delivery = "steer";
		const item = rememberDelivery(requestId, command, delivery, content);
		emit("dispatch_requested", {
			request_id: requestId,
			command,
			message_sha256: item.message_sha256,
			was_idle: wasIdle,
		});
		scheduleDelivery(item, ctx.sessionManager.getSessionId(), wasIdle);
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
		const item = pending.find((candidate) => candidate.message_sha256 === digest && !candidate.aborted && !candidate.runtime_accepted);
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
		const item = pending.find((candidate) => candidate.message_sha256 === digest && !candidate.aborted && !candidate.message_consumed);
		if (!item) return;
		item.message_consumed = true;
		item.content = "";
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
		if (stopping) {
			emit("stop_abort_reasserted", { request_id: activeRequestId });
			ctx.abort();
		}
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
