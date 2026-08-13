# Context runtime trajectory harness

This suite keeps deterministic context-runtime contracts separate from live
Codex behavior evidence.

## Contract mode

The canonical behavior runner invokes:

```powershell
uv run python evals/context_runtime_trajectory/run_context_runtime_trajectory.py `
  --mode contract `
  --operation-root D:\path\to\operation-scoped-root `
  --output D:\path\to\context-runtime-contract.receipt.json
```

The operation root must be new or empty. Each case owns a separate store. The
fresh ablation additionally owns different `enabled-store` and `empty-store`
roots. Contract mode never uses the production Context Fabric, production
Codex homes, a model, network access, or tools.

The four deterministic cases cover:

- S-to-B source-linked fresh materialization versus an empty-store ablation;
- secret-withholding and structural non-authority for discussion and Stop;
- A/C clean-room denial with byte-identical S/B store readback;
- corrupt-store fail-open behavior preserving the L0 current-words layer.

`runtime_claim_allowed` is always `false`. Contract success does **not** prove
that a model interpreted the history correctly, avoided tools, crossed an
actual app-server compact/resume boundary, or reduced longitudinal user burden.

## Live mode

The live interface is:

```powershell
uv run python evals/context_runtime_trajectory/run_context_runtime_trajectory.py `
  --mode live `
  --operation-root D:\path\to\operation-scoped-root `
  --output D:\path\to\context-runtime-live.receipt.json `
  --codex-path D:\path\to\codex.exe `
  --s-codex-home C:\path\to\s-home `
  --b-codex-home C:\path\to\b-home `
  --working-dir E:\XINAO_RESEARCH_WORKSPACES\S `
  --hook-sink D:\path\to\hook-sink-contract.json
```

The hook-sink contract is deliberately non-secret and bounded:

```json
{
  "schema_version": "s.context_runtime_live_hook_sink.v1",
  "model": "gpt-5.6-sol",
  "timeout_seconds": 180,
  "auth_env": "OPENAI_API_KEY"
}
```

The default `auth_mode` is `environment_isolated`. In that mode, `auth_env` may
name only `OPENAI_API_KEY` or `CODEX_ACCESS_TOKEN`; omit it to select the first
one already present. The app-server child receives only
`SYSTEMROOT`, `WINDIR`, `COMSPEC`, `PATH`, `PATHEXT`, `TEMP`, `TMP`, the two
operation paths, and that one selected authentication variable. Every other
ambient variable is dropped. The harness never prints, copies, or writes the
authentication value. The generated hook wrapper strips both admitted
authentication variables and every other ambient variable again before
starting the hook adapter; that child receives only the seven Windows runtime
variables plus the S mount identity and isolated Fabric root.

The harness creates a fresh operation-scoped `CODEX_HOME`, config, hook
registry, thread state, hook wrapper, hook log, and Context Fabric store. The
supplied S home is used only as the S mount identity inside the isolated hook
child. If no environment-provided credential is available, live mode returns
typed `ineligible` and exit code `3` instead of copying `auth.json`.

An explicitly authorized run may instead use Account B's already configured
account session without moving its credential:

```json
{
  "schema_version": "s.context_runtime_live_hook_sink.v1",
  "model": "gpt-5.6-sol",
  "timeout_seconds": 180,
  "auth_mode": "existing_b_home"
}
```

This opt-in mode requires the supplied B home to be the exact admitted
`s-account-b` mount and requires its existing `auth.json`, `AGENTS.md`,
`config.toml`, and `hooks.json`. It cannot also specify `auth_env`. The native
children receive the same seven Windows variables plus only `CODEX_HOME=<B>`
and the operation-scoped `CODEX_CONTEXT_FABRIC_ROOT`; ambient API keys, access
tokens, and unrelated variables are not forwarded. The harness never parses,
reads, hashes, copies, links, or prints the credential. It observes only whether
`auth.json` is a file and records `auth_content_read=false`,
`source_credentials_copied=false`, and `source_credentials_symlinked=false`.

`existing_b_home` uses the already installed, trusted B hooks directly; it
does not generate a temporary hook wrapper or hook log. Evidence comes from
native `hook/completed` notifications and an independent readback of only the
test session's events in the isolated Fabric store. The run creates one named,
persisted test thread/rollout in B's normal session area. Success additionally
requires the non-secret `AGENTS.md`/`config.toml`/`hooks.json` fingerprints to
remain unchanged, auth presence to remain available without reading its
contents, and exactly one new rollout path to contain the returned thread id.
The receipt states `existing_account_session_written=true`. A normal account
token refresh is outside the configuration-stability assertion; an extra
rollout or missing installed-hook/Fabric observation fails the live case.

Claim-eligible live success jointly observes:

1. real `initialize`, `thread/start|resume`, `turn/start`, and
   `thread/compact/start` app-server events;
2. real installed-hook discovery/trust plus app-server
   `hook/started|completed`, and either the operation hook-sink order or the
   existing-B isolated-Fabric session readback;
3. isolated S/B homes and stores; and
4. model item events used by bounded hidden-referent assertions, with no tool
   item in those turns.

The live case starts a persisted thread, runs two turns, requests native
`thread/compact/start`, requires a `contextCompaction` item and
the corresponding completed compaction turn plus `SessionStart(compact)`, runs
a post-compact turn, then launches a different native process, performs
`thread/resume`, and runs one more turn. Direct JSON-stdio
calls to the hook adapter cannot satisfy that evidence bar. Success proves only
that one bounded native trajectory survived; it does not isolate Context Fabric
as the sole causal mechanism, prove permanent model uptake, or establish a
longitudinal reduction in correction burden.

Exit codes are `0` pass, `1` assertion or post-eligibility native-protocol
failure, `2` usage or pre-protocol infrastructure failure, and `3` missing live
prerequisites. Once every prerequisite has passed, native protocol errors and
timeouts are recorded as `context_live_observed` / `failed`; they cannot be
downgraded to `context_live_ineligible`.
