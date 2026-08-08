import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { mkdirSync, renameSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import loader from "./frame-loader.cjs";

const {
  SENTINEL,
  composeSystemPrompt,
  isWithin,
  readCodexPosture,
  readSource,
  runCodexHook,
} = loader as any;

const CODEX_ROOT = resolve(process.env.PRIME_CODEX_PARITY_CODEX_ROOT || "C:/Users/xx363/.codex");
const ACCOUNT_HOME = resolve(process.env.PRIME_CODEX_PARITY_ACCOUNT_HOME || "C:/Users/xx363/.codex-s-hardmode-account-b");
const S_ROOT = resolve(process.env.PRIME_CODEX_PARITY_S_ROOT || "E:/XINAO_RESEARCH_WORKSPACES/S");
const OVERLAY_ROOT = resolve(process.env.PRIME_CODEX_PARITY_OVERLAY_ROOT || "D:/XINAO_RESEARCH_RUNTIME/state/prime-agent/parity-test/codex-compatible/overlay");
const RUNTIME_ROOT = resolve(process.env.PRIME_CODEX_PARITY_RUNTIME_ROOT || "D:/XINAO_RESEARCH_RUNTIME/state/prime-agent/parity-test/codex-compatible");
const HOOK_SCRIPT_ROOT = resolve("D:/XINAO_RESEARCH_RUNTIME/state/Codex_Situation_Island/scripts");
const PWSH = resolve(process.env.PRIME_CODEX_PARITY_PWSH || "D:/XINAO_RESEARCH_RUNTIME/tools/powershell/7.6.4/pwsh.exe");

const protectedRoots = [
  CODEX_ROOT,
  ACCOUNT_HOME,
  resolve("E:/XINAO_RESEARCH_WORKSPACES/prime-agent-local-cognition-island"),
  resolve(S_ROOT, "infra/prime_codex_parity_test"),
];

function atomicProbe(targetValue: string | undefined, payload: object): void {
  if (!targetValue) return;
  const target = resolve(targetValue);
  if (!isWithin(target, RUNTIME_ROOT)) {
    throw new Error(`PRIME_CODEX_PARITY_PROBE is outside parity runtime: ${target}`);
  }
  mkdirSync(dirname(target), { recursive: true });
  const temporary = `${target}.${process.pid}.${Date.now()}.tmp`;
  writeFileSync(temporary, JSON.stringify(payload, null, 2), { encoding: "utf8" });
  renameSync(temporary, target);
}

function hookEvent(ctx: any, eventName: string, prompt = "", source = "startup"): object {
  return {
    hook_event_name: eventName,
    session_id: ctx.sessionManager.getSessionId(),
    turn_id: ctx.sessionManager.getLeafId?.() || `${Date.now()}`,
    cwd: ctx.cwd,
    transcript_path: ctx.sessionManager.getSessionFile() || "",
    prompt,
    source,
  };
}

function hookEnv(ctx: any): Record<string, string> {
  return {
    CODEX_ACTIVE_TASK_STATE_ROOT: resolve(RUNTIME_ROOT, "continuation"),
    CODEX_HOOK_TEST_SESSION_ROOT: resolve(ctx.sessionManager.getSessionDir()),
  };
}

function resolveEditPaths(input: Record<string, unknown>, cwd: string): string[] {
  const values: string[] = [];
  for (const key of ["path", "file", "filePath", "target", "targetPath"]) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) {
      values.push(resolve(cwd, value));
    }
  }
  return values;
}

export default function primeCodexParityExtension(pi: ExtensionAPI) {
  let sessionHookContext = "";
  let sessionHookScript = "";

  pi.on("resources_discover", async () => ({
    skillPaths: [
      resolve(CODEX_ROOT, "skills"),
      resolve(OVERLAY_ROOT, "skills"),
    ],
  }));

  pi.on("session_start", async (event, ctx) => {
    try {
      const result = runCodexHook({
        hooksPath: resolve(ACCOUNT_HOME, "hooks.json"),
        eventName: "SessionStart",
        allowedScriptRoot: HOOK_SCRIPT_ROOT,
        pwshPath: PWSH,
        event: hookEvent(ctx, "SessionStart", "", event.reason === "reload" ? "resume" : event.reason),
        env: hookEnv(ctx),
      });
      sessionHookContext = result.context;
      sessionHookScript = result.script;
    } catch (error) {
      sessionHookContext = `SESSION_START_HOOK_ADAPTER_PARTIAL: ${error instanceof Error ? error.message : String(error)}. Continue from current words and live facts; do not invent a task from cwd or reports.`;
      sessionHookScript = resolve(ACCOUNT_HOME, "hooks.json");
    }
  });

  pi.on("before_agent_start", async (event, ctx) => {
    const codexAgents = readSource(resolve(CODEX_ROOT, "AGENTS.md"), { maxBytes: 96 * 1024, sentinel: "SENTINEL:HUMAN_INTENT_CONTINUITY_ROLE_SEPARATION_V1" });
    const memory = readSource(resolve(ACCOUNT_HOME, "memories/memory_summary.md"), { maxBytes: 64 * 1024 });
    const overlay = readSource(resolve(OVERLAY_ROOT, "FRAME.md"), { maxBytes: 24 * 1024, sentinel: SENTINEL });
    const posture = readCodexPosture(resolve(CODEX_ROOT, "config.toml"));
    const hooksSource = readSource(resolve(ACCOUNT_HOME, "hooks.json"), { maxBytes: 32 * 1024 });

    let promptHookContext = "";
    let promptHookScript = "";
    try {
      const result = runCodexHook({
        hooksPath: hooksSource.path,
        eventName: "UserPromptSubmit",
        allowedScriptRoot: HOOK_SCRIPT_ROOT,
        pwshPath: PWSH,
        event: hookEvent(ctx, "UserPromptSubmit", event.prompt, "prompt"),
        env: hookEnv(ctx),
      });
      promptHookContext = result.context;
      promptHookScript = result.script;
    } catch (error) {
      promptHookContext = `ZERO_BEAT_HOOK_ADAPTER_PARTIAL: ${error instanceof Error ? error.message : String(error)}. Decode the current utterance and live object before choosing work; fail open without inventing a task.`;
      promptHookScript = hooksSource.path;
    }

    const effectiveSystemPrompt = composeSystemPrompt(event.systemPrompt, {
      codexAgents,
      hooksSource,
      sessionHookContext,
      promptHookContext,
      memory,
      overlay,
      posture,
    });
    const contextFiles = (event.systemPromptOptions?.contextFiles ?? []).map((item: unknown) =>
      typeof item === "string" ? item : JSON.stringify(item),
    );
    atomicProbe(process.env.PRIME_CODEX_PARITY_PROBE, {
      schema: "xinao.prime_codex_parity.before_agent_start_probe.v1",
      observed_at: new Date().toISOString(),
      session_id: ctx.sessionManager.getSessionId(),
      session_file: ctx.sessionManager.getSessionFile(),
      cwd: ctx.cwd,
      sentinel: SENTINEL,
      codex_agents: { path: codexAgents.path, sha256: codexAgents.sha256, bytes: codexAgents.bytes },
      codex_memory: { path: memory.path, sha256: memory.sha256, bytes: memory.bytes },
      codex_config: { path: posture.path, sha256: posture.sha256, approval_policy: posture.approval, approvals_reviewer: posture.reviewer },
      codex_hooks: { path: hooksSource.path, sha256: hooksSource.sha256, session_script: sessionHookScript, prompt_script: promptHookScript },
      overlay: { path: overlay.path, sha256: overlay.sha256, bytes: overlay.bytes },
      context_files: contextFiles,
      s_context_loaded: effectiveSystemPrompt.includes("SENTINEL:S_GENERIC_ENGINEERING_ROLE_V1") || contextFiles.some((item: string) => item.replaceAll("/", "\\").toLowerCase().includes("xinao_research_workspaces\\s\\agents.md")),
      effective_system_prompt_has_codex_l0: effectiveSystemPrompt.includes("<codex_canonical_l0"),
      effective_system_prompt_has_zero_beat: effectiveSystemPrompt.includes("SENTINEL:ZERO_BEAT_CURRENT_INCREMENT_V1"),
      effective_system_prompt_has_memory: effectiveSystemPrompt.includes("<codex_active_account_memory_advisory"),
      active_account_home: ACCOUNT_HOME,
      active_account_id: process.env.XINAO_ACCOUNT_SLOT || "unknown",
      effective_system_prompt_has_overlay: effectiveSystemPrompt.includes(SENTINEL),
      source_direction: "codex_and_s_read_into_prime_private_overlay_no_reverse_sync",
      formal_owner_appointment_changed: false,
      authority: false,
    });
    return { systemPrompt: effectiveSystemPrompt };
  });

  // The test has full host permission by user choice. This deterministic guard
  // prevents the ordinary edit tool from using an upstream behavior source as
  // the Prime-private evolution target; it is defense in depth, not an OS sandbox.
  pi.on("tool_call", async (event, ctx) => {
    if (event.toolName !== "edit") return;
    const targets = resolveEditPaths(event.input as Record<string, unknown>, ctx.cwd);
    const blocked = targets.find((target) => protectedRoots.some((root) => isWithin(target, root)));
    if (blocked) {
      return {
        block: true,
        reason: `Prime parity upstream behavior source is read-only; write a candidate under ${OVERLAY_ROOT}: ${blocked}`,
      };
    }
  });
}
