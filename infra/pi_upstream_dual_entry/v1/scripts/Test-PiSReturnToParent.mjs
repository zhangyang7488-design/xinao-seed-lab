#!/usr/bin/env node

import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const sourceRoot = dirname(scriptDir);
const extensionPath = process.argv[3]
	? resolve(process.argv[3])
	: join(sourceRoot, "surface-overlays", "prime-s", "extensions", "return-to-parent.ts");
const piPackageRoot = process.argv[2]
	|| process.env.XINAO_PI_AGENT_PACKAGE_ROOT
	|| "D:\\XINAO_RESEARCH_RUNTIME\\tools\\pi\\prime\\0.84.1\\node_modules\\@earendil-works\\pi-coding-agent";
const jitiPath = join(piPackageRoot, "node_modules", "jiti", "lib", "jiti.mjs");
const agentCoreRoot = join(piPackageRoot, "node_modules", "@earendil-works", "pi-agent-core", "dist");
const piAiRoot = join(piPackageRoot, "node_modules", "@earendil-works", "pi-ai", "dist");
const piCodingAgentRoot = join(piPackageRoot, "dist");

const { createJiti } = await import(pathToFileURL(jitiPath).href);
const { runAgentLoop } = await import(pathToFileURL(join(agentCoreRoot, "agent-loop.js")).href);
const { createFauxCore, fauxAssistantMessage, fauxProvider, fauxToolCall } = await import(
	pathToFileURL(join(piAiRoot, "providers", "faux.js")).href
);
const {
	createAgentSession,
	DefaultResourceLoader,
	ModelRuntime,
	SessionManager,
	SettingsManager,
} = await import(pathToFileURL(join(piCodingAgentRoot, "index.js")).href);
const jiti = createJiti(import.meta.url, {
	alias: { typebox: join(piPackageRoot, "node_modules", "typebox", "build", "index.mjs") },
});
const loaded = await jiti.import(extensionPath);
const installExtension = loaded.default ?? loaded;

const originalFenceMarker = process.env.XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE;
delete process.env.XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE;
let missingFenceRegistered;
const missingFenceHandlers = [];
let missingFenceFollowUps = 0;
installExtension({
	on(event) { missingFenceHandlers.push(event); },
	registerTool(tool) { missingFenceRegistered = tool; },
	sendMessage() { missingFenceFollowUps += 1; },
});
assert.equal(missingFenceRegistered, undefined);
assert.deepEqual(missingFenceHandlers, []);
assert.equal(missingFenceFollowUps, 0);
process.env.XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE = "1";

let registered;
let sendUserMessageCalls = 0;
const rootHandlers = new Map();
const sentCustomMessages = [];
const originalChildMarker = process.env.PI_SUBAGENT_CHILD;
delete process.env.PI_SUBAGENT_CHILD;
installExtension({
	on(event, handler) {
		const list = rootHandlers.get(event) ?? [];
		list.push(handler);
		rootHandlers.set(event, list);
	},
	registerTool(tool) { registered = tool; },
	sendMessage(message, options) { sentCustomMessages.push({ message, options }); },
	sendUserMessage() { sendUserMessageCalls += 1; },
});

async function fireRoot(event, data, ctx) {
	const results = [];
	for (const handler of rootHandlers.get(event) ?? []) results.push(await handler(data, ctx));
	return results;
}

assert.equal(registered?.name, "return_to_parent");
assert.equal(registered.executionMode, "sequential");
assert.match(registered.description, /Root Pi only/);
assert.match(registered.promptSnippet, /local boundary/);
assert.equal(registered.promptGuidelines.length, 2);
assert.match(registered.promptGuidelines[1], /not a timer, daemon, task generator/);

let childRegistered;
process.env.PI_SUBAGENT_CHILD = "1";
installExtension({
	registerTool(tool) { childRegistered = tool; },
});
assert.equal(childRegistered, undefined);
if (originalChildMarker === undefined) delete process.env.PI_SUBAGENT_CHILD;
else process.env.PI_SUBAGENT_CHILD = originalChildMarker;

const args = {
	local_boundary: "  local evidence slice   settled ",
	surviving_parent: " parent reality remains   open ",
	next_contact: " contact the second unresolved consumer ",
};

function providerContextText(context) {
	return context.messages.flatMap((message) => {
		if (typeof message.content === "string") return [message.content];
		if (!Array.isArray(message.content)) return [];
		return message.content
			.filter((part) => part?.type === "text" && typeof part.text === "string")
			.map((part) => part.text);
	}).join("\n");
}

function taggedContinuationCount(context) {
	return providerContextText(context).split("ROOT_PARENT_CONTINUATION_ONE_SHOT").length - 1;
}
const directController = new AbortController();
const direct = await registered.execute("direct", args, directController.signal, undefined, {});
assert.equal(direct.details.schema, "xinao.pi_return_to_parent.v3");
assert.equal(direct.details.local_boundary, "local evidence slice settled");
assert.equal(direct.details.queued_message, false);
assert.equal(direct.details.automatic_wake, true);
assert.equal(direct.details.continuation_mode, "one_shot_agent_end_follow_up_abort_fenced");
assert.match(direct.content[0].text, /Continue this same root run/);
assert.equal(sendUserMessageCalls, 0);

await fireRoot(
	"agent_end",
	{ messages: [fauxAssistantMessage("FIRST_RUN_ALREADY_CONSUMED_NEXT_CONTACT", { stopReason: "stop" })] },
	{ signal: directController.signal },
);
assert.equal(sentCustomMessages.length, 1);
assert.deepEqual(sentCustomMessages[0].options, { deliverAs: "followUp", triggerTurn: true });
assert.match(sentCustomMessages[0].message.content, /may already have been consumed/i);
assert.match(sentCustomMessages[0].message.content, /Do not mechanically repeat/i);
assert.equal(sentCustomMessages[0].message.details.schema, "xinao.pi_return_to_parent_continuation.v2");
assert.equal(sentCustomMessages[0].message.details.abort_fenced, true);
assert.equal(sentCustomMessages[0].message.details.provider_context_visibility, "single_current_arm");
assert.match(sentCustomMessages[0].message.details.arm_id, /^[0-9a-f-]{36}$/i);
const directTaggedCustom = {
	role: "custom",
	...sentCustomMessages[0].message,
	timestamp: Date.now(),
};
const staleTaggedCustom = {
	...directTaggedCustom,
	details: { ...directTaggedCustom.details, arm_sequence: 999_999 },
};
const collidingSequenceTaggedCustom = {
	...directTaggedCustom,
	details: { ...directTaggedCustom.details, arm_id: "00000000-0000-4000-8000-000000000000" },
};
const directContinuationController = new AbortController();
await fireRoot("agent_start", {}, { signal: directContinuationController.signal });
const [firstContextFilter] = await fireRoot("context", {
	messages: [
		{ role: "user", content: [{ type: "text", text: "UNRELATED_VISIBLE_INPUT" }], timestamp: Date.now() },
		staleTaggedCustom,
		collidingSequenceTaggedCustom,
		directTaggedCustom,
	],
}, { signal: directContinuationController.signal });
assert.equal(firstContextFilter.messages.includes(directTaggedCustom), true);
assert.equal(firstContextFilter.messages.includes(staleTaggedCustom), false);
assert.equal(firstContextFilter.messages.includes(collidingSequenceTaggedCustom), false);
const [sameRunContextFilter] = await fireRoot(
	"context",
	{ messages: [directTaggedCustom] },
	{ signal: directContinuationController.signal },
);
assert.deepEqual(sameRunContextFilter.messages, [directTaggedCustom], "the current arm must survive every provider context in one continuation run");
await fireRoot(
	"agent_end",
	{ messages: [fauxAssistantMessage("SECOND_END_WITHOUT_REARM", { stopReason: "stop" })] },
	{ signal: directContinuationController.signal },
);
const futureController = new AbortController();
await fireRoot("agent_start", {}, { signal: futureController.signal });
const [futureContextFilter] = await fireRoot("context", { messages: [directTaggedCustom] }, { signal: futureController.signal });
assert.deepEqual(futureContextFilter.messages, [], "agent_end must spend the grant before a future run");
assert.equal(sentCustomMessages.length, 1, "one arm must be consumed exactly once");

await assert.rejects(
	registered.execute("blank-after-clean", { ...args, local_boundary: "   " }, new AbortController().signal, undefined, {}),
	(error) => error?.message === "RETURN_TO_PARENT_FIELDS_REQUIRED_AFTER_NORMALIZATION",
);

const aborted = new AbortController();
aborted.abort();
await assert.rejects(
	registered.execute("aborted", args, aborted.signal, undefined, {}),
	(error) => error?.name === "AbortError" && error?.message === "RETURN_TO_PARENT_ABORTED",
);

function userMessage(text) {
	return { role: "user", content: [{ type: "text", text }], timestamp: Date.now() };
}

function loopTool() {
	return {
		name: registered.name,
		label: registered.label,
		description: registered.description,
		parameters: registered.parameters,
		executionMode: registered.executionMode,
		execute: (id, params, signal, onUpdate) => registered.execute(id, params, signal, onUpdate, {}),
	};
}

async function runScripted(responses, options = {}) {
	const faux = createFauxCore({ provider: `return-parent-${Math.random().toString(16).slice(2)}` });
	faux.setResponses(responses);
	const events = [];
	const messages = await runAgentLoop(
		[userMessage("changed-surface parent case")],
		{ systemPrompt: "test", messages: [], tools: [loopTool()] },
		{
			model: faux.getModel(),
			convertToLlm: (items) => items,
			shouldStopAfterTurn: options.shouldStopAfterTurn,
		},
		async (event) => {
			events.push(event);
			await options.onEvent?.(event);
		},
		options.signal,
		faux.streamSimple,
	);
	return { faux, events, messages };
}

const positive = await runScripted([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-1" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("PARENT_FRONTIER_CONTINUED", { stopReason: "stop" }),
]);
assert.equal(positive.faux.state.callCount, 2);
assert.equal(positive.events.filter((event) => event.type === "tool_execution_start").length, 1);
assert.equal(positive.events.filter((event) => event.type === "turn_start").length, 2);
assert.equal(positive.events.filter((event) => event.type === "agent_end").length, 1);
assert.ok(positive.messages.some((message) => message.role === "toolResult"));
assert.ok(positive.messages.some((message) =>
	message.role === "assistant"
	&& message.content.some((part) => part.type === "text" && part.text === "PARENT_FRONTIER_CONTINUED")
));

const negative = await runScripted([
	fauxAssistantMessage("WHOLE_PARENT_HAS_NO_POSITIVE_FRONTIER", { stopReason: "stop" }),
]);
assert.equal(negative.faux.state.callCount, 1);
assert.equal(negative.events.filter((event) => event.type === "tool_execution_start").length, 0);
assert.equal(negative.events.filter((event) => event.type === "turn_start").length, 1);
assert.equal(negative.events.filter((event) => event.type === "agent_end").length, 1);

const boundaryAbortController = new AbortController();
const boundaryAbort = await runScripted([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-abort-boundary" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("MUST_NOT_BE_CONSUMED_AFTER_ABORT", { stopReason: "stop" }),
], {
	signal: boundaryAbortController.signal,
	onEvent(event) {
		if (event.type === "turn_end" && event.toolResults?.length > 0) boundaryAbortController.abort();
	},
	shouldStopAfterTurn: () => boundaryAbortController.signal.aborted,
});
assert.equal(boundaryAbort.faux.state.callCount, 1);
assert.equal(boundaryAbort.events.filter((event) => event.type === "turn_start").length, 1);
assert.equal(boundaryAbort.events.filter((event) => event.type === "agent_end").length, 1);
assert.ok(!boundaryAbort.messages.some((message) =>
	message.role === "assistant"
	&& message.content.some((part) => part.type === "text" && part.text === "MUST_NOT_BE_CONSUMED_AFTER_ABORT")
));

async function runNativeSession(responses, options = {}) {
	const faux = fauxProvider();
	const modelRuntime = await ModelRuntime.create({ modelsPath: null, refreshOnCreate: false });
	modelRuntime.registerNativeProvider(faux.provider);
	const resourceLoader = new DefaultResourceLoader({
		cwd: sourceRoot,
		agentDir: join(sourceRoot, ".return-to-parent-test-agent"),
		extensionFactories: [
			...(options.extensionFactoriesBefore ?? []),
			installExtension,
			...(options.extensionFactoriesAfter ?? []),
		],
	});
	await resourceLoader.reload();
	const settingsManager = SettingsManager.inMemory({
		compaction: { enabled: false },
		retry: { enabled: false, maxRetries: 0 },
	});
	const { session } = await createAgentSession({
		cwd: sourceRoot,
		agentDir: join(sourceRoot, ".return-to-parent-test-agent"),
		model: faux.getModel(),
		thinkingLevel: "off",
		modelRuntime,
		resourceLoader,
		sessionManager: options.sessionManager ?? SessionManager.inMemory(sourceRoot),
		settingsManager,
		tools: ["return_to_parent"],
	});
	const events = [];
	const providerContexts = [];
	session.subscribe((event) => events.push(event));
	await session.bindExtensions({
		mode: options.mode ?? "print",
		abortHandler: options.abortHandler ? () => options.abortHandler({ session, faux }) : undefined,
		shutdownHandler: options.shutdownHandler ? () => options.shutdownHandler({ session, faux }) : () => {},
	});
	try {
		const resolvedResponses = typeof responses === "function"
			? await responses({ session, faux })
			: responses;
		faux.setResponses(resolvedResponses.map((step) => async (context, streamOptions, state, model) => {
			providerContexts.push({ messages: structuredClone(context.messages) });
			return typeof step === "function" ? await step(context, streamOptions, state, model) : step;
		}));
		await options.beforePrompt?.({ session, faux });
		await session.prompt("ROOT_PARENT_NATIVE_CONTINUATION_CASE");
		await session.waitForIdle();
		await options.afterFirstIdle?.({ session, faux, providerContexts });
		await session.waitForIdle();
		return {
			faux,
			events,
			providerContexts,
			messages: structuredClone(session.state.messages),
			hasQueuedMessages: session.agent.hasQueuedMessages(),
			pendingScriptedResponses: faux.getPendingResponseCount(),
		};
	} finally {
		session.dispose();
	}
}

const nativeAcceptanceSessionDir = process.env.XINAO_RETURN_TO_PARENT_ACCEPTANCE_SESSION_DIR;
const nativeContinuation = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-native-1" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("FIRST_RUN_ALREADY_CONTACTED_ARMED_FRONTIER", { stopReason: "stop" }),
	(context) => {
		const continuationText = context.messages
			.filter((message) => message.role === "user")
			.flatMap((message) => message.content)
			.filter((part) => part.type === "text")
			.map((part) => part.text)
			.join("\n");
		assert.match(continuationText, /may already have been consumed/i);
		assert.match(continuationText, /do not mechanically repeat/i);
		return fauxAssistantMessage("SECOND_PROVIDER_RECOMPUTED_SURVIVING_PARENT", { stopReason: "stop" });
	},
], nativeAcceptanceSessionDir
	? { sessionManager: SessionManager.create(sourceRoot, nativeAcceptanceSessionDir) }
	: {});
assert.equal(nativeContinuation.faux.state.callCount, 3, "one armed local boundary must produce one native follow-up provider turn");
assert.equal(nativeContinuation.events.filter((event) => event.type === "agent_settled").length, 1);
assert.equal(nativeContinuation.messages.filter((message) => message.role === "custom").length, 1);
assert.equal(nativeContinuation.hasQueuedMessages, false);
assert.deepEqual(nativeContinuation.providerContexts.map(taggedContinuationCount), [0, 0, 1]);
assert.ok(nativeContinuation.messages.some((message) =>
	message.role === "assistant"
	&& message.content.some((part) => part.type === "text" && part.text === "SECOND_PROVIDER_RECOMPUTED_SURVIVING_PARENT")
));

const multiProviderSignals = [];
const captureMultiProviderSignals = (pi) => {
	pi.on("context", (_event, ctx) => {
		multiProviderSignals.push(ctx.signal);
	});
};
const rearmArgs = {
	local_boundary: "continuation run tool boundary",
	surviving_parent: "same parent survives the continuation run",
	next_contact: "contact after the continuation run tool result",
};
const multiProviderContinuation = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-multi-provider-source" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("SOURCE_RUN_FINAL_BEFORE_MULTI_PROVIDER_CONTINUATION", { stopReason: "stop" }),
	fauxAssistantMessage(
		fauxToolCall("return_to_parent", rearmArgs, { id: "return-parent-inside-continuation-run" }),
		{ stopReason: "toolUse" },
	),
	fauxAssistantMessage("CONTINUATION_RUN_FINAL_AFTER_TOOL_RESULT", { stopReason: "stop" }),
	fauxAssistantMessage("REARMED_NEXT_CONTINUATION_RUN_FINAL", { stopReason: "stop" }),
], { extensionFactoriesAfter: [captureMultiProviderSignals] });
assert.equal(multiProviderContinuation.faux.state.callCount, 5);
assert.deepEqual(multiProviderContinuation.providerContexts.map(taggedContinuationCount), [0, 0, 1, 1, 1]);
assert.equal(multiProviderSignals[2], multiProviderSignals[3], "provider turns within one continuation agent run must share its bound signal");
assert.notEqual(multiProviderSignals[3], multiProviderSignals[4], "a rearmed continuation must bind a fresh agent-run signal");
assert.equal(multiProviderContinuation.hasQueuedMessages, false);

let stopDuringContinuationExecutions = 0;
const stopDuringContinuationProvider = (pi) => {
	pi.on("tool_execution_end", (event, ctx) => {
		if (event.toolName !== "return_to_parent") return;
		stopDuringContinuationExecutions += 1;
		if (stopDuringContinuationExecutions === 2) ctx.abort();
	});
};
let providerCallsAtContinuationStop;
const stoppedDuringContinuation = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-before-continuation-stop" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("SOURCE_FINAL_BEFORE_CONTINUATION_STOP", { stopReason: "stop" }),
	fauxAssistantMessage(
		fauxToolCall("return_to_parent", rearmArgs, { id: "return-parent-trigger-continuation-stop" }),
		{ stopReason: "toolUse" },
	),
	fauxAssistantMessage("POST_STOP_EXPLICIT_NEW_PROMPT", { stopReason: "stop" }),
], {
	extensionFactoriesAfter: [stopDuringContinuationProvider],
	async afterFirstIdle({ session, faux }) {
		providerCallsAtContinuationStop = faux.state.callCount;
		assert.equal(providerCallsAtContinuationStop, 3, "Stop during continuation must suppress the provider after its tool result");
		await session.prompt("EXPLICIT_NEW_PROMPT_AFTER_CONTINUATION_STOP");
	},
});
assert.equal(stoppedDuringContinuation.faux.state.callCount, 4);
assert.equal(providerCallsAtContinuationStop, 3);
assert.deepEqual(stoppedDuringContinuation.providerContexts.map(taggedContinuationCount), [0, 0, 1, 0]);
assert.equal(stoppedDuringContinuation.hasQueuedMessages, false);

const noArmNative = await runNativeSession([
	fauxAssistantMessage("WHOLE_PARENT_REALLY_SETTLED_WITHOUT_ARM", { stopReason: "stop" }),
]);
assert.equal(noArmNative.faux.state.callCount, 1);
assert.equal(noArmNative.messages.filter((message) => message.role === "custom").length, 0);
assert.equal(noArmNative.hasQueuedMessages, false);

const abortAtAgentStart = (pi) => {
	let aborted = false;
	pi.on("agent_start", (_event, ctx) => {
		if (aborted) return;
		aborted = true;
		ctx.abort();
		ctx.abort();
	});
};
const agentStartFencedNative = await runNativeSession([
	fauxAssistantMessage("MUST_NOT_REACH_PROVIDER_AFTER_AGENT_START_ABORT", { stopReason: "stop" }),
], { extensionFactoriesBefore: [abortAtAgentStart] });
assert.equal(agentStartFencedNative.faux.state.callCount, 0);
assert.equal(agentStartFencedNative.pendingScriptedResponses, 1);
assert.equal(agentStartFencedNative.providerContexts.length, 0);

const abortDuringAsyncContextTransform = (pi) => {
	let aborted = false;
	pi.on("context", async (event, ctx) => {
		if (aborted) return;
		aborted = true;
		await Promise.resolve();
		ctx.abort();
		return { messages: event.messages };
	});
};
const preProviderFencedNative = await runNativeSession([
	fauxAssistantMessage("MUST_NOT_REACH_PROVIDER_AFTER_ASYNC_TRANSFORM_ABORT", { stopReason: "stop" }),
], { extensionFactoriesBefore: [abortDuringAsyncContextTransform] });
assert.equal(preProviderFencedNative.faux.state.callCount, 0);
assert.equal(preProviderFencedNative.pendingScriptedResponses, 1);
assert.equal(preProviderFencedNative.providerContexts.length, 0);

const authResolutionFencedNative = await runNativeSession([
	fauxAssistantMessage("MUST_NOT_REACH_PROVIDER_AFTER_ASYNC_AUTH_ABORT", { stopReason: "stop" }),
], {
	beforePrompt({ session }) {
		const originalGetApiKey = session.agent.getApiKey;
		session.agent.getApiKey = async (provider) => {
			const resolved = await originalGetApiKey?.(provider);
			session.agent.abort();
			return resolved;
		};
	},
});
assert.equal(authResolutionFencedNative.faux.state.callCount, 0);
assert.equal(authResolutionFencedNative.pendingScriptedResponses, 1);
assert.equal(authResolutionFencedNative.providerContexts.length, 0);

const unrelatedPromptAfterContinuation = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-before-unrelated-prompt" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("FIRST_RUN_BEFORE_UNRELATED_PROMPT", { stopReason: "stop" }),
	fauxAssistantMessage("ONE_SHOT_CONTINUATION_BEFORE_UNRELATED_PROMPT", { stopReason: "stop" }),
	fauxAssistantMessage("UNRELATED_PROMPT_FINISHED", { stopReason: "stop" }),
], {
	async afterFirstIdle({ session }) {
		await session.prompt("UNRELATED_FUTURE_PROMPT");
	},
});
assert.equal(unrelatedPromptAfterContinuation.faux.state.callCount, 4);
assert.deepEqual(unrelatedPromptAfterContinuation.providerContexts.map(taggedContinuationCount), [0, 0, 1, 0]);
assert.match(providerContextText(unrelatedPromptAfterContinuation.providerContexts[3]), /UNRELATED_FUTURE_PROMPT/);

const resumeSessionManager = SessionManager.inMemory(sourceRoot);
const preResumeContinuation = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-before-resume" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("FIRST_RUN_BEFORE_RESUME", { stopReason: "stop" }),
	fauxAssistantMessage("CONTINUATION_BEFORE_RESUME", { stopReason: "stop" }),
], { sessionManager: resumeSessionManager });
assert.deepEqual(preResumeContinuation.providerContexts.map(taggedContinuationCount), [0, 0, 1]);
const resumedSession = await runNativeSession([
	fauxAssistantMessage("RESUMED_UNRELATED_PROMPT_FINISHED", { stopReason: "stop" }),
], { sessionManager: resumeSessionManager });
assert.equal(resumedSession.faux.state.callCount, 1);
assert.deepEqual(resumedSession.providerContexts.map(taggedContinuationCount), [0]);
assert.equal(resumedSession.messages.filter((message) =>
	message.role === "custom" && message.customType === "xinao-return-to-parent-continuation"
).length, 1, "historical receipt may remain in the transcript but must be filtered from resumed provider context");
const resumedRearmArgs = {
	local_boundary: "resumed process local boundary",
	surviving_parent: "resumed process surviving parent",
	next_contact: "resumed newest concrete contact",
};
const resumedRearmedSession = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", resumedRearmArgs, { id: "return-parent-after-resume-sequence-collision" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("FIRST_RUN_AFTER_RESUMED_REARM", { stopReason: "stop" }),
	fauxAssistantMessage("CONTINUATION_AFTER_RESUMED_REARM", { stopReason: "stop" }),
], { sessionManager: resumeSessionManager });
assert.deepEqual(resumedRearmedSession.providerContexts.map(taggedContinuationCount), [0, 0, 1]);
const resumedRearmedContextText = providerContextText(resumedRearmedSession.providerContexts[2]);
assert.match(resumedRearmedContextText, /resumed newest concrete contact/);
assert.doesNotMatch(resumedRearmedContextText, /Armed first contact: contact the second unresolved consumer/);

const secondArgs = {
	local_boundary: "later local boundary",
	surviving_parent: "same surviving parent with newer effects",
	next_contact: "newest concrete contact",
};
const repeatedArmNative = await runNativeSession([
	fauxAssistantMessage([
		fauxToolCall("return_to_parent", args, { id: "return-parent-repeat-1" }),
		fauxToolCall("return_to_parent", secondArgs, { id: "return-parent-repeat-2" }),
	], { stopReason: "toolUse" }),
	fauxAssistantMessage("BOTH_LOCAL_CALLS_CONSUMED_IN_FIRST_RUN", { stopReason: "stop" }),
	fauxAssistantMessage("ONE_FOLLOW_UP_ONLY", { stopReason: "stop" }),
]);
const repeatedCustom = repeatedArmNative.messages.filter((message) => message.role === "custom");
assert.equal(repeatedArmNative.faux.state.callCount, 3);
assert.equal(repeatedCustom.length, 1, "multiple calls in one root run must still arm only one follow-up");
assert.equal(repeatedCustom[0].details.armed_first_contact, secondArgs.next_contact);
assert.equal(repeatedArmNative.hasQueuedMessages, false);

const queueOrdinaryFollowUp = (pi) => {
	let queued = false;
	pi.on("agent_end", () => {
		if (queued) return;
		queued = true;
		pi.sendMessage({
			customType: "ordinary-noncontinuation-follow-up",
			content: "ORDINARY_NONCONTINUATION_FOLLOW_UP",
			display: true,
			details: { ordinary: true },
		}, { deliverAs: "followUp", triggerTurn: true });
	});
};
const ordinaryFollowUpNative = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-with-ordinary-follow-up" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("FIRST_RUN_WITH_TWO_DIFFERENT_FOLLOW_UPS", { stopReason: "stop" }),
	fauxAssistantMessage("RETURN_CONTINUATION_PROVIDER_FINISHED", { stopReason: "stop" }),
	fauxAssistantMessage("ORDINARY_FOLLOW_UP_PROVIDER_FINISHED", { stopReason: "stop" }),
], { extensionFactoriesAfter: [queueOrdinaryFollowUp] });
assert.equal(ordinaryFollowUpNative.faux.state.callCount, 4);
assert.deepEqual(ordinaryFollowUpNative.providerContexts.map(taggedContinuationCount), [0, 0, 1, 1]);
assert.equal(ordinaryFollowUpNative.providerContexts.filter((context) =>
	providerContextText(context).includes("ORDINARY_NONCONTINUATION_FOLLOW_UP")
).length, 1, "return_to_parent filtering must not remove an ordinary follow-up");
assert.equal(ordinaryFollowUpNative.messages.filter((message) =>
	message.role === "custom" && message.customType === "ordinary-noncontinuation-follow-up"
).length, 1);
assert.equal(ordinaryFollowUpNative.hasQueuedMessages, false);

const ordinaryFollowUpBeforeReturnNative = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "ordinary-follow-up-before-return-parent" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("FIRST_RUN_WITH_ORDINARY_QUEUE_FIRST", { stopReason: "stop" }),
	fauxAssistantMessage("ORDINARY_QUEUE_FIRST_PROVIDER_FINISHED", { stopReason: "stop" }),
	fauxAssistantMessage("RETURN_QUEUE_SECOND_PROVIDER_FINISHED", { stopReason: "stop" }),
], { extensionFactoriesBefore: [queueOrdinaryFollowUp] });
assert.equal(ordinaryFollowUpBeforeReturnNative.faux.state.callCount, 4);
assert.deepEqual(ordinaryFollowUpBeforeReturnNative.providerContexts.map(taggedContinuationCount), [0, 0, 0, 1]);
assert.match(providerContextText(ordinaryFollowUpBeforeReturnNative.providerContexts[2]), /ORDINARY_NONCONTINUATION_FOLLOW_UP/);
assert.match(providerContextText(ordinaryFollowUpBeforeReturnNative.providerContexts[3]), /ORDINARY_NONCONTINUATION_FOLLOW_UP/);
assert.equal(ordinaryFollowUpBeforeReturnNative.hasQueuedMessages, false);

const abortedNative = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-native-abort" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("ABORTED_AFTER_TOOL_RESULT", { stopReason: "aborted" }),
	fauxAssistantMessage("MUST_REMAIN_UNCONSUMED_AFTER_ABORT", { stopReason: "stop" }),
]);
assert.equal(abortedNative.faux.state.callCount, 2);
assert.equal(abortedNative.pendingScriptedResponses, 1);
assert.equal(abortedNative.messages.filter((message) => message.role === "custom").length, 0);
assert.equal(abortedNative.hasQueuedMessages, false);

const errorNative = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-native-error" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("ERROR_AFTER_TOOL_RESULT", { stopReason: "error", errorMessage: "SCRIPTED_PROVIDER_ERROR" }),
	fauxAssistantMessage("MUST_REMAIN_UNCONSUMED_AFTER_ERROR", { stopReason: "stop" }),
]);
assert.equal(errorNative.faux.state.callCount, 2);
assert.equal(errorNative.pendingScriptedResponses, 1);
assert.equal(errorNative.messages.filter((message) => message.role === "custom").length, 0);
assert.equal(errorNative.hasQueuedMessages, false);

const lengthNative = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-native-length" }), { stopReason: "toolUse" }),
	Object.assign(
		fauxAssistantMessage("MAX_TOKENS_AFTER_TOOL_RESULT", { stopReason: "length" }),
		{ rawStopReason: "max_tokens" },
	),
	fauxAssistantMessage("MUST_REMAIN_UNCONSUMED_AFTER_LENGTH", { stopReason: "stop" }),
]);
assert.equal(lengthNative.faux.state.callCount, 2);
assert.equal(lengthNative.pendingScriptedResponses, 1);
assert.equal(lengthNative.messages.filter((message) => message.role === "custom").length, 0);
assert.equal(lengthNative.hasQueuedMessages, false);

const stopAtAgentEnd = (pi) => {
	pi.on("agent_end", (_event, ctx) => ctx.abort());
};
const stoppedNative = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-native-stop" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("CLEAN_FINAL_BUT_OWNER_STOP_IS_ACTIVE", { stopReason: "stop" }),
	fauxAssistantMessage("MUST_REMAIN_UNCONSUMED_AFTER_STOP", { stopReason: "stop" }),
], { extensionFactoriesBefore: [stopAtAgentEnd] });
assert.equal(stoppedNative.faux.state.callCount, 2);
assert.equal(stoppedNative.pendingScriptedResponses, 1);
assert.equal(stoppedNative.messages.filter((message) => message.role === "custom").length, 0);
assert.equal(stoppedNative.hasQueuedMessages, false);

// Reproduce the dangerous ordering: return_to_parent's agent_end handler queues
// its custom follow-up first, then a later supervisor/owner Stop aborts the
// completed run before AgentSession performs its post-run queue check.
const stopAfterContinuationEnqueue = (pi) => {
	pi.on("agent_end", (_event, ctx) => {
		ctx.abort();
		ctx.abort(); // Stop is idempotent.
	});
};
const stoppedAfterEnqueueNative = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-native-post-enqueue-stop" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("CLEAN_FINAL_BEFORE_POST_ENQUEUE_STOP", { stopReason: "stop" }),
	fauxAssistantMessage("MUST_NOT_RUN_AFTER_POST_ENQUEUE_STOP", { stopReason: "stop" }),
], { extensionFactoriesAfter: [stopAfterContinuationEnqueue] });
assert.equal(stoppedAfterEnqueueNative.faux.state.callCount, 2, "Stop after continuation enqueue must add zero provider calls");
assert.equal(stoppedAfterEnqueueNative.pendingScriptedResponses, 1);
assert.equal(stoppedAfterEnqueueNative.messages.filter((message) =>
	message.role === "custom" && message.customType === "xinao-return-to-parent-continuation"
).length, 0, "cancelled tagged continuation must not persist in session context");
assert.equal(stoppedAfterEnqueueNative.hasQueuedMessages, false);
assert.deepEqual(stoppedAfterEnqueueNative.providerContexts.map(taggedContinuationCount), [0, 0]);

const postStopSessionManager = SessionManager.inMemory(sourceRoot);
const postStopNewPromptNative = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-post-stop-new-prompt" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("CLEAN_FINAL_BEFORE_STOP_AND_NEW_PROMPT", { stopReason: "stop" }),
	fauxAssistantMessage("POST_STOP_NEW_PROMPT_FINISHED", { stopReason: "stop" }),
], {
	extensionFactoriesAfter: [stopAfterContinuationEnqueue],
	sessionManager: postStopSessionManager,
	async afterFirstIdle({ session, faux, providerContexts }) {
		assert.equal(faux.state.callCount, 2, "Stop must add zero provider calls before a later explicit prompt");
		assert.deepEqual(providerContexts.map(taggedContinuationCount), [0, 0]);
		await session.prompt("POST_STOP_EXPLICIT_NEW_PROMPT");
	},
});
assert.equal(postStopNewPromptNative.faux.state.callCount, 3);
assert.deepEqual(postStopNewPromptNative.providerContexts.map(taggedContinuationCount), [0, 0, 0]);
assert.equal(postStopNewPromptNative.messages.filter((message) =>
	message.role === "custom" && message.customType === "xinao-return-to-parent-continuation"
).length, 0);
const resumedAfterStopNative = await runNativeSession([
	fauxAssistantMessage("RESUMED_AFTER_STOP_FINISHED", { stopReason: "stop" }),
], { sessionManager: postStopSessionManager });
assert.deepEqual(resumedAfterStopNative.providerContexts.map(taggedContinuationCount), [0]);

const tuiStoppedAfterEnqueueNative = await runNativeSession([
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-native-tui-post-enqueue-stop" }), { stopReason: "toolUse" }),
	fauxAssistantMessage("CLEAN_FINAL_BEFORE_TUI_POST_ENQUEUE_STOP", { stopReason: "stop" }),
	fauxAssistantMessage("MUST_NOT_RUN_AFTER_TUI_POST_ENQUEUE_STOP", { stopReason: "stop" }),
], {
	mode: "tui",
	extensionFactoriesAfter: [stopAfterContinuationEnqueue],
	abortHandler({ session }) {
		// The real interactive consumer's restoreQueuedMessagesToEditor({abort:true})
		// clears Session/Agent queues synchronously, then aborts the active run.
		session.clearQueue();
		session.agent.abort();
	},
});
assert.equal(tuiStoppedAfterEnqueueNative.faux.state.callCount, 2);
assert.equal(tuiStoppedAfterEnqueueNative.pendingScriptedResponses, 1);
assert.equal(tuiStoppedAfterEnqueueNative.messages.filter((message) =>
	message.role === "custom" && message.customType === "xinao-return-to-parent-continuation"
).length, 0);
assert.equal(tuiStoppedAfterEnqueueNative.hasQueuedMessages, false);
assert.deepEqual(tuiStoppedAfterEnqueueNative.providerContexts.map(taggedContinuationCount), [0, 0]);

const shutdownNative = await runNativeSession(async ({ session }) => [
	fauxAssistantMessage(fauxToolCall("return_to_parent", args, { id: "return-parent-native-shutdown" }), { stopReason: "toolUse" }),
	async () => {
		await session.extensionRunner.emit({ type: "session_shutdown", reason: "quit" });
		return fauxAssistantMessage("FINAL_AFTER_SESSION_SHUTDOWN", { stopReason: "stop" });
	},
	fauxAssistantMessage("MUST_REMAIN_UNCONSUMED_AFTER_SHUTDOWN", { stopReason: "stop" }),
]);
assert.equal(shutdownNative.faux.state.callCount, 2);
assert.equal(shutdownNative.pendingScriptedResponses, 1);
assert.equal(shutdownNative.messages.filter((message) => message.role === "custom").length, 0);
assert.equal(shutdownNative.hasQueuedMessages, false);

const parserFixtureDirs = [];
const liveParserPath = join(scriptDir, "Test-PiSReturnToParentLive.mjs");
const parserBaseRecords = [
	{
		type: "session",
		id: "parser-session",
		version: 3,
		timestamp: "2026-08-09T12:00:00.000Z",
		cwd: sourceRoot,
	},
	{
		type: "message",
		id: "parser-call-record",
		parentId: null,
		timestamp: "2026-08-09T12:00:00.001Z",
		message: {
			role: "assistant",
			provider: "faux",
			model: "faux-1",
			stopReason: "toolUse",
			content: [{
				type: "toolCall",
				id: "parser-return-call",
				name: "return_to_parent",
				arguments: {
					local_boundary: "  parser   local boundary ",
					surviving_parent: " parser parent   survives ",
					next_contact: " parser   next contact ",
				},
			}],
		},
	},
	{
		type: "message",
		id: "parser-tool-result",
		parentId: "parser-call-record",
		timestamp: "2026-08-09T12:00:00.002Z",
		message: {
			role: "toolResult",
			toolCallId: "parser-return-call",
			toolName: "return_to_parent",
			content: [{ type: "text", text: "LOCAL_BOUNDARY_ONLY" }],
			details: {
				schema: "xinao.pi_return_to_parent.v3",
				local_boundary: "parser local boundary",
				surviving_parent: "parser parent survives",
				next_contact: "parser next contact",
			},
		},
	},
	{
		type: "message",
		id: "parser-first-final",
		parentId: "parser-tool-result",
		timestamp: "2026-08-09T12:00:00.003Z",
		message: {
			role: "assistant",
			provider: "faux",
			model: "faux-1",
			stopReason: "stop",
			content: [{ type: "text", text: "PARSER_FIRST_FINAL" }],
		},
	},
	{
		type: "custom_message",
		id: "parser-arm",
		parentId: "parser-first-final",
		timestamp: "2026-08-09T12:00:00.004Z",
		customType: "xinao-return-to-parent-continuation",
		content: "ROOT_PARENT_CONTINUATION_ONE_SHOT\nIt may already have been consumed. Do not mechanically repeat.",
		details: {
			schema: "xinao.pi_return_to_parent_continuation.v2",
			arm_id: "11111111-1111-4111-8111-111111111111",
			arm_sequence: 1,
			local_boundary: "parser local boundary",
			surviving_parent: "parser parent survives",
			armed_first_contact: "parser next contact",
			one_shot: true,
			next_contact_may_already_be_consumed: true,
			abort_fenced: true,
			provider_context_visibility: "single_current_arm",
		},
	},
	{
		type: "message",
		id: "parser-continuation",
		parentId: "parser-arm",
		timestamp: "2026-08-09T12:00:00.005Z",
		message: {
			role: "assistant",
			provider: "faux",
			model: "faux-1",
			stopReason: "stop",
			content: [{ type: "text", text: "PARSER_CONTINUATION" }],
		},
	},
];
function runLiveParserFixture(records) {
	const fixtureDir = mkdtempSync(join(tmpdir(), "xinao-return-parser-"));
	parserFixtureDirs.push(fixtureDir);
	writeFileSync(
		join(fixtureDir, "session.jsonl"),
		records.map((record) => JSON.stringify(record)).join("\n") + "\n",
		"utf8",
	);
	return spawnSync(process.execPath, [liveParserPath, fixtureDir, "faux", "faux-1"], {
		encoding: "utf8",
		windowsHide: true,
	});
}
try {
	const parserPositive = runLiveParserFixture(structuredClone(parserBaseRecords));
	assert.equal(parserPositive.status, 0, parserPositive.stderr);
	const parserPositiveAcceptance = JSON.parse(parserPositive.stdout);
	assert.equal(parserPositiveAcceptance.normalized_argument_binding, true);
	assert.equal(parserPositiveAcceptance.matching_tool_result_unique, true);
	assert.equal(parserPositiveAcceptance.matching_arm_first_and_unique, true);

	const resultMismatchRecords = structuredClone(parserBaseRecords);
	resultMismatchRecords.find((record) => record.id === "parser-tool-result").message.details.next_contact = "wrong contact";
	const parserResultMismatch = runLiveParserFixture(resultMismatchRecords);
	assert.notEqual(parserResultMismatch.status, 0, "toolResult details not equal to normalized call args must be rejected");

	const armMismatchRecords = structuredClone(parserBaseRecords);
	armMismatchRecords.find((record) => record.id === "parser-arm").details.armed_first_contact = "wrong contact";
	const parserArmMismatch = runLiveParserFixture(armMismatchRecords);
	assert.notEqual(parserArmMismatch.status, 0, "arm details not equal to normalized call args must be rejected");

	const ambiguousResultRecords = structuredClone(parserBaseRecords);
	const duplicateResult = structuredClone(ambiguousResultRecords.find((record) => record.id === "parser-tool-result"));
	duplicateResult.id = "parser-tool-result-duplicate";
	ambiguousResultRecords.push(duplicateResult);
	const parserAmbiguousResult = runLiveParserFixture(ambiguousResultRecords);
	assert.notEqual(parserAmbiguousResult.status, 0);
	assert.match(parserAmbiguousResult.stderr, /RETURN_TO_PARENT_LIVE_TOOL_RESULT_AMBIGUOUS/);

	const ambiguousArmRecords = structuredClone(parserBaseRecords);
	const duplicateArm = structuredClone(ambiguousArmRecords.find((record) => record.id === "parser-arm"));
	duplicateArm.id = "parser-arm-duplicate";
	duplicateArm.timestamp = "2026-08-09T12:00:00.0045Z";
	ambiguousArmRecords.push(duplicateArm);
	const parserAmbiguousArm = runLiveParserFixture(ambiguousArmRecords);
	assert.notEqual(parserAmbiguousArm.status, 0);
	assert.match(parserAmbiguousArm.stderr, /RETURN_TO_PARENT_LIVE_ARM_AMBIGUOUS/);

	const nonFirstArmRecords = structuredClone(parserBaseRecords);
	const wrongFirstArm = structuredClone(nonFirstArmRecords.find((record) => record.id === "parser-arm"));
	wrongFirstArm.id = "parser-wrong-first-arm";
	wrongFirstArm.details.arm_id = "22222222-2222-4222-8222-222222222222";
	wrongFirstArm.details.armed_first_contact = "another contact";
	const matchingArmIndex = nonFirstArmRecords.findIndex((record) => record.id === "parser-arm");
	nonFirstArmRecords.splice(matchingArmIndex, 0, wrongFirstArm);
	const parserNonFirstArm = runLiveParserFixture(nonFirstArmRecords);
	assert.notEqual(parserNonFirstArm.status, 0);
	assert.match(parserNonFirstArm.stderr, /RETURN_TO_PARENT_LIVE_ARM_NOT_FIRST/);
} finally {
	for (const fixtureDir of parserFixtureDirs) rmSync(fixtureDir, { recursive: true, force: true });
}

if (originalFenceMarker === undefined) delete process.env.XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE;
else process.env.XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE = originalFenceMarker;

process.stdout.write(`${JSON.stringify({
	schema: "xinao.pi_return_to_parent.acceptance.v3",
	status: "mechanically_verified",
	behavior_selection_status: "pending_live_sol",
	root_only_registration: true,
	abort_fence_runtime_handshake_required: true,
	missing_handshake_inert: true,
	normalized_empty_rejected: true,
	same_run_continuation_after_local_boundary: true,
	scripted_no_action_path_does_not_auto_continue: true,
	pre_execute_abort_rejected: true,
	turn_boundary_abort_prevents_next_provider: true,
	queued_user_messages: 0,
	automatic_wake: true,
	native_one_shot_follow_up: true,
	next_contact_may_already_be_consumed: true,
	repeated_calls_single_follow_up: true,
	abort_error_stop_shutdown_suppress_follow_up: true,
	strict_clean_stop_reason_allowlist: true,
	post_enqueue_stop_provider_delta: 0,
	tui_and_print_abort_paths_fenced: true,
	agent_start_abort_fence: true,
	pre_provider_abort_fence: true,
	async_auth_abort_fence: true,
	continuation_run_signal_lifecycle_bound: true,
	tagged_context_same_continuation_run_all_providers: true,
	tagged_context_single_current_arm_per_provider: true,
	tagged_context_future_prompt_zero: true,
	tagged_context_resume_zero: true,
	arm_id_prevents_resume_sequence_collision: true,
	ordinary_follow_up_preserved: true,
	stop_during_continuation_provider_delta: 0,
	live_parser_normalized_argument_binding: true,
	live_parser_matching_tool_result_unique: true,
	live_parser_matching_arm_first_and_unique: true,
	live_parser_ambiguity_rejected: true,
	no_residual_continuation_queue: true,
	provider_calls_positive: positive.faux.state.callCount,
	provider_calls_negative: negative.faux.state.callCount,
	provider_calls_native_continuation: nativeContinuation.faux.state.callCount,
	provider_calls_multi_provider_continuation: multiProviderContinuation.faux.state.callCount,
})}\n`);
