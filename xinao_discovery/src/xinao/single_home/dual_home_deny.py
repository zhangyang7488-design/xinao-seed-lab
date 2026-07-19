"""Guards that deny dual ledger classes and forbidden parallel import homes."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from xinao.single_home.errors import DualHomeDenyError
from xinao.single_home.provisional_versions import (
    FORBIDDEN_PARALLEL_HOME_MODULES,
    LOGICAL_OBJECT_IDS,
    SINGLE_HOME_MODULES,
)

# Exact governed GlobalTrialLedger home module identity (contracts / SINGLE_HOME).
GOVERNED_LEDGER_HOME_MODULE = "xinao.single_home.global_trial_ledger"


def deny_forbidden_import_paths(module_names: Iterable[str]) -> None:
    """DENY if any historical dual-home module is treated as current home."""

    seen = list(module_names)
    forbidden_hits = sorted({m for m in seen if m in FORBIDDEN_PARALLEL_HOME_MODULES})
    if forbidden_hits:
        raise DualHomeDenyError(
            "FORBIDDEN_PARALLEL_HOME",
            "historical wave1 dual modules are not current home: " + ", ".join(forbidden_hits),
        )


def deny_dual_ledger_classes(classes: Sequence[type[Any]]) -> None:
    """DENY more than one GlobalTrialLedger home class identity.

    Accepts classes that declare LOGICAL_OBJECT_ID and HOME_MODULE.
    Distinct Python classes with the same logical id are still dual homes if
    more than one is registered as active home truth. Arbitrary HOME_MODULE
    values are DENY; only the exact governed single-home module is admitted.
    """

    if not classes:
        raise DualHomeDenyError("NO_LEDGER_HOME", "at least one GlobalTrialLedger home required")

    names = [getattr(c, "__name__", repr(c)) for c in classes]
    modules = [getattr(c, "HOME_MODULE", None) or getattr(c, "__module__", "") for c in classes]
    logical_ids = [getattr(c, "LOGICAL_OBJECT_ID", None) for c in classes]

    # Any class without the pinned logical id is not a valid home.
    expected = LOGICAL_OBJECT_IDS["GlobalTrialLedger"]
    for cls, lid in zip(classes, logical_ids, strict=True):
        if lid != expected:
            raise DualHomeDenyError(
                "DUAL_LEDGER_CLASS_FORBIDDEN",
                f"{getattr(cls, '__name__', cls)} has LOGICAL_OBJECT_ID={lid!r} "
                f"expected {expected!r}",
            )

    # More than one distinct class object => dual home DENY.
    unique_classes = {id(c) for c in classes}
    if len(unique_classes) > 1:
        raise DualHomeDenyError(
            "DUAL_LEDGER_CLASS_FORBIDDEN",
            "exactly one GlobalTrialLedger class home allowed; got "
            + ", ".join(f"{n}@{m}" for n, m in zip(names, modules, strict=True)),
        )

    # Module must be the exact governed single-home ledger module.
    for mod in modules:
        if mod == GOVERNED_LEDGER_HOME_MODULE:
            continue
        if mod in FORBIDDEN_PARALLEL_HOME_MODULES:
            raise DualHomeDenyError(
                "FORBIDDEN_PARALLEL_HOME",
                f"class home module {mod!r} is a superseded dual home",
            )
        if mod in SINGLE_HOME_MODULES and mod != GOVERNED_LEDGER_HOME_MODULE:
            raise DualHomeDenyError(
                "BAD_HOME_MODULE",
                f"HOME_MODULE {mod!r} is not the governed ledger home "
                f"{GOVERNED_LEDGER_HOME_MODULE!r}",
            )
        raise DualHomeDenyError(
            "BAD_HOME_MODULE",
            f"HOME_MODULE must be exact {GOVERNED_LEDGER_HOME_MODULE!r}, got {mod!r}",
        )


def deny_dual_power_plan_homes(module_names: Iterable[str]) -> None:
    """DENY simultaneous use of both wave1 PowerPlan homes."""

    mods = set(module_names)
    g3 = "drafts.xinao.g3.power_plan_version"
    g5 = "drafts.xinao.gates.g5_power_plan"
    if g3 in mods and g5 in mods:
        raise DualHomeDenyError(
            "DUAL_LEDGER_CLASS_FORBIDDEN",
            "PowerPlan dual homes forbidden; use xinao.single_home.power_plan",
        )
    deny_forbidden_import_paths(mods)


def assert_single_home_import_set(module_names: Iterable[str]) -> None:
    """Consumers may only import single_home modules for ledger/power/ess."""

    mods = list(module_names)
    deny_forbidden_import_paths(mods)
    deny_dual_power_plan_homes(mods)
    # Dual wave1 ledger import DENY even if not marked home.
    g3l = "drafts.xinao.g3.global_trial_ledger"
    g5l = "drafts.xinao.gates.g5_global_trial_ledger"
    if g3l in mods and g5l in mods:
        raise DualHomeDenyError(
            "DUAL_LEDGER_CLASS_FORBIDDEN",
            "cannot import both wave1 G3 and G5 GlobalTrialLedger modules",
        )
