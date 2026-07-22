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
