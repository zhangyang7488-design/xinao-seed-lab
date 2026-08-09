#!/usr/bin/env node

import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const sourceRoot = dirname(scriptDir);
const extensionPath = join(sourceRoot, "surface-overlays", "prime-s", "extensions", "return-to-parent.ts");
const piPackageRoot = process.argv[2]
	|| process.env.XINAO_PI_AGENT_PACKAGE_ROOT
	|| "D:\\XINAO_RESEARCH_RUNTIME\\tools\\pi\\prime\\0.84.1\\node_modules\\@earendil-works\\pi-coding-agent";
const jitiPath = join(piPackageRoot, "node_modules", "jiti", "lib", "jiti.mjs");
const agentCoreRoot = join(piPackageRoot, "node_modules", "@earendil-works", "pi-agent-core", "dist");
const piAiRoot = join(piPackageRoot, "node_modules", "@earendil-works", "pi-ai", "dist");

const { createJiti } = await import(pathToFileURL(jitiPath).href);
const { runAgentLoop } = await import(pathToFileURL(join(agentCoreRoot, "agent-loop.js")).href);
const { createFauxCore, fauxAssistantMessage, fauxToolCall } = await import(
	pathToFileURL(join(piAiRoot, "providers", "faux.js")).href
);
const jiti = createJiti(import.meta.url, {
	alias: { typebox: join(piPackageRoot, "node_modules", "typebox", "build", "index.mjs") },
});
const loaded = await jiti.import(extensionPath);
const installExtension = loaded.default ?? loaded;

let registered;
let sendUserMessageCalls = 0;
const originalChildMarker = process.env.PI_SUBAGENT_CHILD;
delete process.env.PI_SUBAGENT_CHILD;
installExtension({
	registerTool(tool) { registered = tool; },
	sendUserMessage() { sendUserMessageCalls += 1; },
});

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
const direct = await registered.execute("direct", args, new AbortController().signal, undefined, {});
assert.equal(direct.details.schema, "xinao.pi_return_to_parent.v1");
assert.equal(direct.details.local_boundary, "local evidence slice settled");
assert.equal(direct.details.queued_message, false);
assert.equal(direct.details.automatic_wake, false);
assert.match(direct.content[0].text, /Continue this same root run/);
assert.equal(sendUserMessageCalls, 0);

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

process.stdout.write(`${JSON.stringify({
	schema: "xinao.pi_return_to_parent.acceptance.v1",
	status: "mechanically_verified",
	behavior_selection_status: "pending_live_sol",
	root_only_registration: true,
	normalized_empty_rejected: true,
	same_run_continuation_after_local_boundary: true,
	scripted_no_action_path_does_not_auto_continue: true,
	pre_execute_abort_rejected: true,
	turn_boundary_abort_prevents_next_provider: true,
	queued_user_messages: 0,
	automatic_wake: false,
	provider_calls_positive: positive.faux.state.callCount,
	provider_calls_negative: negative.faux.state.callCount,
})}\n`);
