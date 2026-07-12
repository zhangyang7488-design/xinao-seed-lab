import fs from "node:fs";
import process from "node:process";
import readline from "node:readline";
import { pathToFileURL } from "node:url";

function emit(value) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}

async function exitAfterFlush(code) {
  await new Promise((resolve) => process.stdout.write("", resolve));
  process.exit(code);
}

function safeError(error) {
  return {
    message: error instanceof Error ? error.message : String(error),
    code: typeof error?.code === "string" ? error.code : undefined,
  };
}

function sanitizedEvent(event, requestId) {
  if (event.type === "text_delta") {
    if (event.stream === "thought") {
      return {
        type: "thought_progress",
        requestId,
        chars: event.text.length,
        tag: event.tag,
      };
    }
    return {
      type: "text_delta",
      requestId,
      text: event.text,
      stream: event.stream ?? "output",
      tag: event.tag,
    };
  }
  if (event.type === "tool_call") {
    return {
      type: "tool_call",
      requestId,
      toolCallId: event.toolCallId,
      title: event.title,
      status: event.status,
      kind: event.kind,
      tag: event.tag,
    };
  }
  if (event.type === "status") {
    return {
      type: "status",
      requestId,
      text: event.text,
      tag: event.tag,
      used: event.used,
      size: event.size,
    };
  }
  return { type: event.type, requestId };
}

async function main() {
  let input;
  let turn;
  let turnStarted = false;
  let resultAuthoritative = false;
  const specPath = process.argv[2];
  try {
    if (!specPath) {
      throw new Error("operation spec path is required");
    }
    const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
    for (const [key, value] of Object.entries(spec.agent_env ?? {})) {
      process.env[key] = String(value);
    }

    let cancelPending = false;
    let startSeen = false;
    let resolveStart;
    let rejectStart;
    const startSignal = new Promise((resolve, reject) => {
      resolveStart = resolve;
      rejectStart = reject;
    });
    input = readline.createInterface({ input: process.stdin });
    input.on("line", (line) => {
      try {
        const command = JSON.parse(line);
        if (command.action === "start" && !startSeen) {
          startSeen = true;
          resolveStart();
          return;
        }
        if (command.action !== "cancel") return;
        cancelPending = true;
        if (turn) {
          void turn.cancel({ reason: command.reason ?? "cancel requested" });
        }
      } catch {
        emit({ type: "control_error", requestId: spec.request_id });
      }
    });
    input.on("close", () => {
      if (!startSeen) rejectStart(new Error("control stream closed before start gate"));
    });
    await startSignal;

    const runtimeModule = await import(pathToFileURL(spec.runtime_module).href);
    const registry = runtimeModule.createAgentRegistry({
      overrides: {
        "grok-build":
          "D:/XINAO_RESEARCH_RUNTIME/tools/hidden-stdio/generations/hidden-stdio-ed4e70b708e564e68f815858/xinao-hidden-stdio.exe " +
          "C:/Users/xx363/.grok/bin/grok.exe --no-auto-update --disallowed-tools run_terminal_cmd,run_terminal_command agent stdio",
      },
    });
    const runtime = runtimeModule.createAcpRuntime({
      cwd: spec.cwd,
      sessionStore: runtimeModule.createRuntimeStore({ stateDir: spec.state_dir }),
      agentRegistry: registry,
      permissionMode: spec.permission_mode,
      nonInteractivePermissions: spec.non_interactive_permissions,
      timeoutMs: spec.timeout_ms,
    });

    await runtime.probeAvailability();
    const handle = await runtime.ensureSession({
      sessionKey: spec.session_key,
      agent: "grok-build",
      mode: "persistent",
      cwd: spec.cwd,
      sessionOptions: {
        model: spec.model,
        allowedTools: spec.allowed_tools,
        maxTurns: spec.max_turns,
      },
    });
    emit({
      type: "session_resolved",
      requestId: spec.request_id,
      sessionKey: handle.sessionKey,
      acpxRecordId: handle.acpxRecordId,
      backendSessionId: handle.backendSessionId,
      agentSessionId: handle.agentSessionId,
    });

    if (cancelPending) {
      emit({
        type: "terminal",
        requestId: spec.request_id,
        result: { status: "cancelled", stopReason: "canceled_before_prompt" },
        finalText: "",
        turnStarted: false,
        resultAuthoritative: true,
        acpxRecordId: handle.acpxRecordId,
        backendSessionId: handle.backendSessionId,
        agentSessionId: handle.agentSessionId,
      });
      input.close();
      await exitAfterFlush(0);
      return;
    }

    emit({ type: "turn_starting", requestId: spec.request_id });
    turnStarted = true;
    turn = runtime.startTurn({
      handle,
      text: spec.prompt,
      mode: "prompt",
      requestId: spec.request_id,
      timeoutMs: spec.timeout_ms,
    });

    let finalText = "";
    for await (const event of turn.events) {
      if (event.type === "text_delta" && event.stream !== "thought") {
        finalText += event.text;
      }
      emit(sanitizedEvent(event, spec.request_id));
    }
    const result = await turn.result;
    resultAuthoritative = true;
    const status = await runtime.getStatus({ handle }).catch(() => ({}));
    emit({
      type: "terminal",
      requestId: spec.request_id,
      result,
      finalText,
      turnStarted,
      resultAuthoritative,
      acpxRecordId: status.acpxRecordId ?? handle.acpxRecordId,
      backendSessionId: status.backendSessionId ?? handle.backendSessionId,
      agentSessionId: status.agentSessionId ?? handle.agentSessionId,
    });
    input.close();
    await exitAfterFlush(result.status === "failed" ? 2 : 0);
  } catch (error) {
    emit({
      type: "terminal",
      status: "failed",
      error: safeError(error),
      turnStarted,
      resultAuthoritative,
    });
    input?.close();
    await exitAfterFlush(2);
  }
}

void main();
