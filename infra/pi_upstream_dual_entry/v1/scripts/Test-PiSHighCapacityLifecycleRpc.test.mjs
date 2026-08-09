import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { getHighCapacityReplayPaths } from "./Test-PiSHighCapacitySupport.mjs";

const replay = getHighCapacityReplayPaths();
const TEST_DIR = replay.tempRoot;
const RPC_PATH = join(replay.subagentsRoot, "src", "extension", "rpc.ts");
const { createJiti } = await import(pathToFileURL(join(replay.agentDir, "npm", "node_modules", "jiti", "lib", "jiti.mjs")).href);
const jiti = createJiti(import.meta.url, { moduleCache: false });
const {
	registerSubagentRpcBridge,
	SUBAGENT_RPC_REQUEST_EVENT,
	subagentRpcReplyEvent,
} = await jiti.import(pathToFileURL(RPC_PATH).href);

class TestEventBus {
	#listeners = new Map();

	on(event, handler) {
		const listeners = this.#listeners.get(event) ?? new Set();
		listeners.add(handler);
		this.#listeners.set(event, listeners);
		return () => listeners.delete(handler);
	}

	emit(event, data) {
		for (const handler of this.#listeners.get(event) ?? []) handler(data);
	}
}

function emptyRoots() {
	const root = mkdtempSync(join(TEST_DIR, "_capacity-lifecycle-rpc-"));
	assert.ok(resolve(root).toLowerCase().startsWith(`${resolve(TEST_DIR).toLowerCase()}\\`));
	return {
		asyncDirRoot: join(root, "async"),
		resultsDir: join(root, "results"),
		cleanup() {
			rmSync(root, { recursive: true, force: true });
		},
	};
}

function makeState(ownerSessionId) {
	return {
		currentSessionId: ownerSessionId,
		sessionStopFences: new Set(),
		asyncJobs: new Map(),
		foregroundControls: new Map(),
		workflowControllers: new Map(),
	};
}

function makeContext(ownerSessionId) {
	return {
		cwd: TEST_DIR,
		sessionManager: {
			getSessionFile: () => ownerSessionId,
			getSessionId: () => "native-root-session",
		},
	};
}

function capacityBinding(token = "a".repeat(64)) {
	return {
		rootKey: "b".repeat(64),
		epoch: 7,
		token,
	};
}

function capacityRuntime({ requested = true, binding = () => capacityBinding(), mark, confirm } = {}) {
	return {
		isRequested: () => requested,
		resolveBinding: () => binding(),
		markStopped: mark ?? (async () => ({ stopped: true, terminalConfirmed: false })),
		confirmTerminal: confirm ?? (async () => ({ stopped: true, terminalConfirmed: true })),
	};
}

function addForegroundChild(state, ownerSessionId, { runId = "fg-1", interrupt } = {}) {
	const child = {
		index: 0,
		agent: "recursive-peer",
		startedAt: Date.now(),
		updatedAt: Date.now(),
		interrupt,
	};
	const control = {
		runId,
		sessionId: ownerSessionId,
		mode: "single",
		startedAt: Date.now(),
		updatedAt: Date.now(),
		schedulingOwners: 1,
		activeChildren: new Map([[0, child]]),
	};
	state.foregroundControls.set(runId, control);
	return { control, child };
}

async function createHarness({ runtime, state, ownerSessionId = join(TEST_DIR, "root-session.jsonl") }) {
	const roots = emptyRoots();
	const events = new TestEventBus();
	const ctx = makeContext(ownerSessionId);
	const bridge = registerSubagentRpcBridge({
		events,
		getContext: () => ctx,
		execute: async () => {
			throw new Error("stop-session must not call the generic executor");
		},
		state,
		asyncDirRoot: roots.asyncDirRoot,
		resultsDir: roots.resultsDir,
		ownerSessionStopWaitMs: 12,
		ownerSessionStopPollMs: 1,
		capacityStopRuntime: runtime,
		capacityEnv: {},
	});
	let requestSequence = 0;
	return {
		async stop() {
			const requestId = `stop-${++requestSequence}`;
			return new Promise((resolveReply, reject) => {
				const timer = setTimeout(() => reject(new Error("timed out waiting for stop-session reply")), 2_000);
				const unsubscribe = events.on(subagentRpcReplyEvent(requestId), (reply) => {
					clearTimeout(timer);
					unsubscribe();
					resolveReply(reply);
				});
				events.emit(SUBAGENT_RPC_REQUEST_EVENT, {
					version: 1,
					requestId,
					method: "stop-session",
					params: {},
				});
			});
		},
		close() {
			bridge.dispose();
			roots.cleanup();
		},
	};
}

test("capacity Stop marks durably before foreground interruption and confirms only after disappearance", async () => {
	const ownerSessionId = join(TEST_DIR, "ordered-root.jsonl");
	const state = makeState(ownerSessionId);
	const order = [];
	const { control } = addForegroundChild(state, ownerSessionId, {
		interrupt: () => {
			order.push("interrupt");
			control.activeChildren.delete(0);
			control.schedulingOwners = 0;
			state.foregroundControls.delete(control.runId);
			return true;
		},
	});
	const harness = await createHarness({
		ownerSessionId,
		state,
		runtime: capacityRuntime({
			mark: async () => {
				order.push("mark");
				return { stopped: true, terminalConfirmed: false };
			},
			confirm: async () => {
				order.push("confirm");
				return { stopped: true, terminalConfirmed: true };
			},
		}),
	});
	try {
		const reply = await harness.stop();
		assert.equal(reply.success, true);
		assert.equal(reply.data.status, "verified");
		assert.equal(reply.data.stopFence, true);
		assert.equal(reply.data.targetCount, 2);
		assert.deepEqual(order, ["mark", "interrupt", "confirm"]);
		assert.ok(reply.data.results.every((result) => result.disposition === "foreground_terminal"));
	} finally {
		harness.close();
	}
});

test("a typed durable-mark failure stays partial but does not suppress foreground interruption", async () => {
	const ownerSessionId = join(TEST_DIR, "mark-failure-root.jsonl");
	const state = makeState(ownerSessionId);
	const order = [];
	const { control } = addForegroundChild(state, ownerSessionId, {
		interrupt: () => {
			order.push("interrupt");
			control.activeChildren.delete(0);
			control.schedulingOwners = 0;
			state.foregroundControls.delete(control.runId);
			return true;
		},
	});
	const harness = await createHarness({
		ownerSessionId,
		state,
		runtime: capacityRuntime({
			mark: async () => {
				order.push("mark");
				throw Object.assign(new Error("durable mark refused"), { code: "XINAO_PI_CAPACITY_STALE_EPOCH" });
			},
			confirm: async () => {
				order.push("confirm");
				return { stopped: true, terminalConfirmed: true };
			},
		}),
	});
	try {
		const reply = await harness.stop();
		assert.equal(reply.success, true);
		assert.equal(reply.data.status, "partial");
		assert.deepEqual(order, ["mark", "interrupt"]);
		assert.match(reply.data.enumerationErrors.join("\n"), /XINAO_PI_CAPACITY_STALE_EPOCH.*durable mark refused/);
	} finally {
		harness.close();
	}
});

test("a resolved negative durable-mark readback remains partial and cannot confirm", async () => {
	const ownerSessionId = join(TEST_DIR, "negative-mark-root.jsonl");
	const state = makeState(ownerSessionId);
	let confirms = 0;
	const harness = await createHarness({
		ownerSessionId,
		state,
		runtime: capacityRuntime({
			mark: async () => ({ stopped: false, terminalConfirmed: false }),
			confirm: async () => {
				confirms += 1;
				return { stopped: true, terminalConfirmed: true };
			},
		}),
	});
	try {
		const reply = await harness.stop();
		assert.equal(reply.success, true);
		assert.equal(reply.data.status, "partial");
		assert.equal(confirms, 0);
		assert.match(reply.data.enumerationErrors.join("\n"), /XINAO_PI_CAPACITY_STOP_MARK_INVALID_READBACK/);
	} finally {
		harness.close();
	}
});

test("a resolved negative terminal-confirmation readback cannot report verified", async () => {
	const ownerSessionId = join(TEST_DIR, "negative-confirm-root.jsonl");
	const state = makeState(ownerSessionId);
	const harness = await createHarness({
		ownerSessionId,
		state,
		runtime: capacityRuntime({
			confirm: async () => ({ stopped: true, terminalConfirmed: false }),
		}),
	});
	try {
		const reply = await harness.stop();
		assert.equal(reply.success, true);
		assert.equal(reply.data.status, "partial");
		assert.match(reply.data.enumerationErrors.join("\n"), /XINAO_PI_CAPACITY_STOP_CONFIRM_INVALID_READBACK/);
	} finally {
		harness.close();
	}
});

test("an interrupt-unknown foreground child remains partial and cannot confirm terminal", async () => {
	const ownerSessionId = join(TEST_DIR, "unknown-root.jsonl");
	const state = makeState(ownerSessionId);
	let confirms = 0;
	addForegroundChild(state, ownerSessionId, { interrupt: () => false });
	const harness = await createHarness({
		ownerSessionId,
		state,
		runtime: capacityRuntime({
			confirm: async () => {
				confirms += 1;
				return { stopped: true, terminalConfirmed: true };
			},
		}),
	});
	try {
		const reply = await harness.stop();
		assert.equal(reply.success, true);
		assert.equal(reply.data.status, "partial");
		assert.equal(confirms, 0);
		assert.ok(reply.data.results.some((result) => result.disposition === "delivery_failed"));
		assert.ok(reply.data.results.some((result) => result.disposition === "stop_unverified"));
	} finally {
		harness.close();
	}
});

test("capacity-unset preserves the ordinary stop-session target surface", async () => {
	const ownerSessionId = join(TEST_DIR, "ordinary-root.jsonl");
	const state = makeState(ownerSessionId);
	let interrupts = 0;
	addForegroundChild(state, ownerSessionId, {
		interrupt: () => {
			interrupts += 1;
			return true;
		},
	});
	const harness = await createHarness({
		ownerSessionId,
		state,
		runtime: capacityRuntime({ requested: false }),
	});
	try {
		const reply = await harness.stop();
		assert.equal(reply.success, true);
		assert.equal(reply.data.status, "verified");
		assert.equal(reply.data.targetCount, 0);
		assert.equal(interrupts, 0);
	} finally {
		harness.close();
	}
});

test("stop-operation memoization is scoped by rootKey, epoch, and token", async () => {
	const ownerSessionId = join(TEST_DIR, "memo-root.jsonl");
	const state = makeState(ownerSessionId);
	let token = "1".repeat(64);
	let marks = 0;
	const harness = await createHarness({
		ownerSessionId,
		state,
		runtime: capacityRuntime({
			binding: () => capacityBinding(token),
			mark: async () => {
				marks += 1;
				return { stopped: true, terminalConfirmed: false };
			},
		}),
	});
	try {
		assert.equal((await harness.stop()).success, true);
		assert.equal((await harness.stop()).success, true);
		assert.equal(marks, 1);
		token = "2".repeat(64);
		assert.equal((await harness.stop()).success, true);
		assert.equal(marks, 2);
	} finally {
		harness.close();
	}
});

test("partial Stop is not memoized and a later terminal retry re-enumerates then verifies", async () => {
	const ownerSessionId = join(TEST_DIR, "partial-retry-root.jsonl");
	const state = makeState(ownerSessionId);
	const { control } = addForegroundChild(state, ownerSessionId, { interrupt: () => false });
	let marks = 0;
	let confirms = 0;
	const harness = await createHarness({
		ownerSessionId,
		state,
		runtime: capacityRuntime({
			mark: async () => {
				marks += 1;
				return { stopped: true, terminalConfirmed: false };
			},
			confirm: async () => {
				confirms += 1;
				return { stopped: true, terminalConfirmed: true };
			},
		}),
	});
	try {
		const first = await harness.stop();
		assert.equal(first.success, true);
		assert.equal(first.data.status, "partial");
		assert.equal(marks, 1);
		assert.equal(confirms, 0);

		control.activeChildren.clear();
		control.schedulingOwners = 0;
		state.foregroundControls.delete(control.runId);
		const second = await harness.stop();
		assert.equal(second.success, true);
		assert.equal(second.data.status, "verified");
		assert.equal(marks, 2, "retry must execute a fresh durable mark instead of returning the partial memo");
		assert.equal(confirms, 1);
	} finally {
		harness.close();
	}
});
