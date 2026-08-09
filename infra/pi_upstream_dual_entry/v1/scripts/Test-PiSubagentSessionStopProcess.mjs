import fs from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const harnessPath = fileURLToPath(import.meta.url);

function parseArgs(argv) {
	const result = {};
	for (let index = 0; index < argv.length; index += 1) {
		const token = argv[index];
		if (!token.startsWith("--")) throw new Error(`Unexpected argument: ${token}`);
		const value = argv[index + 1];
		if (!value || value.startsWith("--")) throw new Error(`Missing value for ${token}`);
		result[token.slice(2)] = value;
		index += 1;
	}
	return result;
}

function required(args, name) {
	if (!args[name]) throw new Error(`Missing --${name}`);
	return path.resolve(args[name]);
}

function writeJson(filePath, value) {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function readJson(filePath) {
	return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function sha256File(filePath) {
	return createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function findKey(value, key) {
	if (!value || typeof value !== "object") return undefined;
	if (Object.hasOwn(value, key) && typeof value[key] === "string") return value[key];
	for (const item of Array.isArray(value) ? value : Object.values(value)) {
		const found = findKey(item, key);
		if (found !== undefined) return found;
	}
	return undefined;
}

function processAlive(pid) {
	if (!Number.isSafeInteger(pid) || pid <= 0) return false;
	try {
		process.kill(pid, 0);
		return true;
	} catch {
		return false;
	}
}

function delay(milliseconds) {
	return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitForFile(filePath, timeoutMs) {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		if (fs.existsSync(filePath)) return;
		await delay(50);
	}
	throw new Error(`Timed out waiting for file: ${filePath}`);
}

function fixtureAgent(name, description) {
	return `---\nname: ${name}\ndescription: ${description}\nmodel: openai-codex/gpt-5.6-sol\nthinking: low\ntools: bash\nextensions:\nsystemPromptMode: replace\ninheritProjectContext: false\ninheritSkills: false\ndefaultContext: fresh\nasync: true\ntimeoutMs: 120000\ncompletionGuard: false\nmaxSubagentDepth: 0\nturnBudget: {"maxTurns":3,"graceTurns":0}\n---\nYou are a deterministic process-lifecycle fixture. Execute the exact bash command in the task immediately and exactly once. Do not explain, summarize, or return a final response while that tool call is running.\n`;
}

async function main() {
	const args = parseArgs(process.argv.slice(2));
	const cliPath = required(args, "cli");
	const rpcClientPath = required(args, "rpc-client");
	const agentDir = required(args, "agent-dir");
	const sessionDir = required(args, "session-dir");
	const codexHome = required(args, "codex-home");
	const cwd = required(args, "cwd");
	const extensionPath = required(args, "extension");
	const fixturePath = required(args, "fixture");
	const evidenceDir = required(args, "evidence-dir");
	const timeoutMs = Number(args["timeout-ms"] ?? "60000");
	const receiptOutput = args.receipt ? path.resolve(args.receipt) : undefined;
	const packageRoot = path.join(agentDir, "npm", "node_modules", "pi-subagents");
	const sourcePaths = {
		rpc: path.join(packageRoot, "src", "extension", "rpc.ts"),
		executor: path.join(packageRoot, "src", "runs", "foreground", "subagent-executor.ts"),
		process_guard: path.join(packageRoot, "src", "shared", "post-exit-stdio-guard.ts"),
		runner: path.join(packageRoot, "src", "runs", "background", "subagent-runner.ts"),
		test_extension: extensionPath,
		fixture: fixturePath,
		harness: harnessPath,
	};

	for (const filePath of [cliPath, rpcClientPath, ...Object.values(sourcePaths), path.join(agentDir, "PI_CONTRACT.md")]) {
		if (!fs.statSync(filePath).isFile()) throw new Error(`Required file is not a file: ${filePath}`);
	}
	for (const directory of [agentDir, sessionDir, codexHome, cwd]) {
		if (!fs.statSync(directory).isDirectory()) throw new Error(`Required directory is not a directory: ${directory}`);
	}

	fs.mkdirSync(evidenceDir, { recursive: true });
	const extensionReceiptPath = path.join(evidenceDir, "extension-receipt.json");
	const primaryReadyPath = path.join(evidenceDir, "primary-ready.json");
	const primaryExitPath = path.join(evidenceDir, "primary-exit.json");
	const raceReadyPath = path.join(evidenceDir, "race-ready.json");
	const raceExitPath = path.join(evidenceDir, "race-exit.json");
	for (const stalePath of [extensionReceiptPath, primaryReadyPath, primaryExitPath, raceReadyPath, raceExitPath]) {
		fs.rmSync(stalePath, { force: true });
	}
	const primaryAgent = "stop-fixture";
	const raceAgent = "stop-race-fixture";
	const agentProjection = path.join(agentDir, "agents");
	fs.mkdirSync(agentProjection, { recursive: true });
	writeJson(path.join(evidenceDir, "test-inputs.json"), {
		cli_path: cliPath,
		agent_dir: agentDir,
		session_dir: sessionDir,
		extension_path: extensionPath,
		fixture_path: fixturePath,
	});
	fs.writeFileSync(
		path.join(agentProjection, `${primaryAgent}.md`),
		fixtureAgent(primaryAgent, "Isolated owner Stop process fixture."),
		"utf8",
	);
	fs.writeFileSync(
		path.join(agentProjection, `${raceAgent}.md`),
		fixtureAgent(raceAgent, "Isolated owner Stop race fixture; launch must be rejected."),
		"utf8",
	);

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
			"--extension", extensionPath,
			"--append-system-prompt", path.join(agentDir, "PI_CONTRACT.md"),
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
			XINAO_PI_OWNER_STOP_PROCESS_RECEIPT: extensionReceiptPath,
			XINAO_PI_OWNER_STOP_PRIMARY_READY: primaryReadyPath,
			XINAO_PI_OWNER_STOP_PRIMARY_EXIT: primaryExitPath,
			XINAO_PI_OWNER_STOP_RACE_READY: raceReadyPath,
			XINAO_PI_OWNER_STOP_RACE_EXIT: raceExitPath,
			XINAO_PI_OWNER_STOP_FIXTURE: fixturePath.replaceAll("\\", "/"),
			XINAO_PI_OWNER_STOP_PRIMARY_AGENT: primaryAgent,
			XINAO_PI_OWNER_STOP_RACE_AGENT: raceAgent,
		},
	});

	try {
		await client.start();
		await waitForFile(extensionReceiptPath, timeoutMs);
		const extensionReceipt = readJson(extensionReceiptPath);
		if (extensionReceipt.error) throw new Error(`Fixture extension failed: ${extensionReceipt.error}`);
		const spawn = extensionReceipt.primary_spawn;
		const stop = extensionReceipt.stop_reply;
		const race = extensionReceipt.race_spawn;
		if (spawn?.success !== true) throw new Error(`Primary spawn was not accepted: ${JSON.stringify(spawn)}`);
		if (stop?.success !== true || stop?.data?.status !== "verified" || stop?.data?.stopFence !== true) {
			throw new Error(`Owner-session Stop was not verified: ${JSON.stringify(stop)}`);
		}
		if (race?.success !== false || !/stop|fence|shut/i.test(String(race?.error?.message ?? ""))) {
			throw new Error(`Commit-fence race launch was not rejected: ${JSON.stringify(race)}`);
		}
		if (fs.existsSync(raceReadyPath)) throw new Error(`Race child started despite the Stop fence: ${raceReadyPath}`);

		const outerAsyncDir = findKey(spawn, "asyncDir");
		if (!outerAsyncDir) throw new Error(`Primary spawn omitted outer async directory: ${JSON.stringify(spawn)}`);
		const result = stop.data.results?.find(
			(item) => item?.kind === "detached" && item?.disposition === "stopped_observed",
		);
		if (!result || result.kind !== "detached" || result.disposition !== "stopped_observed") {
			throw new Error(`Detached target lacks observed Stop proof: ${JSON.stringify(stop.data.results)}`);
		}
		const runId = result.runId;
		const asyncDir = path.join(path.dirname(outerAsyncDir), runId);

		const status = readJson(path.join(asyncDir, "status.json"));
		const processTerminal = readJson(path.join(asyncDir, "process-terminal.json"));
		const childReady = readJson(primaryReadyPath);
		if (status.state !== "stopped") throw new Error(`Detached status is not stopped: ${JSON.stringify(status)}`);
		if (processTerminal.state !== "observed") throw new Error(`Process terminal proof is not observed: ${JSON.stringify(processTerminal)}`);
		const deathDeadline = Date.now() + 5_000;
		while (Date.now() < deathDeadline && processAlive(childReady.pid)) await delay(50);
		if (processAlive(childReady.pid)) throw new Error(`External child PID survived owner Stop: ${childReady.pid}`);

		const receipt = {
			schema: "xinao.pi_subagent_owner_session_stop_process_acceptance.v2",
			status: "verified",
			profile_local: true,
			real_detached_process_started: true,
			real_detached_process_terminated: true,
			process_terminal_observed: true,
			status_stopped: true,
			launch_commit_fence_rejected_race: true,
			async_id: runId,
			child_pid: childReady.pid,
			stop_disposition: result.disposition,
			source_sha256: Object.fromEntries(
				Object.entries(sourcePaths).map(([name, filePath]) => [name, sha256File(filePath)]),
			),
		};
		if (receiptOutput) writeJson(receiptOutput, receipt);
		process.stdout.write(`${JSON.stringify(receipt)}\n`);
	} finally {
		await client.stop();
	}
}

main().catch((error) => {
	process.stderr.write(`PI_SUBAGENT_OWNER_SESSION_STOP_PROCESS_TEST_ERROR: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
	process.exitCode = 1;
});
