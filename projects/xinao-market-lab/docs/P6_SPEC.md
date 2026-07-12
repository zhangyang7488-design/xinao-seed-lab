# P6 public-source role and RuleClaim acquisition contract

Resolution: p6-public-source-role-and-ruleclaim-acquisition-contract-v1.

P6 is two physically separate stages:

1. one bounded network acquisition of four exact public official HTML URLs into one immutable,
   uncompressed WARC/1.1 bundle on D:;
2. network-disabled formalization and replay from that same pinned bundle.

It does not recapture for A/B reproducibility. Formal A/B runs consume identical WARC bytes and must
produce byte-identical artifacts.

## Exact acquisition boundary

Only HTTPS GET is allowed, with no proxy, cookie, authorization, request body, form, login, browser,
script execution, embedded asset crawl, commercial URL, or farm/mirror fetch:

- https://www.gov.mo/zh-hans/news/787749/
- https://www.dicj.gov.mo/web/en/legislation/index.html
- https://www.dicj.gov.mo/web/cn/legislation/LotCh/index.html
- https://special.hkjc.com/e-win/en-US/betting-info/marksix/lotteries-rules/

The capture contract is written with exclusive creation and strictly read back before the first
request. The implementation disables automatic redirects; any redirect is a contract failure rather
than an implicit allowlist expansion. DNS answers and the connected peer must be public/global.
TLS uses the platform default trust store and hostname validation. Body, header, timeout, and total
byte limits are fixed in the contract.

The WARC is a normalized HTTP response/entity-body capture, not a wire-exact packet trace. urllib
dechunks the entity; Transfer-Encoding, cookies, and framing headers are stripped before WARC
serialization, and stored Content-Length is recomputed. WARC internal digests are verified and
external SHA-256 pins bind the contract, event chain, WARC, each body, manifest, and external capture
anchor. warcio==1.8.1 is the only added carrier dependency.

## Source roles and claims

- The PJ government notice is the only direct source for the narrow captured claim that the named
  “澳门六合彩” government-approval claim is rejected.
- DICJ pages are regulator context and retain their reference-only disclaimer.
- HKJC is a licensed foreign non-operator comparator showing the shape of a genuine rules
  instrument. It has zero target-RuleClaim weight.
- w1.kka8f.com is never fetched. It remains an unverified commercial origin whose branding
  conflicts with a general regulator notice; its exact-domain legal status is NOT_DETERMINED and
  its semantic vote weight is zero.

The two target RuleClaims remain:

- payout_basis = INSUFFICIENT_TARGET_OPERATOR_EVIDENCE
- special_two_sided_49_policy = INSUFFICIENT_TARGET_OPERATOR_EVIDENCE

Both keep semantics_hash=null and compiler_execution_permitted=false.

## Formal Judge boundary

The only positive P6 statuses are:

- PUBLIC_PRIMARY_SOURCE_BUNDLE_VERIFIED
- MACAU_OFFICIAL_PRODUCT_CLAIM_REJECTED

The blocking statuses remain:

- SEMANTICS_STILL_UNRESOLVED
- ECONOMIC_CLAIM_BLOCKED

Operator rule truth, target-source truth, semantics compilation, historical price availability,
ranking, recommendation, real-money use, Q/F/T capture, minhash/template voting, candidate
selection, and whole-project completion all remain false or absent.

Formal verification reparses WARC/1.1 with digest checks, rehashes the file before and after reading,
strictly decodes declared HTML charsets, extracts static markup text without script/style/hidden
subtrees, applies NFC plus whitespace normalization, and replays W3C TextQuote/TextPosition
selectors. The trusted formal anchor is outside both A/B run directories and refuses overwrite.
