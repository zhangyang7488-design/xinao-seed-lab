import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const READ_TOOLS = new Set(["read", "ls"]);
const SEARCH_TOOLS = new Set(["find", "grep", "session_search", "memory_search"]);
const EXTERNAL_SEARCH_TOOLS = new Set(["web_search"]);
const COMPUTE_TOOLS = new Set(["bash", "init_experiment", "run_experiment", "log_experiment"]);
const WRITE_TOOLS = new Set(["edit", "write", "memory_add", "memory_remove", "memory_replace"]);
const CHILD_TOOLS = new Set(["subagent"]);
const CHILD_CONTROL_TOOLS = new Set(["subagent_wait", "subagent_supervisor", "intercom"]);

function setActivity(ctx: ExtensionContext, message?: string): void {
	if (ctx.mode !== "tui" || !ctx.hasUI) return;
	ctx.ui.setWorkingMessage(message);
}

export function activityForTool(toolName: string): string {
	if (READ_TOOLS.has(toolName)) return "正在读取和核对证据…";
	if (SEARCH_TOOLS.has(toolName)) return "正在检索本地事实与既有证据…";
	if (EXTERNAL_SEARCH_TOOLS.has(toolName)) return "正在搜索外部证据并准备撞回本地现实…";
	if (COMPUTE_TOOLS.has(toolName)) return "正在执行命令、计算或实验…";
	if (WRITE_TOOLS.has(toolName)) return "正在写入，并准备回读真实效果…";
	if (CHILD_TOOLS.has(toolName)) return "孩子正在工作；根 Pi 随后会比较和吸收…";
	if (CHILD_CONTROL_TOOLS.has(toolName)) return "正在与孩子通信并核对进展…";
	return "正在调用工具；原生工具卡与结果仍保持可见…";
}

export default function activityVisibility(pi: ExtensionAPI): void {
	const activeTools = new Map<string, string>();

	pi.on("agent_start", async (_event, ctx) => {
		activeTools.clear();
		setActivity(ctx, "正在理解当前任务并组织下一步…");
	});

	pi.on("turn_start", async (_event, ctx) => {
		setActivity(ctx, "正在分析证据并形成下一步…");
	});

	pi.on("tool_execution_start", async (event, ctx) => {
		activeTools.set(event.toolCallId, event.toolName);
		setActivity(
			ctx,
			activeTools.size > 1
				? `正在并行使用 ${activeTools.size} 个工具；原生工具卡显示细节…`
				: activityForTool(event.toolName),
		);
	});

	pi.on("tool_execution_end", async (event, ctx) => {
		activeTools.delete(event.toolCallId);
		setActivity(
			ctx,
			event.isError
				? activeTools.size > 0
					? `一个工具失败，另有 ${activeTools.size} 个仍在运行；详情见原生工具卡…`
					: "工具返回失败，正在判断恢复或换路…"
				: activeTools.size > 0
					? `已取得一个结果，仍有 ${activeTools.size} 个工具在运行…`
					: "已取得工具结果，正在综合并决定下一步…",
		);
	});

	pi.on("session_before_compact", async (_event, ctx) => {
		activeTools.clear();
		setActivity(ctx, "上下文接近边界，正在压缩并保留父任务…");
	});

	pi.on("session_compact", async (_event, ctx) => {
		setActivity(ctx, "压缩完成，正在同一会话继续…");
	});

	pi.on("agent_end", async (_event, ctx) => {
		setActivity(ctx, "本轮模型已返回，正在检查续接、压缩或排队消息…");
	});

	pi.on("agent_settled", async (_event, ctx) => {
		activeTools.clear();
		setActivity(ctx);
	});

	pi.on("session_shutdown", async (_event, ctx) => {
		setActivity(ctx);
	});
}
