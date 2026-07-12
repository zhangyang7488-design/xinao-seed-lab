# P2 类型化规则目录 + 纯结算 + lineage 纵切

Resolution key: `p2-rule-catalog-pure-settle-v1`.

This phase preserves the P1 ledger contract and the verified lineage-v2 foundation, then adds eight
strictly typed exact-number projections and a hash-chained conformance ledger. It is not a general
betting-rule engine and does not upgrade packet material to operator truth.

## Source catalog and provenance

- Read the canonical packet only; all evidence stays under the D-drive lab state root.
- Preserve all 136 play-structure rows and all 4,043 parsed odds candidates as `CANDIDATE` rows with
  source row numbers and file hashes.
- Pin the full-v3 capture time `2026-05-12T11:12:34.754Z` separately from the later bundle creation
  time. Never substitute the bundle timestamp for quote capture time.
- Validate the full-v3 49-number modal snapshot on every implemented page: 特码 A at 47.285, 正码 A at
  7.850, and 正1特..正6特 A at 42.300. Alias pages must agree. The `49 -> 132` period-number parser
  artifact and label candidates are rejected explicitly; exact-number 49 remains resolvable.
- The packet does not define inclusive-return versus net-win payout meaning. Payout basis therefore
  remains `UNRESOLVED`; inclusive-return arithmetic is only the named mechanics assumption
  `mechanics-assumption-inclusive-return-v1`.

## Lineage-v2

Keep all 1,209 source rows in lineage evidence and never upgrade `verify=false`.

1. Define the outcome identity as the seven drawn numbers. Wave/zodiac labels are derived annotations,
   not identity fields. For identical open time and outcome, choose deterministically by expect-year consistency,
   then source verification, then source index.
2. `2023004` and `2024004` are the same 2024-01-04 draw. The validation-ranked canonical row is
   `2024004`; `2023004` is quarantined as its malformed alias.
3. For a full outcome repeated at a later time, retain the earliest canonical row and quarantine the
   later repetition.
4. The resulting lineage-v2 replay has 1,204 strictly time-increasing draws. P1 remains unchanged at
   1,203 under its legacy keep-first policy.

## Eight typed rules and compiler gate

- `special-a`: `pid=1/tid=14/pan=A`, win iff selection equals the seventh number.
- `regular-a`: `pid=2/tid=16/pan=A`, win iff selection is in the first six numbers.
- `regular-position-1-a` .. `regular-position-6-a`: `pid=3/tid=18..23/pan=A`, win iff selection equals
  the corresponding ordered regular position.
- Rule hashes include only revision, typed projection identity, selection domain, outcome predicate and
  push policy. Snapshot price and payout claims are outside the semantics hash.
- The source JSON bundle is strict Pydantic input with five source hash pins. Every one of the 136
  play-structure rows is classified as `IMPLEMENTED` or `UNRESOLVED`; resolution defaults to
  `UNRESOLVED` and never infers a rule from labels.
- The packet's payout basis and 特码两面 treatment of 49 are separate `UNRESOLVED` claims. An
  unresolved claim has no semantics hash and the compiler must reject it.
- The regular-set mechanics probability is exactly `6/49`. Under the explicit inclusive-return
  assumption and displayed 7.85, the mechanics RTP is `471/490` and net expectation is `-19/490`.

## Pure mechanics, hash chain and acceptance

P2 uses only `always_no_bet` and `fixed_01`; it does not open a search loop.

- Exhaust all selections 1..49 and assert each of the eight typed projections has the declared win set.
- Emit three golden conformance events (win, lose, no-bet) for every rule. Every event contains the
  `rule_hash`, `cost_model_id`, `input_hash`, `output_hash`, exact `previous_hash`, and its own event hash.
- Reject tampered payload, output hash, event hash, sequence or previous link.
- Assert no-bet stake, gross and net are zero.
- Mutate a real future suffix and require all earlier decision bytes to remain unchanged.
- Require input hashes before/after to match and two fresh evidence directories to produce identical
  catalog, lineage, trial and `conformance_events.jsonl` bytes.
- Keep P1's 4,812-line ledger SHA-256
  `9c2a59d6f9c26097ac933681dd84e5d9fa84e8ded19df32632873eae11fc0980` unchanged.
- Permit only a typed-mechanics/lineage-v2 verification claim. Operator rule truth, historical price
  availability, predictive ranking, recommendations, real-money use and whole-project completion are
  forbidden.
