import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { registerHooks, stripTypeScriptTypes } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { getHighCapacityReplayPaths } from "./Test-PiSHighCapacitySupport.mjs";

const replay = getHighCapacityReplayPaths();
const candidateRoot = replay.tempRoot;
const subagentsRoot = replay.subagentsRoot;
const coreAnchor = pathToFileURL(replay.coreAnchor).href;

registerHooks({
	resolve(specifier, context, nextResolve) {
		if (specifier.startsWith("@earendil-works/")) {
			return nextResolve(specifier, { ...context, parentURL: coreAnchor });
		}
		return nextResolve(specifier, context);
	},
	load(url, context, nextLoad) {
		if (url.endsWith(".ts")) {
			const filename = fileURLToPath(url);
			if (filename.startsWith(subagentsRoot)) {
				return {
					format: "module",
					source: stripTypeScriptTypes(readFileSync(filename, "utf8"), { mode: "transform" }),
					shortCircuit: true,
				};
			}
		}
		return nextLoad(url, context);
	},
});

const turnBudgetModule = await import(pathToFileURL(path.join(subagentsRoot, "src", "runs", "shared", "turn-budget.ts")).href);
const executorModule = await import(pathToFileURL(path.join(subagentsRoot, "src", "runs", "foreground", "subagent-executor.ts")).href);
const dynamicFanoutModule = await import(pathToFileURL(path.join(subagentsRoot, "src", "runs", "shared", "dynamic-fanout.ts")).href);
const asyncResumeModule = await import(pathToFileURL(path.join(subagentsRoot, "src", "runs", "background", "async-resume.ts")).href);

const {
	resolveCapacityTurnBudgetConfig,
	resolveTurnBudgetConfig,
	turnBudgetDecision,
	turnBudgetHardLimit,
} = turnBudgetModule;
const { validateCapacityFanoutWidth } = executorModule;
const { materializeDynamicParallelStep } = dynamicFanoutModule;
const { readAsyncRecoveryDescriptor } = asyncResumeModule;

const policy = Object.freeze({
	turnMin: 10,
	turnMax: 30,
	turnDefaultMax: 30,
	turnDefaultGrace: 0,
});

test("capacity defaults to 30+0 while the unset legacy resolver keeps its grace", () => {
	assert.deepEqual(resolveCapacityTurnBudgetConfig(undefined, "turnBudget", policy), {
		turnBudget: { maxTurns: 30, graceTurns: 0 },
	});
	assert.deepEqual(resolveTurnBudgetConfig({ maxTurns: 30 }), {
		turnBudget: { maxTurns: 30, graceTurns: 1 },
	});
});

test("initial capacity hard budget is exactly constrained to 10..30", () => {
	for (const budget of [
		{ maxTurns: 10 },
		{ maxTurns: 29, graceTurns: 1 },
		{ maxTurns: 30, graceTurns: 0 },
	]) {
		const result = resolveCapacityTurnBudgetConfig(budget, "turnBudget", policy);
		assert.equal(result.error, undefined);
		assert.ok(result.turnBudget);
		assert.ok(turnBudgetHardLimit(result.turnBudget) >= 10);
		assert.ok(turnBudgetHardLimit(result.turnBudget) <= 30);
	}
	for (const budget of [
		{ maxTurns: 9, graceTurns: 0 },
		{ maxTurns: 30, graceTurns: 1 },
		{ maxTurns: 31, graceTurns: 0 },
	]) {
		assert.match(resolveCapacityTurnBudgetConfig(budget, "turnBudget", policy).error ?? "", /between 10 and 30/);
	}
});

test("steering recovery admits 1..29 remaining turns without expanding the initial hard limit", () => {
	const initialHard = 20;
	for (const budget of [{ maxTurns: 1, graceTurns: 0 }, { maxTurns: 19, graceTurns: 1 }]) {
		const result = resolveCapacityTurnBudgetConfig(
			budget,
			"steeringRecovery.turnBudget",
			policy,
			{ minimum: 1, maximum: Math.min(policy.turnMax - 1, initialHard) },
		);
		assert.equal(result.error, undefined);
		assert.ok(result.turnBudget);
		assert.ok(turnBudgetHardLimit(result.turnBudget) <= initialHard);
	}
	assert.match(resolveCapacityTurnBudgetConfig(
		{ maxTurns: 21, graceTurns: 0 },
		"steeringRecovery.turnBudget",
		policy,
		{ minimum: 1, maximum: Math.min(policy.turnMax - 1, initialHard) },
	).error ?? "", /between 1 and 20/);
	assert.match(resolveCapacityTurnBudgetConfig(
		{ maxTurns: 30, graceTurns: 0 },
		"steeringRecovery.turnBudget",
		policy,
		{ minimum: 1, maximum: policy.turnMax - 1 },
	).error ?? "", /between 1 and 29/);
});

test("capacity aborts a tool-starting 30th assistant turn while ordinary runs still defer", () => {
	const budget = { maxTurns: 30, graceTurns: 0 };
	let assistantTurns = 0;
	let activeToolAborts = 0;
	while (assistantTurns < 31) {
		assistantTurns += 1;
		const decision = turnBudgetDecision(budget, assistantTurns, false, assistantTurns === 30, true);
		if (decision === "abort") {
			activeToolAborts += 1;
			break;
		}
	}
	assert.equal(assistantTurns, 30, "capacity must not admit a 31st assistant turn");
	assert.equal(activeToolAborts, 1, "the active/starting tool is aborted at the hard boundary");
	assert.equal(turnBudgetDecision(budget, 30, false, true, false), "defer");
	assert.equal(turnBudgetDecision(budget, 30, false, true), "defer");
});

test("foreground and durable background bind hard turns only to capacity handshakes", () => {
	const foregroundSource = readFileSync(path.join(subagentsRoot, "src", "runs", "foreground", "execution.ts"), "utf8");
	assert.match(foregroundSource, /options\.capacitySpawnLaunch !== undefined \|\| options\.enforceHardTurnLimit === true/);

	const asyncSource = readFileSync(path.join(subagentsRoot, "src", "runs", "background", "async-execution.ts"), "utf8");
	assert.equal((asyncSource.match(/const enforceHardTurnLimit = params\.capacityRootContext !== undefined;/g) ?? []).length, 2);
	assert.ok((asyncSource.match(/\benforceHardTurnLimit,\r?\n/g) ?? []).length >= 3, "chain config, single descriptor, and single config persist the flag");
	assert.match(asyncSource, /const persistedInitialTurnBudget: ResolvedTurnBudget \| undefined = initialTurnBudget/);
	assert.match(asyncSource, /\{ initialTurnBudget: persistedInitialTurnBudget \}/);

	const runnerSource = readFileSync(path.join(subagentsRoot, "src", "runs", "background", "subagent-runner.ts"), "utf8");
	assert.match(runnerSource, /turnBudgetDecision\(budget, turnCount, terminalAssistantStop, toolWorkActiveOrStarting, config\.enforceHardTurnLimit === true\)/);
	assert.match(runnerSource, /ctx\.enforceHardTurnLimit === true,/);
	assert.match(runnerSource, /Capacity-bound async runs require hard assistant-turn enforcement/);
});

test("durable recovery descriptor retains and validates the hard-turn flag", () => {
	const asyncDir = mkdtempSync(path.join(candidateRoot, "pi-hard-turn-recovery-"));
	const descriptorPath = path.join(asyncDir, "recovery-descriptor.json");
	const descriptor = {
		version: 1,
		sourceRunId: "run-1",
		agent: "recursive-self",
		cwd: candidateRoot,
		systemPromptMode: "append",
		inheritProjectContext: true,
		inheritSkills: true,
		outputMode: "inline",
		maxSubagentDepth: 2,
		share: false,
		initialTurnBudget: { maxTurns: 30, graceTurns: 0 },
		enforceHardTurnLimit: true,
	};
	try {
		writeFileSync(descriptorPath, JSON.stringify(descriptor), "utf8");
		const canonical = readAsyncRecoveryDescriptor(asyncDir);
		assert.deepEqual(canonical?.initialTurnBudget, { maxTurns: 30, graceTurns: 0 });
		assert.equal(canonical?.enforceHardTurnLimit, true);

		writeFileSync(descriptorPath, JSON.stringify({
			...descriptor,
			initialTurnBudget: { maxTurns: 30, graceTurns: 0, outcome: "within-budget", turnCount: 0 },
		}), "utf8");
		const normalizedLegacy = readAsyncRecoveryDescriptor(asyncDir);
		assert.deepEqual(normalizedLegacy?.initialTurnBudget, { maxTurns: 30, graceTurns: 0 });
		assert.equal(Object.hasOwn(normalizedLegacy?.initialTurnBudget ?? {}, "outcome"), false);
		assert.equal(Object.hasOwn(normalizedLegacy?.initialTurnBudget ?? {}, "turnCount"), false);
		assert.equal(normalizedLegacy?.enforceHardTurnLimit, true, "legacy normalization must not weaken the sibling hard-turn flag");

		for (const [invalid, pattern] of [
			[{ maxTurns: 30, graceTurns: 0, extra: true }, /extra is not supported/],
			[{ maxTurns: 30, graceTurns: 0, outcome: "within-budget" }, /must contain exactly/],
			[{ maxTurns: 30, graceTurns: 0, turnCount: 0 }, /must contain exactly/],
			[{ maxTurns: 30, graceTurns: 0, outcome: "wrap-up-requested", turnCount: 0 }, /outcome must be 'within-budget'/],
			[{ maxTurns: 30, graceTurns: 0, outcome: "within-budget", turnCount: 1 }, /turnCount must be 0/],
			[{ maxTurns: 30, graceTurns: 0, outcome: "within-budget", turnCount: 0, wrapUpRequestedAtTurn: 30 }, /must contain exactly/],
		]) {
			writeFileSync(descriptorPath, JSON.stringify({ ...descriptor, initialTurnBudget: invalid }), "utf8");
			assert.throws(() => readAsyncRecoveryDescriptor(asyncDir), pattern);
		}

		writeFileSync(descriptorPath, JSON.stringify({ ...descriptor, enforceHardTurnLimit: "yes" }), "utf8");
		assert.throws(() => readAsyncRecoveryDescriptor(asyncDir), /enforceHardTurnLimit must be a boolean/);
	} finally {
		rmSync(asyncDir, { recursive: true, force: true });
	}
});

test("top-level and static chain width count repeated children and reject 11", () => {
	const tasks10 = Array.from({ length: 10 }, (_, index) => ({ agent: "recursive-peer", task: String(index) }));
	assert.equal(validateCapacityFanoutWidth({ tasks: tasks10 }, 10, 10), undefined);
	assert.match(validateCapacityFanoutWidth({ tasks: [...tasks10, tasks10[0]] }, 10, 10) ?? "", /top-level tasks \(11\)/);
	assert.equal(validateCapacityFanoutWidth({ tasks: [{ agent: "recursive-peer", task: "x", count: 10 }] }, 10, 10), undefined);
	assert.match(validateCapacityFanoutWidth({ tasks: [{ agent: "recursive-peer", task: "x", count: 11 }] }, 10, 10) ?? "", /top-level tasks \(11\)/);

	const static10 = { parallel: Array.from({ length: 10 }, () => ({ agent: "recursive-peer", task: "x" })) };
	assert.equal(validateCapacityFanoutWidth({ chain: [static10] }, 10, 10), undefined);
	assert.match(validateCapacityFanoutWidth({ chain: [{ parallel: [...static10.parallel, static10.parallel[0]] }] }, 10, 10) ?? "", /11 static children/);
});

test("dynamic effective maxItems is policy-bounded and materialization rechecks actual count", () => {
	const dynamic = {
		expand: { from: { output: "seed", path: "" } },
		parallel: { agent: "recursive-peer", task: "inspect {item}" },
		collect: { as: "collected" },
	};
	assert.equal(validateCapacityFanoutWidth({ chain: [dynamic] }, 10, 10), undefined);
	assert.match(validateCapacityFanoutWidth({ chain: [{ ...dynamic, expand: { ...dynamic.expand, maxItems: 11 } }] }, 10, 10) ?? "", /effective maxItems 11/);
	assert.equal(validateCapacityFanoutWidth({ chain: [{ ...dynamic, expand: { ...dynamic.expand, maxItems: 10 } }] }, 11, 10), undefined);

	assert.throws(() => materializeDynamicParallelStep(
		dynamic,
		{
			seed: {
				text: "seed",
				structured: Array.from({ length: 11 }, (_, index) => index),
				agent: "recursive-peer",
				stepIndex: 0,
			},
		},
		1,
		{ maxItems: 10 },
	), /resolved 11 items, exceeding maxItems 10/);
});

test("normal launch width preflight precedes spawn-budget preflight and reservation", () => {
	const source = readFileSync(path.join(subagentsRoot, "src", "runs", "foreground", "subagent-executor.ts"), "utf8");
	const launchWidth = source.lastIndexOf("const widthError = validateCapacityFanoutWidth(");
	const requestedSpawns = source.indexOf("const requestedSpawns =", launchWidth);
	const spawnPreflight = source.indexOf("const spawnPreflight = preflightSpawnBudget(", requestedSpawns);
	const reservation = source.indexOf("const reservation = reserveSpawnBudget(", spawnPreflight);
	assert.ok(launchWidth >= 0 && launchWidth < requestedSpawns);
	assert.ok(requestedSpawns < spawnPreflight);
	assert.ok(spawnPreflight < reservation);
});
