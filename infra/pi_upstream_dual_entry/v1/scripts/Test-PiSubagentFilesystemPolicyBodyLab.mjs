#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { pathToFileURL } from "node:url";

const STUB_PROVIDER = "filesystem-policy-stub";
const STUB_MODEL = "fixture-model";
const POLICY_SOURCE_PATHS = [
	"src/extension/schemas.ts",
	"src/runs/background/async-execution.ts",
	"src/runs/background/async-resume.ts",
	"src/runs/background/stale-run-reconciler.ts",
	"src/runs/background/subagent-runner.ts",
	"src/runs/foreground/chain-execution.ts",
	"src/runs/foreground/execution.ts",
	"src/runs/foreground/subagent-executor.ts",
	"src/runs/shared/filesystem-policy.ts",
	"src/runs/shared/parallel-utils.ts",
	"src/runs/shared/pi-args.ts",
	"src/runs/shared/subagent-prompt-runtime.ts",
	"src/shared/launch-contract.ts",
	"src/shared/types.ts",
	"src/workflows/scripted-workflow.ts",
];

function parseArgs(argv) {
	const result = {};
	for (let index = 0; index < argv.length; index += 2) {
		const key = argv[index];
		const value = argv[index + 1];
		if (!key?.startsWith("--") || value === undefined) throw new Error(`Expected --name value pairs, got: ${argv.join(" ")}`);
		result[key.slice(2)] = value;
	}
	return result;
}

function required(args, name) {
	if (!args[name]) throw new Error(`Missing --${name}`);
	return path.resolve(args[name]);
}

function sha256(value) {
	return createHash("sha256").update(value).digest("hex");
}

function writeJson(filePath, value) {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const temporary = `${filePath}.${process.pid}.${Date.now()}.tmp`;
	fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
	fs.renameSync(temporary, filePath);
}

function readJson(filePath) {
	return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function delay(milliseconds) {
	return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function deepFindString(value, key) {
	if (!value || typeof value !== "object") return undefined;
	if (typeof value[key] === "string") return value[key];
	for (const item of Array.isArray(value) ? value : Object.values(value)) {
		const found = deepFindString(item, key);
		if (found !== undefined) return found;
	}
	return undefined;
}

function messageText(message) {
	if (typeof message?.content === "string") return message.content;
	if (!Array.isArray(message?.content)) return "";
	return message.content.map((part) => typeof part?.text === "string" ? part.text : JSON.stringify(part)).join("\n");
}

function toolNames(body) {
	return (Array.isArray(body?.tools) ? body.tools : [])
		.map((tool) => tool?.function?.name ?? tool?.name)
		.filter((value) => typeof value === "string");
}

function caseNameFromBody(body) {
	const matches = [...JSON.stringify(body?.messages ?? []).matchAll(/CASE_[A-Z0-9_]+/g)];
	return matches.at(-1)?.[0] ?? "CASE_UNKNOWN";
}

function lastMessage(body) {
	return Array.isArray(body?.messages) ? body.messages.at(-1) : undefined;
}

function ownerStopFixtureCommand(body) {
	const text = (Array.isArray(body?.messages) ? body.messages : [])
		.map((message) => messageText(message))
		.join("\n");
	return text
		.split(/\r?\n/)
		.map((line) => line.trim())
		.findLast((line) => /^node\s+/i.test(line) && line.includes("pi-owner-stop-child.mjs"));
}

function chatCompletionChunk(id, delta, finishReason = null) {
	return {
		id,
		object: "chat.completion.chunk",
		created: Math.floor(Date.now() / 1000),
		model: STUB_MODEL,
		choices: [{ index: 0, delta, finish_reason: finishReason }],
	};
}

function sendSse(res, response) {
	const id = `chatcmpl-${randomUUID()}`;
	res.writeHead(200, {
		"content-type": "text/event-stream; charset=utf-8",
		"cache-control": "no-cache",
		connection: "keep-alive",
	});
	const send = (value) => res.write(`data: ${JSON.stringify(value)}\n\n`);
	send(chatCompletionChunk(id, { role: "assistant" }));
	if (response.toolCall) {
		send(chatCompletionChunk(id, {
			tool_calls: [{
				index: 0,
				id: response.toolCall.id,
				type: "function",
				function: { name: response.toolCall.name, arguments: JSON.stringify(response.toolCall.arguments) },
			}],
		}));
		send(chatCompletionChunk(id, {}, "tool_calls"));
	} else {
		send(chatCompletionChunk(id, { content: response.text ?? "STUB_DONE" }));
		send(chatCompletionChunk(id, {}, "stop"));
	}
	res.write("data: [DONE]\n\n");
	res.end();
}

function makeRootToolCall(caseName, fixture) {
	const isAsync = caseName === "CASE_DETACHED_SAFE" || caseName === "CASE_NO_POLICY_DETACHED_SAFE";
	const isNoPolicy = caseName.startsWith("CASE_NO_POLICY_");
	const isResume = caseName === "CASE_RESUME_SAFE" || caseName === "CASE_NO_POLICY_RESUME_SAFE";
	const item = isResume
		? {
				resume: fixture.resumeRunIds?.[caseName],
				task: `${caseName} ${fixture.labRunMarker}: perform the single requested operation, then return only the case completion marker.`,
			}
		: {
				agent: "peer",
				task: `${caseName} ${fixture.labRunMarker}: perform the single requested operation, then return only the case completion marker.`,
				cwd: fixture.root,
				model: `${STUB_PROVIDER}/${STUB_MODEL}`,
				acceptance: false,
			};
	if (!isNoPolicy && !isResume) {
		item.filesystemPolicy = {
			allowedRoots: ["safe-root"],
			deniedPaths: ["safe-root/denied"],
			bash: "deny",
		};
	}
	if (isAsync) item.async = true;
	return {
		id: `call-root-${caseName.toLowerCase()}-${randomUUID()}`,
		name: "subagent",
		arguments: {
			workflowScript: `return runs.run(${JSON.stringify(caseName.toLowerCase())}, ${JSON.stringify(item)});`,
			async: false,
			chatProgress: "off",
			mission: false,
			context: "fresh",
			...(!isResume ? { model: `${STUB_PROVIDER}/${STUB_MODEL}` } : {}),
		},
	};
}

function makeChildToolCall(caseName, fixture) {
	const tool = (name, args) => ({ id: `call-child-${caseName.toLowerCase()}-${randomUUID()}`, name, arguments: args });
	switch (caseName) {
		case "CASE_FOREGROUND_SAFE":
		case "CASE_DETACHED_SAFE":
		case "CASE_RESUME_SAFE":
		case "CASE_NO_POLICY_DETACHED_SAFE":
		case "CASE_NO_POLICY_RESUME_SAFE":
			return tool("read", { path: "safe-root/safe.txt" });
		case "CASE_DENIED_READ":
			return tool("read", { path: "safe-root/denied/secret.txt" });
		case "CASE_JUNCTION_READ":
			return tool("read", { path: "safe-root/junction-out/secret.txt" });
		case "CASE_BROAD_GREP":
			return tool("grep", { pattern: "SAFE_ALLOWED_CONTENT", path: "safe-root" });
		case "CASE_SAFE_GREP":
			return tool("grep", { pattern: "SAFE_ALLOWED_CONTENT", path: "safe-root/sibling" });
		case "CASE_BASH_DENY":
			return tool("bash", {
				command: [
					`rg SAFE_ALLOWED_CONTENT safe-root > ${JSON.stringify(fixture.restrictedMarkers.rg)}`,
					`powershell -NoProfile -Command \"Set-Content -LiteralPath '${fixture.restrictedMarkers.powershell.replaceAll("'", "''")}' -Value pwned\"`,
					`node -e \"require('fs').writeFileSync(${JSON.stringify(fixture.restrictedMarkers.node)},'pwned')\"`,
					`python -c \"open(r'${fixture.restrictedMarkers.python}','w').write('pwned')\"`,
				].join(" && "),
			});
		case "CASE_NO_POLICY_BASH":
			return tool("bash", { command: `node -e \"require('fs').writeFileSync('no-policy-created.txt','ok')\"` });
		default:
			return undefined;
	}
}

function responseForBody(body, fixture, requestLog) {
	const names = toolNames(body);
	const serializedMessages = JSON.stringify(body?.messages ?? []);
	// Every child launch is tagged by buildPiArgs. Ordinary no-policy children
	// may expose only the subagent tool after session restoration, so tool shape
	// alone cannot distinguish root from child without causing recursive fixture
	// launches.
	const isChild = serializedMessages.includes("<active_agent name=");
	const isRoot = !isChild && names.includes("subagent");
	const caseName = caseNameFromBody(body);
	const last = lastMessage(body);
	const rootToolAlreadyIssued = isRoot && requestLog.some((entry) => entry.isRoot && entry.caseName === caseName);
	requestLog.push({
		at: Date.now(),
		isRoot,
		caseName,
		toolNames: names,
		body,
	});
	if (last?.role === "tool") {
		return { text: `${isRoot ? "ROOT" : "CHILD"}_DONE_${caseName}` };
	}
	if (rootToolAlreadyIssued) return { text: `ROOT_DONE_${caseName}` };
	if (isRoot) return { toolCall: makeRootToolCall(caseName, fixture) };
	const childToolCall = makeChildToolCall(caseName, fixture);
	if (childToolCall) return { toolCall: childToolCall };
	const stopCommand = ownerStopFixtureCommand(body);
	if (stopCommand) {
		return {
			toolCall: {
				id: `call-child-owner-stop-${randomUUID()}`,
				name: "bash",
				arguments: { command: stopCommand },
			},
		};
	}
	return { text: `CHILD_DONE_${caseName}` };
}

async function startStubServer(fixture) {
	const requests = [];
	const server = http.createServer((req, res) => {
		if (req.method === "GET" && req.url?.endsWith("/models")) {
			res.writeHead(200, { "content-type": "application/json" });
			res.end(JSON.stringify({ object: "list", data: [{ id: STUB_MODEL, object: "model", owned_by: "xinao-test" }] }));
			return;
		}
		if (req.method !== "POST" || !req.url?.endsWith("/chat/completions")) {
			res.writeHead(404, { "content-type": "application/json" });
			res.end(JSON.stringify({ error: { message: "not found" } }));
			return;
		}
		const chunks = [];
		req.on("data", (chunk) => chunks.push(chunk));
		req.on("end", () => {
			try {
				const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
				sendSse(res, responseForBody(body, fixture, requests));
			} catch (error) {
				res.writeHead(500, { "content-type": "application/json" });
				res.end(JSON.stringify({ error: { message: error instanceof Error ? error.message : String(error) } }));
			}
		});
	});
	await new Promise((resolve, reject) => {
		server.once("error", reject);
		server.listen(0, "127.0.0.1", resolve);
	});
	const address = server.address();
	if (!address || typeof address === "string") throw new Error("Stub server did not bind a TCP port.");
	return {
		baseUrl: `http://127.0.0.1:${address.port}/v1`,
		requests,
		close: () => new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve())),
	};
}

function snapshotTree(root) {
	const result = {};
	const visit = (directory) => {
		for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
			const absolute = path.join(directory, entry.name);
			const relative = path.relative(root, absolute).replaceAll("\\", "/");
			if (entry.isSymbolicLink()) {
				result[relative] = `link:${fs.readlinkSync(absolute)}`;
			} else if (entry.isDirectory()) {
				result[`${relative}/`] = "dir";
				visit(absolute);
			} else {
				result[relative] = `file:${sha256(fs.readFileSync(absolute))}`;
			}
		}
	};
	visit(root);
	return result;
}

function childSessionFiles(agentDir) {
	const sessionsRoot = path.join(agentDir, "sessions", "children");
	const result = [];
	const visit = (directory) => {
		if (!fs.existsSync(directory)) return;
		for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
			const absolute = path.join(directory, entry.name);
			if (entry.isDirectory()) visit(absolute);
			else if (entry.isFile() && entry.name === "session.jsonl") result.push(absolute);
		}
	};
	visit(sessionsRoot);
	return result;
}

function childToolResultText(message) {
	if (!Array.isArray(message?.content)) return "";
	return message.content.map((part) => typeof part?.text === "string" ? part.text : JSON.stringify(part)).join("\n");
}

function loadChildToolEvidence(agentDir, fixture, caseName) {
	const toolCallPrefix = `call-child-${caseName.toLowerCase()}-`;
	const matches = [];
	for (const transcriptPath of childSessionFiles(agentDir)) {
		const transcript = fs.readFileSync(transcriptPath);
		const text = transcript.toString("utf8");
		if (!text.includes(fixture.labRunMarker) || !text.includes(toolCallPrefix)) continue;
		const records = text.split(/\r?\n/).filter(Boolean).map((line, index) => {
			try {
				return JSON.parse(line);
			} catch (error) {
				throw new Error(`Malformed child transcript ${transcriptPath}:${index + 1}: ${error instanceof Error ? error.message : String(error)}`);
			}
		});
		const toolCalls = records.flatMap((record) => {
			const message = record?.message;
			if (message?.role !== "assistant" || !Array.isArray(message.content)) return [];
			return message.content.filter((part) => part?.type === "toolCall" && typeof part.id === "string" && part.id.startsWith(toolCallPrefix));
		});
		for (const toolCall of toolCalls) {
			const toolResults = records
				.map((record) => record?.message)
				.filter((message) => message?.role === "toolResult" && message.toolCallId === toolCall.id);
			assert.equal(toolResults.length, 1, `${caseName} expected one toolResult for ${toolCall.id} in ${transcriptPath}`);
			const toolResult = toolResults[0];
			assert.equal(typeof toolResult.isError, "boolean", `${caseName} toolResult.isError must be explicit`);
			matches.push({ transcriptPath, transcript, toolCall, toolResult });
		}
	}
	assert.equal(matches.length, 1, `${caseName} expected exactly one nonce-bound child tool call/result, found ${matches.length}`);
	const match = matches[0];
	const resultText = childToolResultText(match.toolResult);
	return {
		caseName,
		transcriptPath: match.transcriptPath,
		transcriptSha256: sha256(match.transcript),
		transcriptBytes: match.transcript.byteLength,
		toolCallId: match.toolCall.id,
		toolName: match.toolCall.name,
		toolArguments: match.toolCall.arguments,
		isError: match.toolResult.isError,
		resultText,
		resultTextSha256: sha256(resultText),
		resultTextBytes: Buffer.byteLength(resultText, "utf8"),
	};
}

function assertChildToolEvidence(agentDir, fixture, caseName) {
	const evidence = loadChildToolEvidence(agentDir, fixture, caseName);
	const expect = (toolName, isError) => {
		assert.equal(evidence.toolName, toolName, `${caseName} tool name drifted`);
		assert.equal(evidence.isError, isError, `${caseName} toolResult.isError drifted: ${evidence.resultText}`);
	};
	switch (caseName) {
		case "CASE_FOREGROUND_SAFE":
		case "CASE_DETACHED_SAFE":
		case "CASE_RESUME_SAFE":
		case "CASE_NO_POLICY_DETACHED_SAFE":
		case "CASE_NO_POLICY_RESUME_SAFE":
			expect("read", false);
			assert.deepEqual(evidence.toolArguments, { path: "safe-root/safe.txt" });
			assert.equal(evidence.resultText, "SAFE_ALLOWED_CONTENT\n");
			break;
		case "CASE_DENIED_READ":
			expect("read", true);
			assert.deepEqual(evidence.toolArguments, { path: "safe-root/denied/secret.txt" });
			assert.equal(evidence.resultText, "Blocked by task filesystem policy: target is within deniedPaths.");
			break;
		case "CASE_JUNCTION_READ":
			expect("read", true);
			assert.deepEqual(evidence.toolArguments, { path: "safe-root/junction-out/secret.txt" });
			assert.equal(evidence.resultText, "Blocked by task filesystem policy: target is outside allowedRoots.");
			break;
		case "CASE_BROAD_GREP":
			expect("grep", true);
			assert.deepEqual(evidence.toolArguments, { pattern: "SAFE_ALLOWED_CONTENT", path: "safe-root" });
			assert.equal(evidence.resultText, "Blocked by task filesystem policy: recursive/search root is an ancestor of a denied subtree.");
			break;
		case "CASE_SAFE_GREP":
			expect("grep", false);
			assert.deepEqual(evidence.toolArguments, { pattern: "SAFE_ALLOWED_CONTENT", path: "safe-root/sibling" });
			assert.equal(evidence.resultText, "sibling.txt:1: SAFE_ALLOWED_CONTENT");
			break;
		case "CASE_BASH_DENY":
			expect("bash", true);
			assert.match(evidence.resultText, /^(?:Tool bash not found|Blocked by task filesystem policy: bash is denied\.)$/);
			break;
		case "CASE_NO_POLICY_BASH":
			expect("bash", false);
			assert.equal(evidence.resultText, "(no output)");
			break;
		default:
			throw new Error(`No child tool-result expectation for ${caseName}`);
	}
	for (const sentinel of [fixture.contextSentinel, fixture.deniedSentinel, fixture.junctionSentinel]) {
		assert.ok(!evidence.resultText.includes(sentinel), `${caseName} toolResult leaked forbidden sentinel`);
	}
	return {
		caseName: evidence.caseName,
		transcriptPath: evidence.transcriptPath,
		transcriptSha256: evidence.transcriptSha256,
		transcriptBytes: evidence.transcriptBytes,
		toolCallId: evidence.toolCallId,
		toolName: evidence.toolName,
		isError: evidence.isError,
		resultTextSha256: evidence.resultTextSha256,
		resultTextBytes: evidence.resultTextBytes,
	};
}

async function waitForTerminalStatus(statusPath, timeoutMs) {
	const deadline = Date.now() + timeoutMs;
	let last;
	while (Date.now() < deadline) {
		if (fs.existsSync(statusPath)) {
			try {
				last = readJson(statusPath);
				if (["complete", "failed", "aborted", "timeout", "stopped"].includes(last?.state)) return last;
			} catch {
				// Atomic replacement can race the reader.
			}
		}
		await delay(100);
	}
	throw new Error(`Timed out waiting for ${statusPath}; last=${JSON.stringify(last)}`);
}

function assertNoExtensionErrors(events, label) {
	const errors = events.filter((event) => event?.type === "extension_error");
	assert.deepEqual(errors, [], `${label} extension errors`);
}

function findSubagentExecution(events, caseName) {
	const starts = events.filter((event) => event?.type === "tool_execution_start"
		&& event.toolName === "subagent"
		&& typeof event.args?.workflowScript === "string"
		&& (!caseName || event.args.workflowScript.includes(caseName)));
	assert.equal(starts.length, 1, `expected one subagent execution, got ${JSON.stringify(starts)}`);
	const end = events.find((event) => event?.type === "tool_execution_end" && event.toolCallId === starts[0].toolCallId);
	assert.ok(end, "subagent execution end missing");
	return { start: starts[0], end };
}

function createRootClient({
	RpcClient,
	cliPath,
	agentDir,
	sessionDir,
	codexHome,
	fixture,
	persistent = false,
	sessionFile,
}) {
	const sessionArgs = sessionFile
		? ["--session", sessionFile]
		: persistent
			? []
			: ["--no-session"];
	return new RpcClient({
		cliPath,
		cwd: fixture.root,
		provider: STUB_PROVIDER,
		model: STUB_MODEL,
		args: [
			...sessionArgs,
			"--thinking", "low",
			"--tools", "subagent",
			"--api-key", "filesystem-policy-lab",
			"--session-dir", sessionDir,
		],
		env: {
			PI_CODING_AGENT_DIR: agentDir,
			PI_CODING_AGENT_SESSION_DIR: sessionDir,
			PI_SKIP_VERSION_CHECK: "1",
			PI_TELEMETRY: "0",
			CODEX_HOME: codexHome,
			XINAO_PI_PROFILE: "prime-s",
			XINAO_PI_SUPERVISOR_ENABLED: "0",
		},
	});
}

async function runRootCase({ RpcClient, cliPath, agentDir, sessionDir, codexHome, fixture, caseName, timeoutMs }) {
	const client = createRootClient({ RpcClient, cliPath, agentDir, sessionDir, codexHome, fixture });
	try {
		await client.start();
		const eventsPromise = client.collectEvents(timeoutMs);
		await client.prompt(`${caseName}: invoke the one deterministic subagent lab case. Do not mention cwd context content.`);
		const events = await eventsPromise;
		assertNoExtensionErrors(events, caseName);
		const execution = findSubagentExecution(events, caseName);
		let asyncStatus;
		if (caseName === "CASE_DETACHED_SAFE") {
			const workflowValue = execution.end?.result?.details?.workflow?.value;
			const asyncDir = deepFindString(execution.end, "asyncDir")
				?? (Array.isArray(workflowValue?.artifactPaths) ? workflowValue.artifactPaths.find((value) => typeof value === "string") : undefined);
			assert.ok(asyncDir, `detached asyncDir missing before root RPC shutdown: ${JSON.stringify(execution.end)}`);
			asyncStatus = await waitForTerminalStatus(path.join(asyncDir, "status.json"), timeoutMs);
		}
		return { events, execution, asyncStatus };
	} finally {
		await client.stop();
	}
}

async function runDetachedAndResumeCase({
	RpcClient,
	cliPath,
	agentDir,
	sessionDir,
	codexHome,
	fixture,
	timeoutMs,
	detachedCaseName = "CASE_DETACHED_SAFE",
	resumeCaseName = "CASE_RESUME_SAFE",
}) {
	const launchDetached = async (caseName, sessionOptions = {}) => {
		const client = createRootClient({
			RpcClient,
			cliPath,
			agentDir,
			sessionDir,
			codexHome,
			fixture,
			...sessionOptions,
		});
		try {
			await client.start();
			const rootState = await client.getState();
			const eventsPromise = client.collectEvents(timeoutMs);
			await client.prompt(`${caseName}: invoke the one deterministic detached subagent lab case.`);
			const events = await eventsPromise;
			assertNoExtensionErrors(events, caseName);
			return { events, execution: findSubagentExecution(events, caseName), rootState };
		} finally {
			// The normal root result watcher intentionally consumes delivered result
			// files. Close this persisted root immediately after launch so the harness
			// can read the exact durable result before reproducing that consumption.
			await client.stop();
		}
	};

	const detachedLaunch = await launchDetached(detachedCaseName, { persistent: true });
	const detachedEvents = detachedLaunch.events;
	const detachedExecution = detachedLaunch.execution;
	const rootSessionFile = detachedLaunch.rootState?.sessionFile;
	const rootSessionId = detachedLaunch.rootState?.sessionId;
	assert.ok(rootSessionFile, `persisted detached root session file missing: ${JSON.stringify(detachedLaunch.rootState)}`);
	assert.ok(rootSessionId, `persisted detached root session id missing: ${JSON.stringify(detachedLaunch.rootState)}`);
	const workflowValue = detachedExecution.end?.result?.details?.workflow?.value;
	const asyncDir = deepFindString(detachedExecution.end, "asyncDir")
		?? (Array.isArray(workflowValue?.artifactPaths) ? workflowValue.artifactPaths.find((value) => typeof value === "string") : undefined);
	assert.ok(asyncDir, `detached asyncDir missing before root RPC shutdown: ${JSON.stringify(detachedExecution.end)}`);
	const sourceRunId = workflowValue?.runId;
	assert.ok(sourceRunId, `detached run id missing: ${JSON.stringify(workflowValue)}`);
	fixture.resumeRunIds ??= {};
	fixture.resumeRunIds[resumeCaseName] = sourceRunId;
	const asyncStatus = await waitForTerminalStatus(path.join(asyncDir, "status.json"), timeoutMs);
	assert.equal(asyncStatus.state, "complete", JSON.stringify(asyncStatus));
	// Preserve the source lifecycle surfaces before resume consumes/moves the
	// completed result. The resumed child is itself detached, so the root tool
	// returning only proves launch acceptance, not provider execution.
	const sourceSurfaces = await waitForAsyncSurfaces(asyncDir, sourceRunId, timeoutMs);
	fs.rmSync(sourceSurfaces.resultPath, { force: true });

	const resumeLaunch = await launchDetached(resumeCaseName, { sessionFile: rootSessionFile });
	assert.equal(resumeLaunch.rootState?.sessionId, rootSessionId, "resume root did not reopen the detached launch session");
	assert.equal(path.resolve(resumeLaunch.rootState?.sessionFile), path.resolve(rootSessionFile), "resume root session file changed");
	const resumeEvents = resumeLaunch.events;
	const resumeExecution = resumeLaunch.execution;
	const resumeWorkflowValue = resumeExecution.end?.result?.details?.workflow?.value;
	const resumeAsyncDir = deepFindString(resumeExecution.end, "asyncDir")
		?? (Array.isArray(resumeWorkflowValue?.artifactPaths)
			? resumeWorkflowValue.artifactPaths.find((value) => typeof value === "string")
			: undefined);
	assert.ok(resumeAsyncDir, `resume asyncDir missing before root RPC shutdown: ${JSON.stringify(resumeExecution.end)}`);
	const resumeRunId = resumeWorkflowValue?.runId
		?? deepFindString(resumeExecution.end, "asyncId")
		?? deepFindString(resumeExecution.end, "runId");
	assert.ok(resumeRunId, `resume run id missing: ${JSON.stringify(resumeExecution.end)}`);
	const resumeStatus = await waitForTerminalStatus(path.join(resumeAsyncDir, "status.json"), timeoutMs);
	assert.equal(resumeStatus.state, "complete", JSON.stringify(resumeStatus));
	const resumeSurfaces = await waitForAsyncSurfaces(resumeAsyncDir, resumeRunId, timeoutMs);
	return {
		detached: { events: detachedEvents, execution: detachedExecution, asyncStatus },
		resume: { events: resumeEvents, execution: resumeExecution, asyncStatus: resumeStatus },
		rootSessionFile,
		rootSessionId,
		asyncDir,
		runId: sourceRunId,
		sourceSurfaces,
		resumeAsyncDir,
		resumeRunId,
		resumeSurfaces,
	};
}

function createFixture(root) {
	const safeRoot = path.join(root, "safe-root");
	const deniedRoot = path.join(safeRoot, "denied");
	const siblingRoot = path.join(safeRoot, "sibling");
	const outsideRoot = path.join(root, "outside");
	for (const directory of [root, safeRoot, deniedRoot, siblingRoot, outsideRoot]) fs.mkdirSync(directory, { recursive: true });
	const contextSentinel = `FORBIDDEN_CONTEXT_${randomUUID()}`;
	const deniedSentinel = `FORBIDDEN_DENIED_${randomUUID()}`;
	const junctionSentinel = `FORBIDDEN_JUNCTION_TARGET_${randomUUID()}`;
	const labRunMarker = `LAB_RUN_${randomUUID()}`;
	fs.writeFileSync(path.join(root, "AGENTS.md"), `# Attack context\n${contextSentinel}\n`, "utf8");
	fs.writeFileSync(path.join(safeRoot, "safe.txt"), "SAFE_ALLOWED_CONTENT\n", "utf8");
	fs.writeFileSync(path.join(siblingRoot, "sibling.txt"), "SAFE_ALLOWED_CONTENT\n", "utf8");
	fs.writeFileSync(path.join(deniedRoot, "secret.txt"), `${deniedSentinel}\n`, "utf8");
	fs.writeFileSync(path.join(outsideRoot, "secret.txt"), `${junctionSentinel}\n`, "utf8");
	const junction = path.join(safeRoot, "junction-out");
	fs.symlinkSync(outsideRoot, junction, "junction");
	const restrictedMarkers = Object.fromEntries(["rg", "powershell", "node", "python"].map((name) => [name, path.join(root, `restricted-${name}.txt`)]));
	return { root, safeRoot, deniedRoot, siblingRoot, outsideRoot, junction, contextSentinel, deniedSentinel, junctionSentinel, labRunMarker, restrictedMarkers };
}

function configureStubModel(agentDir, baseUrl) {
	const modelsPath = path.join(agentDir, "models.json");
	const settingsPath = path.join(agentDir, "settings.json");
	const previous = fs.existsSync(modelsPath) ? fs.readFileSync(modelsPath) : undefined;
	const previousSettings = fs.readFileSync(settingsPath);
	const settings = JSON.parse(previousSettings.toString("utf8"));
	const modelAllow = settings?.subagents?.modelScope?.allow;
	if (!Array.isArray(modelAllow)) throw new Error("Body lab settings lack subagents.modelScope.allow.");
	if (!modelAllow.includes(`${STUB_PROVIDER}/${STUB_MODEL}`)) modelAllow.push(`${STUB_PROVIDER}/${STUB_MODEL}`);
	writeJson(settingsPath, settings);
	writeJson(modelsPath, {
		providers: {
			[STUB_PROVIDER]: {
				baseUrl,
				api: "openai-completions",
				apiKey: "filesystem-policy-lab",
				compat: { supportsDeveloperRole: false, supportsReasoningEffort: false, supportsStrictMode: false },
				models: [{
					id: STUB_MODEL,
					name: "Filesystem policy lab stub",
					reasoning: false,
					input: ["text"],
					contextWindow: 128000,
					maxTokens: 4096,
					cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
				}],
			},
			"openai-codex": {
				baseUrl,
				api: "openai-completions",
				apiKey: "filesystem-policy-lab",
				compat: { supportsDeveloperRole: false, supportsReasoningEffort: false, supportsStrictMode: false },
				models: [{
					id: "gpt-5.6-sol",
					name: "Owner Stop lab stub",
					reasoning: false,
					input: ["text"],
					contextWindow: 128000,
					maxTokens: 4096,
					cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
				}],
			},
		},
	});
	return () => {
		if (previous === undefined) fs.rmSync(modelsPath, { force: true });
		else fs.writeFileSync(modelsPath, previous);
		fs.writeFileSync(settingsPath, previousSettings);
	};
}

function loadRestrictedAsyncSurfaces(asyncDir, runId) {
	const status = readJson(path.join(asyncDir, "status.json"));
	const descriptor = readJson(path.join(asyncDir, "recovery-descriptor.json"));
	const resultPath = path.join(path.dirname(path.dirname(asyncDir)), "async-subagent-results", `${runId}.json`);
	const result = readJson(resultPath);
	return { status, descriptor, result, resultPath };
}

async function waitForAsyncSurfaces(asyncDir, runId, timeoutMs) {
	const deadline = Date.now() + timeoutMs;
	let lastError;
	while (Date.now() < deadline) {
		try {
			return loadRestrictedAsyncSurfaces(asyncDir, runId);
		} catch (error) {
			lastError = error;
		}
		await delay(50);
	}
	throw new Error(`Timed out waiting for durable async surfaces for ${runId}: ${lastError instanceof Error ? lastError.message : String(lastError)}`);
}

function runHiddenProcess(command, args, { cwd, env, timeoutMs }) {
	return new Promise((resolve, reject) => {
		const child = spawn(command, args, {
			cwd,
			env,
			windowsHide: true,
			stdio: ["ignore", "pipe", "pipe"],
		});
		const stdout = [];
		const stderr = [];
		child.stdout.on("data", (chunk) => stdout.push(chunk));
		child.stderr.on("data", (chunk) => stderr.push(chunk));
		const timer = setTimeout(() => {
			child.kill("SIGTERM");
			reject(new Error(`Timed out after ${timeoutMs}ms: ${command} ${args.join(" ")}`));
		}, timeoutMs);
		child.once("error", (error) => {
			clearTimeout(timer);
			reject(error);
		});
		child.once("close", (code, signal) => {
			clearTimeout(timer);
			resolve({
				code,
				signal,
				stdout: Buffer.concat(stdout).toString("utf8"),
				stderr: Buffer.concat(stderr).toString("utf8"),
			});
		});
	});
}

async function runOwnerStopProcessLab({
	cliPath,
	rpcClientPath,
	agentDir,
	codexHome,
	fixture,
	timeoutMs,
	stopHarnessPath,
	stopExtensionPath,
	stopFixturePath,
}) {
	const evidenceDir = path.join(fixture.root, "owner-stop-evidence");
	const receiptPath = path.join(evidenceDir, "owner-stop-receipt.json");
	const stopSessionDir = path.join(fixture.root, "owner-stop-sessions");
	fs.mkdirSync(stopSessionDir, { recursive: true });
	const projectedAgentPaths = ["stop-fixture.md", "stop-race-fixture.md"]
		.map((name) => path.join(agentDir, "agents", name));
	const previousAgentFiles = projectedAgentPaths.map((filePath) => ({
		filePath,
		content: fs.existsSync(filePath) ? fs.readFileSync(filePath) : undefined,
	}));
	try {
		const processResult = await runHiddenProcess(process.execPath, [
			stopHarnessPath,
			"--cli", cliPath,
			"--rpc-client", rpcClientPath,
			"--agent-dir", agentDir,
			"--session-dir", stopSessionDir,
			"--codex-home", codexHome,
			"--cwd", fixture.root,
			"--extension", stopExtensionPath,
			"--fixture", stopFixturePath,
			"--evidence-dir", evidenceDir,
			"--receipt", receiptPath,
			"--timeout-ms", String(timeoutMs),
		], {
			cwd: fixture.root,
			env: { ...process.env },
			timeoutMs: timeoutMs + 30_000,
		});
		assert.equal(processResult.code, 0, `Owner Stop process lab failed (${processResult.signal ?? processResult.code}): ${processResult.stderr}\n${processResult.stdout}`);
		const receipt = readJson(receiptPath);
		assert.equal(receipt.status, "verified");
		assert.equal(receipt.real_detached_process_started, true);
		assert.equal(receipt.real_detached_process_terminated, true);
		assert.equal(receipt.process_terminal_observed, true);
		assert.equal(receipt.status_stopped, true);
		assert.equal(receipt.launch_commit_fence_rejected_race, true);
		return receipt;
	} finally {
		for (const previous of previousAgentFiles) {
			if (previous.content === undefined) fs.rmSync(previous.filePath, { force: true });
			else fs.writeFileSync(previous.filePath, previous.content);
		}
	}
}

async function runDirectPolicyBootstrapFailures({
	cliPath,
	agentDir,
	codexHome,
	fixture,
	timeoutMs,
	stub,
}) {
	const packageRoot = path.join(agentDir, "npm", "node_modules", "pi-subagents");
	const runtimePath = path.join(packageRoot, "src", "runs", "shared", "subagent-prompt-runtime.ts");
	const gatePath = path.join(packageRoot, "src", "runs", "shared", "filesystem-policy.ts");
	const policy = {
		version: 1,
		cwd: fs.realpathSync.native(fixture.root),
		allowedRoots: [fs.realpathSync.native(fixture.safeRoot)],
		deniedPaths: [fs.realpathSync.native(fixture.deniedRoot)],
		bash: "deny",
		allowedTools: ["read", "grep", "find", "ls"],
	};
	const payload = JSON.stringify(policy);
	const basePolicyEnv = {
		PI_SUBAGENT_FILESYSTEM_POLICY_REQUIRED: "1",
		PI_SUBAGENT_FILESYSTEM_POLICY: payload,
		PI_SUBAGENT_FILESYSTEM_POLICY_SHA256: sha256(payload),
		PI_SUBAGENT_FILESYSTEM_POLICY_RUNTIME_PATH: runtimePath,
		PI_SUBAGENT_FILESYSTEM_POLICY_RUNTIME_SHA256: sha256(fs.readFileSync(runtimePath)),
		PI_SUBAGENT_FILESYSTEM_POLICY_GATE_PATH: gatePath,
		PI_SUBAGENT_FILESYSTEM_POLICY_GATE_SHA256: sha256(fs.readFileSync(gatePath)),
	};
	const cases = [
		{
			name: "missing_payload",
			env: { PI_SUBAGENT_FILESYSTEM_POLICY: "" },
			expected: /Missing PI_SUBAGENT_FILESYSTEM_POLICY/,
		},
		{
			name: "malformed_payload",
			env: { PI_SUBAGENT_FILESYSTEM_POLICY: "{", PI_SUBAGENT_FILESYSTEM_POLICY_SHA256: sha256("{") },
			expected: /not valid JSON/,
		},
		{
			name: "payload_hash_mismatch",
			env: { PI_SUBAGENT_FILESYSTEM_POLICY_SHA256: "0".repeat(64) },
			expected: /payload hash mismatch/,
		},
		{
			name: "runtime_path_mismatch",
			env: {
				PI_SUBAGENT_FILESYSTEM_POLICY_RUNTIME_PATH: gatePath,
				PI_SUBAGENT_FILESYSTEM_POLICY_RUNTIME_SHA256: sha256(fs.readFileSync(gatePath)),
			},
			expected: /forced runtime path mismatch/,
		},
		{
			name: "runtime_hash_mismatch",
			env: { PI_SUBAGENT_FILESYSTEM_POLICY_RUNTIME_SHA256: "0".repeat(64) },
			expected: /forced runtime hash mismatch/,
		},
		{
			name: "gate_path_mismatch",
			env: {
				PI_SUBAGENT_FILESYSTEM_POLICY_GATE_PATH: runtimePath,
				PI_SUBAGENT_FILESYSTEM_POLICY_GATE_SHA256: sha256(fs.readFileSync(runtimePath)),
			},
			expected: /gate module path mismatch/,
		},
		{
			name: "gate_hash_mismatch",
			env: { PI_SUBAGENT_FILESYSTEM_POLICY_GATE_SHA256: "0".repeat(64) },
			expected: /gate module hash mismatch/,
		},
	];
	const results = [];
	for (const testCase of cases) {
		const requestCountBefore = stub.requests.length;
		const processResult = await runHiddenProcess(process.execPath, [
			cliPath,
			"--mode", "json",
			"-p",
			"--no-session",
			"--no-context-files",
			"--no-skills",
			"--no-extensions",
			"--extension", runtimePath,
			"--tools", "read",
			"--model", `${STUB_PROVIDER}/${STUB_MODEL}`,
			`Task: CASE_PREPROVIDER_${testCase.name.toUpperCase()}: return only if provider execution was incorrectly reached.`,
		], {
			cwd: fixture.root,
			env: {
				...process.env,
				PI_CODING_AGENT_DIR: agentDir,
				PI_CODING_AGENT_SESSION_DIR: path.join(fixture.root, "preprovider-sessions"),
				PI_SKIP_VERSION_CHECK: "1",
				PI_TELEMETRY: "0",
				CODEX_HOME: codexHome,
				XINAO_PI_PROFILE: "prime-s",
				XINAO_PI_SUPERVISOR_ENABLED: "0",
				PI_SUBAGENT_CHILD: "1",
				...basePolicyEnv,
				...testCase.env,
			},
			timeoutMs,
		});
		const combinedOutput = `${processResult.stderr}\n${processResult.stdout}`;
		assert.notEqual(processResult.code, 0, `${testCase.name} unexpectedly exited successfully: ${combinedOutput}`);
		assert.match(combinedOutput, testCase.expected, `${testCase.name} emitted the wrong fail-closed error`);
		assert.equal(stub.requests.length, requestCountBefore, `${testCase.name} reached the provider before failing`);
		results.push({ name: testCase.name, providerRequests: 0, exitCode: processResult.code });
	}
	return { runtimePath, gatePath, cases: results };
}

async function runMissingForcedRuntimeParentLab({
	RpcClient,
	cliPath,
	agentDir,
	sessionDir,
	codexHome,
	fixture,
	timeoutMs,
	stub,
}) {
	const runtimePath = path.join(agentDir, "npm", "node_modules", "pi-subagents", "src", "runs", "shared", "subagent-prompt-runtime.ts");
	const heldPath = `${runtimePath}.filesystem-policy-missing-runtime-test-${process.pid}`;
	const requestCountBefore = stub.requests.length;
	try {
		fs.renameSync(runtimePath, heldPath);
		const value = await runRootCase({
			RpcClient,
			cliPath,
			agentDir,
			sessionDir,
			codexHome,
			fixture,
			caseName: "CASE_RUNTIME_MISSING",
			timeoutMs,
		});
		const serialized = JSON.stringify(value.execution.end);
		assert.match(serialized, /subagent-prompt-runtime|ENOENT|no such file/i, `missing forced runtime did not fail launch: ${serialized}`);
		assert.equal(stub.requests.slice(requestCountBefore).some((request) => !request.isRoot), false, "missing forced runtime reached the child provider");
		return { providerRequests: 0, launchRejected: true };
	} finally {
		if (fs.existsSync(heldPath)) fs.renameSync(heldPath, runtimePath);
	}
}

function assertRestrictedAsyncSurfaces({ status, descriptor, result }, fixture) {
	const statusStep = status.steps?.[0];
	const resultChild = result.results?.[0];
	assert.equal(status.state, "complete");
	assert.equal(descriptor.maxSubagentDepth, 0);
	assert.equal(descriptor.inheritProjectContext, false);
	assert.equal(descriptor.inheritSkills, false);
	assert.deepEqual(descriptor.skills ?? [], []);
	assert.equal(descriptor.acceptance, false);
	assert.equal(descriptor.share, false);
	assert.equal(descriptor.artifactConfig?.dir, "temp");
	assert.equal(descriptor.model, `${STUB_PROVIDER}/${STUB_MODEL}:max`);
	assert.equal(descriptor.thinking, "max");
	assert.ok(typeof descriptor.artifactsDir === "string" && !path.resolve(descriptor.artifactsDir).toLowerCase().startsWith(`${path.resolve(fixture.root).toLowerCase()}${path.sep}`));
	for (const [label, value] of [
		["status root", status],
		["status step", statusStep],
		["descriptor", descriptor],
		["result root", result],
		["result child", resultChild],
	]) {
		assert.ok(value?.filesystemPolicy, `${label} missing filesystemPolicy`);
		assert.equal(value.filesystemPolicyDigest, descriptor.filesystemPolicyDigest, `${label} digest mismatch`);
		assert.deepEqual(value.filesystemPolicy, descriptor.filesystemPolicy, `${label} policy mismatch`);
		assert.equal(value.cwd, fixture.root, `${label} cwd mismatch`);
	}
	for (const [label, value] of [
		["status root", status],
		["status step", statusStep],
		["result root", result],
		["result child", resultChild],
	]) {
		assert.equal(value.launchContractDigest, descriptor.launchContractDigest, `${label} launch digest mismatch`);
	}
	return {
		filesystemPolicyDigest: descriptor.filesystemPolicyDigest,
		launchContractDigest: descriptor.launchContractDigest,
		maxSubagentDepth: descriptor.maxSubagentDepth,
		inheritProjectContext: descriptor.inheritProjectContext,
		inheritSkills: descriptor.inheritSkills,
		artifactsDir: descriptor.artifactsDir,
	};
}

function assertNoPolicyAsyncSurfaces({ status, descriptor, result }, fixture) {
	const statusStep = status.steps?.[0];
	const resultChild = result.results?.[0];
	assert.equal(status.state, "complete");
	assert.equal(descriptor.model, `${STUB_PROVIDER}/${STUB_MODEL}:max`);
	assert.equal(descriptor.thinking, "max");
	for (const [label, value] of [
		["status root", status],
		["status step", statusStep],
		["descriptor", descriptor],
		["result root", result],
		["result child", resultChild],
	]) {
		assert.ok(value, `${label} missing`);
		assert.equal(value.filesystemPolicy, undefined, `${label} unexpectedly gained filesystemPolicy`);
		assert.equal(value.filesystemPolicyDigest, undefined, `${label} unexpectedly gained filesystemPolicyDigest`);
		assert.equal(value.cwd, fixture.root, `${label} cwd mismatch`);
	}
	return { model: descriptor.model, thinking: descriptor.thinking };
}

async function exerciseStaleRepairFromRealSurfaces(packageRoot, surfaces, fixture) {
	const { reconcileAsyncRun } = await import(pathToFileURL(path.join(packageRoot, "src", "runs", "background", "stale-run-reconciler.ts")).href);
	const { resolveAsyncResumeTarget } = await import(pathToFileURL(path.join(packageRoot, "src", "runs", "background", "async-resume.ts")).href);
	const staleRoot = path.join(fixture.root, "synthetic-stale-runs");
	const resultsRoot = path.join(fixture.root, "synthetic-stale-results");
	const staleRunId = randomUUID();
	const staleDir = path.join(staleRoot, staleRunId);
	fs.mkdirSync(staleDir, { recursive: true });
	fs.mkdirSync(resultsRoot, { recursive: true });
	writeJson(path.join(staleDir, "recovery-descriptor.json"), { ...surfaces.descriptor, sourceRunId: staleRunId });
	writeJson(path.join(staleDir, "status.json"), {
		...surfaces.status,
		runId: staleRunId,
		state: "running",
		pid: 2147483000,
		endedAt: undefined,
		processTerminal: undefined,
		steps: surfaces.status.steps.map((step) => ({ ...step, status: "running", endedAt: undefined, processTerminal: undefined })),
	});
	const deadPid = () => {
		const error = new Error("missing process");
		error.code = "ESRCH";
		throw error;
	};
	const repair = reconcileAsyncRun(staleDir, { resultsDir: resultsRoot, kill: deadPid, now: () => Date.now() + 1000 });
	assert.equal(repair.repaired, true);
	const repaired = readJson(path.join(resultsRoot, `${staleRunId}.json`));
	assert.deepEqual(repaired.filesystemPolicy, surfaces.descriptor.filesystemPolicy);
	assert.equal(repaired.filesystemPolicyDigest, surfaces.descriptor.filesystemPolicyDigest);
	assert.deepEqual(repaired.results?.[0]?.filesystemPolicy, surfaces.descriptor.filesystemPolicy);
	assert.equal(repaired.results?.[0]?.filesystemPolicyDigest, surfaces.descriptor.filesystemPolicyDigest);
	fs.rmSync(staleDir, { recursive: true, force: true });
	assert.throws(
		() => resolveAsyncResumeTarget({ id: staleRunId }, { asyncDirRoot: staleRoot, resultsDir: resultsRoot }, { requireSessionFile: false }),
		/recovery descriptor is missing filesystemPolicy evidence/,
	);
	return { repaired: true, resultOnlyResumeRejected: true };
}

async function main() {
	const args = parseArgs(process.argv.slice(2));
	const cliPath = required(args, "cli");
	const rpcClientPath = required(args, "rpc-client");
	const agentDir = required(args, "agent-dir");
	const moduleRoot = required(args, "module-root");
	const codexHome = required(args, "codex-home");
	const stopHarnessPath = required(args, "stop-harness");
	const stopExtensionPath = required(args, "stop-extension");
	const stopFixturePath = required(args, "stop-fixture");
	const fixtureRoot = required(args, "fixture-root");
	const sessionDir = required(args, "session-dir");
	const receiptPath = args.receipt ? path.resolve(args.receipt) : undefined;
	const timeoutMs = Number(args["timeout-ms"] ?? "120000");

	for (const file of [
		cliPath,
		rpcClientPath,
		stopHarnessPath,
		stopExtensionPath,
		stopFixturePath,
		path.join(agentDir, "npm", "node_modules", "pi-subagents", "src", "runs", "shared", "filesystem-policy.ts"),
	]) {
		assert.ok(fs.statSync(file).isFile(), `required file missing: ${file}`);
	}
	for (const directory of [agentDir, codexHome]) assert.ok(fs.statSync(directory).isDirectory(), `required directory missing: ${directory}`);
	fs.mkdirSync(fixtureRoot, { recursive: true });
	fs.mkdirSync(sessionDir, { recursive: true });
	const fixture = createFixture(fixtureRoot);
	const safeBefore = snapshotTree(fixture.safeRoot);
	const stub = await startStubServer(fixture);
	const restoreModels = configureStubModel(agentDir, stub.baseUrl);
	const { RpcClient } = await import(pathToFileURL(rpcClientPath).href);
	const cases = {};
	let durableEvidence;
	let staleEvidence;
	let stopEvidence;
	let bootstrapFailureEvidence;
	let missingRuntimeEvidence;
	let childToolEvidence;
	try {
		for (const caseName of [
			"CASE_FOREGROUND_SAFE",
			"CASE_DENIED_READ",
			"CASE_JUNCTION_READ",
			"CASE_BROAD_GREP",
			"CASE_SAFE_GREP",
			"CASE_BASH_DENY",
		]) {
			cases[caseName] = await runRootCase({ RpcClient, cliPath, agentDir, sessionDir, codexHome, fixture, caseName, timeoutMs });
		}
		const detachedAndResume = await runDetachedAndResumeCase({ RpcClient, cliPath, agentDir, sessionDir, codexHome, fixture, timeoutMs });
		cases.CASE_DETACHED_SAFE = detachedAndResume.detached;
		cases.CASE_RESUME_SAFE = detachedAndResume.resume;
		const surfaces = detachedAndResume.sourceSurfaces;
		durableEvidence = assertRestrictedAsyncSurfaces(surfaces, fixture);
		const resumedDurableEvidence = assertRestrictedAsyncSurfaces(detachedAndResume.resumeSurfaces, fixture);
		assert.equal(resumedDurableEvidence.filesystemPolicyDigest, durableEvidence.filesystemPolicyDigest, "resume changed retained filesystemPolicy digest");
		staleEvidence = await exerciseStaleRepairFromRealSurfaces(moduleRoot, surfaces, fixture);
		const noPolicyDetachedAndResume = await runDetachedAndResumeCase({
			RpcClient,
			cliPath,
			agentDir,
			sessionDir,
			codexHome,
			fixture,
			timeoutMs,
			detachedCaseName: "CASE_NO_POLICY_DETACHED_SAFE",
			resumeCaseName: "CASE_NO_POLICY_RESUME_SAFE",
		});
		cases.CASE_NO_POLICY_DETACHED_SAFE = noPolicyDetachedAndResume.detached;
		cases.CASE_NO_POLICY_RESUME_SAFE = noPolicyDetachedAndResume.resume;
		const noPolicyDurableEvidence = assertNoPolicyAsyncSurfaces(noPolicyDetachedAndResume.sourceSurfaces, fixture);
		const noPolicyResumeEvidence = assertNoPolicyAsyncSurfaces(noPolicyDetachedAndResume.resumeSurfaces, fixture);
		assert.deepEqual(noPolicyResumeEvidence, noPolicyDurableEvidence, "no-policy resume changed model identity/thinking evidence");
		cases.CASE_NO_POLICY_BASH = await runRootCase({ RpcClient, cliPath, agentDir, sessionDir, codexHome, fixture, caseName: "CASE_NO_POLICY_BASH", timeoutMs });
		bootstrapFailureEvidence = await runDirectPolicyBootstrapFailures({
			cliPath,
			agentDir,
			codexHome,
			fixture,
			timeoutMs,
			stub,
		});
		missingRuntimeEvidence = await runMissingForcedRuntimeParentLab({
			RpcClient,
			cliPath,
			agentDir,
			sessionDir,
			codexHome,
			fixture,
			timeoutMs,
			stub,
		});
		stopEvidence = await runOwnerStopProcessLab({
			cliPath,
			rpcClientPath,
			agentDir,
			codexHome,
			fixture,
			timeoutMs,
			stopHarnessPath,
			stopExtensionPath,
			stopFixturePath,
		});

		for (const [caseName, value] of Object.entries(cases)) {
			assert.equal(value.execution.end.isError, false, `${caseName} root subagent tool failed: ${JSON.stringify(value.execution.end)}`);
		}
		childToolEvidence = Object.fromEntries(
			Object.keys(cases).sort().map((caseName) => [caseName, assertChildToolEvidence(agentDir, fixture, caseName)]),
		);

		const detachedWorkflowValue = cases.CASE_DETACHED_SAFE.execution.end?.result?.details?.workflow?.value;
		const asyncDir = deepFindString(cases.CASE_DETACHED_SAFE.execution.end, "asyncDir")
			?? (Array.isArray(detachedWorkflowValue?.artifactPaths) ? detachedWorkflowValue.artifactPaths.find((value) => typeof value === "string") : undefined);
		assert.ok(asyncDir, "detached asyncDir missing");
		const asyncStatus = cases.CASE_DETACHED_SAFE.asyncStatus;
		assert.equal(asyncStatus.state, "complete", JSON.stringify(asyncStatus));

		const restrictedCases = new Set([
			"CASE_FOREGROUND_SAFE", "CASE_DENIED_READ", "CASE_JUNCTION_READ", "CASE_BROAD_GREP",
			"CASE_SAFE_GREP", "CASE_BASH_DENY", "CASE_DETACHED_SAFE", "CASE_RESUME_SAFE",
		]);
		const childRequests = stub.requests.filter((request) => !request.isRoot);
		assert.ok(childRequests.length >= restrictedCases.size + 1, `too few child requests: ${childRequests.length}`);
		assert.ok(
			childRequests.some((request) => request.caseName === "CASE_RESUME_SAFE"),
			`resume did not reach the retained child provider: ${JSON.stringify(cases.CASE_RESUME_SAFE.execution.end)}`,
		);
		for (const request of childRequests.filter((entry) => restrictedCases.has(entry.caseName))) {
			const serialized = JSON.stringify(request.body);
			assert.ok(!serialized.includes(fixture.contextSentinel), `${request.caseName} leaked cwd AGENTS sentinel to child provider`);
			assert.ok(!serialized.includes(fixture.deniedSentinel), `${request.caseName} leaked denied sentinel to child provider`);
			assert.ok(!serialized.includes(fixture.junctionSentinel), `${request.caseName} leaked junction target sentinel to child provider`);
			assert.deepEqual(request.toolNames.sort(), ["find", "grep", "ls", "read"], `${request.caseName} child tool set drifted`);
		}
		const rootAttackObserved = stub.requests.some((request) => request.isRoot && JSON.stringify(request.body).includes(fixture.contextSentinel));
		assert.equal(rootAttackObserved, true, "root request did not ingest the cwd AGENTS attack fixture; preload negative was not exercised");
		const bashProcessesCreated = Object.values(fixture.restrictedMarkers).some((markerPath) => fs.existsSync(markerPath));
		assert.equal(bashProcessesCreated, false, `restricted bash created a process marker: ${JSON.stringify(fixture.restrictedMarkers)}`);
		assert.equal(fs.readFileSync(path.join(fixture.root, "no-policy-created.txt"), "utf8"), "ok", "ordinary no-policy bash did not execute");
		assert.deepEqual(snapshotTree(fixture.safeRoot), safeBefore, "restricted allowed source tree changed");
		assert.equal(fs.existsSync(path.join(fixture.root, ".pi-subagents")), false, "restricted artifacts were written under child cwd");

		const transcriptBinding = Object.values(childToolEvidence)
			.sort((left, right) => left.caseName.localeCompare(right.caseName))
			.map((evidence) => `${evidence.caseName}\t${evidence.transcriptPath}\t${evidence.transcriptSha256}`)
			.join("\n");
		const harnessPath = path.resolve(process.argv[1]);
		const sourceSha256 = Object.fromEntries(POLICY_SOURCE_PATHS.map((relativePath) => [
			relativePath,
			sha256(fs.readFileSync(path.join(moduleRoot, relativePath))),
		]));
		const sourceAggregateSha256 = sha256(POLICY_SOURCE_PATHS
			.map((relativePath) => `${relativePath}\t${sourceSha256[relativePath]}\n`)
			.join(""));
		const receipt = {
			schema: "xinao.pi_subagents_filesystem_policy_body_lab.v1",
			status: "verified",
			provider: `${STUB_PROVIDER}/${STUB_MODEL}`,
			filesystem_policy_source_sha256: sourceSha256,
			filesystem_policy_source_aggregate_sha256: sourceAggregateSha256,
			foreground_safe_read: childToolEvidence.CASE_FOREGROUND_SAFE.isError === false,
			denied_read_blocked: childToolEvidence.CASE_DENIED_READ.isError === true,
			junction_escape_blocked_without_sentinel: childToolEvidence.CASE_JUNCTION_READ.isError === true,
			broad_grep_blocked: childToolEvidence.CASE_BROAD_GREP.isError === true,
			safe_sibling_grep: childToolEvidence.CASE_SAFE_GREP.isError === false,
			bash_processes_created: bashProcessesCreated,
			child_tool_result_evidence: childToolEvidence,
			child_tool_transcript_binding_sha256: sha256(transcriptBinding),
			lab_harness_path: harnessPath,
			lab_harness_sha256: sha256(fs.readFileSync(harnessPath)),
			detached_async_complete: true,
			pre_context_sentinel_absent_from_child_provider: true,
			root_attack_fixture_observed: true,
			no_policy_bash_unchanged: true,
			no_policy_detached_resume_unchanged: true,
			resume_retained_policy: true,
			resume_max_subagent_depth: durableEvidence.maxSubagentDepth,
			durable_root_child_policy_digest_consistent: true,
			durable_launch_digest_consistent: true,
			effective_inherit_project_context: durableEvidence.inheritProjectContext,
			effective_inherit_skills: durableEvidence.inheritSkills,
			restricted_artifacts_dir: durableEvidence.artifactsDir,
			stale_repair_retained_markers: staleEvidence.repaired,
			stale_result_only_resume_rejected: staleEvidence.resultOnlyResumeRejected,
			allowed_source_tree_unchanged: true,
			project_artifacts_written: false,
			owner_stop_process_verified: stopEvidence.status === "verified",
			owner_stop_process_terminated: stopEvidence.real_detached_process_terminated,
			owner_stop_commit_fence_rejected: stopEvidence.launch_commit_fence_rejected_race,
			owner_stop_source_sha256: stopEvidence.source_sha256,
			owner_stop_process_receipt: stopEvidence,
			preprovider_failure_cases: bootstrapFailureEvidence.cases,
			forced_runtime_missing_rejected_before_child_provider: missingRuntimeEvidence.launchRejected,
			filesystem_policy_runtime_path: bootstrapFailureEvidence.runtimePath,
			filesystem_policy_gate_path: bootstrapFailureEvidence.gatePath,
			async_id: detachedWorkflowValue?.runId ?? deepFindString(cases.CASE_DETACHED_SAFE.execution.end, "asyncId") ?? deepFindString(cases.CASE_DETACHED_SAFE.execution.end, "runId"),
			async_dir: asyncDir,
			request_count: stub.requests.length,
			child_request_count: childRequests.length,
		};
		if (receiptPath) writeJson(receiptPath, receipt);
		process.stdout.write(`${JSON.stringify(receipt)}\n`);
	} finally {
		restoreModels();
		await stub.close();
	}
}

main().catch((error) => {
	process.stderr.write(`PI_FILESYSTEM_POLICY_BODY_LAB_ERROR: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
	process.exitCode = 1;
});
