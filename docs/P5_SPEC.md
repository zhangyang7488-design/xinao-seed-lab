# P5 unresolved-semantics evidence-catalog contract

Resolution: `p5-unresolved-semantics-evidence-catalog-v1`.

P5 follows the independently accepted P4 result `STRUCTURE_NULL_RETAINED` while preserving
`ECONOMIC_CLAIM_BLOCKED`. It catalogs the local packet's ability to answer the two unresolved P2
RuleClaims. It does not reinterpret P4 as fairness, resolve payout semantics from generic prose,
compile a new rule, rank a candidate, or create a live Quote/Fill path.

## Frozen surfaces

- RuleClaims are exactly `payout_basis` and `special_two_sided_49_policy`.
- The separate P2 classification surface remains exactly 136 rows: 16 implemented references and
  120 unresolved rows. A classification row is never promoted into a third RuleClaim.
- The input snapshot contains exactly 33 files. Twenty-seven declared evidence sources are scanned;
  two binary archives, three draw-history files, and one executable helper remain hash-pinned with an
  explicit exclusion reason.
- The earlier peer message saying "scan files=30" described a pre-formal exploratory marker pass. It
  is not the frozen inventory equation. The formal contract is the explicit 33 = 27 scanned + 6
  excluded surface above; exclusions are evidence, not silent omissions.
- Scanned roles are limited to `captured_page_snapshot`, `package_manifest`,
  `human_context_hypothesis`, and `derived_catalog`. No role means operator truth.
- The 22-term vocabulary and order are protocol material. The first 12 terms preserve the accepted
  payout-language audit; ten additional phrases explicitly test special-number-49 policy language.

## Selectors and normalization

Bytes must decode strictly as UTF-8 with optional BOM. CRLF and CR are converted to LF, then string
values are normalized to NFC. Offsets count Unicode code points and use zero-based half-open ranges.

- JSON string values use strict RFC 6901 JSON Pointers. Duplicate keys, invalid escapes, missing
  members, `-`, leading-zero array indices, and out-of-range indices fail closed.
- JSONL adds a zero-based record index and one-based physical line number; blank records fail closed.
- CSV uses a strict logical-record parser, a pinned header hash, a column name, and a JSON Pointer over
  the canonical row object. Quoted multiline cells are not split manually.
- Every selected value also carries W3C-style TextQuote and TextPosition selectors. `exact`, the
  adjacent 32-code-point prefix/suffix, and start/end must all replay from the current source bytes.

The schema borrows the W3C PROV concepts Entity, Activity, and derivation only as provenance seams;
it does not add RDF, JSON-LD, or a second workflow platform.

## Non-circular verification

`p5-verify` rebuilds the exact 33-file inventory and hashes from the real packet, applies the role and
exclusion mapping from code rather than trusting run artifacts, rebuilds the vocabulary, rescans all
27 sources, reconstructs the complete expected hit set, replays every selector, and re-derives the
two RuleClaims plus the 136/16/120 classification surface. Claims and classifications are parsed
directly from the hash-pinned P2 `rule_catalog.json`; current P2 builders cannot replace that accepted
artifact. It then compares every semantic artifact byte-for-byte before checking the manifest and
optional out-of-run anchor.

The producer writes an unsigned in-toto Statement-shaped source manifest before scanning. Its source
selection is an explicit allowlist, not a package-wide glob, and verification rebuilds it from the
current P5 source bytes. The manifest reports historical artifact integrity separately from current
source replay. It is deliberately marked unauthenticated with SLSA Build and Source levels
`not-claimed`; no signature, hosted builder, source-control history, or third-party certification is
implied.

The frozen snapshot contains no direct payout-basis or special-49 policy marker. The generic counts
are `赔付=1`, `输赢=1`, and `结算=18`; all other frozen query terms are zero. Therefore both RuleClaims
must end as `INSUFFICIENT_LOCAL_EVIDENCE`. The Judge may emit only
`EVIDENCE_CATALOG_VERIFIED`, `SEMANTICS_STILL_UNRESOLVED` (or a genuinely re-derived conflict), and
`ECONOMIC_CLAIM_BLOCKED`.

## Forbidden upgrades

P5 never sets a semantics hash, compiler execution right, source/operator truth, historical price
availability, edge, ranking, recommendation, real-money permission, or whole-project completion.
Network capture, Playwright, Splink, ruptures, schedulers, and new dependencies are outside this
phase.
