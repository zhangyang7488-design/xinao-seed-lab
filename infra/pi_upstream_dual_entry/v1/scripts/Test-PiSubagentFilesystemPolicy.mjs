import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";

const candidateRoot = process.argv[2];
if (!candidateRoot || !fs.statSync(candidateRoot).isDirectory()) {
	throw new Error("usage: node --experimental-strip-types Test-PiSubagentFilesystemPolicy.mjs <pi-subagents-package-root>");
}

const load = (relativePath) => import(pathToFileURL(path.join(candidateRoot, relativePath)).href);
const policyModule = await load("src/runs/shared/filesystem-policy.ts");
const piArgsModule = await load("src/runs/shared/pi-args.ts");
const launchModule = await load("src/shared/launch-contract.ts");
const asyncExecutionModule = await load("src/runs/background/async-execution.ts");
const asyncResumeModule = await load("src/runs/background/async-resume.ts");
const staleReconcilerModule = await load("src/runs/background/stale-run-reconciler.ts");
const foregroundExecutionModule = await load("src/runs/foreground/execution.ts");
const executorModule = await load("src/runs/foreground/subagent-executor.ts");
const workflowModule = await load("src/workflows/scripted-workflow.ts");
const typesModule = await load("src/shared/types.ts");

const {
	FILESYSTEM_POLICY_REQUIRED_ENV,
	FILESYSTEM_POLICY_ENV,
	FILESYSTEM_POLICY_SHA256_ENV,
	FILESYSTEM_POLICY_RUNTIME_PATH_ENV,
	FILESYSTEM_POLICY_RUNTIME_SHA256_ENV,
	FILESYSTEM_POLICY_GATE_PATH_ENV,
	FILESYSTEM_POLICY_GATE_SHA256_ENV,
	FILESYSTEM_POLICY_MODULE_PATH,
	resolveFilesystemPolicy,
	evaluateFilesystemPolicyToolCall,
	registerFilesystemPolicyGate,
	encodeFilesystemPolicy,
	filesystemPolicyDigest,
	fileSha256,
	decodeFilesystemPolicyEnvironment,
	assertFilesystemPolicyLaunchContract,
} = policyModule;
const {
	PROMPT_RUNTIME_EXTENSION_PATH,
	buildPiArgs,
	cleanupTempDir,
	resolvePiLaunchToolPlan,
} = piArgsModule;
const { launchBindingDigest } = launchModule;
const { buildAsyncRunnerSteps, executeAsyncSingle } = asyncExecutionModule;
const { readAsyncRecoveryDescriptor, resolveAsyncResumeTarget } = asyncResumeModule;
const { reconcileAsyncRun } = staleReconcilerModule;
const { runSync } = foregroundExecutionModule;
const { prepareWorkflowLaunchParams } = executorModule;
const { runWorkflowScript } = workflowModule;
const { DIRS, TEMP_ARTIFACTS_DIR } = typesModule;

const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const expectBlocked = (policy, toolName, input, fragment) => {
	const decision = evaluateFilesystemPolicyToolCall(policy, toolName, input);
	assert.equal(decision.allowed, false, `${toolName} unexpectedly allowed: ${JSON.stringify(input)}`);
	if (fragment) assert.match(decision.reason ?? "", fragment);
	return decision;
};
const expectAllowed = (policy, toolName, input) => {
	const decision = evaluateFilesystemPolicyToolCall(policy, toolName, input);
	assert.equal(decision.allowed, true, `${toolName} unexpectedly blocked: ${decision.reason}`);
	return decision;
};
const throws = (fn, pattern) => assert.throws(fn, pattern);

const runtimeTempRoot = "D:\\XINAO_RESEARCH_RUNTIME\\temp";
fs.mkdirSync(runtimeTempRoot, { recursive: true });
const fixtureRoot = fs.mkdtempSync(path.join(runtimeTempRoot, "pi-fs-policy-security-"));
const sentinel = `FORBIDDEN_SENTINEL_${Date.now()}_${process.pid}`;
const allowedRoot = path.join(fixtureRoot, "AllowedRoot");
const safeRoot = path.join(allowedRoot, "safe-sibling");
const deniedRoot = path.join(allowedRoot, "denied-subtree");
const outsideRoot = path.join(fixtureRoot, `outside-${sentinel}`);
const safeFile = path.join(safeRoot, "safe.txt");
const deniedFile = path.join(deniedRoot, "secret.txt");
const outsideFile = path.join(outsideRoot, "outside.txt");
const junctionPath = path.join(allowedRoot, "junction-outside");
const bashMarkers = [];
const checks = {};

try {
	for (const dir of [safeRoot, deniedRoot, outsideRoot]) fs.mkdirSync(dir, { recursive: true });
	fs.writeFileSync(safeFile, "SAFE_PROJECTION_CONTENT\n", "utf8");
	fs.writeFileSync(deniedFile, `${sentinel}\n`, "utf8");
	fs.writeFileSync(outsideFile, `${sentinel}\n`, "utf8");
	fs.symlinkSync(outsideRoot, junctionPath, "junction");
	assert.equal(fs.realpathSync.native(junctionPath), fs.realpathSync.native(outsideRoot));

	const policy = resolveFilesystemPolicy({
		allowedRoots: [allowedRoot.replace(/\\/g, "/"), allowedRoot.toLowerCase()],
		deniedPaths: [deniedRoot.replace(/\\/g, "/")],
		bash: "deny",
	}, allowedRoot);
	assert.equal(policy.version, 1);
	assert.equal(policy.bash, "deny");
	assert.deepEqual(policy.allowedTools, ["read", "grep", "find", "ls"]);
	assert.equal(policy.allowedRoots.length, 1, "case/slash-equivalent allowed roots must deduplicate");
	checks.normalization = true;

	const safeRelative = path.relative(allowedRoot, safeFile);
	expectAllowed(policy, "read", { path: safeRelative });
	expectAllowed(policy, "read", { path: safeFile.toUpperCase().replace(/\\/g, "/") });
	assert.equal(fs.readFileSync(expectAllowed(policy, "read", { path: safeFile }).resolvedPath, "utf8"), "SAFE_PROJECTION_CONTENT\n");
	checks.safeRead = true;

	expectBlocked(policy, "read", { path: deniedFile }, /deniedPaths/);
	expectBlocked(policy, "read", { path: deniedFile.toUpperCase().replace(/\\/g, "/") }, /deniedPaths/);
	expectBlocked(policy, "read", { path: path.join("..", "outside", "outside.txt") }, /traversal/);
	expectBlocked(policy, "read", { path: outsideFile }, /outside allowedRoots/);
	const junctionDecision = expectBlocked(policy, "read", { path: path.join(junctionPath, "outside.txt") }, /outside allowedRoots/);
	assert.equal((junctionDecision.reason ?? "").includes(sentinel), false, "child-visible block reason must not disclose a junction target path");
	checks.deniedTraversalCaseSlashJunction = true;

	expectBlocked(policy, "grep", { path: allowedRoot, pattern: "safe" }, /ancestor of a denied subtree/);
	expectAllowed(policy, "grep", { path: safeRoot, pattern: "../outside" });
	expectBlocked(policy, "grep", { path: safeRoot, pattern: "safe", glob: "../outside" }, /glob\/pattern/);
	expectBlocked(policy, "grep", { path: safeRoot, pattern: "safe", glob: outsideFile.replace(/\\/g, "/") }, /glob\/pattern/);
	expectBlocked(policy, "find", { path: allowedRoot, pattern: "safe" }, /ancestor of a denied subtree/);
	expectAllowed(policy, "find", { path: safeRoot, pattern: "safe" });
	expectBlocked(policy, "find", { path: safeRoot, pattern: "../outside" }, /glob\/pattern/);
	expectBlocked(policy, "ls", { path: allowedRoot }, /ancestor of a denied subtree/);
	expectAllowed(policy, "ls", { path: safeRoot });
	// ls has no pattern/glob argument in Pi. Unknown and malformed arguments
	// fail closed instead of being reinterpreted as path selectors.
	expectBlocked(policy, "ls", { path: safeRoot, pattern: "../outside" }, /unknown argument/);
	expectBlocked(policy, "grep", { path: safeRoot, pattern: ["safe"] }, /malformed/);
	expectBlocked(policy, "grep", { path: safeRoot, pattern: "safe", glob: ["*.txt"] }, /malformed/);
	expectBlocked(policy, "find", { path: safeRoot }, /malformed/);
	expectBlocked(policy, "read", { path: safeFile, mystery: true }, /unknown argument/);
	checks.broadSearchBlockedSafeSiblingAllowed = true;
	checks.toolSchemaTypingFailClosed = true;

	expectBlocked(policy, "write", { path: safeFile }, /fixed read\/grep\/find\/ls allowlist/);
	expectBlocked(policy, "edit", { path: safeFile }, /fixed read\/grep\/find\/ls allowlist/);
	expectBlocked(policy, "custom_file_tool", { path: safeFile }, /fixed read\/grep\/find\/ls allowlist/);
	checks.unknownToolsBlocked = true;

	let toolHandler;
	const fakePi = { on(event, handler) { if (event === "tool_call") toolHandler = handler; } };
	const encoded = encodeFilesystemPolicy(policy);
	const validEnv = {
		[FILESYSTEM_POLICY_REQUIRED_ENV]: "1",
		[FILESYSTEM_POLICY_ENV]: encoded.payload,
		[FILESYSTEM_POLICY_SHA256_ENV]: encoded.digest,
		[FILESYSTEM_POLICY_RUNTIME_PATH_ENV]: PROMPT_RUNTIME_EXTENSION_PATH,
		[FILESYSTEM_POLICY_RUNTIME_SHA256_ENV]: fileSha256(PROMPT_RUNTIME_EXTENSION_PATH),
		[FILESYSTEM_POLICY_GATE_PATH_ENV]: FILESYSTEM_POLICY_MODULE_PATH,
		[FILESYSTEM_POLICY_GATE_SHA256_ENV]: fileSha256(FILESYSTEM_POLICY_MODULE_PATH),
	};
	registerFilesystemPolicyGate(fakePi, validEnv, PROMPT_RUNTIME_EXTENSION_PATH);
	assert.equal(typeof toolHandler, "function");
	for (const [name, command] of [
		["rg", `rg ${sentinel} .`],
		["powershell", `powershell -NoProfile -Command \"Set-Content '${path.join(fixtureRoot, "ps.marker")}' '${sentinel}'\"`],
		["node", `node -e \"require('fs').writeFileSync('${path.join(fixtureRoot, "node.marker")}', '${sentinel}')\"`],
		["python", `python -c \"open(r'${path.join(fixtureRoot, "python.marker")}','w').write('${sentinel}')\"`],
	]) {
		const marker = path.join(fixtureRoot, `${name}.marker`);
		bashMarkers.push(marker);
		const decision = await toolHandler({ toolName: "bash", input: { command } });
		assert.equal(decision?.block, true);
		assert.match(decision?.reason ?? "", /bash is always denied/);
		assert.equal(fs.existsSync(marker), false, `${name} marker proves a process ran`);
	}
	checks.bashNoProcess = true;

	assert.deepEqual(decodeFilesystemPolicyEnvironment(validEnv, PROMPT_RUNTIME_EXTENSION_PATH), policy);
	for (const envKey of [
		FILESYSTEM_POLICY_REQUIRED_ENV,
		FILESYSTEM_POLICY_ENV,
		FILESYSTEM_POLICY_SHA256_ENV,
		FILESYSTEM_POLICY_RUNTIME_PATH_ENV,
		FILESYSTEM_POLICY_RUNTIME_SHA256_ENV,
		FILESYSTEM_POLICY_GATE_PATH_ENV,
		FILESYSTEM_POLICY_GATE_SHA256_ENV,
	]) {
		const missing = { ...validEnv };
		delete missing[envKey];
		throws(() => decodeFilesystemPolicyEnvironment(missing, PROMPT_RUNTIME_EXTENSION_PATH), /Invalid|Missing|identity/);
	}
	const corruptJson = { ...validEnv, [FILESYSTEM_POLICY_ENV]: "{" };
	corruptJson[FILESYSTEM_POLICY_SHA256_ENV] = sha256(corruptJson[FILESYSTEM_POLICY_ENV]);
	throws(() => decodeFilesystemPolicyEnvironment(corruptJson, PROMPT_RUNTIME_EXTENSION_PATH), /not valid JSON/);
	throws(() => decodeFilesystemPolicyEnvironment({ ...validEnv, [FILESYSTEM_POLICY_SHA256_ENV]: "0".repeat(64) }, PROMPT_RUNTIME_EXTENSION_PATH), /hash mismatch/);
	throws(() => decodeFilesystemPolicyEnvironment({ ...validEnv, [FILESYSTEM_POLICY_RUNTIME_SHA256_ENV]: "0".repeat(64) }, PROMPT_RUNTIME_EXTENSION_PATH), /runtime hash mismatch/);
	throws(() => decodeFilesystemPolicyEnvironment({ ...validEnv, [FILESYSTEM_POLICY_GATE_SHA256_ENV]: "0".repeat(64) }, PROMPT_RUNTIME_EXTENSION_PATH), /gate module hash mismatch/);
	checks.environmentFailClosed = true;

	const launch = buildPiArgs({
		baseArgs: ["--mode", "json", "-p"],
		task: "read only the safe projection",
		sessionEnabled: false,
		inheritProjectContext: true,
		inheritSkills: true,
		tools: ["read", "grep", "find", "ls", "bash", "write", "custom_file_tool", "C:\\untrusted\\extension.ts"],
		extensions: ["C:\\untrusted\\ambient.ts"],
		subagentOnlyExtensions: ["C:\\untrusted\\child.ts"],
		mcpDirectTools: ["filesystem/custom"],
		cwd: allowedRoot,
		childAgentName: "peer",
		filesystemPolicy: policy,
	});
	try {
		const toolsIndex = launch.args.indexOf("--tools");
		assert.notEqual(toolsIndex, -1);
		assert.deepEqual(new Set(launch.args[toolsIndex + 1].split(",")), new Set(["read", "grep", "find", "ls"]));
		assert.ok(launch.args.includes("--no-extensions"));
		assert.ok(launch.args.includes("--no-context-files"));
		assert.ok(launch.args.includes("--no-skills"));
		assert.equal(launch.env.PI_SUBAGENT_INHERIT_PROJECT_CONTEXT, "0");
		assert.equal(launch.env.PI_SUBAGENT_INHERIT_SKILLS, "0");
		const extensionValues = launch.args.flatMap((arg, index) => arg === "--extension" ? [launch.args[index + 1]] : []);
		assert.deepEqual(extensionValues, [PROMPT_RUNTIME_EXTENSION_PATH]);
		assert.equal(launch.args.includes("bash"), false);
		assertFilesystemPolicyLaunchContract({ policy, args: launch.args, env: launch.env, runtimeModulePath: PROMPT_RUNTIME_EXTENSION_PATH });

		let providerCalls = 0;
		const preflightThenProvider = (args, env) => {
			assertFilesystemPolicyLaunchContract({ policy, args, env, runtimeModulePath: PROMPT_RUNTIME_EXTENSION_PATH });
			providerCalls++;
		};
		for (const mutate of [
			(args, env) => { env[FILESYSTEM_POLICY_REQUIRED_ENV] = ""; },
			(args, env) => { env[FILESYSTEM_POLICY_ENV] = ""; },
			(args, env) => { env[FILESYSTEM_POLICY_ENV] = "{"; },
			(args, env) => { env[FILESYSTEM_POLICY_SHA256_ENV] = "0".repeat(64); },
			(args) => { const index = args.indexOf("--extension"); args.splice(index, 2); },
			(args, env) => { env[FILESYSTEM_POLICY_RUNTIME_SHA256_ENV] = "0".repeat(64); },
			(args, env) => { env[FILESYSTEM_POLICY_GATE_SHA256_ENV] = "0".repeat(64); },
		]) {
			const args = [...launch.args];
			const env = { ...launch.env };
			mutate(args, env);
			throws(() => preflightThenProvider(args, env), /filesystem policy|Filesystem policy|Invalid|Missing|hash|runtime/i);
		}
		assert.equal(providerCalls, 0, "provider must not be reached by any corrupt launch contract");
		checks.preProviderFailClosed = true;
	} finally {
		cleanupTempDir(launch.tempDir);
	}

	const priorEnv = Object.fromEntries([
		FILESYSTEM_POLICY_REQUIRED_ENV,
		FILESYSTEM_POLICY_ENV,
		FILESYSTEM_POLICY_SHA256_ENV,
		FILESYSTEM_POLICY_RUNTIME_PATH_ENV,
		FILESYSTEM_POLICY_RUNTIME_SHA256_ENV,
		FILESYSTEM_POLICY_GATE_PATH_ENV,
		FILESYSTEM_POLICY_GATE_SHA256_ENV,
	].map((key) => [key, process.env[key]]));
	try {
		for (const key of Object.keys(priorEnv)) process.env[key] = "stale-inherited-policy";
		const ordinaryLaunch = buildPiArgs({
			baseArgs: ["--mode", "json", "-p"],
			task: "ordinary peer",
			sessionEnabled: false,
			inheritProjectContext: true,
			inheritSkills: true,
			tools: ["read", "grep", "find", "ls", "bash"],
			cwd: safeRoot,
			childAgentName: "peer",
		});
		try {
			for (const key of Object.keys(priorEnv)) assert.equal(ordinaryLaunch.env[key], "", `${key} must shadow inherited policy state`);
			const ordinaryPlan = resolvePiLaunchToolPlan({ tools: ["read", "grep", "find", "ls", "bash"] });
			assert.ok(ordinaryPlan.effectiveToolAllowlist.includes("bash"));
			assert.ok(ordinaryPlan.effectiveToolAllowlist.includes("read"));
			let ordinaryHandler;
			assert.equal(registerFilesystemPolicyGate({ on(event, handler) { ordinaryHandler = handler; } }, ordinaryLaunch.env, PROMPT_RUNTIME_EXTENSION_PATH), undefined);
			assert.equal(ordinaryHandler, undefined);
			assert.equal(fs.readFileSync(safeFile, "utf8"), "SAFE_PROJECTION_CONTENT\n");
			const harmless = spawnSync(process.execPath, ["-e", "process.stdout.write('ordinary-bash-ok')"], { encoding: "utf8", windowsHide: true });
			assert.equal(harmless.status, 0);
			assert.equal(harmless.stdout, "ordinary-bash-ok");
			checks.noPolicyUnchanged = true;
		} finally {
			cleanupTempDir(ordinaryLaunch.tempDir);
		}
	} finally {
		for (const [key, value] of Object.entries(priorEnv)) {
			if (value === undefined) delete process.env[key];
			else process.env[key] = value;
		}
	}

	const baseBinding = {
		definitionDigest: "d".repeat(64),
		task: "same task",
		inheritProjectContext: false,
		inheritSkills: false,
		tools: ["read", "grep", "find", "ls"],
	};
	const withoutPolicyDigest = launchBindingDigest(baseBinding);
	const restrictedArtifactConfig = {
		enabled: true,
		dir: "temp",
		includeInput: true,
		includeOutput: true,
		includeJsonl: false,
		includeTranscript: true,
		includeMetadata: true,
		cleanupDays: 7,
	};
	const withPolicyDigest = launchBindingDigest({ ...baseBinding, filesystemPolicy: policy, artifactsDir: TEMP_ARTIFACTS_DIR, artifactConfig: restrictedArtifactConfig });
	assert.notEqual(withPolicyDigest, withoutPolicyDigest);
	const expandedPolicy = resolveFilesystemPolicy({ allowedRoots: [fixtureRoot], deniedPaths: [deniedRoot] }, allowedRoot);
	assert.notEqual(launchBindingDigest({ ...baseBinding, filesystemPolicy: expandedPolicy, artifactsDir: TEMP_ARTIFACTS_DIR, artifactConfig: restrictedArtifactConfig }), withPolicyDigest);
	assert.notEqual(launchBindingDigest({ ...baseBinding, filesystemPolicy: policy, artifactsDir: path.join(allowedRoot, ".pi-subagents", "artifacts"), artifactConfig: { ...restrictedArtifactConfig, dir: "project" } }), withPolicyDigest);
	checks.launchDigestBound = true;

	const workflowDefault = { filesystemPolicy: { allowedRoots: [allowedRoot], deniedPaths: [deniedRoot], bash: "deny" } };
	const defaultLaunch = prepareWorkflowLaunchParams(workflowDefault, { agent: "peer", task: "safe" }, "wf-parent", "safe-default");
	assert.deepEqual(defaultLaunch.filesystemPolicy, workflowDefault.filesystemPolicy);
	const itemPolicy = { allowedRoots: [safeRoot], deniedPaths: [], bash: "deny" };
	const itemLaunch = prepareWorkflowLaunchParams(workflowDefault, { agent: "peer", task: "safe", filesystemPolicy: itemPolicy }, "wf-parent", "safe-item");
	assert.deepEqual(itemLaunch.filesystemPolicy, itemPolicy);
	throws(() => prepareWorkflowLaunchParams(workflowDefault, { agent: "peer", task: "unsafe-combination", worktree: true }, "wf-parent", "worktree-policy"), /cannot be combined with worktree:true/);
	const resumeLaunch = prepareWorkflowLaunchParams(workflowDefault, { resume: "run-123", task: "follow-up" }, "wf-parent", "resume");
	assert.equal(resumeLaunch.filesystemPolicy, undefined, "workflow defaults must not replace a retained resume policy");
	throws(() => prepareWorkflowLaunchParams(workflowDefault, { resume: "run-123", task: "follow-up", filesystemPolicy: { allowedRoots: [fixtureRoot] } }, "wf-parent", "resume-expand"), /cannot be overridden/);
	checks.workflowDefaultAndItemResumeNoExpansion = true;

	const hostBypassMarker = path.join(fixtureRoot, "host-bypass.marker");
	const hostBypassCommand = `node -e "require('fs').writeFileSync(${JSON.stringify(hostBypassMarker)}, 'bypass')"`;
	for (const [label, child, pattern] of [
		["gate", { agent: "peer", task: "safe", gate: hostBypassCommand }, /cannot use gate commands/],
		["verify", { agent: "peer", task: "safe", acceptance: { level: "verified", verify: [{ id: "escape", command: hostBypassCommand }] } }, /acceptance\.verify/],
		["review", { agent: "peer", task: "safe", acceptance: { level: "checked", review: { agent: "writer", required: true } } }, /acceptance\.review/],
		["output", { agent: "peer", task: "safe", output: hostBypassMarker }, /host-side output/],
		["file-only", { agent: "peer", task: "safe", outputMode: "file-only" }, /file-only/],
		["share", { agent: "peer", task: "safe", share: true }, /share child sessions/],
	]) {
		throws(() => prepareWorkflowLaunchParams(workflowDefault, child, "wf-parent", `blocked-${label}`), pattern);
		assert.equal(fs.existsSync(hostBypassMarker), false, `${label} bypass must not create a process or file`);
	}
	const safeCheckedLaunch = prepareWorkflowLaunchParams(workflowDefault, { agent: "peer", task: "safe", acceptance: "checked" }, "wf-parent", "checked");
	assert.equal(safeCheckedLaunch.acceptance, "checked");
	assert.equal(safeCheckedLaunch.output, false);
	assert.equal(safeCheckedLaunch.outputMode, "inline");
	assert.equal(safeCheckedLaunch.share, false);
	assert.equal(safeCheckedLaunch.context, "fresh");
	checks.hostAcceptanceOutputSharePreLaunchReject = true;

	const workflowLaunchStub = (launches) => async (key) => {
		launches.push(key);
		return { key, ok: true, output: `ok:${key}`, artifactPaths: [] };
	};
	{
		const launches = [];
		await assert.rejects(() => runWorkflowScript({
			script: `await runs.run("first", { agent: "peer", task: "safe" }); return runs.run("second", { agent: "peer", task: "safe" });`,
			defaultFilesystemPolicyActive: true,
			launch: workflowLaunchStub(launches),
			status: async () => ({ key: "status", ok: true, output: "ok", artifactPaths: [] }),
		}), /only child launch|only permitted launch/);
		assert.deepEqual(launches, ["first"]);
	}
	{
		const launches = [];
		await assert.rejects(() => runWorkflowScript({
			script: `return runs.all([{ key: "a", agent: "peer", task: "safe" }, { key: "b", agent: "peer", task: "safe" }]);`,
			defaultFilesystemPolicyActive: true,
			launch: workflowLaunchStub(launches),
			status: async () => ({ key: "status", ok: true, output: "ok", artifactPaths: [] }),
		}), /cannot be used with runs\.all/);
		assert.deepEqual(launches, []);
	}
	for (const script of [
		`await runs.run("plain", { agent: "peer", task: "safe" }); return runs.run("restricted", { agent: "peer", task: "safe", filesystemPolicy: { allowedRoots: ["safe"] } });`,
		`await runs.run("restricted", { agent: "peer", task: "safe", filesystemPolicy: { allowedRoots: ["safe"] } }); return runs.run("plain", { agent: "peer", task: "safe" });`,
	]) {
		const launches = [];
		await assert.rejects(() => runWorkflowScript({
			script,
			launch: workflowLaunchStub(launches),
			status: async () => ({ key: "status", ok: true, output: "ok", artifactPaths: [] }),
		}), /only child launch|only permitted launch/);
		assert.equal(launches.length, 1);
	}
	{
		const launches = [];
		const reused = await runWorkflowScript({
			script: `const a = await runs.run("restricted", { agent: "peer", task: "safe", filesystemPolicy: { allowedRoots: ["safe"] } }); const b = await runs.run("restricted", { agent: "peer", task: "safe", filesystemPolicy: { allowedRoots: ["safe"] } }); return [a.output, b.output];`,
			launch: workflowLaunchStub(launches),
			status: async () => ({ key: "status", ok: true, output: "ok", artifactPaths: [] }),
		});
		assert.deepEqual(reused.value, ["ok:restricted", "ok:restricted"]);
		assert.deepEqual(launches, ["restricted"]);
	}
	checks.workflowRestrictedSingleLaunchOnly = true;

	const asyncDir = path.join(fixtureRoot, "async-descriptor");
	fs.mkdirSync(asyncDir, { recursive: true });
	const descriptorPath = path.join(asyncDir, "recovery-descriptor.json");
	const descriptor = {
		version: 1,
		sourceRunId: "run-policy",
		agent: "peer",
		cwd: policy.cwd,
		systemPromptMode: "append",
		outputMode: "inline",
		inheritProjectContext: false,
		inheritSkills: false,
		acceptance: false,
		share: false,
		maxSubagentDepth: 0,
		artifactsDir: TEMP_ARTIFACTS_DIR,
		artifactConfig: restrictedArtifactConfig,
		filesystemPolicy: policy,
		filesystemPolicyDigest: filesystemPolicyDigest(policy),
	};
	fs.writeFileSync(descriptorPath, JSON.stringify(descriptor));
	const retained = readAsyncRecoveryDescriptor(asyncDir);
	assert.deepEqual(retained.filesystemPolicy, policy);
	assert.equal(retained.filesystemPolicyDigest, filesystemPolicyDigest(policy));
	fs.writeFileSync(descriptorPath, JSON.stringify({ ...descriptor, filesystemPolicy: expandedPolicy }));
	throws(() => readAsyncRecoveryDescriptor(asyncDir), /filesystemPolicyDigest mismatch/);
	fs.writeFileSync(descriptorPath, JSON.stringify({ ...descriptor, maxSubagentDepth: 1 }));
	throws(() => readAsyncRecoveryDescriptor(asyncDir), /maxSubagentDepth=0/);
	fs.writeFileSync(descriptorPath, JSON.stringify({ ...descriptor, acceptance: { level: "verified", verify: [{ id: "escape", command: hostBypassCommand }] } }));
	throws(() => readAsyncRecoveryDescriptor(asyncDir), /acceptance\.verify/);
	fs.writeFileSync(descriptorPath, JSON.stringify({ ...descriptor, artifactsDir: path.join(allowedRoot, ".pi-subagents", "artifacts") }));
	throws(() => readAsyncRecoveryDescriptor(asyncDir), /managed temp artifacts directory/);
	fs.writeFileSync(descriptorPath, JSON.stringify({ ...descriptor, artifactConfig: { ...restrictedArtifactConfig, dir: "project" } }));
	throws(() => readAsyncRecoveryDescriptor(asyncDir), /artifactConfig\.dir='temp'/);
	fs.writeFileSync(descriptorPath, JSON.stringify({ ...descriptor, filesystemPolicy: undefined }));
	throws(() => readAsyncRecoveryDescriptor(asyncDir), /filesystemPolicyDigest requires/);

	const resumeAsyncRoot = path.join(fixtureRoot, "async-resume-root");
	const resumeResultsRoot = path.join(fixtureRoot, "async-resume-results");
	const resumeRunId = "resume-policy-run";
	const resumeRunDir = path.join(resumeAsyncRoot, resumeRunId);
	const resumeDescriptorPath = path.join(resumeRunDir, "recovery-descriptor.json");
	const resumeStatusPath = path.join(resumeRunDir, "status.json");
	const resumeResultPath = path.join(resumeResultsRoot, `${resumeRunId}.json`);
	fs.mkdirSync(resumeRunDir, { recursive: true });
	fs.mkdirSync(resumeResultsRoot, { recursive: true });
	const retainedFields = { filesystemPolicy: policy, filesystemPolicyDigest: filesystemPolicyDigest(policy) };
	const resumeDescriptor = { ...descriptor, sourceRunId: resumeRunId, ...retainedFields };
	const resumeStatus = {
		runId: resumeRunId,
		mode: "single",
		state: "complete",
		startedAt: Date.now() - 10,
		endedAt: Date.now(),
		lastUpdate: Date.now(),
		cwd: policy.cwd,
		...retainedFields,
		steps: [{ agent: "peer", status: "complete", cwd: policy.cwd, ...retainedFields }],
	};
	const resumeResult = {
		id: resumeRunId,
		agent: "peer",
		mode: "single",
		state: "complete",
		success: true,
		cwd: policy.cwd,
		...retainedFields,
		results: [{ agent: "peer", success: true, cwd: policy.cwd, ...retainedFields }],
	};
	const clone = (value) => JSON.parse(JSON.stringify(value));
	const writeResumeArtifacts = ({ status = resumeStatus, result = resumeResult, recovery = resumeDescriptor } = {}) => {
		fs.writeFileSync(resumeStatusPath, JSON.stringify(status));
		fs.writeFileSync(resumeResultPath, JSON.stringify(result));
		if (recovery) fs.writeFileSync(resumeDescriptorPath, JSON.stringify(recovery));
		else fs.rmSync(resumeDescriptorPath, { force: true });
	};
	const resolveResume = () => resolveAsyncResumeTarget(
		{ id: resumeRunId },
		{ asyncDirRoot: resumeAsyncRoot, resultsDir: resumeResultsRoot },
		{ requireSessionFile: false },
	);

	writeResumeArtifacts();
	const validResume = resolveResume();
	assert.deepEqual(validResume.filesystemPolicy, policy);
	assert.equal(validResume.filesystemPolicyDigest, filesystemPolicyDigest(policy));
	assert.equal(validResume.cwd, policy.cwd);

	writeResumeArtifacts({ recovery: null });
	throws(resolveResume, /recovery descriptor is missing filesystemPolicy evidence/);

	const statusMissingRoot = clone(resumeStatus);
	delete statusMissingRoot.filesystemPolicy;
	delete statusMissingRoot.filesystemPolicyDigest;
	writeResumeArtifacts({ status: statusMissingRoot });
	throws(resolveResume, /status root is missing filesystemPolicy evidence/);

	const statusMissingStep = clone(resumeStatus);
	delete statusMissingStep.steps[0].filesystemPolicy;
	delete statusMissingStep.steps[0].filesystemPolicyDigest;
	writeResumeArtifacts({ status: statusMissingStep });
	throws(resolveResume, /status step 0 is missing filesystemPolicy evidence/);

	const resultMissingRoot = clone(resumeResult);
	delete resultMissingRoot.filesystemPolicy;
	delete resultMissingRoot.filesystemPolicyDigest;
	writeResumeArtifacts({ result: resultMissingRoot });
	throws(resolveResume, /result root is missing filesystemPolicy evidence/);

	const resultMissingChild = clone(resumeResult);
	delete resultMissingChild.results[0].filesystemPolicy;
	delete resultMissingChild.results[0].filesystemPolicyDigest;
	writeResumeArtifacts({ result: resultMissingChild });
	throws(resolveResume, /result child 0 is missing filesystemPolicy evidence/);

	const resultConflict = clone(resumeResult);
	resultConflict.results[0].filesystemPolicy = expandedPolicy;
	resultConflict.results[0].filesystemPolicyDigest = filesystemPolicyDigest(expandedPolicy);
	writeResumeArtifacts({ result: resultConflict });
	throws(resolveResume, /filesystem policy conflict/);

	const statusPartial = clone(resumeStatus);
	delete statusPartial.steps[0].filesystemPolicyDigest;
	writeResumeArtifacts({ status: statusPartial });
	throws(resolveResume, /must either both be present or both be absent/);

	const legacyStatus = clone(resumeStatus);
	delete legacyStatus.filesystemPolicy;
	delete legacyStatus.filesystemPolicyDigest;
	delete legacyStatus.steps[0].filesystemPolicy;
	delete legacyStatus.steps[0].filesystemPolicyDigest;
	const legacyResult = clone(resumeResult);
	delete legacyResult.filesystemPolicy;
	delete legacyResult.filesystemPolicyDigest;
	delete legacyResult.results[0].filesystemPolicy;
	delete legacyResult.results[0].filesystemPolicyDigest;
	writeResumeArtifacts({ status: legacyStatus, result: legacyResult, recovery: null });
	const legacyResume = resolveResume();
	assert.equal(legacyResume.filesystemPolicy, undefined);
	assert.equal(legacyResume.filesystemPolicyDigest, undefined);
	checks.resumeDurableSurfaceConsistency = true;
	checks.durableResumeDescriptor = true;

	const staleAsyncRoot = path.join(fixtureRoot, "stale-async-root");
	const staleResultsRoot = path.join(fixtureRoot, "stale-results-root");
	const staleRunId = "stale-policy-run";
	const staleRunDir = path.join(staleAsyncRoot, staleRunId);
	fs.mkdirSync(staleRunDir, { recursive: true });
	fs.mkdirSync(staleResultsRoot, { recursive: true });
	fs.writeFileSync(path.join(staleRunDir, "recovery-descriptor.json"), JSON.stringify({ ...descriptor, sourceRunId: staleRunId }));
	const staleLaunchDigest = "a".repeat(64);
	fs.writeFileSync(path.join(staleRunDir, "status.json"), JSON.stringify({
		...resumeStatus,
		runId: staleRunId,
		state: "running",
		pid: 2147483000,
		endedAt: undefined,
		launchContractDigest: staleLaunchDigest,
		steps: [{ agent: "peer", status: "running", cwd: policy.cwd, launchContractDigest: staleLaunchDigest, ...retainedFields }],
	}));
	const deadPid = () => {
		const error = new Error("missing process");
		error.code = "ESRCH";
		throw error;
	};
	const staleRepair = reconcileAsyncRun(staleRunDir, { resultsDir: staleResultsRoot, kill: deadPid, now: () => Date.now() + 1000 });
	assert.equal(staleRepair.repaired, true);
	const repairedResult = JSON.parse(fs.readFileSync(path.join(staleResultsRoot, `${staleRunId}.json`), "utf8"));
	assert.deepEqual(repairedResult.filesystemPolicy, policy);
	assert.equal(repairedResult.filesystemPolicyDigest, filesystemPolicyDigest(policy));
	assert.equal(repairedResult.launchContractDigest, staleLaunchDigest);
	assert.equal(repairedResult.cwd, policy.cwd);
	assert.deepEqual(repairedResult.results[0].filesystemPolicy, policy);
	assert.equal(repairedResult.results[0].filesystemPolicyDigest, filesystemPolicyDigest(policy));
	assert.equal(repairedResult.results[0].launchContractDigest, staleLaunchDigest);
	assert.equal(repairedResult.results[0].cwd, policy.cwd);
	fs.rmSync(staleRunDir, { recursive: true, force: true });
	throws(() => resolveAsyncResumeTarget(
		{ id: staleRunId },
		{ asyncDirRoot: staleAsyncRoot, resultsDir: staleResultsRoot },
		{ requireSessionFile: false },
	), /recovery descriptor is missing filesystemPolicy evidence/);
	checks.staleRepairRetainsRestrictedMarkers = true;

	const asyncBuild = buildAsyncRunnerSteps("async-policy", {
		chain: [{ agent: "peer", task: "safe read" }],
		agents: [{
			name: "peer",
			description: "test peer",
			systemPrompt: "",
			systemPromptMode: "append",
			inheritProjectContext: false,
			inheritSkills: false,
			tools: ["read", "grep", "find", "ls", "bash"],
			source: "project",
			filePath: path.join(fixtureRoot, "peer.md"),
		}],
		ctx: { cwd: allowedRoot },
		cwd: allowedRoot,
		asyncDir: path.join(fixtureRoot, "async-run"),
		maxSubagentDepth: 9,
		filesystemPolicy: { allowedRoots: [allowedRoot], deniedPaths: [deniedRoot], bash: "deny" },
	});
	assert.match(asyncBuild.error ?? "", /filesystemPolicy v1 supports detached async single runs only/);
	checks.asyncChainParallelPolicyPreLaunchReject = true;
	const asyncWorktreeBuild = buildAsyncRunnerSteps("async-worktree-policy", {
		chain: [{ parallel: [{ agent: "peer", task: "safe read" }], worktree: true }],
		agents: [{
			name: "peer", description: "test peer", systemPrompt: "", systemPromptMode: "append",
			inheritProjectContext: false, inheritSkills: false, tools: ["read"], source: "project",
			filePath: path.join(fixtureRoot, "peer.md"),
		}],
		ctx: { cwd: allowedRoot }, cwd: allowedRoot, asyncDir: path.join(fixtureRoot, "async-worktree"),
		maxSubagentDepth: 9, filesystemPolicy: { allowedRoots: [allowedRoot], deniedPaths: [deniedRoot] },
	});
	assert.match(asyncWorktreeBuild.error ?? "", /filesystemPolicy v1 supports detached async single runs only/);
	checks.worktreePolicyPreLaunchReject = true;

	const externalAgent = {
			name: "external",
			description: "external test",
			systemPrompt: "",
			systemPromptMode: "append",
			inheritProjectContext: false,
			inheritSkills: false,
			tools: [],
			source: "project",
			filePath: path.join(fixtureRoot, "external.md"),
			runner: { type: "external-cli", command: process.execPath, args: ["-e", "process.exit(99)"] },
	};
	const externalBuild = executeAsyncSingle("external-policy", {
		agent: "external",
		task: "must reject",
		agentConfig: externalAgent,
		ctx: { pi: { events: { emit() {} } }, cwd: allowedRoot, currentSessionId: "test-session" },
		cwd: allowedRoot,
		artifactConfig: { enabled: false, includeInput: false, includeOutput: false, includeJsonl: false, includeMetadata: false, cleanupDays: 0 },
		shareEnabled: false,
		maxSubagentDepth: 9,
		filesystemPolicy: { allowedRoots: [allowedRoot], deniedPaths: [deniedRoot] },
	});
	assert.equal(externalBuild.isError, true);
	assert.match(externalBuild.content[0]?.text ?? "", /external-cli.*filesystem policy/);
	checks.externalCliPreLaunchReject = true;

	const nativeAgent = {
		name: "peer",
		description: "native restricted peer",
		systemPrompt: "",
		systemPromptMode: "append",
		inheritProjectContext: true,
		inheritSkills: true,
		tools: ["read", "grep", "find", "ls", "bash"],
		source: "project",
		filePath: path.join(fixtureRoot, "peer.md"),
	};
	const foregroundRejected = await runSync(allowedRoot, [nativeAgent], "peer", "must reject before provider", {
		runId: "foreground-host-bypass",
		context: "fresh",
		filesystemPolicy: policy,
		acceptance: { level: "verified", verify: [{ id: "escape", command: hostBypassCommand }] },
	});
	assert.equal(foregroundRejected.exitCode, 1);
	assert.match(foregroundRejected.error ?? "", /acceptance\.verify/);
	assert.equal(fs.existsSync(hostBypassMarker), false);

	for (const [label, overrides, pattern] of [
		["verify", { acceptance: { level: "verified", verify: [{ id: "escape", command: hostBypassCommand }] } }, /acceptance\.verify/],
		["review", { acceptance: { level: "checked", review: { agent: "writer", required: true } } }, /acceptance\.review/],
		["output", { output: hostBypassMarker }, /host-side output/],
		["file-only", { outputMode: "file-only" }, /file-only/],
		["share", { shareEnabled: true }, /share child sessions/],
	]) {
		const id = `async-host-bypass-${process.pid}-${label}`;
		const asyncPath = path.join(DIRS.async, id);
		assert.equal(fs.existsSync(asyncPath), false, "test async id must begin unused");
		const rejected = executeAsyncSingle(id, {
			agent: "peer",
			task: "must reject before runner/provider",
			agentConfig: nativeAgent,
			ctx: { pi: { events: { emit() {} } }, cwd: allowedRoot, currentSessionId: "test-session" },
			cwd: allowedRoot,
			artifactConfig: restrictedArtifactConfig,
			shareEnabled: false,
			maxSubagentDepth: 9,
			filesystemPolicy: policy,
			...overrides,
		});
		assert.equal(rejected.isError, true, label);
		assert.match(rejected.content[0]?.text ?? "", pattern, label);
		assert.equal(fs.existsSync(asyncPath), false, `${label} must reject before async runner directory creation`);
		assert.equal(fs.existsSync(hostBypassMarker), false, `${label} must not create host bypass marker`);
	}
	checks.directForegroundAsyncHostBypassPreProviderReject = true;

	const receipt = {
		schema: "xinao.pi_subagents_filesystem_policy_security_acceptance.v1",
		generatedAt: new Date().toISOString(),
		candidateRoot,
		candidatePolicySourceSha256: fileSha256(path.join(candidateRoot, "src/runs/shared/filesystem-policy.ts")),
		candidateRuntimeSourceSha256: fileSha256(PROMPT_RUNTIME_EXTENSION_PATH),
		candidateGateSourceSha256: fileSha256(FILESYSTEM_POLICY_MODULE_PATH),
		checks,
	};
	assert.equal(Object.values(checks).every(Boolean), true);
	const serialized = JSON.stringify(receipt);
	assert.equal(serialized.includes(sentinel), false, "receipt/output must not contain forbidden sentinel content");
	process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
} finally {
	for (const marker of bashMarkers) assert.equal(fs.existsSync(marker), false);
	fs.rmSync(fixtureRoot, { recursive: true, force: true });
}
