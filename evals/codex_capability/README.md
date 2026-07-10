# Codex capability eval

This bounded eval exercises Codex through the app-server protocol in a read-only,
ephemeral thread. It verifies a local file read, structured output, app-server
metadata, and the token ledger. It inherits the canonical Codex capability
configuration without disabling Apps, plugins, or MCP servers; the evaluation
itself remains bounded by a read-only sandbox, no approvals, and an ephemeral
thread.

The assertions require the exact structured result, app-server thread and turn
identifiers, a `read-only` sandbox with `never` approval policy, at least one
local command-execution item, and positive prompt/completion/total token
metadata.

The pinned Promptfoo runtime is installed at:

`D:\XINAO_RESEARCH_RUNTIME\tools\promptfoo\node_modules\.bin\promptfoo.cmd`

Run from the repository root:

```powershell
.\scripts\run_codex_capability_eval.ps1
```

Results are written below
`D:\XINAO_RESEARCH_RUNTIME\state\human-capabilities\evals\codex-app-server`.
Promptfoo's state and logs for this evaluator are also kept below that D-drive
directory.
The configuration contains no API key. It uses the current `CODEX_HOME` login,
defaulting explicitly to `C:\Users\xx363\.codex`, declines approvals, and never
attaches to the interactive Codex Desktop process.
