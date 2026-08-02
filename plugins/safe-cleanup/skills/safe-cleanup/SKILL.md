---
name: safe-cleanup
description: Use for authorized Windows file or directory cleanup when Codex should execute deletion itself, especially after Remove-Item access-denied failures, stale worktree cleanup, exact cache/runtime retirement, or cleanup spanning multiple paths. It plans immutable exact targets, blocks protected roots and active Git/process consumers, handles bounded ACL repair, and returns typed receipts. Do not use it to decide whether an object has value, to edit tracked files, or for unclassified broad cleanup.
---

# Safe Cleanup

Use the MCP tools as the normal execution surface. Do not write or hand the user an equivalent
PowerShell deletion block while the tool is available.

1. Bind the current cleanup authorization, exact object, consumer status, unique value, and
   recovery basis. The tool executes a classification; it does not decide value or grant authority.
2. Call `safe_cleanup_plan` with absolute literal paths. Never pass an arbitrary command, wildcard,
   unresolved variable, drive root, workspace root, or inferred sibling path.
3. Use `quarantine` for an unclassified but currently removable object. Use `permanent` only when
   current authority covers deletion and the object is disposable, committed/recoverable, or
   rebuildable. State the concrete recovery basis.
4. Read every blocker. Do not bypass protected roots, registered Git worktrees, active consumers,
   root reparse points, or a stale plan. Resolve only the exact legitimate dependency and re-plan.
5. Call `safe_cleanup_execute` with the exact returned `plan_id` and `plan_sha256`. If ACL repair is
   needed, the tool applies it only to the planned target during execution. It never traverses a
   reparse point and exposes no arbitrary command channel.
6. Verify the source is absent, the receipt status is `completed`, disk free bytes are reconciled,
   and unrelated protected objects remain present. A plan, partial receipt, or moved quarantine is
   not permanent-deletion completion.

If execution returns `LOCKED`, identify the exact owning process and stop it only when current scope
and session ownership permit; then create a fresh plan. If it returns `ELEVATION_REQUIRED`, keep the
failure typed and repair the product entry rather than sending the user a shell recipe.
