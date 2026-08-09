import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { createReplayJiti, getHighCapacityReplayPaths } from "./Test-PiSHighCapacitySupport.mjs";

const replay = getHighCapacityReplayPaths();
const ROOT = replay.tempRoot;
const PKG = replay.subagentsRoot;
const RUNTIME = join(PKG, "src", "runs", "shared", "xinao-pi-subagent-capacity-runtime.js");

function source(relativePath) {
    return readFileSync(join(PKG, relativePath), "utf8");
}

test("spawn tickets cross every native foreground and detached-runner launch seam", () => {
    const types = source("src/shared/types.ts");
    const piArgs = source("src/runs/shared/pi-args.ts");
    const execution = source("src/runs/foreground/execution.ts");
    const executor = source("src/runs/foreground/subagent-executor.ts");
    const chain = source("src/runs/foreground/chain-execution.ts");
    const asyncExecution = source("src/runs/background/async-execution.ts");
    const runner = source("src/runs/background/subagent-runner.ts");
	const scriptedWorkflow = source("src/workflows/scripted-workflow.ts");

    assert.match(types, /interface XinaoPiCapacitySpawnReservationV1/);
    assert.match(types, /capacitySpawnLaunch\?: XinaoPiCapacitySpawnLaunchV1/);
    assert.match(piArgs, /assertCapacityLaunchOrOrdinary\(input\.capacitySpawnLaunch\)/);
    assert.match(execution, /capacitySpawnLaunch: options\.capacitySpawnLaunch/);
    assert.match(chain, /reserveCapacitySpawnGroup/);
    assert.match(chain, /closeCapacitySpawnReservation\(dynamicCapacityReservation\)/);
    assert.match(asyncExecution, /capacitySpawnReservation: params\.capacitySpawnReservation/);
    assert.match(asyncExecution, /ALL_CAPACITY_CHILD_ENV_KEYS/);
    assert.match(runner, /capacityStaticReservationQueue/);
    assert.match(runner, /appendedStaticCount/);
    assert.match(runner, /capacitySpawnLaunch: dynamicCapacityLaunches\?\.\[taskIdx\]/);
    assert.match(runner, /Promise\.allSettled\(/);
    assert.match(runner, /uniqueCapacityReservations\.map\(\(reservation\) => closeCapacitySpawnReservation\(reservation\)\)/);
    assert.match(runner, /Failed to close .*Pi capacity spawn reservation/);
	assert.match(executor, /if \(params\.workflowScript !== undefined\)[\s\S]*resolveXinaoCapacityContext\(\)[\s\S]*CAPACITY_WORKFLOW_UNAVAILABLE_REASON/);
	assert.match(scriptedWorkflow, /if \(runsAllDisabledReason\) throw new Error\(runsAllDisabledReason\)/);
	assert.doesNotMatch(scriptedWorkflow, /run\.all\.prepare|prepareAllEnabled|preparedGroup/);
	assert.doesNotMatch(executor, /preparedCapacitySpawnLaunch|Prepared runs\.all capacity ticket/);
	assert.match(executor, /normalizePublicSubagentExecution\(params, options\)/);
	assert.match(executor, /deferCapacityCloseUntilForegroundIdle/);
});

test("public execution admits only a standalone typed capacity tasks batch", async () => {
	const jiti = createReplayJiti(import.meta.url);
	const { normalizePublicSubagentExecution } = await jiti.import(join(PKG, "src", "extension", "public-execution.ts"));
	const tasks = [{ agent: "recursive-peer", task: "compute" }];

	assert.equal(normalizePublicSubagentExecution({ tasks }).ok, false, "ordinary public callers must keep rejecting legacy tasks");
	assert.equal(normalizePublicSubagentExecution({ tasks, concurrency: 6 }, { allowCapacityTasks: true }).ok, true);
	assert.equal(normalizePublicSubagentExecution({ concurrency: 6 }, { allowCapacityTasks: true }).ok, false);
	assert.equal(normalizePublicSubagentExecution({ action: "list" }, { allowCapacityTasks: true }).ok, true);
	assert.equal(normalizePublicSubagentExecution({ workflowScript: "return runs.run('x',{agent:'recursive-peer',task:'x'})" }, { allowCapacityTasks: true }).ok, false);
	assert.equal(normalizePublicSubagentExecution({ action: "schedule.create", workflowScript: "return runs.run('x',{agent:'recursive-peer',task:'x'})" }, { allowCapacityTasks: true }).ok, false);
	for (const mixed of [
		{ action: "status" },
		{ workflowScript: "return 1" },
		{ agent: "recursive-peer" },
		{ task: "direct" },
		{ step: { agent: "recursive-peer", task: "next" } },
		{ chain: [{ agent: "recursive-peer", task: "next" }] },
		{ parallel: true },
		{ chainDir: "x" },
		{ resume: "run" },
		{ clarify: true },
	]) {
		const normalized = normalizePublicSubagentExecution({ tasks, ...mixed }, { allowCapacityTasks: true });
		assert.equal(normalized.ok, false, `tasks mixed with ${Object.keys(mixed)[0]} must fail closed`);
	}
});

test("canonical ticket helpers are fail-closed and keep ordered one-shot identity", { skip: !existsSync(RUNTIME) && "canonical runtime projection has not landed yet" }, async () => {
	const jiti = createReplayJiti(import.meta.url);
    const api = await jiti.import(join(PKG, "src", "runs", "shared", "spawn-budget.ts"));

    assert.deepEqual(api.assertCapacityLaunchOrOrdinary(undefined, {}), {});
    assert.throws(
        () => api.assertCapacityLaunchOrOrdinary(undefined, { XINAO_PI_SUBAGENT_CAPACITY_V1: "" }),
        /missing its exact spawn ticket/,
    );

    const rootContext = {
        staticPayload: "static",
        staticSha256: "a".repeat(64),
        bindingPayload: "binding",
        bindingSha256: "b".repeat(64),
    };
    const reservation = {
        rootContext,
        reservationId: "c".repeat(64),
        tickets: [
            { ticketId: "d".repeat(64), ordinal: 0 },
            { ticketId: "e".repeat(64), ordinal: 1 },
        ],
    };
    const canonicalLaunchKey = createHash("sha256")
        .update("xinao.pi.capacity.launch.v1\0launch-1")
        .digest("hex");
    assert.deepEqual(api.capacitySpawnLaunchAt(reservation, 1, "launch-1"), {
        rootContext,
        reservationId: "c".repeat(64),
        ticketId: "e".repeat(64),
        launchKey: canonicalLaunchKey,
    });
    assert.throws(() => api.capacitySpawnLaunchAt(reservation, 2, "launch-2"), /no ordered ticket/);
    assert.throws(
        () => api.capacitySpawnLaunchAt({ ...reservation, reservationId: "reservation" }, 0, "launch-0"),
        /reservationId is not canonical/,
    );
    assert.throws(
        () => api.capacitySpawnLaunchAt({ ...reservation, tickets: [{ ticketId: "ticket-0", ordinal: 0 }] }, 0, "launch-0"),
        /non-canonical ticketId/,
    );
    assert.throws(
        () => api.assertCapacityReservationRootContext(reservation, { ...rootContext, bindingSha256: "c".repeat(64) }),
        /different root binding/,
    );
});

test("capacity-unset runs.all keeps the ordinary direct launch path", async () => {
	const jiti = createReplayJiti(import.meta.url);
	const { runWorkflowScript } = await jiti.import(join(PKG, "src", "workflows", "scripted-workflow.ts"));
	const seen = [];
	const result = await runWorkflowScript({
		script: "return runs.all([{key:'a',agent:'worker',task:'a'},{key:'b',agent:'worker',task:'b'}])",
		launch: async (key) => {
			seen.push(key);
			return { key, ok: true, output: key, artifactPaths: [] };
		},
		status: async (key) => ({ key, ok: true, output: key, artifactPaths: [] }),
	});
	assert.deepEqual(seen.sort(), ["a", "b"]);
	assert.equal(result.children.length, 2);
});

test("the internal scripted-workflow runs.all defense remains fail-closed even though capacity public workflow is unreachable", async () => {
	const jiti = createReplayJiti(import.meta.url);
	const { runWorkflowScript } = await jiti.import(join(PKG, "src", "workflows", "scripted-workflow.ts"));
	let reserveCalls = 0;
	let launchCalls = 0;
	let providerCalls = 0;
	await assert.rejects(runWorkflowScript({
		script: "return runs.all([{key:'blocked',agent:'recursive-peer',task:'work',turnBudget:{maxTurns:31,graceTurns:0},clarify:true,async:true}])",
		runsAllDisabledReason: "Pi capacity v1 does not support workflowScript runs.all; use top-level tasks or parallel fanout.",
		launch: async (key) => {
			reserveCalls += 1;
			launchCalls += 1;
			providerCalls += 1;
			return { key, ok: true, output: key, artifactPaths: [] };
		},
		status: async (key) => ({ key, ok: true, output: key, artifactPaths: [] }),
	}), /Pi capacity v1 does not support workflowScript runs\.all/);
	assert.equal(reserveCalls, 0);
	assert.equal(launchCalls, 0);
	assert.equal(providerCalls, 0);

	let sequentialLaunches = 0;
	const sequential = await runWorkflowScript({
		script: "return await runs.run('allowed',{agent:'recursive-peer',task:'work'})",
		runsAllDisabledReason: "Pi capacity v1 does not support workflowScript runs.all.",
		launch: async (key) => {
			sequentialLaunches += 1;
			return { key, ok: true, output: key, artifactPaths: [] };
		},
		status: async (key) => ({ key, ok: true, output: key, artifactPaths: [] }),
	});
	assert.equal(sequentialLaunches, 1);
	assert.equal(sequential.children.length, 1);
});

test("foreground capacity ownership closes only after scheduler and every materialized child are terminal", async () => {
	const jiti = createReplayJiti(import.meta.url);
	const { __xinaoCapacityForegroundOwnershipForTests: ownership } = await jiti.import(join(PKG, "src", "runs", "foreground", "subagent-executor.ts"));
	let closes = 0;
	const control = { schedulingOwners: 1, activeChildren: new Map([[0, {}], [1, {}]]) };
	const state = { foregroundControls: new Map([["group", control]]), lastForegroundControlId: "group" };
	ownership.defer(control, () => { closes += 1; });
	assert.equal(ownership.removeIfIdle(state, "group"), false);
	assert.equal(closes, 0, "outer receipt must not refund while the scheduler owns the group");
	control.schedulingOwners = 0;
	assert.equal(ownership.removeIfIdle(state, "group"), false);
	assert.equal(closes, 0, "early rejection/detach must not refund while any sibling is live");
	control.activeChildren.delete(0);
	assert.equal(ownership.removeIfIdle(state, "group"), false);
	assert.equal(closes, 0);
	control.activeChildren.delete(1);
	assert.equal(ownership.removeIfIdle(state, "group"), true);
	assert.equal(closes, 1);
	assert.equal(state.foregroundControls.has("group"), false);
	assert.equal(state.lastForegroundControlId, null);
	assert.equal(ownership.removeIfIdle(state, "group"), true);
	assert.equal(closes, 1, "terminal close must be exactly once");
});

test("the registered model tool catalog exposes all 40 retained children", async () => {
	const jiti = createReplayJiti(import.meta.url);
	const agentDir = mkdtempSync(join(ROOT, "pi-capacity-tool-description-"));
	const priorAgentDir = process.env.PI_CODING_AGENT_DIR;
	const priorChild = process.env.PI_SUBAGENT_CHILD;
	try {
		process.env.PI_CODING_AGENT_DIR = agentDir;
		delete process.env.PI_SUBAGENT_CHILD;
		const [{ default: registerSubagentExtension }, descriptions] = await Promise.all([
			jiti.import(join(PKG, "src", "extension", "index.ts")),
			jiti.import(join(PKG, "src", "extension", "tool-description.ts")),
		]);
		let registeredTool;
		const events = { on() { return () => undefined; }, emit() {} };
		const fakePi = new Proxy({
			events,
			registerTool(tool) { if (tool.name === "subagent") registeredTool = tool; },
			registerCommand() {},
			registerShortcut() {},
			registerMessageRenderer() {},
			sendMessage() {},
			getSessionName() { return undefined; },
		}, {
			get(target, property) {
				if (property in target) return target[property];
				return () => undefined;
			},
		});
		registerSubagentExtension(fakePi);
		assert.ok(registeredTool, "subagent tool must be registered into the model catalog");
		assert.match(registeredTool.description, /up to 40 completed retained children/);
		assert.match(descriptions.buildSubagentToolDescription({ toolDescriptionMode: "compact" }), /last 40 retained children/);
	} finally {
		const cleanup = globalThis.__piSubagentRuntimeCleanup;
		if (typeof cleanup === "function") cleanup();
		delete globalThis.__piSubagentRuntimeCleanup;
		if (priorAgentDir === undefined) delete process.env.PI_CODING_AGENT_DIR;
		else process.env.PI_CODING_AGENT_DIR = priorAgentDir;
		if (priorChild === undefined) delete process.env.PI_SUBAGENT_CHILD;
		else process.env.PI_SUBAGENT_CHILD = priorChild;
		rmSync(agentDir, { recursive: true, force: true });
	}
});

test("verified capacity root catalog exposes only the honest typed batch surface", async () => {
	const jiti = createReplayJiti(import.meta.url);
	const runtime = await import(pathToFileURL(replay.npmCapacityRuntime).href);
	const agentDir = mkdtempSync(join(ROOT, "_capacity-root-catalog-"));
	const configDir = join(agentDir, "extensions", "subagent");
	mkdirSync(configDir, { recursive: true });
	writeFileSync(join(configDir, "config.json"), JSON.stringify({
		maxSubagentDepth: 3,
		maxSubagentSpawnsPerSession: 40,
		globalConcurrencyLimit: 6,
		parallel: { maxTasks: 10, concurrency: 6 },
		chain: { dynamicFanout: { maxItems: 10 } },
		asyncByDefault: false,
		scheduledRuns: { enabled: false },
		missions: { enabled: false },
	}), "utf8");
	const encoded = runtime.encodeCanonicalEnvPayload(runtime.createStaticCapacityPayload());
	const envKeys = [runtime.CAPACITY_STATIC_ENV_KEY, runtime.CAPACITY_STATIC_SHA_ENV_KEY, "PI_SUBAGENT_CHILD", "PI_CODING_AGENT_DIR"];
	const prior = Object.fromEntries(envKeys.map((key) => [key, process.env[key]]));
	try {
		process.env.PI_CODING_AGENT_DIR = agentDir;
		delete process.env.PI_SUBAGENT_CHILD;
		process.env[runtime.CAPACITY_STATIC_ENV_KEY] = encoded.raw;
		process.env[runtime.CAPACITY_STATIC_SHA_ENV_KEY] = encoded.sha;
		const { default: registerSubagentExtension } = await jiti.import(join(PKG, "src", "extension", "index.ts"));
		let registeredTool;
		const events = { on() { return () => undefined; }, emit() {} };
		const fakePi = new Proxy({
			events,
			registerTool(tool) { if (tool.name === "subagent") registeredTool = tool; },
			registerCommand() {}, registerShortcut() {}, registerMessageRenderer() {}, sendMessage() {}, getSessionName() { return undefined; },
		}, { get(target, property) { return property in target ? target[property] : () => undefined; } });
		registerSubagentExtension(fakePi);
		assert.ok(registeredTool);
		assert.equal(registeredTool.parameters.properties.tasks.maxItems, 10);
		assert.equal(registeredTool.parameters.properties.concurrency.maximum, 6);
		assert.equal(registeredTool.parameters.properties.chain, undefined);
		assert.equal(registeredTool.parameters.properties.workflowScript, undefined);
		assert.equal(registeredTool.parameters.properties.chatProgress, undefined);
		assert.equal(registeredTool.parameters.properties.resume, undefined);
		assert.equal(registeredTool.parameters.properties.filesystemPolicy.type, "object");
		assert.match(registeredTool.parameters.properties.filesystemPolicy.description, /Root-only restricted single-child policy.*exactly one expanded tasks\[\] item/i);
		assert.equal(registeredTool.parameters.properties.tasks.items.properties.turnBudget, undefined);
		assert.equal(registeredTool.parameters.properties.tasks.items.properties.filesystemPolicy, undefined);
		assert.equal(registeredTool.parameters.properties.turnBudget.properties.maxTurns.maximum, 30);
		assert.equal(registeredTool.parameters.properties.turnBudget.properties.graceTurns.maximum, 29);
		assert.match(registeredTool.parameters.properties.turnBudget.description, /must total 10 through 30.*Omit turnBudget for 30 \+ 0/);
		assert.match(registeredTool.description, /Tasks stay foreground by default; set async:true to detach/);
		assert.match(registeredTool.description, /hard assistant-turn limit is maxTurns \+ graceTurns, must total 10 through 30, and defaults to 30 \+ 0/);
		assert.match(registeredTool.description, /executes? only through typed top-level|only through typed top-level/i);
		assert.match(registeredTool.description, /Missions, scheduled runs, and spawn-budget grants are unavailable/);
		assert.match(registeredTool.description, /verified root alone may launch one restricted filesystem child/i);
		assert.match(registeredTool.description, /exactly one child.*fresh single-child path with depth 0/i);
		assert.doesNotMatch(registeredTool.description, /runs\.run|runs\.all|sequential workflow|workflowScript is sequential/i);
		assert.doesNotMatch(registeredTool.description, /Async\/background runs are the default|Use async:false only/);
		assert.doesNotMatch(registeredTool.description, /dynamic fanout|legacy chain/i);
	} finally {
		const cleanup = globalThis.__piSubagentRuntimeCleanup;
		if (typeof cleanup === "function") cleanup();
		delete globalThis.__piSubagentRuntimeCleanup;
		for (const key of envKeys) {
			if (prior[key] === undefined) delete process.env[key];
			else process.env[key] = prior[key];
		}
		rmSync(agentDir, { recursive: true, force: true });
	}
});

test("depth-one recursive peer exposes capacity tasks only under an exact child handshake and remains self-only", async () => {
	const jiti = createReplayJiti(import.meta.url);
	const runtime = await import(pathToFileURL(replay.npmCapacityRuntime).href);
	const [{ default: registerFanoutChild }, piArgs, ceiling] = await Promise.all([
		jiti.import(join(PKG, "src", "extension", "fanout-child.ts")),
		jiti.import(join(PKG, "src", "runs", "shared", "pi-args.ts")),
		jiti.import(join(PKG, "src", "runs", "shared", "capability-ceiling.ts")),
	]);
	const testRoot = mkdtempSync(join(ROOT, "_capacity-child-catalog-"));
	const registryRoot = join(testRoot, "registry");
	const agentDir = join(testRoot, "agent");
	const sessionFile = join(testRoot, "session.jsonl");
	mkdirSync(agentDir, { recursive: true });
	writeFileSync(sessionFile, "{}\n", "utf8");
	const harness = runtime.__testing.createIsolatedHarness({ registryRoot });
	const activation = await harness.activate({ agentDir, profile: "prime-s", sessionId: "capacity-child-catalog", sessionFile });
	const reservation = await harness.reserve({ reservationId: "capacity child catalog", count: 1 });
	const childEnv = harness.childEnv({
		reservationId: reservation.reservationId,
		ticketId: reservation.tickets[0].ticketId,
		launchKey: "depth-one-recursive-peer",
	});
	const capacityKeys = [
		runtime.CAPACITY_STATIC_ENV_KEY,
		runtime.CAPACITY_STATIC_SHA_ENV_KEY,
		runtime.ROOT_BINDING_ENV_KEY,
		runtime.ROOT_BINDING_SHA_ENV_KEY,
		runtime.CAPACITY_LAUNCH_TICKET_ENV_KEY,
		runtime.CAPACITY_LAUNCH_TICKET_SHA_ENV_KEY,
	];
	const envKeys = [...capacityKeys, "PI_SUBAGENT_CHILD", "PI_SUBAGENT_FANOUT_CHILD", "PI_CODING_AGENT_DIR"];
	const prior = Object.fromEntries(envKeys.map((key) => [key, process.env[key]]));
	const applyChildEnv = (values) => {
		for (const key of capacityKeys) delete process.env[key];
		for (const [key, value] of Object.entries(values)) process.env[key] = value;
		process.env.PI_SUBAGENT_CHILD = "1";
		process.env.PI_SUBAGENT_FANOUT_CHILD = "1";
		process.env.PI_CODING_AGENT_DIR = agentDir;
	};
	const captureTool = () => {
		let tool;
		const pi = { events: { on() { return () => undefined; }, emit() {} }, registerTool(value) { if (value.name === "subagent") tool = value; } };
		registerFanoutChild(pi);
		assert.ok(tool);
		return tool;
	};
	try {
		applyChildEnv(childEnv);
		const validTool = captureTool();
		assert.equal(validTool.parameters.properties.tasks.maxItems, 10);
		assert.equal(validTool.parameters.properties.workflowScript, undefined);
		assert.equal(validTool.parameters.properties.resume, undefined);
		assert.equal(validTool.parameters.properties.filesystemPolicy, undefined);
		assert.match(validTool.description, /hard turnBudget=maxTurns\+graceTurns must total 10\.\.30.*defaults to 30\+0/);
		assert.match(validTool.description, /workflowScript, top-level resume, direct agent\/task execution, and filesystemPolicy are unavailable from capacity descendants/);
		const descendantFilesystemResult = await validTool.execute("descendant-fs", {
			tasks: [{ agent: "recursive-peer", task: "x" }],
			filesystemPolicy: { allowedRoots: [testRoot], bash: "deny" },
		}, new AbortController().signal, undefined, {});
		assert.equal(descendantFilesystemResult.isError, true);
		assert.match(descendantFilesystemResult.content[0].text, /filesystemPolicy.*verified root model tool/i);

		applyChildEnv({});
		const absentTool = captureTool();
		assert.equal(absentTool.parameters.properties.tasks, undefined);
		const absentResult = await absentTool.execute("absent", { tasks: [{ agent: "recursive-peer", task: "x" }] }, new AbortController().signal, undefined, {});
		assert.equal(absentResult.isError, true);
		assert.match(absentResult.content[0].text, /Legacy top-level chain and parallel inputs were removed/);

		applyChildEnv({ [runtime.CAPACITY_STATIC_ENV_KEY]: childEnv[runtime.CAPACITY_STATIC_ENV_KEY] });
		const malformedTool = captureTool();
		assert.equal(malformedTool.parameters.properties.tasks, undefined);
		const malformedResult = await malformedTool.execute("malformed", { tasks: [{ agent: "recursive-peer", task: "x" }] }, new AbortController().signal, undefined, {});
		assert.equal(malformedResult.isError, true);

		const plan = piArgs.resolvePiLaunchToolPlan({ agentName: "recursive-peer", tools: ["subagent"] });
		assert.deepEqual(plan.capabilityCeiling.allowedAgents, ["recursive-peer"]);
		assert.equal(ceiling.isAgentAllowedByCapabilityCeiling("recursive-peer", plan.capabilityCeiling), true);
		assert.equal(ceiling.isAgentAllowedByCapabilityCeiling("filesystem-policy", plan.capabilityCeiling), false);
	} finally {
		for (const key of envKeys) {
			if (prior[key] === undefined) delete process.env[key];
			else process.env[key] = prior[key];
		}
		await runtime.closeRootSpawnReservation({ env: harness.env, reservationId: reservation.reservationId });
		await activation.release();
		rmSync(testRoot, { recursive: true, force: true });
	}
});
