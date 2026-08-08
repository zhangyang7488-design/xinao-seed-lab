#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

function parseArgs(argv) {
	const values = {};
	for (let index = 0; index < argv.length; index += 2) {
		const key = argv[index];
		const value = argv[index + 1];
		if (!key?.startsWith("--") || value === undefined) throw new Error(`Expected --name value pairs: ${argv.join(" ")}`);
		values[key.slice(2)] = value;
	}
	return values;
}

function required(values, key) {
	if (!values[key]) throw new Error(`Missing --${key}`);
	return values[key];
}

function contentText(content) {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content.filter((part) => part?.type === "text").map((part) => part.text ?? "").join("\n");
}

function inspectChildSession(file, marker, expectedProvider, expectedModel) {
	let provider;
	let model;
	let text = "";
	let cleanStop = false;
	for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
		if (!line.trim()) continue;
		const entry = JSON.parse(line);
		if (entry.type === "model_change") {
			provider = entry.provider;
			model = entry.modelId;
		}
		if (entry.type !== "message" || entry.message?.role !== "assistant") continue;
		text += `\n${contentText(entry.message.content)}`;
		if (entry.message.stopReason === "stop") cleanStop = true;
	}
	if (!cleanStop || !text.includes(marker) || provider !== expectedProvider || model !== expectedModel) return undefined;
	return { provider, model, text: text.trim() };
}

function findChild(sessionDir, marker, provider, model, startedAt) {
	const candidates = [];
	const visit = (directory, depth) => {
		if (depth > 5 || !fs.existsSync(directory)) return;
		for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
			const full = path.join(directory, entry.name);
			if (entry.isDirectory()) visit(full, depth + 1);
			if (!entry.isFile() || entry.name !== "session.jsonl") continue;
			const mtimeMs = fs.statSync(full).mtimeMs;
			if (mtimeMs >= startedAt - 2000) candidates.push({ full, mtimeMs });
		}
	};
	visit(sessionDir, 0);
	candidates.sort((left, right) => right.mtimeMs - left.mtimeMs);
	for (const candidate of candidates) {
		try {
			const inspected = inspectChildSession(candidate.full, marker, provider, model);
			if (inspected) return { ...inspected, sessionFile: candidate.full };
		} catch {
			// A concurrently finalized JSONL candidate may be retried by the caller.
		}
	}
	return undefined;
}

async function waitForChild(sessionDir, marker, provider, model, startedAt, timeoutMs) {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		const child = findChild(sessionDir, marker, provider, model, startedAt);
		if (child) return child;
		await new Promise((resolve) => setTimeout(resolve, 250));
	}
	throw new Error(`DeepSeek child session did not settle with marker ${marker}`);
}

async function main() {
	const args = parseArgs(process.argv.slice(2));
	const cliPath = required(args, "cli");
	const rpcClientPath = required(args, "rpc-client");
	const cwd = required(args, "cwd");
	const agentDir = required(args, "agent-dir");
	const sessionDir = required(args, "session-dir");
	const codexHome = required(args, "codex-home");
	const modelRef = required(args, "model");
	const marker = required(args, "marker");
	const profile = args.profile ?? path.basename(path.resolve(agentDir));
	const accountSlot = args["account-slot"] ?? "main";
	const role = args.role ?? "primary";
	const timeoutMs = Number(args["timeout-ms"] ?? "180000");
	const receiptPath = args.receipt;
	const [provider, model] = modelRef.split("/", 2);
	if (provider !== "deepseek" || !/^deepseek-v4-(flash|pro)$/.test(model ?? "")) {
		throw new Error(`Unsupported DeepSeek child model: ${modelRef}`);
	}
	if (!new Set(["prime-s", "prime-b"]).has(profile)) throw new Error(`Unsupported profile: ${profile}`);
	if (!new Set(["main", "account-b"]).has(accountSlot)) throw new Error(`Unsupported account slot: ${accountSlot}`);

	const contract = path.join(agentDir, "PI_CONTRACT.md");
	const bindingPath = path.join(agentDir, "account-binding.json");
	for (const file of [cliPath, rpcClientPath, contract, bindingPath]) if (!fs.statSync(file).isFile()) throw new Error(`Required file missing: ${file}`);
	for (const directory of [cwd, agentDir, sessionDir, codexHome]) if (!fs.statSync(directory).isDirectory()) throw new Error(`Required directory missing: ${directory}`);
	const binding = JSON.parse(fs.readFileSync(bindingPath, "utf8"));
	if (binding.active_slot !== accountSlot || path.resolve(binding.selected_codex_home).toLowerCase() !== path.resolve(codexHome).toLowerCase()) {
		throw new Error(`Profile binding does not match invocation: ${JSON.stringify({ active_slot: binding.active_slot, selected_codex_home: binding.selected_codex_home })}`);
	}

	const { RpcClient } = await import(pathToFileURL(rpcClientPath).href);
	const client = new RpcClient({
		cliPath,
		cwd,
		provider: "openai-codex",
		model: "gpt-5.6-sol",
		args: [
			"--no-session",
			"--thinking", "low",
			"--tools", "subagent",
			"--append-system-prompt", contract,
			"--session-dir", sessionDir,
		],
		env: {
			PI_CODING_AGENT_DIR: agentDir,
			PI_CODING_AGENT_SESSION_DIR: sessionDir,
			PI_SKIP_VERSION_CHECK: "1",
			PI_TELEMETRY: "0",
			PI_SUBAGENT_MAX_DEPTH: "2",
			CODEX_HOME: codexHome,
			XINAO_ACCOUNT_SLOT: accountSlot,
			XINAO_PI_ROLE: role,
			XINAO_PI_PROFILE: profile,
			XINAO_PI_SUPERVISOR_ENABLED: "0",
		},
	});

	const startedAt = Date.now();
	try {
		await client.start();
		const eventsPromise = client.collectEvents(timeoutMs);
		const workflow = `return await runs.run("deepseek-native-child", {agent:"probe", model:"${modelRef}", task:"Do not call tools. Reply exactly ${marker}."});`;
		await client.prompt(
			`Call the subagent tool exactly once with async false, chatProgress off, mission false, and this exact workflowScript: ${workflow} ` +
			`Do not call another tool. After it settles, reply only PIS_DEEPSEEK_CHILD_PARENT_DONE.`,
		);
		const events = await eventsPromise;
		const starts = events.filter((event) => event?.type === "tool_execution_start");
		const ends = events.filter((event) => event?.type === "tool_execution_end");
		const executionStarts = starts.filter((event) => event.toolName === "subagent" && typeof event.args?.workflowScript === "string");
		const allowedDiscoveryStarts = starts.filter((event) => event.toolName === "subagent" && event.args?.action === "list");
		const unexpectedStarts = starts.filter((event) => !executionStarts.includes(event) && !allowedDiscoveryStarts.includes(event));
		if (executionStarts.length !== 1 || unexpectedStarts.length > 0 || allowedDiscoveryStarts.length > 1) {
			throw new Error(`Expected one execution and at most one read-only discovery: ${JSON.stringify(starts)}`);
		}
		const executionEnd = ends.find((event) => event.toolCallId === executionStarts[0].toolCallId);
		if (!executionEnd || executionEnd.toolName !== "subagent" || executionEnd.isError) {
			throw new Error(`Expected successful execution end: ${JSON.stringify(ends)}`);
		}
		const child = await waitForChild(sessionDir, marker, provider, model, startedAt, timeoutMs);
		const normalizedRoot = `${path.resolve(sessionDir)}${path.sep}`.toLowerCase();
		if (!path.resolve(child.sessionFile).toLowerCase().startsWith(normalizedRoot)) throw new Error(`Child session escaped profile: ${child.sessionFile}`);

		const receipt = {
			schema: "xinao.pis.deepseek_native_child_rpc_acceptance.v1",
			status: "verified",
			profile,
			account_slot: accountSlot,
			role,
			profile_binding_matches_invocation: true,
			transport: "pi-subagents-native-child",
			provider: child.provider,
			model: child.model,
			marker_consumed: true,
			child_session: child.sessionFile,
			child_session_under_profile_root: true,
			codex_external_worker_used: false,
			read_only_agent_discovery_used: allowedDiscoveryStarts.length === 1,
			duration_ms: Date.now() - startedAt,
		};
		if (receiptPath) {
			fs.mkdirSync(path.dirname(receiptPath), { recursive: true });
			fs.writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
		}
		process.stdout.write(`${JSON.stringify(receipt)}\n`);
	} finally {
		await client.stop();
	}
}

main().catch((error) => {
	process.stderr.write(`PI_S_DEEPSEEK_CHILD_RPC_TEST_ERROR: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
	process.exitCode = 1;
});
