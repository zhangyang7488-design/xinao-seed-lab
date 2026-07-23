# G4 hidden-capability seam — synthetic HOLD

This directory retains the reusable part of the independently accepted
`SEAM_VERIFIED_HOLD` candidate. It is a synthetic isolation seam, not an activated G4
capability and not evidence of real hidden-case performance.

The retained surface is deliberately narrow:

- generic seam source under `src/g4_hidden_capability_seam`;
- the deterministic offline Promptfoo adapter;
- schema and contract shapes;
- focused unit and security-regression tests.

Generated Vault contents, operation state, SQLite databases, ledgers, receipts, evidence,
artifact manifests, packaging scripts, provider authority, real scoring, G4/G5 activation,
and parent-completion claims are not integrated.

The tests exercise Windows ACL behavior and therefore run in the repository's Windows
project job:

```powershell
uv sync --frozen
uv run ruff check src adapters tests
uv run ruff format --check src adapters tests
uv run pytest -q
```

All public objects remain marked synthetic and non-authoritative. Any future activation,
real provider call, or broader threat model requires a separate work key and completion
contract.

## Bounded-family route preflight

`scripts/run_g4_full_capacity_preflight.py` is the fail-closed consumer for the next
bounded family execution boundary. It selects three size-stratified cases from a newly generated
training-only suite, sends only their public views, and accepts route measurements only
when the relay records the exact prompt hash, a hash-pinned provider contract, the
filesystem-unavailable boundary, actual model identity, positive usage, and artifact hash
readbacks.

The preflight never generates a heldout suite, scores an outcome, freezes authority, or
closes G4. Percentage-only and absolute quota telemetry are planning advisories: neither is
a hard gate for pre-registered, bounded family batches. Every executable family still needs
its own PowerPlan, budget, stopping conditions, immutable receipts, and no-peek boundary;
`G4_FULL` remains false until the complete H01-H14/configuration/repeat result set is present.
An immutable calibration attempt can be re-adjudicated without another provider call when
adjudication logic changes. A relay-envelope or route-identity change requires a fresh
public calibration.

Live dispatch requires `--launcher` to name an installed provider-bound thin adapter.
The provider-neutral stable relay entry intentionally has no implicit provider, endpoint,
or credential binding and is not a dispatch default.
