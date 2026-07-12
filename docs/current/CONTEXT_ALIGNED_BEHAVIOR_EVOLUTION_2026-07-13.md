# Context-aligned behavior evolution

## What changed

The observed failure was low-loss and reversible: existing authorization to close, merge, and push
work was incorrectly expanded into four new private GitHub repositories. The useful correction is
not a repository-creation ban or another approval workflow. It is a context-conditioned learning
loop that preserves fast local action.

## Hot-path behavior

For each user increment, recover the current goal, stable user preferences, real local objects, and
prior decisions. Choose the interpretation closest to the current state that is reversible. Only
when an interpretation would create an object, change topology or route, publish, or cause another
material external effect, run a lightweight official maturity comparison and let it affect the
choice. Validate object-to-intent fit before validating engineering correctness.

This orientation does not add routine questions. Reversible local work proceeds. A user answer is
needed only when inspection cannot resolve a material external-effect fork. Agent assumptions may
generate candidates, but never authorization.

## Cold-path learning loop

1. Capture one evidenced failure trajectory and the corrected user intent.
2. Convert it into balanced behavior cases: the failed case, ordinary productivity cases, explicit
   authority cases, and prohibited-side-effect cases.
3. Change one instruction, prompt, router, skill, or thin adapter at a time.
4. Replay the cases through the real agent surface in a read-only sandbox.
5. Promote only when the failed behavior flips while productivity and negative cases remain green.
6. Keep the old behavior as a regression and feed later user corrections back into the suite.

The implementation here is `AGENTS.md` plus `evals/context_intent_alignment`; it creates no daemon,
fixed score, fixed lane count, mandatory tool sequence, or second control plane.

## External maturity basis

- [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices):
  mine real failures, use scoped balanced tests, automate evaluation, and calibrate with humans.
- [OpenAI realtime evaluation guide](https://developers.openai.com/cookbook/examples/realtime_eval_guide#42-build-for-iteration-not-just-volume):
  localize behavior, change one thing, rerun, and confirm no regressions.
- [Anthropic agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents):
  turn user-reported failures into test cases and graduate capability tests into regressions.
- [Google SRE postmortem culture](https://sre.google/workbook/postmortem-culture/): use
  blameless systemic learning rather than blame or rule accumulation.
- [NIST AI RMF Map](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/): establish the
  use context before a go/no-go decision and interpret outputs inside that context.
- [Microsoft Human-AI Guideline G10](https://www.microsoft.com/en-us/research/blog/guidelines-for-human-ai-interaction-design/):
  scope services when goal uncertainty is material.

## Repository disposition

The useful engineering histories of `xinao-dual-brain-coordination` and `xinao-market-lab` are
preserved under `projects/` with exact source tree hashes. The two Grok identity/isolation
workspaces stay in verified offline bundles; publishing them would reintroduce local identity,
path, and control-surface material without adding a product boundary. The recovery manifest records
the exact four repository IDs, source commits, bundle digests, and dispositions.
