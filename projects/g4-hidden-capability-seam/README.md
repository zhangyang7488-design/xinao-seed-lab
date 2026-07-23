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

## Provider-neutral bounded batch execution

`xinao.capability.g4_batch` defines the scientific identity of one pre-registered G4
batch: the exact cells, suite/evaluator/policy identities, PowerPlan, stopping and retry
rules, holdout/no-peek contract, and ledger snapshot. Provider, model, transport, relay,
quota, and whole-campaign capacity fields are forbidden from that identity.

`scripts/run_g4_batch_execution_admission.py` is the fail-closed consumer for one selected
batch attempt. It accepts the provider-neutral batch together with the existing common
`LogicalExecutionContract` and `ExecutionAttemptReceipt`, verifies their hashes and
observed route identity, and projects the seven scoped phase conditions. The selected
provider/transport is evidence for that attempt only; the same scientific batch may be
retried through another admitted worker-bus route without changing its content hash.

Quota and capacity are batch scheduling inputs. They may hold the current batch route but
cannot lock the campaign to one API account, require a full-campaign capacity precommit,
freeze G4 engineering or G5 pre-outcome design/preregistration, or authorize parent-global
waiting. `G4_FULL` remains false until the complete pre-registered result set is present;
G5 final adjudication and G6 formal research remain closed until their own prerequisites
are complete.

The former `scripts/run_g4_full_capacity_preflight.py` entry is a no-effect tombstone. It
does not query quota or invoke a relay and points callers to the batch admission consumer.
