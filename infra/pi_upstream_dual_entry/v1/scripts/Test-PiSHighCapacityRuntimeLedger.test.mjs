import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { getHighCapacityReplayPaths } from "./Test-PiSHighCapacitySupport.mjs";

const replay = getHighCapacityReplayPaths();
const candidateRoot = replay.tempRoot;
const agentDir = replay.piToolRoot;
const sessionFile = replay.sessionFile;
const runtimeUrl = pathToFileURL(replay.npmCapacityRuntime).href;
const runtime = await import(runtimeUrl);

function spawnHiddenRuntimeHelper(source, args) {
	return spawn(process.execPath, ["--input-type=module", "-e", source, runtimeUrl, ...args], {
		windowsHide: true,
		stdio: ["ignore", "pipe", "pipe"],
	});
}

function readHelperReceipt(child, timeoutMs = 10000) {
	return new Promise((resolve, reject) => {
		let stdout = "";
		let stderr = "";
		let settled = false;
		const finish = (error, value) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			child.stdout.off("data", onStdout);
			child.stderr.off("data", onStderr);
			child.off("exit", onExit);
			error ? reject(error) : resolve(value);
		};
		const onStdout = (chunk) => {
			stdout += chunk.toString("utf8");
			const newline = stdout.indexOf("\n");
			if (newline < 0) return;
			try { finish(undefined, JSON.parse(stdout.slice(0, newline))); }
			catch (error) { finish(new Error(`Invalid helper receipt: ${error.message}; stdout=${stdout}; stderr=${stderr}`)); }
		};
		const onStderr = (chunk) => { stderr += chunk.toString("utf8"); };
		const onExit = (code, signal) => finish(new Error(`Runtime helper exited before ready (code=${code}, signal=${signal}): ${stderr}`));
		const timer = setTimeout(() => finish(new Error(`Runtime helper timed out: ${stderr}`)), timeoutMs);
		child.stdout.on("data", onStdout);
		child.stderr.on("data", onStderr);
		child.once("exit", onExit);
	});
}

async function terminateExactHelper(child) {
	if (child.exitCode !== null || child.signalCode !== null) return;
	const exited = once(child, "exit");
	assert.equal(child.kill(), true);
	await exited;
}

test("strict handshake and durable root lifecycle keep one canonical capacity truth", async (t) => {
	const testRoot = mkdtempSync(join(candidateRoot, "_runtime-capacity-"));
	t.after(() => rmSync(testRoot, { recursive: true, force: true }));
	const registryRoot = join(testRoot, "registry");

	const production = runtime.encodeCanonicalEnvPayload(runtime.createStaticCapacityPayload());
	assert.equal(runtime.parseStaticCapacityEnv({
		[runtime.CAPACITY_STATIC_ENV_KEY]: production.raw,
		[runtime.CAPACITY_STATIC_SHA_ENV_KEY]: production.sha,
	}).maxTreeSpawns, 40);
	assert.equal(runtime.parseStaticCapacityEnv({}), null);
	const unregisteredIsolated = runtime.encodeCanonicalEnvPayload({
		...runtime.createStaticCapacityPayload(),
		registryRoot,
	});
	assert.throws(() => runtime.parseStaticCapacityEnv({
		[runtime.CAPACITY_STATIC_ENV_KEY]: unregisteredIsolated.raw,
		[runtime.CAPACITY_STATIC_SHA_ENV_KEY]: unregisteredIsolated.sha,
	}), /canonical main-prime value/);
	const harness = runtime.__testing.createIsolatedHarness({ registryRoot });
	assert.equal(runtime.parseStaticCapacityEnv({
		[runtime.CAPACITY_STATIC_ENV_KEY]: harness.staticEncoded.raw,
		[runtime.CAPACITY_STATIC_SHA_ENV_KEY]: harness.staticEncoded.sha,
	}).maxTreeSpawns, 40, "explicit isolated harness registration must survive exact env serialization");

	const identity = { agentDir, profile: "prime-s", sessionId: "runtime-ledger-test", sessionFile };
	let activation = await harness.activate(identity);
	const firstBinding = activation.binding;
	assert.match(firstBinding.rootKey, /^[0-9a-f]{64}$/);
	assert.match(firstBinding.token, /^[0-9a-f]{64}$/);
	let snapshot = await harness.inspect();
	assert.equal(snapshot.spawnCount, 0);
	assert.equal(snapshot.stopped, false);
	assert.equal(snapshot.terminalConfirmed, false);

	const contender = runtime.__testing.createIsolatedHarness({ registryRoot });
	await assert.rejects(contender.activate(identity), (error) => error.code === "XINAO_PI_CAPACITY_ALREADY_ACTIVE");

	const reservation = await harness.reserve({ reservationId: "first reservation", count: 3 });
	assert.match(reservation.reservationId, /^[0-9a-f]{64}$/);
	assert.equal(reservation.tickets.length, 3);
	assert.ok(reservation.tickets.every((ticket) => /^[0-9a-f]{64}$/.test(ticket.ticketId)));

	const firstChildEnv = harness.childEnv({
		reservationId: reservation.reservationId,
		ticketId: reservation.tickets[0].ticketId,
		launchKey: "first launch",
	});
	assert.equal(runtime.classifyProviderCapacityGate(firstChildEnv).mode, "gated");
	const firstProvider = await runtime.acquireProviderSlot({ env: firstChildEnv });
	await firstProvider.release();
	snapshot = await harness.inspect();
	assert.equal(snapshot.spawnCount, 1);
	assert.equal(snapshot.pendingSpawns, 2);

	await runtime.refundRootSpawnTicketBeforeSpawn({
		env: harness.env,
		reservationId: reservation.reservationId,
		ticketId: reservation.tickets[1].ticketId,
		launchKey: "second launch never spawned",
	});
	await runtime.closeRootSpawnReservation({ env: harness.env, reservationId: reservation.reservationId });
	snapshot = await harness.inspect();
	assert.equal(snapshot.spawnCount, 1);
	assert.equal(snapshot.pendingSpawns, 0);

	const seven = await harness.reserve({ reservationId: "seven providers", count: 7 });
	const childEnvs = seven.tickets.map((ticket, index) => harness.childEnv({
		reservationId: seven.reservationId,
		ticketId: ticket.ticketId,
		launchKey: `provider ${index}`,
	}));
	const held = await Promise.all(childEnvs.slice(0, 6).map((env) => runtime.acquireProviderSlot({ env })));
	assert.equal(new Set(held.map((lease) => lease.slot)).size, 6);
	const abort = new AbortController();
	const seventh = runtime.acquireProviderSlot({ env: childEnvs[6], signal: abort.signal });
	setTimeout(() => abort.abort(new DOMException("queued provider cancelled", "AbortError")), 30);
	await assert.rejects(seventh, (error) => error.name === "AbortError");
	await Promise.all(held.map((lease) => lease.release()));
	snapshot = await harness.inspect();
	assert.equal(snapshot.spawnCount, 8);
	assert.equal(snapshot.pendingSpawns, 0);

	await activation.release();
	harness.freshRootEnv();
	activation = await harness.activate(identity);
	assert.equal(activation.binding.epoch, firstBinding.epoch);
	assert.equal(activation.binding.token, firstBinding.token);
	assert.equal((await harness.inspect()).spawnCount, 8);

	const oldBinding = activation.binding;
	const oldEnv = harness.registerEnv({ ...harness.env });
	await harness.markStopped();
	await assert.rejects(runtime.assertCurrentRootBinding({ env: harness.env, binding: oldBinding }), (error) => error.code === "XINAO_PI_CAPACITY_STOPPED");
	await harness.confirmTerminal();
	await activation.release();

	harness.freshRootEnv();
	activation = await harness.activate(identity);
	assert.equal(activation.binding.epoch, oldBinding.epoch + 1);
	assert.notEqual(activation.binding.token, oldBinding.token);
	assert.equal((await harness.inspect()).spawnCount, 8);
	await assert.rejects(runtime.assertCurrentRootBinding({ env: oldEnv, binding: oldBinding }), (error) => error.code === "XINAO_PI_CAPACITY_STALE_BINDING");
	await activation.release();
});

test("four width-ten groups commit exactly forty and the forty-first group is rejected pre-provider", async (t) => {
	const testRoot = mkdtempSync(join(candidateRoot, "_runtime-capacity-40-"));
	t.after(() => rmSync(testRoot, { recursive: true, force: true }));
	const harness = runtime.__testing.createIsolatedHarness({ registryRoot: join(testRoot, "registry") });
	const activation = await harness.activate({ agentDir, profile: "prime-s", sessionId: "runtime-ledger-40", sessionFile });
	t.after(() => activation.release());

	await assert.rejects(
		harness.reserve({ reservationId: "width eleven", count: 11 }),
		(error) => error.code === "XINAO_PI_CAPACITY_FANOUT_EXCEEDED",
	);
	for (let group = 0; group < 4; group += 1) {
		const reservation = await harness.reserve({ reservationId: `group ${group}`, count: 10 });
		assert.equal(reservation.tickets.length, 10);
		for (const [index, ticket] of reservation.tickets.entries()) {
			const env = harness.childEnv({
				reservationId: reservation.reservationId,
				ticketId: ticket.ticketId,
				launchKey: `group ${group} child ${index}`,
			});
			const lease = await runtime.acquireProviderSlot({ env });
			await lease.release();
		}
	}
	const beforeRejection = await harness.inspect();
	assert.equal(beforeRejection.spawnCount, 40);
	assert.equal(beforeRejection.pendingSpawns, 0);
	await assert.rejects(
		harness.reserve({ reservationId: "forty first", count: 1 }),
		(error) => error.code === "XINAO_PI_CAPACITY_TREE_SPAWNS_EXCEEDED",
	);
	assert.deepEqual(await harness.inspect(), beforeRejection);
	await activation.release();
});

test("a crashed root preserves claimed and reserved uncertainty across an ordinary same-session restart", async (t) => {
	const testRoot = mkdtempSync(join(candidateRoot, "_runtime-capacity-crash-"));
	t.after(() => rmSync(testRoot, { recursive: true, force: true }));
	const registryRoot = join(testRoot, "registry");
	const sessionId = "runtime-ledger-root-crash";
	const helper = spawnHiddenRuntimeHelper(`
		const [runtimeUrl, registryRoot, agentDir, sessionFile, sessionId] = process.argv.slice(1);
		const runtime = await import(runtimeUrl);
		const harness = runtime.__testing.createIsolatedHarness({ registryRoot });
		const activation = await harness.activate({ agentDir, profile: "prime-s", sessionId, sessionFile });
		const reservation = await harness.reserve({ reservationId: "crash uncertainty", count: 2 });
		await runtime.claimRootSpawnTicket({
			env: harness.env,
			reservationId: reservation.reservationId,
			ticketId: reservation.tickets[0].ticketId,
			launchKey: "claimed before root crash",
		});
		process.stdout.write(JSON.stringify({ binding: activation.binding, reservation }) + "\\n");
		setInterval(() => {}, 1000);
	`, [registryRoot, agentDir, sessionFile, sessionId]);
	t.after(() => terminateExactHelper(helper));
	const crashed = await readHelperReceipt(helper);
	await terminateExactHelper(helper);

	const harness = runtime.__testing.createIsolatedHarness({ registryRoot });
	const activation = await harness.activate({ agentDir, profile: "prime-s", sessionId, sessionFile });
	t.after(() => activation.release());
	assert.equal(activation.binding.epoch, crashed.binding.epoch);
	assert.equal(activation.binding.token, crashed.binding.token);
	assert.equal((await harness.inspect()).pendingSpawns, 2);
	const fillers = [];
	for (let index = 0; index < 3; index += 1) fillers.push(await harness.reserve({ reservationId: `crash filler ${index}`, count: 10 }));
	await assert.rejects(harness.reserve({ reservationId: "overbook after crash", count: 10 }), (error) => error.code === "XINAO_PI_CAPACITY_TREE_SPAWNS_EXCEEDED");
	for (const filler of fillers) await runtime.closeRootSpawnReservation({ env: harness.env, reservationId: filler.reservationId });

	await runtime.closeRootSpawnReservation({ env: harness.env, reservationId: crashed.reservation.reservationId });
	assert.equal((await harness.inspect()).pendingSpawns, 1, "close refunds only never-claimed tickets");
	await runtime.refundRootSpawnTicketBeforeSpawn({
		env: harness.env,
		reservationId: crashed.reservation.reservationId,
		ticketId: crashed.reservation.tickets[0].ticketId,
		launchKey: "claimed before root crash",
	});
	assert.equal((await harness.inspect()).pendingSpawns, 0);
	await activation.release();
});

test("durable Stop rejects a queued seventh provider and rotation waits for every old slot", async (t) => {
	const testRoot = mkdtempSync(join(candidateRoot, "_runtime-capacity-stop-"));
	t.after(() => rmSync(testRoot, { recursive: true, force: true }));
	const registryRoot = join(testRoot, "registry");
	const identity = { agentDir, profile: "prime-s", sessionId: "runtime-ledger-stop-queue", sessionFile };
	const harness = runtime.__testing.createIsolatedHarness({ registryRoot });
	const activation = await harness.activate(identity);
	const oldBinding = activation.binding;
	const reservation = await harness.reserve({ reservationId: "stop queue", count: 7 });
	const envs = reservation.tickets.map((ticket, index) => harness.childEnv({
		reservationId: reservation.reservationId,
		ticketId: ticket.ticketId,
		launchKey: `stop queue ${index}`,
	}));
	const held = await Promise.all(envs.slice(0, 6).map((env) => runtime.acquireProviderSlot({ env })));
	t.after(() => Promise.all(held.map((lease) => lease.release())));
	const queued = runtime.acquireProviderSlot({ env: envs[6] });
	await new Promise((resolve) => setTimeout(resolve, 30));
	await harness.markStopped();
	await assert.rejects(
		Promise.race([
			queued,
			new Promise((_, reject) => setTimeout(() => reject(new Error("queued Stop readback timed out")), 750)),
		]),
		(error) => error.code === "XINAO_PI_CAPACITY_STOPPED",
	);
	await harness.confirmTerminal();
	await activation.release();

	const blockedRotation = runtime.__testing.createIsolatedHarness({ registryRoot });
	await assert.rejects(
		blockedRotation.activate(identity),
		(error) => error.code === "XINAO_PI_CAPACITY_SLOTS_BUSY",
	);
	await Promise.all(held.map((lease) => lease.release()));

	const rotated = runtime.__testing.createIsolatedHarness({ registryRoot });
	const nextActivation = await rotated.activate(identity);
	t.after(() => nextActivation.release());
	assert.equal(nextActivation.binding.epoch, oldBinding.epoch + 1);
	assert.notEqual(nextActivation.binding.token, oldBinding.token);
	assert.equal((await rotated.inspect()).spawnCount, 7, "Stop rotation never restores committed launch capacity");
	await assert.rejects(
		runtime.assertCurrentRootBinding({ env: harness.env, binding: oldBinding }),
		(error) => error.code === "XINAO_PI_CAPACITY_STALE_BINDING",
	);
	await nextActivation.release();
});

test("Windows process death releases real SQLite provider locks for a waiting native child", async (t) => {
	const testRoot = mkdtempSync(join(candidateRoot, "_runtime-capacity-slot-kill-"));
	t.after(() => rmSync(testRoot, { recursive: true, force: true }));
	const registryRoot = join(testRoot, "registry");
	const harness = runtime.__testing.createIsolatedHarness({ registryRoot });
	const activation = await harness.activate({ agentDir, profile: "prime-s", sessionId: "runtime-ledger-slot-kill", sessionFile });
	t.after(() => activation.release());
	const reservation = await harness.reserve({ reservationId: "killed slot holders", count: 7 });
	const envs = reservation.tickets.map((ticket, index) => harness.childEnv({
		reservationId: reservation.reservationId,
		ticketId: ticket.ticketId,
		launchKey: `killed holder ${index}`,
	}));
	const encodedEnvs = Buffer.from(JSON.stringify(envs.slice(0, 6)), "utf8").toString("base64");
	const helper = spawnHiddenRuntimeHelper(`
		const [runtimeUrl, registryRoot, encodedEnvs] = process.argv.slice(1);
		const runtime = await import(runtimeUrl);
		const harness = runtime.__testing.createIsolatedHarness({ registryRoot });
		const envs = JSON.parse(Buffer.from(encodedEnvs, "base64").toString("utf8"));
		for (const env of envs) harness.registerEnv(env);
		const leases = await Promise.all(envs.map((env) => runtime.acquireProviderSlot({ env })));
		process.stdout.write(JSON.stringify({ slots: leases.map((lease) => lease.slot) }) + "\\n");
		setInterval(() => {}, 1000);
	`, [registryRoot, encodedEnvs]);
	t.after(() => terminateExactHelper(helper));
	const ready = await readHelperReceipt(helper);
	assert.equal(new Set(ready.slots).size, 6);
	await terminateExactHelper(helper);

	const recovered = await Promise.race([
		runtime.acquireProviderSlot({ env: envs[6] }),
		new Promise((_, reject) => setTimeout(() => reject(new Error("slot did not recover after holder death")), 1500)),
	]);
	assert.ok(ready.slots.includes(recovered.slot));
	await recovered.release();
	assert.equal((await harness.inspect()).spawnCount, 7);
	await activation.release();
});

test("corrupt, missing, linked, and unknown-schema ledgers fail closed without reset", async (t) => {
	const cases = ["corrupt", "missing", "linked", "unknown-schema"];
	for (const variant of cases) {
		await t.test(variant, async (t) => {
			const testRoot = mkdtempSync(join(candidateRoot, `_runtime-capacity-${variant}-`));
			t.after(() => rmSync(testRoot, { recursive: true, force: true }));
			const registryRoot = join(testRoot, "registry");
			const identity = { agentDir, profile: "prime-s", sessionId: `runtime-ledger-${variant}`, sessionFile };
			const harness = runtime.__testing.createIsolatedHarness({ registryRoot });
			const activation = await harness.activate(identity);
			const binding = activation.binding;
			await activation.release();
			const ledger = join(registryRoot, "roots", binding.rootKey, "ledger.sqlite");

			if (variant === "corrupt") {
				writeFileSync(ledger, "not a sqlite database", "utf8");
			} else if (variant === "missing") {
				rmSync(ledger, { force: true });
			} else if (variant === "linked") {
				const target = join(testRoot, "linked-target.sqlite");
				writeFileSync(target, "not a sqlite database", "utf8");
				rmSync(ledger, { force: true });
				symlinkSync(target, ledger, "file");
			} else {
				const { DatabaseSync } = await import("node:sqlite");
				const db = new DatabaseSync(ledger);
				try { db.exec("UPDATE capacity_meta SET schema_version=999 WHERE singleton=1"); }
				finally { db.close(); }
			}

			const contender = runtime.__testing.createIsolatedHarness({ registryRoot });
			await assert.rejects(contender.activate(identity), (error) => {
				if (variant === "missing") return error.code === "XINAO_PI_CAPACITY_LEDGER_MISSING";
				if (variant === "linked") return error.code === "XINAO_PI_CAPACITY_DATABASE_INVALID";
				if (variant === "unknown-schema") return error.code === "XINAO_PI_CAPACITY_LEDGER_DRIFT";
				return error.code === "XINAO_PI_CAPACITY_DATABASE_INVALID";
			});
			if (variant === "corrupt") assert.equal(readFileSync(ledger, "utf8"), "not a sqlite database");
			if (variant === "missing") assert.equal(existsSync(ledger), false);
			if (variant === "linked") assert.equal(readFileSync(join(testRoot, "linked-target.sqlite"), "utf8"), "not a sqlite database");
		});
	}
});

test("registry junctions are rejected before mkdir and non-fixed or non-NTFS facts fail closed", async (t) => {
	const testRoot = mkdtempSync(join(candidateRoot, "_runtime-capacity-reparse-"));
	t.after(() => rmSync(testRoot, { recursive: true, force: true }));
	const realRegistry = join(testRoot, "real-registry");
	mkdirSync(realRegistry, { recursive: true });
	const linkedRegistry = join(testRoot, "registry-link");
	symlinkSync(realRegistry, linkedRegistry, "junction");
	const harness = runtime.__testing.createIsolatedHarness({ registryRoot: linkedRegistry });
	await assert.rejects(
		harness.activate({ agentDir, profile: "prime-s", sessionId: "runtime-ledger-reparse", sessionFile }),
		(error) => error.code === "XINAO_PI_CAPACITY_PATH_INVALID",
	);
	assert.equal(existsSync(join(realRegistry, "roots")), false, "pre-write validation must not materialize through a junction");
	assert.throws(
		() => runtime.__testing.assertFixedNtfsVolumeFacts({ DriveType: 4, DriveFormat: "NTFS", IsReady: true }, "Z:\\"),
		(error) => error.code === "XINAO_PI_CAPACITY_VOLUME_INVALID",
	);
	assert.throws(
		() => runtime.__testing.assertFixedNtfsVolumeFacts({ DriveType: 3, DriveFormat: "ReFS", IsReady: true }, "Z:\\"),
		(error) => error.code === "XINAO_PI_CAPACITY_VOLUME_INVALID",
	);
});
