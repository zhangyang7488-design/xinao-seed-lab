import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { join, resolve } from "node:path";

const MARKER = "PIS_POST_0841_UPSTREAM_COMPATIBILITY_V1";
const args = process.argv.slice(2);

function arg(name, fallback) {
  const index = args.indexOf(name);
  if (index < 0) return fallback;
  if (index + 1 >= args.length) throw new Error(`Missing value for ${name}`);
  return args[index + 1];
}

const piRootArg = arg("--pi-root", undefined);
if (!piRootArg) {
  throw new Error("Usage: Test-PiSPost0841UpstreamCompatibility.mjs --pi-root <isolated patched root>");
}
const piRoot = resolve(piRootArg);
const upstreamRoot = resolve(
  arg("--upstream-root", "D:/XINAO_RESEARCH_RUNTIME/tools/pi/0.84.1"),
);

const packageRoot = join(piRoot, "node_modules", "@earendil-works", "pi-coding-agent");
const upstreamPackageRoot = join(
  upstreamRoot,
  "node_modules",
  "@earendil-works",
  "pi-coding-agent",
);
const aiRoot = join(packageRoot, "node_modules", "@earendil-works", "pi-ai");
const tuiRoot = join(packageRoot, "node_modules", "@earendil-works", "pi-tui");
const upstreamTuiRoot = join(
  upstreamPackageRoot,
  "node_modules",
  "@earendil-works",
  "pi-tui",
);

async function json(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

async function sha256(path) {
  return createHash("sha256").update(await readFile(path)).digest("hex");
}

const packageJson = await json(join(packageRoot, "package.json"));
const aiPackage = await json(join(aiRoot, "package.json"));
const tuiPackage = await json(join(tuiRoot, "package.json"));
assert.equal(packageJson.name, "@earendil-works/pi-coding-agent");
assert.equal(packageJson.version, "0.84.1");
assert.equal(aiPackage.version, "0.84.1");
assert.equal(tuiPackage.version, "0.84.1");

const paths = {
  ai: join(aiRoot, "dist", "api", "openai-completions.js"),
  models: join(aiRoot, "dist", "providers", "data", "deepseek.json"),
  layout: join(tuiRoot, "dist", "layout.js"),
  upstreamLayout: join(upstreamTuiRoot, "dist", "layout.js"),
};
const observedHashes = {
  ai: await sha256(paths.ai),
  models: await sha256(paths.models),
  layout: await sha256(paths.layout),
  upstreamLayout: await sha256(paths.upstreamLayout),
};
assert.deepEqual(observedHashes, {
  ai: "bd251314511dfac520d6a850871a3359c1d82a3e68f0ef4b72f13dc5e0137070",
  models: "3594c8981450f5c44db389788da793ef5c78f153856c9560394eba1da6dfc3db",
  layout: "257a5e2f77e2bbb14d577279f4800bcd765bdd64c7e41d02d2c7929b28ee0b46",
  upstreamLayout: "fdc6c58b4245e735a0daabdc93201017e77cbbb01d7d440eda6427270556b2af",
});

const providers = await import(
  pathToFileURL(join(aiRoot, "dist", "providers", "all.js")).href
);
const completions = await import(
  pathToFileURL(join(aiRoot, "dist", "api", "openai-completions.js")).href
);
const flash = providers.getBuiltinModel("deepseek", "deepseek-v4-flash");
const pro = providers.getBuiltinModel("deepseek", "deepseek-v4-pro");
assert.ok(flash);
assert.ok(pro);
assert.equal(flash.compat?.maxTokensField, "max_tokens");
assert.equal(pro.compat?.maxTokensField, "max_tokens");

async function capturePayload(model) {
  let payload;
  const stream = completions.streamSimple(
    model,
    { messages: [{ role: "user", content: "payload-only", timestamp: Date.now() }] },
    {
      apiKey: "local-payload-test-key",
      maxTokens: 123,
      onPayload(value) {
        payload = value;
        throw new Error("PIS_PAYLOAD_CAPTURE_COMPLETE");
      },
    },
  );
  try {
    await stream.result();
  } catch {
    // The deliberate onPayload exception prevents every network request.
  }
  assert.ok(payload, `payload missing for ${model.provider}/${model.id}`);
  assert.equal(payload.max_tokens, 123);
  assert.equal(payload.max_completion_tokens, undefined);
}

await capturePayload(flash);
await capturePayload(pro);
await capturePayload({
  ...flash,
  id: "custom-deepseek-payload-test",
  provider: "custom-deepseek-payload-test",
  baseUrl: "https://api.deepseek.com",
  compat: {
    ...flash.compat,
    maxTokensField: undefined,
  },
});

const patchedLayout = await import(pathToFileURL(paths.layout).href);
const upstreamLayout = await import(pathToFileURL(paths.upstreamLayout).href);
const patchedText = await import(
  pathToFileURL(join(tuiRoot, "dist", "components", "text.js")).href
);
const upstreamText = await import(
  pathToFileURL(join(upstreamTuiRoot, "dist", "components", "text.js")).href
);
const patchedUtils = await import(pathToFileURL(join(tuiRoot, "dist", "utils.js")).href);
const upstreamUtils = await import(
  pathToFileURL(join(upstreamTuiRoot, "dist", "utils.js")).href
);
const sample = "\u001b[1m中文研究进度\u001b[0m\nchild verifier still active";
const patchedFrame = patchedLayout.renderLayoutFrame(
  new patchedText.Text(sample, 0, 0),
  50,
  5,
  () => {},
);
const upstreamFrame = upstreamLayout.renderLayoutFrame(
  new upstreamText.Text(sample, 0, 0),
  50,
  5,
  () => {},
);
assert.deepEqual(
  patchedFrame.lines.map((line) => patchedUtils.stripTerminalSequences(line)),
  upstreamFrame.lines.map((line) => upstreamUtils.stripTerminalSequences(line)),
);

process.stdout.write(
  `${JSON.stringify({
    marker: MARKER,
    pi_version: packageJson.version,
    deepseek_builtin_and_custom_use_max_tokens: true,
    provider_request_count: 0,
    fullscreen_render_output_parity: true,
    upstream_layout_preimage_verified: true,
    patched_hashes: observedHashes,
  })}\n`,
);
