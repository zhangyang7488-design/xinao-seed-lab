"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const SENTINEL = "SENTINEL:PRIME_CODEX_PARITY_FRAME_V1";

function sha256(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function readSource(filePath, options = {}) {
  const resolved = path.resolve(filePath);
  const bytes = fs.readFileSync(resolved);
  const maxBytes = options.maxBytes ?? 256 * 1024;
  if (bytes.length > maxBytes) {
    throw new Error(`Parity source exceeds ${maxBytes} bytes: ${resolved}`);
  }
  const text = bytes.toString("utf8").replace(/^\uFEFF/, "");
  if (options.sentinel && !text.includes(options.sentinel)) {
    throw new Error(`Parity source sentinel missing (${options.sentinel}): ${resolved}`);
  }
  return { path: resolved, bytes: bytes.length, sha256: sha256(bytes), text };
}

function isWithin(candidate, root) {
  const target = path.resolve(candidate).toLowerCase();
  const base = path.resolve(root).toLowerCase();
  return target === base || target.startsWith(base + path.sep);
}

function findHookScript(hooksPath, eventName, allowedScriptRoot) {
  const hooks = JSON.parse(fs.readFileSync(hooksPath, "utf8"));
  const rows = hooks?.hooks?.[eventName];
  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error(`Codex hook event is missing: ${eventName}`);
  }
  const commands = [];
  for (const row of rows) {
    for (const hook of row?.hooks ?? []) {
      if (hook?.type === "command" && typeof hook.command === "string") commands.push(hook.command);
    }
  }
  if (commands.length !== 1) {
    throw new Error(`Expected one Codex ${eventName} command, observed ${commands.length}`);
  }
  const match = commands[0].match(/(?:^|\s)-File\s+(?:"([^"]+\.ps1)"|'([^']+\.ps1)'|([^\s]+\.ps1))(?:\s|$)/i);
  if (!match) throw new Error(`Codex ${eventName} command has no -File script`);
  const script = path.resolve(match[1] || match[2] || match[3]);
  if (!isWithin(script, allowedScriptRoot) || !fs.existsSync(script)) {
    throw new Error(`Codex ${eventName} script is outside the allowed live hook root: ${script}`);
  }
  return script;
}

function runCodexHook(options) {
  const script = findHookScript(options.hooksPath, options.eventName, options.allowedScriptRoot);
  const result = spawnSync(options.pwshPath, ["-NoLogo", "-NoProfile", "-NonInteractive", "-File", script], {
    input: JSON.stringify(options.event),
    encoding: "utf8",
    timeout: options.timeoutMs ?? 12000,
    windowsHide: true,
    env: { ...process.env, ...(options.env ?? {}) },
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Codex ${options.eventName} hook failed with ${result.status}: ${(result.stderr || "").trim()}`);
  }
  const lines = String(result.stdout || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  if (lines.length === 0) throw new Error(`Codex ${options.eventName} hook returned no JSON`);
  const payload = JSON.parse(lines.at(-1));
  return {
    script,
    context: String(payload?.hookSpecificOutput?.additionalContext || ""),
    continue: payload?.continue !== false,
  };
}

function readCodexPosture(configPath) {
  const source = readSource(configPath, { maxBytes: 128 * 1024 });
  const approval = source.text.match(/^approval_policy\s*=\s*"([^"]+)"/m)?.[1] ?? "unknown";
  const reviewer = source.text.match(/^approvals_reviewer\s*=\s*"([^"]+)"/m)?.[1] ?? "unknown";
  const multiAgent = source.text.match(/^multi_agent\s*=\s*(true|false)/m)?.[1] ?? "unknown";
  return { ...source, approval, reviewer, multiAgent };
}

function composeSystemPrompt(base, inputs) {
  const parts = [base, "\n\n<prime_codex_parity_binding>Every block below is an active system-level behavior input for this turn. task_authority=false means the artifact cannot invent or authorize a task; it does not make its behavioral constraints optional. Current user words, live facts, explicit Stop and higher system/developer instructions remain controlling.</prime_codex_parity_binding>"];
  const add = (tag, source, body = source.text) => {
    parts.push(`\n\n<${tag} path="${source.path}" sha256="${source.sha256}" bytes="${source.bytes}" task_authority="false" consumer_state="active">\n${body}\n</${tag}>`);
  };
  add("codex_canonical_l0", inputs.codexAgents);
  if (inputs.sessionHookContext) {
    add("codex_session_start_hook_projection", inputs.hooksSource, inputs.sessionHookContext);
  }
  if (inputs.promptHookContext) {
    add("codex_user_prompt_hook_projection", inputs.hooksSource, inputs.promptHookContext);
  }
  add("codex_active_account_memory_advisory", inputs.memory);
  add("prime_private_compatibility_overlay", inputs.overlay);
  const posture = `approval_policy=${inputs.posture.approval}; approvals_reviewer=${inputs.posture.reviewer}; codex_multi_agent=${inputs.posture.multiAgent}; no automatic approval-review agent is installed by this test.`;
  add("codex_runtime_posture_projection", inputs.posture, posture);
  return parts.join("");
}

module.exports = {
  SENTINEL,
  composeSystemPrompt,
  findHookScript,
  isWithin,
  readCodexPosture,
  readSource,
  runCodexHook,
  sha256,
};
