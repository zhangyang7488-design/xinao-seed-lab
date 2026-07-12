# P3 ResearchProtocol + JudgeGate

Resolution key: `p3-research-protocol-judge-gate-v1`.

P3 adds experiment discipline to the verified P1/P2 mechanics kernel. It does not add a second
orchestrator, a prediction engine, or a market-data claim.

## Frozen protocol

The protocol is serialized and hashed before any P3 trial row is generated. Every trial row carries
both the semantic protocol hash and the SHA-256 of the frozen protocol artifact.

- `S`: exactly four existing mechanical candidates: `always_no_bet`, `fixed_01`,
  `previous_special`, and `rolling_mode_49`.
- Rules: exactly the eight P2 typed exact-number projections.
- `R`: exactly 32 candidate/rule cells and 38,528 rows over 1,204 lineage-v2 draws. Hidden expansion is
  invalid.
- `P`: input snapshot, accepted P2 evidence, rule hashes, one named CostModel/payout assumption, and
  four explicit chronological event-time folds of 301 draws each.
- `M`: draws, bets, wins, stake, and mechanical gross/net totals under the named assumption. Ordering,
  ranking, winner selection, recommendation, and economic inference are disabled.

The current scale intentionally reuses Pydantic, pytest, Hypothesis, the existing deterministic
runner, and JSONL evidence. MLflow, Great Expectations, scikit-learn, Ray, DVC, and Temporal remain
deferred until their actual storage, collaboration, validation, scheduling, or model-evaluation
surfaces are needed.

## Trial ledger

Each row stamps:

- `experiment_id`, `protocol_hash`, and `protocol_artifact_sha256`;
- `candidate_id`, `rule_key`, `rule_hash`, `cost_model_id`, and payout assumption;
- chronological fold, draw identity, and exact information cutoff;
- canonical input, decision, and output payloads plus their hashes;
- exact `previous_hash` and `event_hash`.

The verifier re-derives every decision and settlement from the frozen protocol and input history. A
changed payload, hash, sequence, link, candidate, rule, cutoff, or result must fail replay.

## Judge and tombstones

`MECHANICS_ACCEPTED` means only that the frozen finite protocol, typed projections, costs, decisions,
and ledger reproduce exactly. It coexists with mandatory `ECONOMIC_CLAIM_BLOCKED` because the packet
does not establish:

- payout basis;
- historical price availability;
- contemporaneous Quote/Fill;
- source truth.

Three deterministic tombstones record the blocked economic ranking, historical edge, and forward
market/liability claims. They are evidence boundaries, not claims that the underlying hypotheses are
false.

## Acceptance

- Protocol bytes exist and validate before trial generation.
- Four candidates, eight rules, 32 cells, and 38,528 rows are complete with no undeclared row.
- Four event-time folds are contiguous and no decision reads its target or future suffix.
- `always_no_bet` is zero for all eight rules.
- Full disk replay re-derives every row and hash-chain link.
- Two empty D-drive run directories produce byte-identical protocol, trials, summaries, Judge, and
  tombstone artifacts.
- P1/P2 ledgers and the read-only mainline snapshot remain unchanged.
- Independent tampering of a decision, hash, link, or forbidden Judge claim is rejected.

No output permits an edge, candidate ranking, recommendation, real-money action, operator truth,
historical/forward price, or whole-project completion claim.
