# Codex load-preserving context closure and old-report reconciliation (2026-07-13)

## Outcome

The implementation goal is to reduce Codex expert-side default context without reducing the user's ability to express incomplete, nontechnical, example-led intent or to access installed capabilities.

- Fresh `codex debug prompt-input` total JSON: **47,231 → 23,337 characters**.
- Merged global + S project AGENTS payload: **30,179 → 6,323 characters** (about 79% smaller).
- Installed/enabled plugins: **40 → 40**. Configured MCPs remain enabled. Core skills, memory, browser/desktop, image, eval, Grok-worker, and Temporal capabilities remain discoverable.
- Full details were not deleted: the D-drive working agreement remains canonical cold context, and the prior S project agreement is versioned as `docs/current/CODEX_S_PROJECT_AGREEMENT_COLD_2026-07-13.md`.
- Repository tests now verify the hot pointer and cold semantic contract together instead of forcing every detailed invariant into every fresh prompt.

## Mature comparison that changed the choice

- OpenAI Codex AGENTS discovery concatenates the global and project files into the prompt and caps project instruction discovery by bytes. This made the 30K local AGENTS payload a real hot-path cost: https://learn.chatgpt.com/docs/agent-configuration/agents-md#how-codex-discovers-guidance
- OpenAI skills use progressive disclosure: startup metadata first, full `SKILL.md` only after selection. Therefore uninstalling plugins/skills was the wrong first lever: https://learn.chatgpt.com/docs/build-skills
- The Agent Skills client pattern exposes name/description/location and reads the body on activation. The same shape now backs the hot AGENTS pointer + cold contract: https://agentskills.io/client-implementation/adding-skills-support
- Anthropic context engineering recommends a small, high-signal context and autonomous just-in-time retrieval. This supported indexing rather than capability deletion: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- OpenHands also exposes Agent Skills progressively, confirming the mechanism across a mature open-source agent: https://docs.openhands.dev/sdk/guides/skill

OpenAI `tool_search/defer_loading` is a Responses API tool-definition mechanism, not a documented Codex CLI `mcp_servers.*` config key. It was therefore **not** hand-welded into the local MCP layer: https://developers.openai.com/api/docs/guides/tools

## What was implemented

1. `C:\Users\xx363\.codex\AGENTS.md` became a global hot routing shell. It retains intent recovery, examples-as-probes, mature-first, capability availability, task authorization, Grok routing, external-effect boundaries, and cold retrieval triggers.
2. `AGENTS.md` became the S-specific hot delta instead of a second detailed global contract.
3. `docs/current/CODEX_S_PROJECT_AGREEMENT_COLD_2026-07-13.md` preserves the detailed S contract on demand.
4. `tests/test_repo_safety.py` validates the hot+cold pair; this prevents both silent capability loss and accidental re-inlining of the detailed contract.
5. Five behavior expectations were corrected where the old fixture contradicted its own scenario: referential object identity comes from restored context; explicitly requested local worker execution is a reversible local effect; a named durable route comes from the current increment; consolidation first inspects the isolated local roots.
6. The integrated-bus CLI now falls back to ASCII JSON escapes when a narrow Windows console codec cannot emit an emoji. The live failure was `UnicodeEncodeError` after the Temporal result already existed.

## Old side-detection report: P0-P7

| Item | Disposition | Current evidence |
|---|---|---|
| P0 canonical home | **Already superseded** | Launcher, config, and situation-island index all name `C:\Users\xx363\.codex`. The old seed directory still exists as historical state but is not the current launcher home. |
| P1 disable non-core plugins | **Explicitly rejected** | 40 plugins remain enabled; fresh context showed skill metadata/progressive loading rather than 336 full skill bodies. Removing capabilities would narrow help for unknown user needs. |
| P2 dedupe/shorten skills | **Old measurement stale; no current change** | Fresh skill catalog is bounded and bodies are JIT. Description optimization remains a measured future candidate only if prompt evidence shows a real trigger/catalog problem. |
| P3 AGENTS index shell | **Implemented and measured** | AGENTS payload fell from 30,179 to 6,323 chars; complete details remain in cold contracts. |
| P4 session index/process bookmarks/auth | **Mostly obsolete or closed** | Codex currently has SQLite state plus 14 session files; the old four-line `session_index.jsonl` is not treated as truth. No live process-manager reference was found. `gh auth status` confirms `delete_repo`, `repo`, and `workflow` scopes in the native keyring. |
| P5 enabled is not invocation proof | **Absorbed and operationalized** | This run used fresh `prompt-input`, `plugin list`, real app-server trajectories, real Temporal history, and lane evidence instead of configuration labels. |
| P6 WorkerPool exit=2 | **Old incident superseded; fallback remains bounded** | Recent pools can run. In this run one full lane passed and two lanes honestly failed at max-turn limits; they were not counted as success. |
| P7 missing root intent loop | **Explicitly rejected** | `root_intent_loop_driver` is legacy/second-controller shape and must not be resurrected. Intent recovery lives in hot routing, checkpoint/memory retrieval, behavior cases, and bounded task episodes. |

## `新建 文本文档.txt` Top-5 closure map

| Chain | Current status | Evidence |
|---|---|---|
| Behavior regression / golden trajectories | **Default on demand** | 59-case catalog, Promptfoo 0.121.18, real Codex app-server traces, deterministic assertions. |
| Trace/failure → candidate | **Implemented, not auto-promoted** | `Import-PromptfooFailuresToBehaviorCandidates.ps1` and `New-BehaviorRegressionCandidate.ps1`; provenance and prohibited-side-effect fields are required. |
| Memory/correction changes behavior | **Implemented as smallest landing; deliberately not autonomous policy rewrite** | decision model, preference cases, checkpoint/memory provenance, and candidate flow. |
| Acceptance before completion claim | **Implemented for material tasks** | `verified-agent-loop` ledger and four-state terminal evidence. It is not imposed as ceremony on trivial dialogue. |
| Context engineering | **Now materially closed at the hot/cold seam** | Fresh prompt measurement, intent cases, hot routing shell, versioned cold contract, and tests that enforce the pair. |

## Honest remaining gaps

- The direct `integrated_bus_runner` workflow completed with workflow `xinao-integrated-bus-03e95993daf2`, run `e37a1a03-06be-4cd8-b83e-aa96e0a2bfda`, history length 185, but reported `GROK_FANIN_REQUIRED`. This entry consumes an existing Grok fan-in and did not itself dispatch research lanes. The generic end-to-end canonical Grok dispatch entry therefore remains **unverified**, not silently repaired here.
- Daily conversation/trace → candidate is an explicit one-way intake, not an always-on monitor. This is intentional until real repeated misses justify a thin native trigger.
- Codex CLI does not document per-MCP `defer_loading`; MCP schema/startup optimization remains a measured future candidate, not a hand-built second gateway.
- Real ephemeral app-server cases did start the configured local stdio MCP process set, so MCP startup latency is a genuine remaining cost even though `prompt-input` itself did not spawn them. No server was disabled because that would trade away capability before a native lazy-start surface is proven.
- The first two fallback research lanes did not both pass. One complete Grok report is valid independent evidence; failed lanes remain failed evidence.
- Complete Grok report: `D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool\gwp_20260713T114630_0527ad2c\lane_01\c25_20260713T114630_c201ce68.out.log`.

## Verification

- `pytest`: 127 passed.
- Ruff: passed.
- `compileall`: passed.
- Fresh prompt core capability markers and both V3 sentinels: present.
- Stable full live behavior run `20260713-115306-196`: **17/19**. The only two failures were the clauses changed afterward. Impacted-domain reruns then passed: worker routing `20260713-120128-910` **4/4**, topology `20260713-120257-046` **2/2**. This composes fresh passing evidence for all changed behavior without rerunning unrelated passing cases as a lottery.
- Task evidence root: `D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\runs\codex-load-preserving-capability-20260713-001`.

Local context-reduction `completion_claim_allowed=true` after the recorded fresh-process, behavior, test, and secret-scan evidence. The generic canonical Grok dispatch entry remains `partial` and is not included in that claim.
