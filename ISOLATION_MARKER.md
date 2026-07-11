# Grok 4.5 Island Isolation Marker
generated: 20260710-232619
status: DEFAULT_SELF_ISOLATED_FROM_ADMIN

## Principle
- Current island is the default base for Grok 4.5.
- Isolated from Grok Admin Isolated workspace.
- Admin must not be harmed; this process does not write Admin workspace.

## Paths
- island: C:\Users\xx363\Grok_Admin_Isolated\workspace-grok-4.5-island
- admin (do not overwrite from 4.5 isolate job): C:\Users\xx363\Grok_Admin_Isolated\workspace
- freeze mirror: C:\Users\xx363\Grok_Admin_Isolated\backups\grok-4.5-island-default-freeze-20260710-232619
- lane: C:\Users\xx363\.grok-4.5-lane
- checkpoint: D:\XINAO_RESEARCH_RUNTIME\state\grok_4_5\session_context
- legacy alias workspace-grok-4.5 -> island (NOT admin)

## Asymmetry
- 4.5 may act on Admin when needed.
- Admin default cannot write 4.5 paths.
- Admin full worker only on user explicit request.

## Contracts
- grok_4_5_self_isolation.v1.json
- grok_admin_isolated_window_boundary.v1.json
- grok_dual_window_full_isolation_target.v1.json