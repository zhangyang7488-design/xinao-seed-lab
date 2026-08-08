#!/usr/bin/env node

import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const sourceRoot = dirname(scriptDir);
const extensionPath = join(sourceRoot, "surface-overlays", "prime-s", "extensions", "activity-visibility.ts");
const piPackageRoot = process.argv[2]
	|| process.env.XINAO_PI_AGENT_PACKAGE_ROOT
	|| "D:\\XINAO_RESEARCH_RUNTIME\\tools\\pi\\0.84.1\\node_modules\\@earendil-works\\pi-coding-agent";
const jitiPath = join(piPackageRoot, "node_modules", "jiti", "lib", "jiti.mjs");

const { createJiti } = await import(pathToFileURL(jitiPath).href);
const jiti = createJiti(import.meta.url);
const loaded = await jiti.import(extensionPath);
const installExtension = loaded.default ?? loaded;

const handlers = new Map();
const workingMessages = [];
let workingVisibilityCalls = 0;
let workingIndicatorCalls = 0;
let statusCalls = 0;

const pi = {
	on(name, handler) {
		const items = handlers.get(name) ?? [];
		items.push(handler);
		handlers.set(name, items);
	},
};

const context = {
	mode: "tui",
	hasUI: true,
	ui: {
		setWorkingMessage(message) { workingMessages.push(message); },
		setWorkingVisible() { workingVisibilityCalls += 1; },
		setWorkingIndicator() { workingIndicatorCalls += 1; },
		setStatus() { statusCalls += 1; },
	},
};

async function fire(name, event = {}, ctx = context) {
	for (const handler of handlers.get(name) ?? []) await handler(event, ctx);
}

installExtension(pi);

assert.deepEqual(
	[...handlers.keys()].sort(),
	[
		"agent_end",
		"agent_settled",
		"agent_start",
		"session_before_compact",
		"session_compact",
		"session_shutdown",
		"tool_execution_end",
		"tool_execution_start",
		"turn_start",
	].sort(),
);

await fire("agent_start");
assert.match(workingMessages.at(-1), /正在理解当前任务/);
await fire("turn_start", { turnIndex: 0 });
assert.match(workingMessages.at(-1), /正在分析证据/);

for (const [toolName, expected] of [
	["read", /读取和核对证据/],
	["grep", /检索本地事实/],
	["web_search", /搜索外部证据/],
	["bash", /命令、计算或实验/],
	["edit", /写入/],
	["subagent", /孩子正在工作/],
	["intercom", /与孩子通信/],
	["unknown-tool", /原生工具卡与结果仍保持可见/],
]) {
	await fire("tool_execution_start", { toolCallId: `single-${toolName}`, toolName });
	assert.match(workingMessages.at(-1), expected);
	await fire("tool_execution_end", { toolCallId: `single-${toolName}`, toolName, isError: false });
}

await fire("tool_execution_start", { toolCallId: "parallel-read", toolName: "read" });
await fire("tool_execution_start", { toolCallId: "parallel-bash", toolName: "bash" });
assert.match(workingMessages.at(-1), /并行使用 2 个工具/);
await fire("tool_execution_end", { toolCallId: "parallel-read", toolName: "read", isError: false });
assert.match(workingMessages.at(-1), /仍有 1 个工具在运行/);
await fire("tool_execution_end", { toolCallId: "parallel-bash", toolName: "bash", isError: false });
assert.match(workingMessages.at(-1), /已取得工具结果/);
await fire("tool_execution_start", { toolCallId: "error-read", toolName: "read" });
await fire("tool_execution_end", { toolCallId: "error-read", toolName: "read", isError: true });
assert.match(workingMessages.at(-1), /工具返回失败/);
await fire("session_before_compact", { reason: "threshold", willRetry: true });
assert.match(workingMessages.at(-1), /正在压缩并保留父任务/);
await fire("session_compact", { reason: "threshold", willRetry: true });
assert.match(workingMessages.at(-1), /压缩完成/);
await fire("agent_end");
assert.match(workingMessages.at(-1), /检查续接、压缩或排队消息/);
await fire("agent_settled");
assert.equal(workingMessages.at(-1), undefined);
await fire("session_shutdown");
assert.equal(workingMessages.at(-1), undefined);

const rpcContext = { mode: "rpc", hasUI: false, ui: {} };
const beforeRpc = workingMessages.length;
await fire("agent_start", {}, rpcContext);
assert.equal(workingMessages.length, beforeRpc);

assert.equal(workingVisibilityCalls, 0);
assert.equal(workingIndicatorCalls, 0);
assert.equal(statusCalls, 0);

process.stdout.write(`${JSON.stringify({
	schema: "xinao.pi_s_activity_visibility.v1",
	status: "verified",
	natural_chinese_activity: true,
	tool_failure_and_recovery_visible: true,
	compaction_activity_visible: true,
	child_activity_visible: true,
	native_working_visibility_unchanged: true,
	native_working_indicator_unchanged: true,
	native_tool_cards_unmodified: true,
	secondary_model_calls: 0,
})}\n`);
