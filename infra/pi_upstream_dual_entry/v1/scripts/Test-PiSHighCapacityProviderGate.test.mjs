import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { getHighCapacityReplayPaths } from "./Test-PiSHighCapacitySupport.mjs";

const replay = getHighCapacityReplayPaths();
const TEST_DIR = replay.tempRoot;
const AGENT_DIR = replay.piToolRoot;
const SESSION_FILE = replay.sessionFile;
const { createAssistantMessageEventStream } = await import(pathToFileURL(path.join(
    replay.corePackageRoot,
    "node_modules",
    "@earendil-works",
    "pi-ai",
    "dist",
    "compat.js",
)).href);
const {
    __xinaoCreateCapacityGatedProviderStreamForTests: createCapacityStream,
} = await import(pathToFileURL(path.join(replay.corePackageRoot, "dist", "core", "sdk.js")).href);
const {
    createStaticCapacityPayload,
    encodeCanonicalEnvPayload,
} = await import(pathToFileURL(replay.coreCapacityRuntime).href);

const model = {
    api: "test-api",
    provider: "test-provider",
    id: "test-model",
};
const context = { messages: [] };
const zeroUsage = {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    totalTokens: 0,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
};

function assistantMessage(stopReason = "stop", errorMessage) {
    return {
        role: "assistant",
        content: [],
        api: model.api,
        provider: model.provider,
        model: model.id,
        usage: zeroUsage,
        stopReason,
        ...(errorMessage === undefined ? {} : { errorMessage }),
        timestamp: Date.now(),
    };
}

function validCapacityEnv(sessionId = "provider-gate-test") {
    const staticPayload = createStaticCapacityPayload();
    const staticEncoded = encodeCanonicalEnvPayload(staticPayload);
    const rootKey = createHash("sha256")
        .update(`${AGENT_DIR.toLowerCase()}\0prime-s\0${SESSION_FILE.toLowerCase()}\0${sessionId}`)
        .digest("hex");
    const dynamicEncoded = encodeCanonicalEnvPayload({
        schema: "xinao.pi.subagent.root-owner-session.v1",
        canonicalAgentDir: AGENT_DIR,
        profile: "prime-s",
        canonicalSessionFile: SESSION_FILE,
        sessionId,
        rootKey,
        epoch: 1,
        token: "a".repeat(64),
        policySha: staticEncoded.sha,
        registryRoot: staticPayload.registryRoot,
    });
    const stableId = (kind) => createHash("sha256").update(`${kind}\0${sessionId}`).digest("hex");
    const ticketEncoded = encodeCanonicalEnvPayload({
        schema: "xinao.pi.subagent.launch-ticket.v1",
        rootKey,
        epoch: 1,
        token: "a".repeat(64),
        reservationId: stableId("reservation"),
        ticketId: stableId("ticket"),
        launchKey: stableId("launch"),
        policySha: staticEncoded.sha,
    });
    return {
        PI_SUBAGENT_CHILD: "1",
        XINAO_PI_SUBAGENT_CAPACITY_V1: staticEncoded.raw,
        XINAO_PI_SUBAGENT_CAPACITY_SHA256_V1: staticEncoded.sha,
        PI_SUBAGENT_ROOT_OWNER_SESSION: dynamicEncoded.raw,
        PI_SUBAGENT_ROOT_OWNER_SESSION_SHA256: dynamicEncoded.sha,
        XINAO_PI_SUBAGENT_LAUNCH_TICKET_V1: ticketEncoded.raw,
        XINAO_PI_SUBAGENT_LAUNCH_TICKET_SHA256_V1: ticketEncoded.sha,
    };
}

function controlledProviderStream() {
    const stream = createAssistantMessageEventStream();
    return {
        stream,
        start() {
            stream.push({ type: "start", partial: assistantMessage() });
        },
        succeed() {
            const message = assistantMessage("stop");
            stream.push({ type: "done", reason: "stop", message });
            stream.end(message);
        },
        fail(messageText = "provider failed") {
            const message = assistantMessage("error", messageText);
            stream.push({ type: "error", reason: "error", error: message });
            stream.end(message);
        },
    };
}

function createSemaphore(limit) {
    let active = 0;
    let peak = 0;
    let releases = 0;
    const queue = [];

    const grant = (waiter) => {
        waiter.signal?.removeEventListener("abort", waiter.onAbort);
        active += 1;
        peak = Math.max(peak, active);
        let released = false;
        waiter.resolve({
            slot: active,
            async release() {
                if (released) {
                    return;
                }
                released = true;
                releases += 1;
                active -= 1;
                while (queue.length > 0 && active < limit) {
                    const next = queue.shift();
                    if (!next.signal?.aborted) {
                        grant(next);
                        break;
                    }
                }
            },
        });
    };

    return {
        acquire({ signal }) {
            if (signal?.aborted) {
                return Promise.reject(signal.reason ?? new DOMException("Request was aborted", "AbortError"));
            }
            return new Promise((resolve, reject) => {
                const waiter = { resolve, reject, signal, onAbort: undefined };
                waiter.onAbort = () => {
                    const index = queue.indexOf(waiter);
                    if (index >= 0) {
                        queue.splice(index, 1);
                    }
                    reject(signal.reason ?? new DOMException("Request was aborted", "AbortError"));
                };
                if (active < limit) {
                    grant(waiter);
                }
                else {
                    signal?.addEventListener("abort", waiter.onAbort, { once: true });
                    queue.push(waiter);
                }
            });
        },
        snapshot() {
            return { active, peak, releases, queued: queue.length };
        },
    };
}

async function waitFor(predicate, timeoutMs = 3000) {
    const deadline = Date.now() + timeoutMs;
    while (!predicate()) {
        if (Date.now() >= deadline) {
            throw new Error("Timed out waiting for provider gate state");
        }
        await new Promise((resolve) => setTimeout(resolve, 5));
    }
}

async function collect(stream) {
    const events = [];
    for await (const event of stream) {
        events.push(event);
    }
    return events;
}

test("absent handshake is an identity-preserving direct path", () => {
    const inner = controlledProviderStream().stream;
    let providerCalls = 0;
    let acquireCalls = 0;
    const actual = createCapacityStream({
        model,
        context,
        options: {},
        env: { PI_SUBAGENT_CHILD: "1" },
        streamSimple() {
            providerCalls += 1;
            return inner;
        },
        acquireProviderSlot() {
            acquireCalls += 1;
            throw new Error("direct requests must not acquire a capacity slot");
        },
    });
    assert.equal(actual, inner);
    assert.equal(providerCalls, 1);
    assert.equal(acquireCalls, 0);
});

test("non-child calls remain direct even if unrelated capacity bytes are malformed", () => {
    const inner = controlledProviderStream().stream;
    const actual = createCapacityStream({
        model,
        context,
        options: {},
        env: {
            PI_SUBAGENT_CHILD: "0",
            XINAO_PI_SUBAGENT_CAPACITY_V1: "not-json",
        },
        streamSimple: () => inner,
        acquireProviderSlot: () => {
            throw new Error("ordinary root must not acquire a capacity slot");
        },
    });
    assert.equal(actual, inner);
});

test("half, composite-incomplete, malformed, and hash-drift child handshakes fail closed without provider calls", async () => {
    let providerCalls = 0;
    const streamSimple = () => {
        providerCalls += 1;
        return controlledProviderStream().stream;
    };
    const half = createCapacityStream({
        model,
        context,
        options: {},
        env: {
            PI_SUBAGENT_CHILD: "1",
            XINAO_PI_SUBAGENT_CAPACITY_V1: "{}",
        },
        streamSimple,
    });
    const malformed = createCapacityStream({
        model,
        context,
        options: {},
        env: {
            PI_SUBAGENT_CHILD: "1",
            XINAO_PI_SUBAGENT_CAPACITY_V1: "not-json",
            XINAO_PI_SUBAGENT_CAPACITY_SHA256_V1: "0".repeat(64),
            PI_SUBAGENT_ROOT_OWNER_SESSION: "not-json",
            PI_SUBAGENT_ROOT_OWNER_SESSION_SHA256: "0".repeat(64),
        },
        streamSimple,
    });
    const driftEnv = validCapacityEnv("hash-drift");
    driftEnv.PI_SUBAGENT_ROOT_OWNER_SESSION_SHA256 = "f".repeat(64);
    const hashDrift = createCapacityStream({
        model,
        context,
        options: {},
        env: driftEnv,
        streamSimple,
    });
    const incompleteEnv = validCapacityEnv("missing-ticket");
    delete incompleteEnv.XINAO_PI_SUBAGENT_LAUNCH_TICKET_V1;
    delete incompleteEnv.XINAO_PI_SUBAGENT_LAUNCH_TICKET_SHA256_V1;
    const compositeIncomplete = createCapacityStream({
        model,
        context,
        options: {},
        env: incompleteEnv,
        streamSimple,
    });
    const [halfEvents, incompleteEvents, malformedEvents, driftEvents, halfResult, incompleteResult, malformedResult, driftResult] = await Promise.all([
        collect(half),
        collect(compositeIncomplete),
        collect(malformed),
        collect(hashDrift),
        half.result(),
        compositeIncomplete.result(),
        malformed.result(),
        hashDrift.result(),
    ]);
    assert.deepEqual(halfEvents.map((event) => event.type), ["error"]);
    assert.deepEqual(incompleteEvents.map((event) => event.type), ["error"]);
    assert.deepEqual(malformedEvents.map((event) => event.type), ["error"]);
    assert.deepEqual(driftEvents.map((event) => event.type), ["error"]);
    assert.equal(halfResult.stopReason, "error");
    assert.equal(incompleteResult.stopReason, "error");
    assert.equal(malformedResult.stopReason, "error");
    assert.equal(driftResult.stopReason, "error");
    assert.equal(providerCalls, 0);
});

test("provider peak is six and an aborted seventh queue entry never calls provider", async () => {
    const semaphore = createSemaphore(6);
    const providers = [];
    const env = validCapacityEnv("peak-six");
    let providerCalls = 0;
    const streamSimple = () => {
        providerCalls += 1;
        const controlled = controlledProviderStream();
        providers.push(controlled);
        controlled.start();
        return controlled.stream;
    };
    const outputs = Array.from({ length: 6 }, () => createCapacityStream({
        model,
        context,
        options: {},
        env,
        streamSimple,
        acquireProviderSlot: (request) => semaphore.acquire(request),
    }));
    const seventhAbort = new AbortController();
    const seventh = createCapacityStream({
        model,
        context,
        options: { signal: seventhAbort.signal },
        env,
        streamSimple,
        acquireProviderSlot: (request) => semaphore.acquire(request),
    });

    await waitFor(() => providerCalls === 6 && semaphore.snapshot().queued === 1);
    assert.equal(semaphore.snapshot().peak, 6);
    seventhAbort.abort(new DOMException("queued request cancelled", "AbortError"));
    const seventhResult = await seventh.result();
    assert.equal(seventhResult.stopReason, "aborted");
    assert.equal(providerCalls, 6);

    for (const provider of providers) {
        provider.succeed();
    }
    const results = await Promise.all(outputs.map((output) => output.result()));
    assert.ok(results.every((result) => result.stopReason === "stop"));
    assert.deepEqual(semaphore.snapshot(), { active: 0, peak: 6, releases: 6, queued: 0 });
});

test("a synchronous provider throw becomes a terminal stream and releases once", async () => {
    let releases = 0;
    const output = createCapacityStream({
        model,
        context,
        options: {},
        env: validCapacityEnv("sync-throw"),
        streamSimple() {
            throw new Error("synchronous provider failure");
        },
        acquireProviderSlot: async () => ({
            async release() {
                releases += 1;
            },
        }),
    });
    const result = await output.result();
    assert.equal(result.stopReason, "error");
    assert.match(result.errorMessage, /synchronous provider failure/);
    assert.equal(releases, 1);
});

test("abort at slot grant is rechecked before provider invocation", async () => {
    const abort = new AbortController();
    let providerCalls = 0;
    let releases = 0;
    const output = createCapacityStream({
        model,
        context,
        options: { signal: abort.signal },
        env: validCapacityEnv("abort-at-grant"),
        streamSimple() {
            providerCalls += 1;
            return controlledProviderStream().stream;
        },
        acquireProviderSlot: async () => {
            abort.abort(new DOMException("cancelled while granting", "AbortError"));
            return {
                async release() {
                    releases += 1;
                },
            };
        },
    });
    const result = await output.result();
    assert.equal(result.stopReason, "aborted");
    assert.equal(providerCalls, 0);
    assert.equal(releases, 1);
});

test("stopped or stale capacity rejection never reaches the provider", async () => {
    for (const code of ["XINAO_PI_CAPACITY_STOPPED", "XINAO_PI_CAPACITY_STALE_EPOCH"]) {
        let providerCalls = 0;
        const output = createCapacityStream({
            model,
            context,
            options: {},
            env: validCapacityEnv(`reject-${code}`),
            streamSimple() {
                providerCalls += 1;
                return controlledProviderStream().stream;
            },
            acquireProviderSlot: async () => {
                const error = new Error(code);
                error.code = code;
                throw error;
            },
        });
        const result = await output.result();
        assert.equal(result.stopReason, "error");
        assert.match(result.errorMessage, new RegExp(code));
        assert.equal(providerCalls, 0);
    }
});

test("underlying error events are forwarded and settle result after release", async () => {
    let releases = 0;
    const provider = controlledProviderStream();
    const output = createCapacityStream({
        model,
        context,
        options: {},
        env: validCapacityEnv("underlying-error"),
        streamSimple: () => provider.stream,
        acquireProviderSlot: async () => ({
            async release() {
                releases += 1;
            },
        }),
    });
    const eventsPromise = collect(output);
    provider.start();
    provider.fail("underlying error");
    const events = await eventsPromise;
    assert.deepEqual(events.map((event) => event.type), ["start", "error"]);
    assert.equal((await output.result()).errorMessage, "underlying error");
    assert.equal(releases, 1);
});

test("result-only consumption drives the provider and releases the slot", async () => {
    let releases = 0;
    const provider = controlledProviderStream();
    const output = createCapacityStream({
        model,
        context,
        options: {},
        env: validCapacityEnv("result-only"),
        streamSimple: () => provider.stream,
        acquireProviderSlot: async () => ({
            async release() {
                releases += 1;
            },
        }),
    });
    provider.succeed();
    const result = await output.result();
    assert.equal(result.stopReason, "stop");
    assert.equal(releases, 1);
});

test("an early outer iterator return does not release the real provider slot", async () => {
    let releases = 0;
    let providerCalls = 0;
    const provider = controlledProviderStream();
    const output = createCapacityStream({
        model,
        context,
        options: {},
        env: validCapacityEnv("early-iterator"),
        streamSimple() {
            providerCalls += 1;
            return provider.stream;
        },
        acquireProviderSlot: async () => ({
            async release() {
                releases += 1;
            },
        }),
    });
    await waitFor(() => providerCalls === 1);
    const iterator = output[Symbol.asyncIterator]();
    provider.start();
    const first = await iterator.next();
    assert.equal(first.value.type, "start");
    await iterator.return();
    assert.equal(releases, 0);
    provider.succeed();
    assert.equal((await output.result()).stopReason, "stop");
    assert.equal(releases, 1);
});
