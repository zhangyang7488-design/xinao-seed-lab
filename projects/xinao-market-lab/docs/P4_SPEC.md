# P4 exact-null + contamination structure contract

Resolution: `p4-exact-null-contamination-structure-v1`.

P4 adds one bounded evidence vertical after the P3 ResearchProtocol/JudgeGate. It does not search
P3 candidates, rank rules, infer a tradable edge, or attribute a generator mechanism.

## Pre-statistical contamination gate

The raw 1,209-row source must reproduce exactly five lineage-v2 quarantines and leave zero residual
aliases:

1. `2023004 -> 2024004`, `expect_year_mismatch_exact_time_alias`;
2. `2024185 -> 2024156`, `later_full_outcome_repetition`;
3. `2025259 -> 2024340`, `later_full_outcome_repetition`;
4. `2025287 -> 2024335`, `later_full_outcome_repetition`;
5. `2026019 -> 2024300`, `later_full_outcome_repetition`.

This gate is deterministic provenance validation, not a p-value and not a Holm hypothesis. Raw-source
collision counts are descriptive only. The three pinned identity spaces are ordered regular-6 plus
special (`M=432938943360`), regular-set plus special (`M=601304088`), and unordered seven
(`M=85900584`). Each currently has five observed source pairs. Because lineage-v2 removes later full
outcome repetitions, collision testing on the canonical 1,204-row stream would be circular and is
forbidden.

## Frozen statistical family

The canonical stream contains 1,204 chronological draws. The family is exactly five hypotheses:

- `T_special`: `49*sum(special_count^2)-n^2`;
- `T_pos_max`: the maximum of the same integer Pearson score over six ordered regular positions;
- `T_regular_incl`: `49*sum(regular_inclusion_count^2)-(6*n)^2`;
- `T_lag1`: `abs(49*equal_adjacent_special-(n-1))`, an explicitly two-sided deviation score;
- `T_fold`: the maximum special score over the same four 301-event folds frozen in P3.

The accepted observed integer scores are `38514`, `69580`, `322812`, `125`, and `12348` in that
order. The position sub-scores are `[50764,47726,69188,48804,59388,69580]`; the fold sub-scores are
`[12348,12250,10682,12348]`; equal adjacent specials are 22. Position and fold sub-scores are
components of their max statistics, not extra hypotheses.

## Joint null and inference

All five statistics use the same Monte Carlo replicates. Every replicate contains 1,204 independent
ordered 6+1 draws, with seven unique integers sampled from 1..49. The exact runtime contract is:

- `numpy==2.5.1`;
- `Generator(PCG64(2026071104))`;
- rejection/resampling of any within-draw duplicate row using `int16` on little-endian Windows;
- batch size 128, C-order batch/draw/position traversal;
- `n_mc=19999`;
- a hash-linked canonical JSONL ledger with every replicate and all five integer scores.

For each test, `b=count(T_sim >= T_obs)` and raw p is the exact fraction `(b+1)/20000`. Holm
step-down uses exact `Fraction` arithmetic, the frozen family order as the tie-break, and
`alpha_FWER=1/20`. The gate, raw collision diagnostics, position components, and fold components do
not enter Holm.

## Judge boundary

After a matching contamination gate, the structural result is either `STRUCTURE_NULL_RETAINED` or
`STRUCTURE_NULL_REJECTED_FWER`. Rejection only licenses a separately frozen later localization phase.
Every path also emits `ECONOMIC_CLAIM_BLOCKED`; candidate ranking, recommendation, source-truth
upgrade, generator attribution, forward price, Quote/Fill, and real-money use remain prohibited.

`p4-verify` rebuilds raw/canonical lineage, recomputes observed statistics, fully resimulates all
19,999 PCG64 replicates, replays plus-one p-values and Holm, and derives Judge/tombstone bytes. Formal
acceptance additionally uses an out-of-run trusted anchor so a disposable attacker cannot replace the
protocol, family, seed, stream, and manifest together.
