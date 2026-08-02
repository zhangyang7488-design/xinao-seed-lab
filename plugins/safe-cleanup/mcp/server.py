from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from safe_cleanup_core import DEFAULT_TTL_SECONDS, SafeCleanupService

mcp = FastMCP(
    "safe-cleanup",
    instructions=(
        "Plan exact Windows cleanup before executing it. Value classification and authorization "
        "remain with the user and Codex. Never invent paths, use globs, or treat a plan as "
        "permission. Execute only the exact plan_id and plan_sha256 returned by safe_cleanup_plan."
    ),
)
service = SafeCleanupService()

_PLAN_TOOL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
_EXECUTE_TOOL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)


@mcp.tool(annotations=_PLAN_TOOL)
def safe_cleanup_plan(
    paths: list[str],
    disposition: Literal["quarantine", "permanent"],
    classification: Literal[
        "authorized_disposable",
        "committed_recoverable",
        "redundant_rebuildable",
        "quarantine_unclassified",
    ],
    justification: str,
    recovery_basis: str = "",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict:
    """Plan cleanup for exact authorized absolute paths without changing files.

    Use this before any cleanup execution. It rejects wildcards, broad/protected roots,
    registered Git worktrees, root reparse points, active process consumers, overlapping targets,
    and permanent deletion of unclassified objects. A permanent plan requires a concrete recovery
    basis. The returned plan_id and plan_sha256 bind the exact target snapshots.
    """
    return service.plan_cleanup(
        paths=paths,
        disposition=disposition,
        classification=classification,
        justification=justification,
        recovery_basis=recovery_basis,
        ttl_seconds=ttl_seconds,
    )


@mcp.tool(annotations=_EXECUTE_TOOL)
def safe_cleanup_execute(plan_id: str, plan_sha256: str) -> dict:
    """Execute one exact non-expired cleanup plan and return a typed receipt.

    Use only after safe_cleanup_plan is ready and current user authority covers the stated
    disposition. The server rechecks protections, consumers, root identity, tree metrics, and plan
    digest before any mutation. It never follows reparse points. Access-denied trees receive a
    bounded take-ownership/ACL repair on the exact planned root before one retry. Locked, stale,
    protected, and elevation failures are returned as typed results rather than shell commands.
    """
    return service.execute_cleanup(plan_id=plan_id, plan_sha256=plan_sha256)


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
