"""Same-host replay runtime for a relocated, sealed foundation v4 tree.

This module is intentionally introduced behind RED tests.  The first green
implementation must resolve the authority interpreter and every nested F1
phase from the relocated ``authority_snapshot`` without importing the editable
live ``xinao`` tree or consulting legacy closure outputs.
"""

from __future__ import annotations

import argparse
import atexit
import base64
import faulthandler
import hashlib
import importlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

FOUNDATION_BLOCK_IDS = (
    "F1_settlement_world",
    "F2_issuer_settlement_cost_space",
    "F3_research_weight",
    "F4_research_factory",
)
F1_ISOLATED_PHASES = ("outer", "seed", "final", "reordered")
LEGACY_OUTPUT_NAMES = frozenset(
    {
        "assertion_bundles",
        "fresh_assertion_bundles",
        "fresh_assertion_bundle_receipts",
        "assertions",
        "artifacts",
        "foundation_closure_report.json",
        "foundation_closure_report_input.json",
        "foundation_closure_verification.json",
        "foundation_closure_pack.json",
    }
)
F1_ENTRYPOINT_RELATIVE = (
    "xinao_discovery/src/xinao/foundation/assertion_verifiers/f1_assertion_actuals.py"
)
NESTED_ENVELOPE_SCHEMA = "xinao.foundation_v4_nested_child_envelope.v1"
NESTED_FAILURE_ATTEMPT_SCHEMA = "xinao.foundation_v4_nested_failure_attempt.v1"
NESTED_FAILURE_CAPTURE_SCHEMA = "xinao.foundation_v4_nested_failure_capture.v1"
NESTED_FAILURE_INDEX_SCHEMA = "xinao.foundation_v4_nested_failure_index.v1"
RUN_RECEIPT_SCHEMA = "xinao.foundation_v4_replay_run_receipt.v1"
REPLAY_BUNDLE_SCHEMA = "xinao.foundation_v4_replay_bundle.v1"
OUTER_START_RECORD_SCHEMA = "xinao.foundation_v4_outer_start_record.v1"
OUTER_FAILURE_CAPTURE_SCHEMA = "xinao.foundation_v4_outer_failure_capture.v1"
FORBIDDEN_GUARD_SCHEMA = "xinao.foundation_v4_forbidden_mutation_guard.v1"
FORBIDDEN_GUARD_PROBE_EVENT = "xinao.replay.forbidden_guard_probe"
FORBIDDEN_GUARD_AGGREGATE_SCHEMA = "xinao.foundation_v4_forbidden_mutation_evidence.v1"
_ZERO_SHA256 = "0" * 64
_GUARD_PROOF_FIELDS = (
    "guard_schema_version",
    "root_set_sha256",
    "probe_observed",
    "covered_mutation_event_count",
    "allowed_mutation_event_count",
    "denied_mutation_event_count",
    "event_log_path",
    "event_log_sha256",
    "event_chain_head_sha256",
    "interpreter_pid",
)
_REPLAY_SPEC_MODULE = __name__ if __name__ in sys.modules else "builtins"
_OUTER_START_RECORD_TO_CLEAN: Path | None = None
_OUTER_STDOUT_COMMITTED = False


@dataclass(frozen=True, slots=True)
class _ReplayBlockSpec:
    __module__ = _REPLAY_SPEC_MODULE

    block_id: str
    capsule_schema_version: str
    authority_entrypoint_relative_path: str
    assertion_ids: tuple[str, ...]
    input_names: tuple[str, ...]
    artifact_names: tuple[str, ...]
    execution_excluded_payload_paths: tuple[str, ...]
    actuals_mode: str
    phase_order: tuple[str, ...]
    include_phase_lineage: bool
    extension_hook: str | None


_COMMON_INPUT_NAMES = (
    "active_quote_projection_sha256",
    "baseline_sha256",
    "compiler_code_sha256",
    "compiler_config_sha256",
    "dataset_sha256",
    "f3_external_synthesis_sha256",
    "f3_prior_draft_sha256",
    "f3_service_graph_sha256",
    "play_catalog_sha256",
    "rule_semantic_map_sha256",
)
_REPLAY_BLOCK_SPECS = {
    "F1_settlement_world": _ReplayBlockSpec(
        block_id="F1_settlement_world",
        capsule_schema_version="xinao.foundation_v4_f1_relocation_capsule.v1",
        authority_entrypoint_relative_path=F1_ENTRYPOINT_RELATIVE,
        assertion_ids=(
            "active_atomic_selection_count_eq",
            "active_settlement_compiled_eq",
            "active_settlement_not_compiled_eq",
            "actual_event_key_set_equals_expected",
            "atomic_ticket_binding_count_eq",
            "atomic_ticket_count_eq",
            "atomic_ticket_domain_lazy_not_materialized",
            "catalog_identity_mapped_eq",
            "catalog_total_eq",
            "distinct_active_world_cells_eq",
            "draw_total_eq",
            "duplicate_event_keys_eq",
            "every_semantic_family_has_positive_negative_boundary_property_tests_and_replay",
            "expected_selection_set_derived_independently_from_catalog_and_baseline",
            "family_total_eq",
            "fresh_process_world_hash_equals_recorded",
            "missing_event_keys_eq",
            "reordered_input_world_hash_equals_recorded",
            "required_rule_fields_complete",
            "rule_semantic_map_selection_set_equals_independent_expected_selection_set",
            "semantic_rule_mapped_eq",
            "unclassified_eq",
            "unexpected_event_keys_eq",
        ),
        input_names=_COMMON_INPUT_NAMES,
        artifact_names=(
            "AtomicTicketBindingVersion",
            "EventMatrixSnapshot",
            "ExpectedSelectionDomainManifestVersion",
            "RuleSemanticMapVersion",
            "RuleSetVersion",
            "SettlementFunctionSetVersion",
            "WorldSnapshot",
        ),
        execution_excluded_payload_paths=("blueprint/blueprint.v1_已合并工具与执行纪律.json",),
        actuals_mode="F1_NESTED",
        phase_order=F1_ISOLATED_PHASES,
        include_phase_lineage=True,
        extension_hook=None,
    ),
    "F2_issuer_settlement_cost_space": _ReplayBlockSpec(
        block_id="F2_issuer_settlement_cost_space",
        capsule_schema_version="xinao.foundation_v4_relocation_source_capsule.v1",
        authority_entrypoint_relative_path=(
            "xinao_discovery/src/xinao/foundation/assertion_verifiers/f2_assertion_actuals.py"
        ),
        assertion_ids=(
            "actual_exposure_or_realized_profit_claimed",
            "all_active_settlement_objects_covered",
            "all_compiler_bindings_nonempty_and_hash_bound",
            "all_intra_quote_payout_tiers_preserved",
            "combinatorial_probability_counts_match_independent_fixtures",
            "coverage_key_set_equals_expected_outcome_x_active_settlement_object_x_payout_tier",
            "event_unit_cost_surface_functionally_complete",
            "expected_unit_cost_recomputed_from_payout_and_rebate",
            "formula_replay_hash_stable",
            "historical_replay_not_probability_definition",
            "hit_miss_void_partition_complete_and_mutually_exclusive",
            "normal_principal_refund_eq",
            "rebate_rate_lte_implied_max",
            "rebate_schedule_covers_all_active_settlement_objects",
            "terminal_outcome_probabilities_sum_to_one",
            "tier_probabilities_gte_zero",
            "tier_probabilities_lte_one",
            "turnover_rebate_materialized",
        ),
        input_names=_COMMON_INPUT_NAMES,
        artifact_names=(
            "OddsSpaceBenchmarkVersion",
            "RebateScheduleVersion",
            "SettlementCostCompileReport",
            "SettlementCostSurfaceVersion",
            "SettlementProbabilitySnapshotVersion",
        ),
        execution_excluded_payload_paths=("blueprint/blueprint.json",),
        actuals_mode="DIRECT",
        phase_order=("outer",),
        include_phase_lineage=False,
        extension_hook=None,
    ),
    "F3_research_weight": _ReplayBlockSpec(
        block_id="F3_research_weight",
        capsule_schema_version="xinao.foundation_v4_relocation_source_capsule.v1",
        authority_entrypoint_relative_path=(
            "xinao_discovery/src/xinao/foundation/assertion_verifiers/f3_assertion_actuals.py"
        ),
        assertion_ids=(
            "all_six_artifacts_recomputable",
            "all_six_artifacts_versioned_and_hash_bound",
            "attention_identity_eq",
            "exploration_share_gt",
            "measured_attention_claimed",
            "research_weight_semantic_role_eq",
            "weight_changes_do_not_change_event_probability_or_settlement",
            "weight_changes_do_not_claim_stake_or_house_exposure",
        ),
        input_names=_COMMON_INPUT_NAMES,
        artifact_names=(
            "ActiveResearchSurfaceVersion",
            "ContentServiceGraphVersion",
            "ResearchAttentionPriorVersion",
            "ResearchPortfolioPolicyVersion",
            "ResearchWeightBaselineVersion",
            "SourceDependencyGraphVersion",
        ),
        execution_excluded_payload_paths=("blueprint/blueprint.json",),
        actuals_mode="DIRECT",
        phase_order=("outer",),
        include_phase_lineage=False,
        extension_hook=None,
    ),
    "F4_research_factory": _ReplayBlockSpec(
        block_id="F4_research_factory",
        capsule_schema_version="xinao.foundation_v4_relocation_source_capsule.v1",
        authority_entrypoint_relative_path=(
            "xinao_discovery/src/xinao/foundation/assertion_verifiers/f4_assertion_actuals.py"
        ),
        assertion_ids=(
            "backpressure_partial_failure_cancel_and_recovery_verified",
            "canonical_work_key_and_source_dependency_dedup_verified",
            "codex_single_writer_boundary_verified",
            "d_drive_evidence_binding_verified",
            "deterministic_fan_in_without_majority_vote_verified",
            "dynamic_multi_lane_capacity_ladder_verified",
            "fixed_time_split_and_leakage_rejection_verified",
            "independent_critique_verified",
            "negative_controls_and_error_budget_verified",
            "open_method_typed_admission_verified",
            "real_model_identity_and_lane_artifacts_verified",
            "real_temporal_workflow_history_verified",
            "research_portfolio_ready_frontier_verified",
            "typed_handoff_and_evidence_schemas_verified",
        ),
        input_names=_COMMON_INPUT_NAMES,
        artifact_names=(
            "DedupPolicyVersion",
            "DeterministicFanInPolicyVersion",
            "DynamicCapacityPolicyVersion",
            "EvidenceSchemaVersion",
            "ResearchFactoryCanaryReport",
            "ResearchWorkItemSchemaVersion",
            "TypedHandoffSchemaVersion",
            "ValidationCourtInterfaceVersion",
        ),
        execution_excluded_payload_paths=("blueprint/blueprint.json",),
        actuals_mode="DIRECT",
        phase_order=("outer",),
        include_phase_lineage=False,
        extension_hook="snapshot_and_verifier_court",
    ),
}


def _validate_replay_block_spec(spec: _ReplayBlockSpec) -> None:
    if spec.block_id not in FOUNDATION_BLOCK_IDS:
        raise FoundationV4ReplayError(f"unknown replay block: {spec.block_id}")
    tuple_fields = (
        spec.assertion_ids,
        spec.input_names,
        spec.artifact_names,
        spec.execution_excluded_payload_paths,
        spec.phase_order,
    )
    if any(
        not values
        or any(not isinstance(value, str) or not value for value in values)
        or len(values) != len(set(values))
        for values in tuple_fields
    ):
        raise FoundationV4ReplayError(f"replay block spec is invalid: {spec.block_id}")
    if (
        tuple(sorted(spec.assertion_ids)) != spec.assertion_ids
        or tuple(sorted(spec.input_names)) != spec.input_names
        or tuple(sorted(spec.artifact_names)) != spec.artifact_names
    ):
        raise FoundationV4ReplayError(
            f"replay block spec canonical inventories drifted: {spec.block_id}"
        )
    _safe_relative_path(
        spec.authority_entrypoint_relative_path,
        label="authority entrypoint relative_path",
    )
    for value in spec.execution_excluded_payload_paths:
        _safe_relative_path(value, label="execution excluded relative_path")
    if spec.actuals_mode == "DIRECT":
        valid_shape = spec.phase_order == ("outer",) and not spec.include_phase_lineage
    elif spec.actuals_mode == "F1_NESTED":
        valid_shape = spec.phase_order == F1_ISOLATED_PHASES and spec.include_phase_lineage
    else:
        valid_shape = False
    if not valid_shape:
        raise FoundationV4ReplayError(f"replay block execution shape is invalid: {spec.block_id}")
    expected_extension_hook = (
        "snapshot_and_verifier_court" if spec.block_id == "F4_research_factory" else None
    )
    if spec.extension_hook != expected_extension_hook:
        raise FoundationV4ReplayError(f"replay block extension hook is invalid: {spec.block_id}")


def _replay_block_spec(block_id: str) -> _ReplayBlockSpec:
    try:
        spec = _REPLAY_BLOCK_SPECS[block_id]
    except KeyError as exc:
        raise FoundationV4ReplayError(
            f"foundation block has no replay implementation: {block_id}"
        ) from exc
    if spec.block_id != block_id:
        raise FoundationV4ReplayError("replay block registry identity drifted")
    _validate_replay_block_spec(spec)
    return spec


class FoundationV4ReplayError(RuntimeError):
    """Raised when relocated replay cannot prove its sealed execution boundary."""


class FoundationV4ForbiddenMutationError(FoundationV4ReplayError):
    """Raised before a covered CPython mutation can touch a forbidden root."""


class OuterReplayProcessError(FoundationV4ReplayError):
    """A failed outer process with explicit failure-preservation state."""

    def __init__(
        self,
        message: str,
        *,
        returncode: int,
        failure_capture_path: Path | None,
        failure_capture_sha256: str | None,
        preservation_complete: bool,
        original_output_root: Path,
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.failure_capture_path = failure_capture_path
        self.failure_capture_sha256 = failure_capture_sha256
        self.preservation_complete = preservation_complete
        self.original_output_root = original_output_root


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_reparse_path(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    attributes = int(getattr(info, "st_file_attributes", 0))
    return stat.S_ISLNK(info.st_mode) or bool(
        attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    )


def _normalized_guard_path(path: object) -> str | None:
    if isinstance(path, int):
        return None
    try:
        value = os.fsdecode(os.fspath(path))
    except (OSError, TypeError, ValueError):
        return None
    return os.path.normcase(os.path.abspath(value))


def _guard_root_set(
    *,
    pack_root: Path,
    forbidden_roots: Sequence[Path],
    injected_live_root: Path,
) -> tuple[str, ...]:
    normalized = {
        value
        for path in (pack_root, *forbidden_roots, injected_live_root)
        if (value := _normalized_guard_path(path)) is not None
    }
    return tuple(sorted(normalized))


def _guard_root_set_sha256(roots: Sequence[str]) -> str:
    return _sha256(_canonical_bytes(list(roots)))


def _matched_guard_root(path: str, roots: Sequence[str]) -> str | None:
    for root in roots:
        try:
            if os.path.commonpath((path, root)) == root:
                return root
        except ValueError:
            continue
    return None


def _validate_guard_output_locations(
    *, roots: Sequence[str], locations: Sequence[tuple[str, Path]]
) -> None:
    for label, path in locations:
        normalized = _normalized_guard_path(path)
        if normalized is None:
            raise FoundationV4ReplayError(f"{label} is not a lexical path")
        matched = _matched_guard_root(normalized, roots)
        if matched is not None:
            raise FoundationV4ReplayError(
                f"{label} overlaps forbidden root: {normalized} under {matched}"
            )


class _ForbiddenMutationGuard:
    """Narrow CPython audit-hook guard for accidental path mutations.

    This is not a malicious-code sandbox.  It closes the listed CPython and
    stdlib mutation events for the sealed, hash-bound F1 call graph.
    """

    _SINGLE_PATH_EVENTS: ClassVar[dict[str, tuple[int, int | None]]] = {
        "os.mkdir": (0, 2),
        "os.remove": (0, 1),
        "os.rmdir": (0, 1),
        "os.chmod": (0, 2),
        "os.chown": (0, 3),
        "os.chflags": (0, None),
        "os.utime": (0, 3),
        "os.setxattr": (0, None),
        "os.removexattr": (0, None),
        "shutil.chown": (0, None),
        "shutil.rmtree": (0, 1),
        "tempfile.mkstemp": (0, None),
        "tempfile.mkdtemp": (0, None),
        "shutil.make_archive": (0, None),
        "shutil.unpack_archive": (1, None),
    }
    _TWO_PATH_EVENTS: ClassVar[dict[str, tuple[int, int, tuple[int, ...]]]] = {
        "os.rename": (0, 1, (2, 3)),
        "os.link": (0, 1, (2, 3)),
        "os.symlink": (0, 1, (2,)),
        "_winapi.CreateJunction": (0, 1, ()),
        "shutil.move": (0, 1, ()),
    }
    _DESTINATION_ONLY_EVENTS: ClassVar[set[str]] = {
        "shutil.copyfile",
        "shutil.copymode",
        "shutil.copystat",
        "shutil.copytree",
    }

    def __init__(
        self,
        *,
        pack_root: Path,
        forbidden_roots: Sequence[Path],
        injected_live_root: Path,
        event_log_path: Path,
        nonce: str,
        role: str,
    ) -> None:
        self.roots = _guard_root_set(
            pack_root=pack_root,
            forbidden_roots=forbidden_roots,
            injected_live_root=injected_live_root,
        )
        self.root_set_sha256 = _guard_root_set_sha256(self.roots)
        if _normalized_guard_path(event_log_path) is None:
            raise FoundationV4ReplayError("guard event log is not a lexical path")
        self.event_log_path = _lexical_absolute(event_log_path)
        self.nonce = nonce
        self.role = role
        self.interpreter_pid = os.getpid()
        self._sequence = 0
        self._previous_event_sha256 = _ZERO_SHA256
        self._probe_observed = False
        self._local = threading.local()
        _validate_guard_output_locations(
            roots=self.roots,
            locations=(("guard event log", self.event_log_path),),
        )
        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        self._fd = os.open(self.event_log_path, flags, 0o600)

    def declaration(self) -> dict[str, Any]:
        return {
            "guard_schema_version": FORBIDDEN_GUARD_SCHEMA,
            "root_set_sha256": self.root_set_sha256,
            "event_log_path": str(self.event_log_path),
            "nonce": self.nonce,
            "role": self.role,
            "interpreter_pid": self.interpreter_pid,
        }

    def install(self) -> None:
        sys.addaudithook(self._audit_hook)
        sys.audit(FORBIDDEN_GUARD_PROBE_EVENT, self.nonce, self.role)
        if not self._probe_observed:
            raise FoundationV4ReplayError("forbidden mutation guard probe was not observed")

    def _write_record(
        self,
        *,
        event: str,
        write_intent: bool,
        normalized_paths: Sequence[str],
        matched_forbidden_root: str | None,
        disposition: str,
    ) -> None:
        self._sequence += 1
        core = {
            "schema_version": FORBIDDEN_GUARD_SCHEMA,
            "sequence": self._sequence,
            "nonce": self.nonce,
            "role": self.role,
            "interpreter_pid": self.interpreter_pid,
            "event": event,
            "write_intent": write_intent,
            "normalized_paths": list(normalized_paths),
            "matched_forbidden_root": matched_forbidden_root,
            "disposition": disposition,
            "root_set_sha256": self.root_set_sha256,
            "previous_event_sha256": self._previous_event_sha256,
        }
        content_sha256 = _canonical_sha256(core)
        raw = _canonical_bytes({**core, "content_sha256": content_sha256}) + b"\n"
        offset = 0
        while offset < len(raw):
            written = os.write(self._fd, raw[offset:])
            if written <= 0:
                raise FoundationV4ReplayError("forbidden guard log write failed")
            offset += written
        self._previous_event_sha256 = content_sha256

    @staticmethod
    def _dir_fd_is_ambiguous(args: tuple[object, ...], positions: Sequence[int]) -> bool:
        for position in positions:
            if position >= len(args):
                continue
            value = args[position]
            if isinstance(value, int) and value >= 0:
                return True
        return False

    @staticmethod
    def _open_has_write_intent(mode: object, flags: object) -> bool:
        if isinstance(mode, str) and any(token in mode for token in "wax+"):
            return True
        if not isinstance(flags, int):
            return False
        access_mask = getattr(
            os,
            "O_ACCMODE",
            os.O_RDONLY | os.O_WRONLY | os.O_RDWR,
        )
        access_mode = flags & access_mask
        creation_flags = os.O_APPEND | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_EXCL"):
            creation_flags |= os.O_EXCL
        return access_mode in {os.O_WRONLY, os.O_RDWR} or bool(flags & creation_flags)

    @staticmethod
    def _sqlite_memory_database(value: object) -> bool:
        if not isinstance(value, (str, bytes, os.PathLike)):
            return False
        raw = os.fsdecode(os.fspath(value)).casefold()
        return raw == ":memory:" or (
            raw.startswith("file:") and (raw.startswith("file::memory:") or "mode=memory" in raw)
        )

    def _mutation_paths(
        self, event: str, args: tuple[object, ...]
    ) -> tuple[list[str], bool] | None:
        candidates: list[object]
        ambiguous = False
        if event == "open":
            if not args or not self._open_has_write_intent(
                args[1] if len(args) > 1 else None,
                args[2] if len(args) > 2 else None,
            ):
                return None
            candidates = [args[0]]
        elif event == "_winapi.CreateFile":
            if len(args) < 4:
                return None
            desired_access = args[1]
            creation_disposition = args[3]
            write_access = 0x40000000 | 0x10000000 | 0x00010000 | 0x00040000
            write_access |= 0x00080000 | 0x00000002 | 0x00000004 | 0x00000010
            write_access |= 0x00000100
            if not (
                (isinstance(desired_access, int) and desired_access & write_access)
                or (isinstance(creation_disposition, int) and creation_disposition in {1, 2, 4, 5})
            ):
                return None
            candidates = [args[0]]
        elif event == "sqlite3.connect":
            if not args or self._sqlite_memory_database(args[0]):
                return None
            candidates = [args[0]]
        elif event in self._SINGLE_PATH_EVENTS:
            path_position, dir_fd_position = self._SINGLE_PATH_EVENTS[event]
            if path_position >= len(args):
                return None
            candidates = [args[path_position]]
            ambiguous = dir_fd_position is not None and self._dir_fd_is_ambiguous(
                args, (dir_fd_position,)
            )
        elif event in self._TWO_PATH_EVENTS:
            source_position, destination_position, dir_fd_positions = self._TWO_PATH_EVENTS[event]
            if max(source_position, destination_position) >= len(args):
                return None
            candidates = [args[source_position], args[destination_position]]
            ambiguous = self._dir_fd_is_ambiguous(args, dir_fd_positions)
        elif event in self._DESTINATION_ONLY_EVENTS:
            if len(args) < 2:
                return None
            candidates = [args[1]]
        elif event == "os.truncate":
            if not args:
                return None
            candidates = [args[0]]
            ambiguous = isinstance(args[0], int)
        elif event == "mmap.__new__":
            if not args:
                return None
            access = args[2] if len(args) > 2 else 0
            if access == 1:
                return None
            candidates = [args[0]]
            ambiguous = True
        else:
            return None

        normalized_paths: list[str] = []
        for candidate in candidates:
            normalized = _normalized_guard_path(candidate)
            if normalized is None:
                ambiguous = True
                normalized_paths.append(f"<AMBIGUOUS:{candidate!r}>")
            else:
                normalized_paths.append(normalized)
        return normalized_paths, ambiguous

    def _audit_hook(self, event: str, args: tuple[object, ...]) -> None:
        if getattr(self._local, "depth", 0):
            return
        self._local.depth = 1
        try:
            if event == FORBIDDEN_GUARD_PROBE_EVENT:
                if args == (self.nonce, self.role):
                    self._write_record(
                        event=event,
                        write_intent=False,
                        normalized_paths=(),
                        matched_forbidden_root=None,
                        disposition="PROBE",
                    )
                    self._probe_observed = True
                return
            mutation = self._mutation_paths(event, args)
            if mutation is None:
                return
            normalized_paths, ambiguous = mutation
            matched = next(
                (
                    root
                    for path in normalized_paths
                    if not path.startswith("<AMBIGUOUS:")
                    for root in (self._match(path),)
                    if root is not None
                ),
                None,
            )
            if ambiguous or matched is not None:
                disposition_root = "AMBIGUOUS" if ambiguous and matched is None else matched
                self._write_record(
                    event=event,
                    write_intent=True,
                    normalized_paths=normalized_paths,
                    matched_forbidden_root=disposition_root,
                    disposition="DENY",
                )
                raise FoundationV4ForbiddenMutationError(
                    f"forbidden mutation denied: event={event}, matched_root={disposition_root}"
                )
            self._write_record(
                event=event,
                write_intent=True,
                normalized_paths=normalized_paths,
                matched_forbidden_root=None,
                disposition="ALLOW",
            )
        finally:
            self._local.depth = 0

    def _match(self, path: str) -> str | None:
        return _matched_guard_root(path, self.roots)


def _verify_forbidden_mutation_log(
    *,
    event_log_path: Path,
    expected_nonce: str,
    expected_role: str,
    expected_interpreter_pid: int,
    expected_roots: Sequence[str],
    require_success: bool,
) -> dict[str, Any]:
    path = _lexical_absolute(event_log_path)
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise FoundationV4ReplayError("forbidden guard log is empty or truncated")
    previous = _ZERO_SHA256
    normalized_roots = tuple(sorted(set(expected_roots)))
    expected_root_set_sha256 = _guard_root_set_sha256(normalized_roots)
    covered_events = {
        "open",
        "_winapi.CreateFile",
        "sqlite3.connect",
        "os.truncate",
        "mmap.__new__",
        *_ForbiddenMutationGuard._SINGLE_PATH_EVENTS,
        *_ForbiddenMutationGuard._TWO_PATH_EVENTS,
        *_ForbiddenMutationGuard._DESTINATION_ONLY_EVENTS,
    }
    probe_count = 0
    allowed_count = 0
    denied_count = 0
    for expected_sequence, line in enumerate(raw.splitlines(), start=1):
        try:
            event = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FoundationV4ReplayError("forbidden guard log is not JSONL") from exc
        if not isinstance(event, dict) or _canonical_bytes(event) != line:
            raise FoundationV4ReplayError("forbidden guard event is not canonical JSON")
        core = dict(event)
        content_sha256 = core.pop("content_sha256", None)
        if (
            content_sha256 != _canonical_sha256(core)
            or event.get("schema_version") != FORBIDDEN_GUARD_SCHEMA
            or event.get("sequence") != expected_sequence
            or event.get("previous_event_sha256") != previous
            or event.get("nonce") != expected_nonce
            or event.get("role") != expected_role
            or event.get("interpreter_pid") != expected_interpreter_pid
            or event.get("root_set_sha256") != expected_root_set_sha256
        ):
            raise FoundationV4ReplayError("forbidden guard event binding drifted")
        disposition = event.get("disposition")
        normalized_paths = event.get("normalized_paths")
        matched_forbidden_root = event.get("matched_forbidden_root")
        if disposition == "PROBE":
            if (
                event.get("event") != FORBIDDEN_GUARD_PROBE_EVENT
                or event.get("write_intent") is not False
                or normalized_paths != []
                or matched_forbidden_root is not None
            ):
                raise FoundationV4ReplayError("forbidden guard probe event drifted")
            probe_count += 1
        else:
            if (
                event.get("event") not in covered_events
                or event.get("write_intent") is not True
                or not isinstance(normalized_paths, list)
                or not normalized_paths
                or not all(isinstance(item, str) and item for item in normalized_paths)
            ):
                raise FoundationV4ReplayError("forbidden guard mutation event drifted")
            ambiguous = any(item.startswith("<AMBIGUOUS:") for item in normalized_paths)
            concrete_paths = [
                item for item in normalized_paths if not item.startswith("<AMBIGUOUS:")
            ]
            if any(_normalized_guard_path(item) != item for item in concrete_paths):
                raise FoundationV4ReplayError("forbidden guard path is not normalized")
            matched = next(
                (
                    root
                    for candidate in concrete_paths
                    if (root := _matched_guard_root(candidate, normalized_roots)) is not None
                ),
                None,
            )
            expected_matched = "AMBIGUOUS" if ambiguous and matched is None else matched
            expected_disposition = "DENY" if ambiguous or matched is not None else "ALLOW"
            if disposition != expected_disposition or matched_forbidden_root != expected_matched:
                raise FoundationV4ReplayError(
                    "forbidden guard disposition does not match normalized paths"
                )
            if disposition == "ALLOW":
                allowed_count += 1
            else:
                denied_count += 1
        previous = str(content_sha256)
    if probe_count != 1:
        raise FoundationV4ReplayError("forbidden guard probe count is invalid")
    if require_success and denied_count != 0:
        raise FoundationV4ReplayError("forbidden guard recorded a denied mutation")
    return {
        "guard_schema_version": FORBIDDEN_GUARD_SCHEMA,
        "root_set_sha256": expected_root_set_sha256,
        "probe_observed": True,
        "covered_mutation_event_count": allowed_count + denied_count,
        "allowed_mutation_event_count": allowed_count,
        "denied_mutation_event_count": denied_count,
        "event_log_path": str(path),
        "event_log_sha256": _sha256(raw),
        "event_chain_head_sha256": previous,
        "interpreter_pid": expected_interpreter_pid,
    }


def _tree_inventory_sha256(root: Path) -> str:
    lexical = _lexical_absolute(root)
    entries: list[list[object]] = []
    for path in sorted(item for item in lexical.rglob("*") if item.is_file()):
        raw = path.read_bytes()
        entries.append([path.relative_to(lexical).as_posix(), len(raw), _sha256(raw)])
    return _sha256(_canonical_bytes(entries))


def _require_plain_path_chain(path: Path, *, label: str) -> Path:
    lexical = _lexical_absolute(path)
    current = lexical
    while True:
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise FoundationV4ReplayError(f"cannot inspect {label} path chain: {current}") from exc
        else:
            attributes = int(getattr(info, "st_file_attributes", 0))
            if stat.S_ISLNK(info.st_mode) or bool(
                attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
            ):
                raise FoundationV4ReplayError(
                    f"{label} path chain contains a reparse point: {current}"
                )
        parent = current.parent
        if parent == current:
            break
        current = parent
    return lexical


def _failure_capture_inventory(root: Path) -> tuple[dict[str, Any], ...]:
    lexical = _require_plain_path_chain(root, label="failure capture")
    rows: list[dict[str, Any]] = []
    for path in sorted(lexical.rglob("*")):
        if _is_reparse_path(path):
            raise FoundationV4ReplayError(f"outer failure capture contains a reparse point: {path}")
        if not path.is_file():
            continue
        raw = path.read_bytes()
        rows.append(
            {
                "relative_path": path.relative_to(lexical).as_posix(),
                "size_bytes": len(raw),
                "sha256": _sha256(raw),
            }
        )
    return tuple(rows)


def _plain_file_observation(path: Path) -> dict[str, Any]:
    lexical = _lexical_absolute(path)
    if not lexical.is_file() or _is_reparse_path(lexical):
        raise FoundationV4ReplayError(f"observed executable/source is not a plain file: {lexical}")
    raw = lexical.read_bytes()
    return {"path": str(lexical), "size_bytes": len(raw), "sha256": _sha256(raw)}


def _content_hashed_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    value, raw = _read_json_object(path, label=label)
    core = dict(value)
    content_sha256 = core.pop("content_sha256", None)
    if content_sha256 != _canonical_sha256(core) or _canonical_bytes(value) != raw:
        raise FoundationV4ReplayError(f"{label} content hash drifted")
    return value, raw


def _validated_nested_failure_invocation(
    argv: Sequence[str],
    *,
    expected_role: str,
    expected_phase: str,
) -> dict[str, Any]:
    values = list(argv)
    if (
        len(values) != 11
        or values[1:6] != ["-X", "faulthandler", "-I", "-S", "-B"]
        or values[7:10] != ["--child-role", expected_role, "--context-json"]
        or not Path(values[0]).is_absolute()
        or not Path(values[6]).is_absolute()
    ):
        raise FoundationV4ReplayError("nested failure exact invocation drifted")
    try:
        context = json.loads(values[10])
    except (TypeError, json.JSONDecodeError) as exc:
        raise FoundationV4ReplayError("nested failure context is not JSON") from exc
    if (
        not isinstance(context, dict)
        or context.get("role") != expected_role
        or context.get("phase") != expected_phase
        or not isinstance(context.get("nonce"), str)
        or not context.get("nonce")
        or type(context.get("run_index")) is not int
        or not isinstance(context.get("run_root"), str)
        or not Path(str(context.get("run_root"))).is_absolute()
        or not isinstance(context.get("entrypoint_path"), str)
        or not Path(str(context.get("entrypoint_path"))).is_absolute()
        or os.path.normcase(str(_lexical_absolute(Path(context["entrypoint_path"]))))
        != os.path.normcase(str(_lexical_absolute(Path(values[6]))))
        or not _is_sha256(context.get("entrypoint_sha256"))
        or not isinstance(context.get("entrypoint_manifest_path"), str)
        or not Path(str(context.get("entrypoint_manifest_path"))).is_absolute()
    ):
        raise FoundationV4ReplayError("nested failure context binding drifted")
    return context


def _validate_copied_nested_failure(
    copied_run_root: Path,
    *,
    expected_nonce: str | None = None,
    expected_run_index: int | None = None,
    expected_original_run_root: Path | None = None,
    expected_runtime_python: Path | None = None,
    expected_sealed_entrypoint: Path | None = None,
    expected_sealed_entrypoint_manifest: Path | None = None,
    outer_stderr: bytes | None = None,
) -> tuple[bool, bool, int]:
    audit_root = _lexical_absolute(copied_run_root) / "audit"
    attempt_path = audit_root / "nested-failure-attempt.json"
    index_path = audit_root / "nested-failure-index.json"
    capture_parent = audit_root / "nested-failures"
    if not attempt_path.exists():
        if index_path.exists() or capture_parent.exists():
            raise FoundationV4ReplayError("nested failure artifact exists without an attempt")
        return False, False, 0
    attempt, _ = _content_hashed_object(attempt_path, label="nested failure attempt")
    if (
        set(attempt)
        != {
            "schema_version",
            "status",
            "role",
            "phase",
            "exact_argv_sha256",
            "launcher_process_pid",
            "returncode_signed",
            "returncode_uint32",
            "returncode_hex",
            "content_sha256",
        }
        or attempt.get("schema_version") != NESTED_FAILURE_ATTEMPT_SCHEMA
        or attempt.get("status") != "CAPTURE_ATTEMPTED"
        or attempt.get("role") not in {"phase", "ascii"}
        or attempt.get("phase") not in {"seed", "final", "reordered"}
        or not _is_sha256(attempt.get("exact_argv_sha256"))
        or type(attempt.get("launcher_process_pid")) is not int
        or attempt.get("launcher_process_pid", 0) <= 0
        or type(attempt.get("returncode_signed")) is not int
        or int(attempt.get("returncode_signed")) == 0
        or type(attempt.get("returncode_uint32")) is not int
        or attempt.get("returncode_uint32") != (int(attempt.get("returncode_signed")) & 0xFFFFFFFF)
        or attempt.get("returncode_hex") != f"0x{int(attempt.get('returncode_uint32')):08X}"
    ):
        raise FoundationV4ReplayError("nested failure attempt shape drifted")
    if not index_path.exists():
        if capture_parent.exists():
            raise FoundationV4ReplayError("nested failure capture exists without an index")
        return True, False, 0
    index, _ = _content_hashed_object(index_path, label="nested failure index")
    if (
        set(index)
        != {
            "schema_version",
            "status",
            "role",
            "phase",
            "exact_argv_sha256",
            "returncode_uint32",
            "capture_receipt_relative_path",
            "capture_receipt_sha256",
            "content_sha256",
        }
        or index.get("schema_version") != NESTED_FAILURE_INDEX_SCHEMA
        or index.get("status") != "FAILURE_CAPTURED"
        or index.get("role") != attempt.get("role")
        or index.get("phase") != attempt.get("phase")
        or index.get("exact_argv_sha256") != attempt.get("exact_argv_sha256")
        or type(index.get("returncode_uint32")) is not int
        or index.get("returncode_uint32") != attempt.get("returncode_uint32")
        or not _is_sha256(index.get("capture_receipt_sha256"))
    ):
        raise FoundationV4ReplayError("nested failure index binding drifted")
    expected_receipt_relative = (
        f"nested-failures/{attempt['role']}-{attempt['phase']}/failure_capture.json"
    )
    if index.get("capture_receipt_relative_path") != expected_receipt_relative:
        raise FoundationV4ReplayError("nested failure index path drifted")
    capture_id = f"{attempt['role']}-{attempt['phase']}"
    if (
        not capture_parent.is_dir()
        or _is_reparse_path(capture_parent)
        or sorted(path.name for path in capture_parent.iterdir()) != [capture_id]
        or not (capture_parent / capture_id).is_dir()
        or _is_reparse_path(capture_parent / capture_id)
    ):
        raise FoundationV4ReplayError("nested failure capture topology drifted")
    receipt_relative = _safe_relative_path(
        index.get("capture_receipt_relative_path"),
        label="nested failure receipt relative_path",
    )
    receipt_path = audit_root / receipt_relative
    receipt, receipt_raw = _content_hashed_object(
        receipt_path, label="nested failure capture receipt"
    )
    if (
        _sha256(receipt_raw) != index.get("capture_receipt_sha256")
        or set(receipt)
        != {
            "schema_version",
            "status",
            "role",
            "phase",
            "exact_argv",
            "exact_argv_sha256",
            "launcher_process_pid",
            "returncode_signed",
            "returncode_uint32",
            "returncode_hex",
            "failure_class",
            "faulthandler_requested",
            "guard_log_path",
            "guard_log_exists",
            "guard_log_size_bytes",
            "guard_log_sha256",
            "artifact_count",
            "artifact_inventory",
            "artifact_inventory_sha256",
            "retry_count",
            "content_sha256",
        }
        or receipt.get("schema_version") != NESTED_FAILURE_CAPTURE_SCHEMA
        or receipt.get("status") != "FAILURE_CAPTURED"
        or receipt.get("role") != attempt.get("role")
        or receipt.get("phase") != attempt.get("phase")
        or not isinstance(receipt.get("exact_argv"), list)
        or not all(isinstance(item, str) and item for item in receipt.get("exact_argv", []))
        or _canonical_sha256(receipt.get("exact_argv")) != receipt.get("exact_argv_sha256")
        or receipt.get("exact_argv_sha256") != attempt.get("exact_argv_sha256")
        or type(receipt.get("launcher_process_pid")) is not int
        or receipt.get("launcher_process_pid") != attempt.get("launcher_process_pid")
        or type(receipt.get("returncode_signed")) is not int
        or receipt.get("returncode_signed") != attempt.get("returncode_signed")
        or type(receipt.get("returncode_uint32")) is not int
        or receipt.get("returncode_uint32") != attempt.get("returncode_uint32")
        or receipt.get("returncode_hex") != attempt.get("returncode_hex")
        or receipt.get("failure_class")
        != (
            "WINDOWS_ACCESS_VIOLATION"
            if receipt.get("returncode_uint32") == 0xC0000005
            else "PROCESS_EXIT_NONZERO"
        )
        or receipt.get("faulthandler_requested") is not True
        or receipt.get("retry_count") != 0
    ):
        raise FoundationV4ReplayError("nested failure capture receipt binding drifted")
    context = _validated_nested_failure_invocation(
        receipt["exact_argv"],
        expected_role=str(attempt["role"]),
        expected_phase=str(attempt["phase"]),
    )
    original_run_root = _lexical_absolute(Path(str(context["run_root"])))
    if (
        (expected_nonce is not None and context.get("nonce") != expected_nonce)
        or (expected_run_index is not None and context.get("run_index") != expected_run_index)
        or (
            expected_run_index is not None and original_run_root.name != f"run-{expected_run_index}"
        )
        or (
            expected_original_run_root is not None
            and os.path.normcase(str(original_run_root))
            != os.path.normcase(str(_lexical_absolute(expected_original_run_root)))
        )
        or (
            expected_runtime_python is not None
            and os.path.normcase(receipt["exact_argv"][0])
            != os.path.normcase(str(_lexical_absolute(expected_runtime_python)))
        )
        or (
            expected_sealed_entrypoint is not None
            and os.path.normcase(receipt["exact_argv"][6])
            != os.path.normcase(str(_lexical_absolute(expected_sealed_entrypoint)))
        )
        or (
            expected_sealed_entrypoint is not None
            and context.get("entrypoint_sha256")
            != _sha256(_lexical_absolute(expected_sealed_entrypoint).read_bytes())
        )
        or (
            expected_sealed_entrypoint_manifest is not None
            and os.path.normcase(str(_lexical_absolute(Path(context["entrypoint_manifest_path"]))))
            != os.path.normcase(str(_lexical_absolute(expected_sealed_entrypoint_manifest)))
        )
    ):
        raise FoundationV4ReplayError("nested failure parent invocation binding drifted")
    expected_guard_name = f"forbidden-{attempt['role']}-{attempt['phase']}.jsonl"
    expected_original_guard = original_run_root / "audit" / expected_guard_name
    copied_guard = audit_root / expected_guard_name
    if (
        receipt.get("guard_log_exists") is not True
        or not isinstance(receipt.get("guard_log_path"), str)
        or os.path.normcase(str(_lexical_absolute(Path(receipt["guard_log_path"]))))
        != os.path.normcase(str(expected_original_guard))
        or not copied_guard.is_file()
        or _is_reparse_path(copied_guard)
        or type(receipt.get("guard_log_size_bytes")) is not int
        or not _is_sha256(receipt.get("guard_log_sha256"))
    ):
        raise FoundationV4ReplayError("nested failure guard observation drifted")
    _verify_file_identity(
        copied_guard,
        expected_size=receipt["guard_log_size_bytes"],
        expected_sha256=receipt["guard_log_sha256"],
        drift_label="nested failure copied guard drift",
    )
    artifacts = receipt.get("artifact_inventory")
    if (
        not isinstance(artifacts, list)
        or receipt.get("artifact_count") != 2
        or len(artifacts) != 2
        or receipt.get("artifact_inventory_sha256") != _canonical_sha256(artifacts)
        or {row.get("relative_path") for row in artifacts if isinstance(row, dict)}
        != {"stdout.bin", "stderr.bin"}
    ):
        raise FoundationV4ReplayError("nested failure artifact inventory drifted")
    capture_root = receipt_path.parent
    committed_inventory = _failure_capture_inventory(capture_root)
    if {row["relative_path"] for row in committed_inventory} != {
        "failure_capture.json",
        "stderr.bin",
        "stdout.bin",
    }:
        raise FoundationV4ReplayError("nested failure committed artifact set drifted")
    for row in artifacts:
        if not isinstance(row, dict) or set(row) != {
            "relative_path",
            "size_bytes",
            "sha256",
        }:
            raise FoundationV4ReplayError("nested failure artifact row drifted")
        relative = _safe_relative_path(
            row.get("relative_path"), label="nested failure artifact relative_path"
        )
        _verify_file_identity(
            capture_root / relative,
            expected_size=row.get("size_bytes"),
            expected_sha256=row.get("sha256"),
            drift_label="nested failure copied artifact drift",
        )
    if outer_stderr is not None:
        receipt_marker = f"sha256={_sha256(receipt_raw)}".encode("ascii")
        if receipt_marker not in outer_stderr:
            raise FoundationV4ReplayError("nested failure lacks the parent stderr observation")
    return True, True, 1


def _outer_start_record_path(*, output_root: Path, run_index: int) -> Path:
    return _lexical_absolute(
        output_root / f"run-{run_index}" / "audit" / "outer-process-start.json"
    )


def _cleanup_committed_outer_start_record() -> None:
    if not _OUTER_STDOUT_COMMITTED or _OUTER_START_RECORD_TO_CLEAN is None:
        return
    try:
        _OUTER_START_RECORD_TO_CLEAN.unlink()
    except FileNotFoundError:
        return


atexit.register(_cleanup_committed_outer_start_record)


def _write_outer_start_record(*, args: argparse.Namespace, run_root: Path) -> Path:
    global _OUTER_START_RECORD_TO_CLEAN
    if not faulthandler.is_enabled():
        raise FoundationV4ReplayError("sealed outer replay faulthandler is not enabled")
    path = _lexical_absolute(run_root / "audit" / "outer-process-start.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    executable = _plain_file_observation(Path(sys.executable))
    base_executable = _base_executable_identity()
    core = {
        "schema_version": OUTER_START_RECORD_SCHEMA,
        "status": "STARTED",
        "block_id": str(args.block_id),
        "nonce": str(args.nonce),
        "run_index": int(args.run_index),
        "interpreter_pid": os.getpid(),
        "parent_pid": os.getppid(),
        "faulthandler_enabled": True,
        "sys_executable": executable,
        "base_executable": base_executable,
        "orig_argv_tail_sha256": _canonical_sha256(list(sys.orig_argv[1:])),
    }
    path.write_bytes(_canonical_bytes({**core, "content_sha256": _canonical_sha256(core)}))
    _OUTER_START_RECORD_TO_CLEAN = path
    return path


def _validated_outer_start_record(
    *,
    path: Path,
    block_id: str,
    nonce: str,
    run_index: int,
    actual_argv: Sequence[str],
    expected_interpreter_pid: int | None = None,
) -> dict[str, Any]:
    value, raw = _read_json_object(path, label="outer process start record")
    core = dict(value)
    content_sha256 = core.pop("content_sha256", None)
    if (
        set(value)
        != {
            "schema_version",
            "status",
            "block_id",
            "nonce",
            "run_index",
            "interpreter_pid",
            "parent_pid",
            "faulthandler_enabled",
            "sys_executable",
            "base_executable",
            "orig_argv_tail_sha256",
            "content_sha256",
        }
        or value.get("schema_version") != OUTER_START_RECORD_SCHEMA
        or value.get("status") != "STARTED"
        or value.get("block_id") != block_id
        or value.get("nonce") != nonce
        or value.get("run_index") != run_index
        or value.get("faulthandler_enabled") is not True
        or not isinstance(value.get("interpreter_pid"), int)
        or value.get("interpreter_pid", 0) <= 0
        or not isinstance(value.get("parent_pid"), int)
        or value.get("parent_pid", 0) <= 0
        or value.get("orig_argv_tail_sha256") != _canonical_sha256(list(actual_argv[1:]))
        or content_sha256 != _canonical_sha256(core)
        or _canonical_bytes(value) != raw
        or (
            expected_interpreter_pid is not None
            and value.get("interpreter_pid") != expected_interpreter_pid
        )
    ):
        raise FoundationV4ReplayError("outer process start record binding drifted")
    return value


def _persist_outer_failure_capture(
    *,
    capture_root: Path,
    block_id: str,
    nonce: str,
    run_index: int,
    argv: Sequence[str],
    cwd: Path,
    returncode: int,
    stdout: bytes,
    stderr: bytes,
    launcher_process_pid: int,
    runtime_python: Path,
    sealed_entrypoint_path: Path,
    sealed_entrypoint_manifest_path: Path,
    output_root: Path,
) -> tuple[Path, str, bool]:
    parent = _require_plain_path_chain(capture_root, label="outer failure capture root")
    if _is_under(parent, (_lexical_absolute(output_root),)):
        raise FoundationV4ReplayError("outer failure capture root is inside ephemeral output")
    parent.mkdir(parents=True, exist_ok=True)
    _require_plain_path_chain(parent, label="outer failure capture root")
    if not parent.is_dir() or _is_reparse_path(parent):
        raise FoundationV4ReplayError("outer failure capture root is not a plain directory")
    unsigned_returncode = returncode & 0xFFFFFFFF
    capture_id = f"{block_id}-{nonce[:16]}-run-{run_index}-exit-{unsigned_returncode:08x}"
    stage = parent / f".{capture_id}.staging"
    final = parent / capture_id
    if stage.exists() or final.exists():
        raise FoundationV4ReplayError("outer failure capture identity already exists")
    stage.mkdir(parents=False, exist_ok=False)
    (stage / "stdout.bin").write_bytes(stdout)
    (stage / "stderr.bin").write_bytes(stderr)

    original_run_root = _lexical_absolute(output_root / f"run-{run_index}")
    copied_run_root: Path | None = None
    if original_run_root.is_dir():
        _require_plain_path_chain(original_run_root, label="outer failure source run root")
        _failure_capture_inventory(original_run_root)
        copied_run_root = stage / "partial_run"
        shutil.copytree(original_run_root, copied_run_root, copy_function=shutil.copyfile)
        if _tree_inventory_sha256(copied_run_root) != _tree_inventory_sha256(original_run_root):
            raise FoundationV4ReplayError("outer failure partial-run copy drifted")

    nested_capture_required = block_id == "F1_settlement_world"
    nested_capture_validated = False
    nested_capture_count = 0
    nested_capture_error: str | None = None
    if copied_run_root is not None:
        try:
            (
                observed_nested_required,
                nested_capture_validated,
                nested_capture_count,
            ) = _validate_copied_nested_failure(
                copied_run_root,
                expected_nonce=nonce,
                expected_run_index=run_index,
                expected_original_run_root=original_run_root,
                expected_runtime_python=runtime_python,
                expected_sealed_entrypoint=sealed_entrypoint_path,
                expected_sealed_entrypoint_manifest=sealed_entrypoint_manifest_path,
                outer_stderr=stderr,
            )
            nested_capture_required = nested_capture_required or observed_nested_required
        except FoundationV4ReplayError as exc:
            nested_capture_error = str(exc)
            nested_capture_required = True
            nested_capture_validated = False
            nested_capture_count = 0

    start_record_validated = False
    start_record_observation: dict[str, Any] | None = None
    if copied_run_root is not None:
        copied_start = copied_run_root / "audit" / "outer-process-start.json"
        if copied_start.is_file():
            try:
                start_record_observation = _validated_outer_start_record(
                    path=copied_start,
                    block_id=block_id,
                    nonce=nonce,
                    run_index=run_index,
                    actual_argv=argv,
                )
            except FoundationV4ReplayError:
                start_record_observation = None
            else:
                if start_record_observation.get("parent_pid") == launcher_process_pid:
                    start_record_validated = True
                else:
                    start_record_observation = None

    artifacts = _failure_capture_inventory(stage)
    artifact_projection = [dict(row) for row in artifacts]
    preservation_verified = start_record_validated and (
        not nested_capture_required or nested_capture_validated
    )
    core = {
        "schema_version": OUTER_FAILURE_CAPTURE_SCHEMA,
        "status": "FAILURE_CAPTURED",
        "block_id": block_id,
        "nonce": nonce,
        "run_index": run_index,
        "cwd": str(_lexical_absolute(cwd)),
        "exact_argv": list(argv),
        "exact_argv_sha256": _canonical_sha256(list(argv)),
        "launcher_process_pid": launcher_process_pid,
        "returncode_signed": returncode,
        "returncode_uint32": unsigned_returncode,
        "returncode_hex": f"0x{unsigned_returncode:08X}",
        "failure_class": (
            "SUCCESS_LIFECYCLE_INCOMPLETE"
            if returncode == 0
            else (
                "WINDOWS_ACCESS_VIOLATION"
                if unsigned_returncode == 0xC0000005
                else "PROCESS_EXIT_NONZERO"
            )
        ),
        "faulthandler_requested": list(argv[1:3]) == ["-X", "faulthandler"],
        "faulthandler_start_record_validated": start_record_validated,
        "faulthandler_observed": (
            start_record_observation.get("faulthandler_enabled")
            if start_record_observation is not None
            else None
        ),
        "runtime_python": _plain_file_observation(runtime_python),
        "sealed_entrypoint": _plain_file_observation(sealed_entrypoint_path),
        "sealed_entrypoint_manifest": _plain_file_observation(sealed_entrypoint_manifest_path),
        "original_run_root": str(original_run_root),
        "partial_run_copied": copied_run_root is not None,
        "partial_run_inventory_sha256": (
            _tree_inventory_sha256(copied_run_root) if copied_run_root is not None else None
        ),
        "nested_failure_capture_required": nested_capture_required,
        "nested_failure_capture_validated": nested_capture_validated,
        "nested_failure_capture_count": nested_capture_count,
        "nested_failure_capture_error": nested_capture_error,
        "artifact_count": len(artifact_projection),
        "artifact_inventory": artifact_projection,
        "artifact_inventory_sha256": _canonical_sha256(artifact_projection),
        "retry_count": 0,
        "preservation_verified": preservation_verified,
    }
    receipt = {**core, "content_sha256": _canonical_sha256(core)}
    receipt_raw = _canonical_bytes(receipt)
    (stage / "failure_capture.json").write_bytes(receipt_raw)
    if (
        stage.parent != final.parent
        or stage.parent != parent
        or os.stat(stage).st_dev != os.stat(parent).st_dev
    ):
        raise FoundationV4ReplayError("outer failure staging is not an atomic sibling")
    stage.rename(final)
    _require_plain_path_chain(final, label="outer failure committed capture")

    observed, observed_raw = _read_json_object(
        final / "failure_capture.json", label="outer failure capture receipt"
    )
    if observed != receipt or observed_raw != receipt_raw:
        raise FoundationV4ReplayError("outer failure capture receipt drifted after commit")
    for row in artifact_projection:
        _verify_file_identity(
            final / Path(*str(row["relative_path"]).split("/")),
            expected_size=row["size_bytes"],
            expected_sha256=row["sha256"],
            drift_label="outer failure capture artifact drift",
        )
    return final, _sha256(receipt_raw), preservation_verified


def _lexical_absolute(path: Path) -> Path:
    """Return an absolute path without following a relocated tree outside itself."""

    return Path(os.path.abspath(os.fspath(path)))


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_bytes(value: object, *, ensure_ascii: bool = False) -> bytes:
    """Canonical JSON for the replay control envelope's I-JSON value subset."""

    return json.dumps(
        value,
        ensure_ascii=ensure_ascii,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii" if ensure_ascii else "utf-8")


def _canonical_sha256(value: object) -> str:
    return _sha256(_canonical_bytes(value))


def _read_json_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise FoundationV4ReplayError(f"relocated source is missing: {path}") from exc
    except OSError as exc:
        raise FoundationV4ReplayError(f"cannot read relocated {label}: {path}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationV4ReplayError(f"relocated {label} is not UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise FoundationV4ReplayError(f"relocated {label} must be a JSON object")
    return value, raw


def _safe_relative_path(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise FoundationV4ReplayError(f"{label} is not a portable relative path")
    relative = Path(*value.split("/"))
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise FoundationV4ReplayError(f"{label} is not a portable relative path")
    return relative


def _verify_file_identity(
    path: Path,
    *,
    expected_size: object,
    expected_sha256: object,
    drift_label: str,
) -> bytes:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise FoundationV4ReplayError(f"relocated source is missing: {path}") from exc
    except OSError as exc:
        raise FoundationV4ReplayError(f"cannot read relocated source: {path}") from exc
    if (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size < 0
        or not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
    ):
        raise FoundationV4ReplayError(f"{drift_label} manifest identity is invalid")
    if len(raw) != expected_size or _sha256(raw) != expected_sha256:
        raise FoundationV4ReplayError(f"{drift_label}: {path}")
    return raw


def _clean_child_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["XINAO_REPLAY_LAUNCHER_OWNER_PID"] = str(os.getpid())
    return environment


def _is_under(path: Path, roots: Sequence[Path]) -> bool:
    candidate = os.path.normcase(os.fspath(_lexical_absolute(path)))
    for root in roots:
        normalized_root = os.path.normcase(os.fspath(_lexical_absolute(root)))
        try:
            if os.path.commonpath((candidate, normalized_root)) == normalized_root:
                return True
        except ValueError:
            continue
    return False


class _AuditRecorder:
    def __init__(self, *, path: Path, nonce: str) -> None:
        self.path = _lexical_absolute(path)
        self.nonce = nonce
        self.pid = os.getpid()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"")

    def _append(self, event: dict[str, Any]) -> None:
        with self.path.open("ab") as stream:
            stream.write(_canonical_bytes({"nonce": self.nonce, "pid": self.pid, **event}) + b"\n")

    def read(self, path: Path, *, expected_sha256: str | None = None) -> bytes:
        lexical = _lexical_absolute(path)
        raw = lexical.read_bytes()
        digest = _sha256(raw)
        if expected_sha256 is not None and digest != expected_sha256:
            raise FoundationV4ReplayError(f"audited source SHA drift: {lexical}")
        self._append(
            {
                "operation": "read",
                "path": str(lexical),
                "content_sha256": digest,
                "size_bytes": len(raw),
            }
        )
        return raw

    def write(self, path: Path, raw: bytes) -> dict[str, str]:
        lexical = _lexical_absolute(path)
        lexical.parent.mkdir(parents=True, exist_ok=True)
        lexical.write_bytes(raw)
        digest = _sha256(raw)
        self._append(
            {
                "operation": "write",
                "path": str(lexical),
                "content_sha256": digest,
                "size_bytes": len(raw),
            }
        )
        return {"path": str(lexical), "sha256": digest}

    def attest_write(self, path: Path) -> dict[str, str]:
        lexical = _lexical_absolute(path)
        raw = lexical.read_bytes()
        digest = _sha256(raw)
        self._append(
            {
                "operation": "write",
                "path": str(lexical),
                "content_sha256": digest,
                "size_bytes": len(raw),
            }
        )
        return {"path": str(lexical), "sha256": digest}


def _scan_payload_tree_nonfollowing(*, foundation: Path) -> set[str]:
    """Enumerate ordinary payload files after rejecting unsafe entry shapes."""

    root = _lexical_absolute(foundation)
    try:
        root_stat = root.stat(follow_symlinks=False)
    except OSError as exc:
        raise FoundationV4ReplayError(
            f"relocated payload root cannot be inspected: {root}"
        ) from exc
    if root.is_symlink() or (getattr(root_stat, "st_file_attributes", 0) & 0x400):
        raise FoundationV4ReplayError("relocated payload root is a reparse entry")
    actual_files: set[str] = set()
    pending = [(root, Path())]
    while pending:
        directory, relative_parent = pending.pop()
        try:
            entries = tuple(os.scandir(directory))
        except OSError as exc:
            raise FoundationV4ReplayError(
                f"relocated payload tree cannot be enumerated: {directory}"
            ) from exc
        for entry in entries:
            relative = relative_parent / entry.name
            relative_posix = relative.as_posix()
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise FoundationV4ReplayError(
                    f"relocated payload entry cannot be inspected: {relative_posix}"
                ) from exc
            if entry.is_symlink() or (getattr(entry_stat, "st_file_attributes", 0) & 0x400):
                raise FoundationV4ReplayError(
                    f"relocated payload contains a reparse entry: {relative_posix}"
                )
            if entry.is_dir(follow_symlinks=False):
                if entry.name == "__pycache__":
                    raise FoundationV4ReplayError(
                        f"relocated payload contains a cache directory: {relative_posix}"
                    )
                pending.append((Path(entry.path), relative))
            elif entry.is_file(follow_symlinks=False):
                if Path(entry.name).suffix.casefold() in {".pyc", ".pyo"}:
                    raise FoundationV4ReplayError(
                        f"relocated payload contains bytecode: {relative_posix}"
                    )
                if relative.parts[0] not in LEGACY_OUTPUT_NAMES:
                    actual_files.add(relative_posix)
            else:
                raise FoundationV4ReplayError(
                    f"relocated payload contains a non-file entry: {relative_posix}"
                )
    return actual_files


def _validate_exact_payload_tree(*, actual_files: set[str], payload_paths: set[str]) -> None:
    """Bind a safe non-following scan to the manifest's exact file inventory."""

    reserved_collisions = sorted(
        path for path in payload_paths if Path(path).parts[0] in LEGACY_OUTPUT_NAMES
    )
    if reserved_collisions:
        raise FoundationV4ReplayError(
            f"relocated payload collides with reserved quarantine namespace: {reserved_collisions}"
        )
    expected_files = {*payload_paths, "capsule_manifest.json"}
    if actual_files != expected_files:
        raise FoundationV4ReplayError(
            "relocated payload tree is not exact: "
            f"missing_files={sorted(expected_files - actual_files)}, "
            f"extra_files={sorted(actual_files - expected_files)}"
        )


def _load_capsule_manifest(
    pack_root: Path, *, spec: _ReplayBlockSpec
) -> tuple[dict[str, Any], Path]:
    manifest_path = _lexical_absolute(pack_root / "foundation" / "capsule_manifest.json")
    manifest, _ = _read_json_object(manifest_path, label="capsule manifest")
    if manifest.get("schema_version") != spec.capsule_schema_version:
        raise FoundationV4ReplayError("relocated capsule manifest schema is invalid")
    return manifest, manifest_path


def _execution_preflight(
    *, pack_root: Path, spec: _ReplayBlockSpec
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    """Validate every execution material while deliberately excluding the oracle."""

    foundation = _lexical_absolute(pack_root / "foundation")
    actual_files = _scan_payload_tree_nonfollowing(foundation=foundation)
    capsule, _ = _load_capsule_manifest(pack_root, spec=spec)
    payload = capsule.get("payload")
    files = payload.get("files") if isinstance(payload, dict) else None
    request_ref = capsule.get("request")
    if not isinstance(files, list) or not isinstance(request_ref, dict):
        raise FoundationV4ReplayError("relocated capsule manifest shape is invalid")
    manifest_block_id = capsule.get("block_id", request_ref.get("block_id"))
    if manifest_block_id != spec.block_id:
        raise FoundationV4ReplayError("relocated request block identity drifted")
    inventory_lines: list[str] = []
    payload_paths: set[str] = set()
    payload_identities: dict[str, tuple[int, str]] = {}
    total_size = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise FoundationV4ReplayError("relocated payload entry is invalid")
        relative = _safe_relative_path(entry.get("relative_path"), label="payload relative_path")
        relative_posix = relative.as_posix()
        if relative_posix in payload_paths:
            raise FoundationV4ReplayError("relocated payload inventory is duplicated")
        payload_paths.add(relative_posix)
        size = entry.get("size_bytes")
        digest = entry.get("sha256")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise FoundationV4ReplayError("relocated payload identity is invalid")
        payload_identities[relative_posix] = (size, digest)
        path = foundation / relative
        if relative_posix not in spec.execution_excluded_payload_paths:
            _verify_file_identity(
                path,
                expected_size=size,
                expected_sha256=digest,
                drift_label=(
                    "authority source SHA drift"
                    if relative_posix.startswith("authority_snapshot/sources/")
                    else "relocated source SHA drift"
                ),
            )
        else:
            try:
                excluded_size = path.stat(follow_symlinks=False).st_size
            except OSError as exc:
                raise FoundationV4ReplayError(
                    f"relocated excluded payload is unavailable: {relative_posix}"
                ) from exc
            if excluded_size != size:
                raise FoundationV4ReplayError(
                    f"relocated excluded payload size drift: {relative_posix}"
                )
        total_size += size
        inventory_lines.append(f"{relative_posix}\t{size}\t{digest}")
    _validate_exact_payload_tree(actual_files=actual_files, payload_paths=payload_paths)
    if _sha256("\n".join(inventory_lines).encode("utf-8")) != payload.get("exact_inventory_sha256"):
        raise FoundationV4ReplayError("relocated payload inventory SHA drift")
    if total_size != payload.get("total_size_bytes"):
        raise FoundationV4ReplayError("relocated payload total size drift")

    request_relative = _safe_relative_path(
        request_ref.get("relative_path"), label="request relative_path"
    )
    if payload_identities.get(request_relative.as_posix()) != (
        request_ref.get("size_bytes"),
        request_ref.get("sha256"),
    ):
        raise FoundationV4ReplayError("relocated request manifest binding drifted")
    request_path = foundation / request_relative
    request_raw = _verify_file_identity(
        request_path,
        expected_size=request_ref.get("size_bytes"),
        expected_sha256=request_ref.get("sha256"),
        drift_label="relocated source SHA drift",
    )
    try:
        request = json.loads(request_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationV4ReplayError("relocated request is not JSON") from exc
    if not isinstance(request, dict) or request.get("block_id") != spec.block_id:
        raise FoundationV4ReplayError("relocated request payload identity drifted")
    return capsule, request, request_raw


def _resolve_import_roots(
    *,
    pack_root: Path,
    dependency_roots: Sequence[Path],
    forbidden_roots: Sequence[Path],
    injected_live_root: Path,
) -> dict[str, Any]:
    authority_sources = _lexical_absolute(
        pack_root / "foundation" / "authority_snapshot" / "sources"
    )
    authority_roots = (
        authority_sources / "xinao_discovery" / "src",
        authority_sources / "projects" / "dual-brain-coordination" / "src",
    )
    received = [
        _lexical_absolute(injected_live_root),
        *(_lexical_absolute(path) for path in forbidden_roots),
        *(_lexical_absolute(path) for path in dependency_roots),
        *(_lexical_absolute(Path(path)) for path in sys.path if path),
    ]
    blocked = (*forbidden_roots, injected_live_root)
    removed = [path for path in received if _is_under(path, blocked)]
    safe_existing = [path for path in received if not _is_under(path, blocked)]
    ordered: list[Path] = []
    for path in (*authority_roots, *dependency_roots, *safe_existing):
        lexical = _lexical_absolute(path)
        if lexical not in ordered and not _is_under(lexical, blocked):
            ordered.append(lexical)
    sys.path[:] = [str(path) for path in ordered]
    return {
        "authority_sources": str(authority_sources),
        "received_path_candidates": [str(path) for path in received],
        "removed_path_candidates": [str(path) for path in removed],
        "effective_path_candidates": [str(path) for path in ordered],
    }


def _xinao_module_origins(authority_sources: Path) -> list[str]:
    origins: set[str] = set()
    for name, module in sys.modules.items():
        if name != "xinao" and not name.startswith("xinao."):
            continue
        value = getattr(module, "__file__", None)
        if value is None:
            continue
        origin = _lexical_absolute(Path(value))
        if not _is_under(origin, (authority_sources,)):
            raise FoundationV4ReplayError(f"xinao module escaped authority: {origin}")
        origins.add(str(origin))
    if not origins:
        raise FoundationV4ReplayError("authority xinao modules were not imported")
    return sorted(origins)


def _authority_entry(authority_manifest: dict[str, Any], *, suffix: str) -> dict[str, Any]:
    entries = authority_manifest.get("entries")
    if not isinstance(entries, list):
        raise FoundationV4ReplayError("authority source inventory is absent")
    matches = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("relative_path"), str)
        and entry["relative_path"].endswith(suffix)
    ]
    if len(matches) != 1:
        raise FoundationV4ReplayError(f"authority source is not unique: {suffix}")
    return matches[0]


def _authority_identity(
    *, pack_root: Path, authority_manifest: dict[str, Any], suffix: str
) -> dict[str, str]:
    entry = _authority_entry(authority_manifest, suffix=suffix)
    relative = _safe_relative_path(entry.get("relative_path"), label="authority relative_path")
    return {
        "path": str(
            _lexical_absolute(
                pack_root / "foundation" / "authority_snapshot" / "sources" / relative
            )
        ),
        "sha256": str(entry["sha256"]),
    }


def _binding_identity(
    *, pack_root: Path, capsule: dict[str, Any], kind: str, name: str
) -> dict[str, str]:
    bindings = capsule.get("reference_bindings")
    if not isinstance(bindings, list):
        raise FoundationV4ReplayError("capsule reference bindings are absent")
    matches = [
        item
        for item in bindings
        if isinstance(item, dict) and item.get("kind") == kind and item.get("name") == name
    ]
    if len(matches) != 1:
        raise FoundationV4ReplayError(f"capsule binding is not unique: {kind}:{name}")
    item = matches[0]
    relative = _safe_relative_path(item.get("capsule_relative_path"), label="binding relative_path")
    return {
        "path": str(_lexical_absolute(pack_root / "foundation" / relative)),
        "sha256": str(item["sha256"]),
    }


def _bootstrap_authority(*, pack_root: Path, resolver: dict[str, Any]) -> dict[str, Any]:
    authority_root = _lexical_absolute(pack_root / "foundation" / "authority_snapshot")
    manifest_path = authority_root / "authority_manifest.json"
    registry_module = importlib.import_module("xinao.foundation.assertion_verifier_registry")
    manifest = registry_module.validate_authority_snapshot(manifest_path, require_live_match=False)
    registry_module._CANONICAL_PYTHON = _lexical_absolute(Path(sys.executable))
    if _lexical_absolute(registry_module.canonical_python_executable()) != (
        _lexical_absolute(Path(sys.executable))
    ):
        raise FoundationV4ReplayError("authority canonical Python override failed")

    runtime_path = authority_root / "runtime_buildinfo.json"
    runtime, _ = _read_json_object(runtime_path, label="runtime buildinfo")
    expected = runtime.get("runtimes", {}).get("xinao_assertion_runtime", {}).get("interpreter", {})
    executable = _lexical_absolute(Path(sys.executable))
    executable_raw = executable.read_bytes()
    expected_path = expected.get("executable_path") if isinstance(expected, dict) else None
    if (
        not isinstance(expected, dict)
        or not isinstance(expected_path, str)
        or os.path.normcase(os.fspath(_lexical_absolute(Path(expected_path))))
        != os.path.normcase(os.fspath(executable))
        or expected.get("executable_sha256") != _sha256(executable_raw)
        or expected.get("executable_size") != len(executable_raw)
    ):
        raise FoundationV4ReplayError("same-host assertion interpreter identity drifted")
    semantic_identity = {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "cache_tag": sys.implementation.cache_tag,
    }
    if any(expected.get(key) != value for key, value in semantic_identity.items()):
        raise FoundationV4ReplayError("same-host interpreter semantics drifted")
    authority_sources = Path(str(resolver["authority_sources"]))
    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "runtime_buildinfo_path": runtime_path,
        "registry_module": registry_module,
        "authority_sources": authority_sources,
        "runtime_identity": {
            "launcher": {
                "path": str(executable),
                "sha256": _sha256(executable_raw),
                "size_bytes": len(executable_raw),
            },
            "interpreter": semantic_identity,
            "base_executable_observation": _base_executable_identity(),
        },
    }


def _materialize_path_neutral_request(
    *,
    pack_root: Path,
    capsule: dict[str, Any],
    source_request: dict[str, Any],
    source_request_raw: bytes,
    destination: Path,
    recorder: _AuditRecorder,
    spec: _ReplayBlockSpec,
) -> dict[str, Any]:
    bindings = capsule.get("reference_bindings")
    if not isinstance(bindings, list):
        raise FoundationV4ReplayError("capsule reference bindings are absent")
    replacements: dict[str, str] = {}
    for item in bindings:
        if not isinstance(item, dict) or item.get("kind") not in {"artifact", "input"}:
            continue
        recorded = item.get("recorded_path")
        relative = item.get("capsule_relative_path")
        if not isinstance(recorded, str) or not isinstance(relative, str):
            raise FoundationV4ReplayError("capsule request binding is invalid")
        _safe_relative_path(relative, label="request binding relative_path")
        replacements[recorded] = relative
    replaced: set[str] = set()

    def relocate(value: object) -> object:
        if isinstance(value, dict):
            return {str(key): relocate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relocate(item) for item in value]
        if isinstance(value, str) and value in replacements:
            replaced.add(value)
            return replacements[value]
        return value

    relocated = relocate(source_request)
    if replaced != set(replacements):
        raise FoundationV4ReplayError("not every capsule request binding was relocated")
    if not isinstance(relocated, dict):
        raise FoundationV4ReplayError("relocated request is not an object")
    assertion_ids = relocated.get("assertion_ids")
    input_evidence = relocated.get("input_evidence")
    input_hashes = relocated.get("input_hashes")
    artifacts = relocated.get("artifacts")
    if (
        relocated.get("block_id") != spec.block_id
        or not isinstance(assertion_ids, list)
        or tuple(assertion_ids) != spec.assertion_ids
        or not isinstance(input_evidence, dict)
        or tuple(sorted(input_evidence)) != spec.input_names
        or not isinstance(input_hashes, dict)
        or tuple(sorted(input_hashes)) != spec.input_names
        or not isinstance(artifacts, dict)
        or tuple(sorted(artifacts)) != spec.artifact_names
    ):
        raise FoundationV4ReplayError(f"relocated request inventory is not exact: {spec.block_id}")
    binding_keys = {
        (str(item.get("kind")), str(item.get("name")))
        for item in bindings
        if isinstance(item, dict) and item.get("kind") in {"artifact", "input"}
    }
    expected_binding_keys = {
        *(("input", name) for name in spec.input_names),
        *(("artifact", name) for name in spec.artifact_names),
    }
    if binding_keys != expected_binding_keys:
        raise FoundationV4ReplayError(
            f"capsule reference binding inventory is not exact: {spec.block_id}"
        )
    canonical_module = importlib.import_module("xinao.canonical")
    for wrapper in artifacts.values():
        if not isinstance(wrapper, dict) or not isinstance(wrapper.get("staged_envelope"), dict):
            raise FoundationV4ReplayError("relocated artifact envelope is invalid")
        wrapper["staged_envelope_content_sha256"] = canonical_module.canonical_sha256(
            wrapper["staged_envelope"]
        )
    relocated_raw = canonical_module.canonical_dumps(relocated)
    relocated = json.loads(relocated_raw)
    for value in _iter_string_values(relocated):
        if os.path.isabs(value) or (len(value) > 2 and value[1] == ":" and value[2] in "\\/"):
            raise FoundationV4ReplayError(f"relocated request retained an absolute path: {value}")
    reference = recorder.write(destination, relocated_raw)
    return {
        "request": relocated,
        "source_request_sha256": _sha256(source_request_raw),
        "executed_request_sha256": _sha256(relocated_raw),
        "executed_request_path": reference["path"],
    }


def _iter_string_values(value: object):
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_string_values(item)
    elif isinstance(value, str):
        yield value


def _sys_flags() -> dict[str, int]:
    return {
        "isolated": int(sys.flags.isolated),
        "no_site": int(sys.flags.no_site),
        "dont_write_bytecode": int(sys.flags.dont_write_bytecode),
    }


def _proof_base(
    *,
    nonce: str,
    resolver: dict[str, Any],
    authority_sources: Path,
    source_request_sha256: str,
    executed_request_sha256: str,
) -> dict[str, Any]:
    return {
        "nonce": nonce,
        "pid": os.getpid(),
        "source_request_sha256": source_request_sha256,
        "executed_request_sha256": executed_request_sha256,
        "sys_flags": _sys_flags(),
        "python_dont_write_bytecode": os.environ.get("PYTHONDONTWRITEBYTECODE"),
        "entrypoint_argv_flags": ["-I", "-S", "-B"],
        "resolver": resolver,
        "sys_path": list(sys.path),
        "xinao_module_origins": _xinao_module_origins(authority_sources),
    }


def _nested_envelope(*, role: str, phase: str, payload: bytes, core: dict[str, Any]) -> bytes:
    envelope_core = {
        "schema_version": NESTED_ENVELOPE_SCHEMA,
        "role": role,
        "phase": phase,
        **core,
        "payload_encoding": "base64",
        "payload_sha256": _sha256(payload),
        "payload": base64.b64encode(payload).decode("ascii"),
    }
    return _canonical_bytes({**envelope_core, "content_sha256": _canonical_sha256(envelope_core)})


def _validate_nested_envelope(
    raw: bytes,
    *,
    role: str,
    phase: str,
    nonce: str,
    launcher_pid: int,
    launcher_owner_pid: int,
) -> tuple[dict[str, Any], bytes]:
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationV4ReplayError("nested child stdout is not JSON") from exc
    if not isinstance(envelope, dict) or _canonical_bytes(envelope) != raw:
        raise FoundationV4ReplayError("nested child stdout is not canonical JSON")
    content = dict(envelope)
    digest = content.pop("content_sha256", None)
    if digest != _canonical_sha256(content):
        raise FoundationV4ReplayError("nested child envelope content drifted")
    if (
        envelope.get("schema_version") != NESTED_ENVELOPE_SCHEMA
        or envelope.get("role") != role
        or envelope.get("phase") != phase
        or envelope.get("nonce") != nonce
        or envelope.get("launcher_pid") != launcher_pid
        or envelope.get("parent_pid") != launcher_pid
        or envelope.get("launcher_owner_pid") != launcher_owner_pid
        or envelope.get("interpreter_pid") != envelope.get("pid")
        or envelope.get("interpreter_pid") == launcher_pid
        or envelope.get("payload_encoding") != "base64"
    ):
        observed = {
            key: envelope.get(key)
            for key in (
                "schema_version",
                "role",
                "phase",
                "nonce",
                "pid",
                "interpreter_pid",
                "launcher_pid",
                "launcher_owner_pid",
                "parent_pid",
                "payload_encoding",
            )
        }
        raise FoundationV4ReplayError(
            "nested child envelope binding drifted: "
            f"observed={observed!r}, expected_role={role!r}, "
            f"expected_phase={phase!r}, expected_nonce={nonce!r}, "
            f"expected_launcher_pid={launcher_pid!r}, "
            f"expected_launcher_owner_pid={launcher_owner_pid!r}"
        )
    try:
        payload = base64.b64decode(envelope.get("payload", ""), validate=True)
    except (TypeError, ValueError) as exc:
        raise FoundationV4ReplayError("nested child payload is invalid") from exc
    if _sha256(payload) != envelope.get("payload_sha256"):
        raise FoundationV4ReplayError("nested child payload SHA drifted")
    return envelope, payload


def _nested_argv(*, entrypoint: Path, role: str, context: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(_lexical_absolute(Path(sys.executable))),
        "-X",
        "faulthandler",
        "-I",
        "-S",
        "-B",
        str(_lexical_absolute(entrypoint)),
        "--child-role",
        role,
        "--context-json",
        _canonical_bytes(context).decode("utf-8"),
    )


def _persist_nested_failure_capture(
    *,
    argv: Sequence[str],
    role: str,
    phase: str,
    returncode: int,
    stdout: bytes,
    stderr: bytes,
    launcher_process_pid: int,
    expected_guard_log_path: Path,
) -> tuple[Path, str]:
    if type(returncode) is not int or returncode == 0:
        raise FoundationV4ReplayError("nested failure capture requires a nonzero exit")
    if type(launcher_process_pid) is not int or launcher_process_pid <= 0:
        raise FoundationV4ReplayError("nested failure launcher PID is invalid")
    _validated_nested_failure_invocation(
        argv,
        expected_role=role,
        expected_phase=phase,
    )
    audit_root = _require_plain_path_chain(
        _lexical_absolute(expected_guard_log_path).parent,
        label="nested failure audit root",
    )
    unsigned_returncode = returncode & 0xFFFFFFFF
    attempt_path = audit_root / "nested-failure-attempt.json"
    if attempt_path.exists():
        raise FoundationV4ReplayError("nested failure attempt already exists")
    attempt_core = {
        "schema_version": NESTED_FAILURE_ATTEMPT_SCHEMA,
        "status": "CAPTURE_ATTEMPTED",
        "role": role,
        "phase": phase,
        "exact_argv_sha256": _canonical_sha256(list(argv)),
        "launcher_process_pid": launcher_process_pid,
        "returncode_signed": returncode,
        "returncode_uint32": unsigned_returncode,
        "returncode_hex": f"0x{unsigned_returncode:08X}",
    }
    attempt_path.write_bytes(
        _canonical_bytes({**attempt_core, "content_sha256": _canonical_sha256(attempt_core)})
    )
    parent = audit_root / "nested-failures"
    _require_plain_path_chain(parent, label="nested failure capture root")
    parent.mkdir(parents=True, exist_ok=True)
    _require_plain_path_chain(parent, label="nested failure capture root")
    capture_id = f"{role}-{phase}"
    stage = parent / f".{capture_id}.staging"
    final = parent / capture_id
    if stage.exists() or final.exists():
        raise FoundationV4ReplayError("nested failure capture identity already exists")
    stage.mkdir(parents=False, exist_ok=False)
    (stage / "stdout.bin").write_bytes(stdout)
    (stage / "stderr.bin").write_bytes(stderr)
    artifacts = [dict(row) for row in _failure_capture_inventory(stage)]
    guard_log = _lexical_absolute(expected_guard_log_path)
    guard_observation = _plain_file_observation(guard_log) if guard_log.is_file() else None
    core = {
        "schema_version": NESTED_FAILURE_CAPTURE_SCHEMA,
        "status": "FAILURE_CAPTURED",
        "role": role,
        "phase": phase,
        "exact_argv": list(argv),
        "exact_argv_sha256": _canonical_sha256(list(argv)),
        "launcher_process_pid": launcher_process_pid,
        "returncode_signed": returncode,
        "returncode_uint32": unsigned_returncode,
        "returncode_hex": f"0x{unsigned_returncode:08X}",
        "failure_class": (
            "WINDOWS_ACCESS_VIOLATION"
            if unsigned_returncode == 0xC0000005
            else "PROCESS_EXIT_NONZERO"
        ),
        "faulthandler_requested": list(argv[1:3]) == ["-X", "faulthandler"],
        "guard_log_path": str(guard_log),
        "guard_log_exists": guard_observation is not None,
        "guard_log_size_bytes": (
            guard_observation["size_bytes"] if guard_observation is not None else None
        ),
        "guard_log_sha256": (
            guard_observation["sha256"] if guard_observation is not None else None
        ),
        "artifact_count": len(artifacts),
        "artifact_inventory": artifacts,
        "artifact_inventory_sha256": _canonical_sha256(artifacts),
        "retry_count": 0,
    }
    receipt = {**core, "content_sha256": _canonical_sha256(core)}
    receipt_raw = _canonical_bytes(receipt)
    (stage / "failure_capture.json").write_bytes(receipt_raw)
    if (
        stage.parent != final.parent
        or stage.parent != parent
        or os.stat(stage).st_dev != os.stat(parent).st_dev
    ):
        raise FoundationV4ReplayError("nested failure staging is not an atomic sibling")
    stage.rename(final)
    _require_plain_path_chain(final, label="nested failure committed capture")
    observed, observed_raw = _read_json_object(
        final / "failure_capture.json", label="nested failure capture receipt"
    )
    if observed != receipt or observed_raw != receipt_raw:
        raise FoundationV4ReplayError("nested failure capture receipt drifted after commit")
    for row in artifacts:
        _verify_file_identity(
            final / Path(*str(row["relative_path"]).split("/")),
            expected_size=row["size_bytes"],
            expected_sha256=row["sha256"],
            drift_label="nested failure capture artifact drift",
        )
    index_core = {
        "schema_version": NESTED_FAILURE_INDEX_SCHEMA,
        "status": "FAILURE_CAPTURED",
        "role": role,
        "phase": phase,
        "exact_argv_sha256": _canonical_sha256(list(argv)),
        "returncode_uint32": unsigned_returncode,
        "capture_receipt_relative_path": (f"nested-failures/{capture_id}/failure_capture.json"),
        "capture_receipt_sha256": _sha256(receipt_raw),
    }
    index_path = audit_root / "nested-failure-index.json"
    if index_path.exists():
        raise FoundationV4ReplayError("nested failure index already exists")
    index_path.write_bytes(
        _canonical_bytes({**index_core, "content_sha256": _canonical_sha256(index_core)})
    )
    return final, _sha256(receipt_raw)


def _run_nested_child(
    *,
    argv: tuple[str, ...],
    expected_role: str,
    expected_phase: str,
    nonce: str,
    expected_guard_log_path: Path,
    expected_guard_roots: Sequence[str],
) -> tuple[dict[str, Any], bytes, int]:
    try:
        entrypoint_index = argv.index("-B") + 1
    except ValueError as exc:
        raise FoundationV4ReplayError("nested child argv lacks the isolation prefix") from exc
    if entrypoint_index >= len(argv):
        raise FoundationV4ReplayError("nested child argv lacks the sealed entrypoint")
    process = subprocess.Popen(
        argv,
        shell=False,
        cwd=str(Path(argv[entrypoint_index]).parent),
        env=_clean_child_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    stdout, stderr = process.communicate(timeout=900)
    if process.returncode != 0:
        capture_path: Path | None = None
        capture_sha256: str | None = None
        capture_error: str | None = None
        try:
            capture_path, capture_sha256 = _persist_nested_failure_capture(
                argv=argv,
                role=expected_role,
                phase=expected_phase,
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
                launcher_process_pid=process.pid,
                expected_guard_log_path=expected_guard_log_path,
            )
        except (OSError, FoundationV4ReplayError) as exc:
            capture_error = str(exc)
        detail = (stderr or stdout).decode("utf-8", errors="replace")[-4000:]
        capture_detail = (
            f" failure_capture={capture_path} sha256={capture_sha256}"
            if capture_path is not None
            else f" failure_capture_error={capture_error}"
        )
        raise FoundationV4ReplayError(
            f"nested {expected_role} {expected_phase} failed with "
            f"exit {process.returncode}: {detail}{capture_detail}"
        )
    if stderr:
        raise FoundationV4ReplayError("nested child wrote unexpected stderr")
    envelope, payload = _validate_nested_envelope(
        stdout,
        role=expected_role,
        phase=expected_phase,
        nonce=nonce,
        launcher_pid=process.pid,
        launcher_owner_pid=os.getpid(),
    )
    expected_argv_sha256 = _canonical_sha256(list(argv))
    if envelope.get("argv_sha256") != expected_argv_sha256:
        raise FoundationV4ReplayError("nested child argv binding drifted")
    guard_role = f"{expected_role}:{expected_phase}"
    expected_root_set_sha256 = _guard_root_set_sha256(expected_guard_roots)
    declaration = envelope.get("forbidden_mutation_guard_declaration")
    if not isinstance(declaration, dict) or declaration != {
        "guard_schema_version": FORBIDDEN_GUARD_SCHEMA,
        "root_set_sha256": expected_root_set_sha256,
        "event_log_path": str(_lexical_absolute(expected_guard_log_path)),
        "nonce": nonce,
        "role": guard_role,
        "interpreter_pid": envelope["interpreter_pid"],
    }:
        raise FoundationV4ReplayError("nested forbidden guard declaration drifted")
    guard_proof = _verify_forbidden_mutation_log(
        event_log_path=expected_guard_log_path,
        expected_nonce=nonce,
        expected_role=guard_role,
        expected_interpreter_pid=int(envelope["interpreter_pid"]),
        expected_roots=expected_guard_roots,
        require_success=True,
    )
    augmented_core = dict(envelope)
    augmented_core.pop("content_sha256")
    augmented_core["forbidden_mutation_guard"] = guard_proof
    envelope = {
        **augmented_core,
        "content_sha256": _canonical_sha256(augmented_core),
    }
    return envelope, payload, process.pid


class _PhaseSubprocessProxy:
    def __init__(
        self,
        *,
        context: dict[str, Any],
        recorder: _AuditRecorder,
        proof_sink: dict[str, dict[str, Any]],
    ) -> None:
        self.context = context
        self.recorder = recorder
        self.proof_sink = proof_sink
        self.content_outputs: dict[str, dict[str, str]] = {}

    def run(self, args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        argv = tuple(str(item) for item in args)
        if (
            len(argv) < 9
            or argv[1:5] != ("-X", "faulthandler", "-I", "-m")
            or argv[5] != "xinao.foundation.assertion_verifiers._f1_phase_worker"
            or argv[6] not in {"seed", "final", "reordered"}
        ):
            raise FoundationV4ReplayError("authority phase argv is not recognized")
        if (
            kwargs.get("capture_output") is not True
            or kwargs.get("check") is not False
            or kwargs.get("encoding") != "utf-8"
        ):
            raise FoundationV4ReplayError("authority phase subprocess contract drifted")
        phase = argv[6]
        if phase in self.proof_sink:
            raise FoundationV4ReplayError(f"authority phase repeated: {phase}")
        catalog = _lexical_absolute(Path(argv[7]))
        dataset = _lexical_absolute(Path(argv[8]))
        compatibility_output = _lexical_absolute(Path(argv[-1]))
        run_root = Path(str(self.context["run_root"]))
        phase_output = _lexical_absolute(run_root / "phases" / f"{phase}.json")
        content_inputs: dict[str, dict[str, str]] = {}
        phase_inputs: list[str] = []
        if phase == "final":
            seed = self.content_outputs.get("seed")
            if seed is None:
                raise FoundationV4ReplayError("final phase has no sealed seed input")
            content_inputs = {"seed": seed}
            phase_inputs = [seed["path"]]
        elif phase == "reordered":
            final = self.content_outputs.get("final")
            if final is None:
                raise FoundationV4ReplayError("reordered phase has no sealed final input")
            content_inputs = {"final": final}
            phase_inputs = [final["path"]]
        child_context = {
            **self.context,
            "role": "phase",
            "phase": phase,
            "catalog_path": str(catalog),
            "dataset_path": str(dataset),
            "phase_inputs": phase_inputs,
            "phase_output": str(phase_output),
            "compatibility_output": str(compatibility_output),
        }
        nested_argv = _nested_argv(
            entrypoint=Path(str(self.context["entrypoint_path"])),
            role="phase",
            context=child_context,
        )
        envelope, payload, observed_pid = _run_nested_child(
            argv=nested_argv,
            expected_role="phase",
            expected_phase=phase,
            nonce=str(self.context["nonce"]),
            expected_guard_log_path=_lexical_absolute(
                run_root / "audit" / f"forbidden-phase-{phase}.jsonl"
            ),
            expected_guard_roots=_guard_root_set(
                pack_root=Path(str(self.context["pack_root"])),
                forbidden_roots=tuple(
                    Path(str(value)) for value in self.context["forbidden_roots"]
                ),
                injected_live_root=Path(str(self.context["injected_live_root"])),
            ),
        )
        if payload:
            raise FoundationV4ReplayError("phase child emitted an unexpected payload")
        content_output = envelope.get("phase_output")
        if not isinstance(content_output, dict):
            raise FoundationV4ReplayError("phase child output identity is absent")
        self.content_outputs[phase] = {
            "path": str(content_output["path"]),
            "sha256": str(content_output["sha256"]),
        }
        envelope_ref = self.recorder.write(
            run_root / "envelopes" / f"phase-{phase}.json",
            _canonical_bytes(envelope),
        )
        proof = {
            "nonce": envelope["nonce"],
            "pid": envelope["pid"],
            "interpreter_pid": envelope["interpreter_pid"],
            "launcher_pid": envelope["launcher_pid"],
            "launcher_owner_pid": envelope["launcher_owner_pid"],
            "observed_pid": observed_pid,
            "env_pid": envelope["env_pid"],
            "parent_pid": envelope["parent_pid"],
            "source_request_sha256": envelope["source_request_sha256"],
            "executed_request_sha256": envelope["executed_request_sha256"],
            "sys_flags": envelope["sys_flags"],
            "python_dont_write_bytecode": envelope["python_dont_write_bytecode"],
            "entrypoint_argv_flags": envelope["entrypoint_argv_flags"],
            "runtime_identity": envelope["runtime_identity"],
            "resolver": envelope["resolver"],
            "sys_path": envelope["sys_path"],
            "xinao_module_origins": envelope["xinao_module_origins"],
            "audit_log_path": envelope["audit_log_path"],
            "content_output": content_output,
            "content_inputs": content_inputs,
            "ascii_children": envelope["ascii_children"],
            "popen_argv_sha256": envelope["argv_sha256"],
            "stdout_envelope": envelope_ref,
            **{key: envelope["forbidden_mutation_guard"][key] for key in _GUARD_PROOF_FIELDS},
        }
        self.proof_sink[phase] = proof
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class _AsciiSubprocessProxy:
    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(
        self,
        *,
        context: dict[str, Any],
        recorder: _AuditRecorder,
        children: list[dict[str, Any]],
    ) -> None:
        self.context = context
        self.recorder = recorder
        self.children = children

    def run(self, args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        argv = tuple(str(item) for item in args)
        projection = kwargs.get("input")
        if (
            len(argv) != 6
            or argv[1:5] != ("-X", "faulthandler", "-I", "-S")
            or not argv[5].endswith("f1_pure_ascii_stream_worker.py")
            or not isinstance(projection, bytes)
            or kwargs.get("capture_output") is not True
            or kwargs.get("check") is not False
        ):
            raise FoundationV4ReplayError("authority ASCII subprocess contract drifted")
        if self.children:
            raise FoundationV4ReplayError("phase launched more than one ASCII child")
        run_root = Path(str(self.context["run_root"]))
        phase = str(self.context["phase"])
        projection_ref = self.recorder.write(
            run_root / "ascii" / f"{phase}-projection.json", projection
        )
        result_path = _lexical_absolute(run_root / "ascii" / f"{phase}-result.json")
        child_context = {
            **self.context,
            "role": "ascii",
            "projection_path": projection_ref["path"],
            "projection_sha256": projection_ref["sha256"],
            "result_path": str(result_path),
        }
        nested_argv = _nested_argv(
            entrypoint=Path(str(self.context["entrypoint_path"])),
            role="ascii",
            context=child_context,
        )
        envelope, payload, observed_pid = _run_nested_child(
            argv=nested_argv,
            expected_role="ascii",
            expected_phase=phase,
            nonce=str(self.context["nonce"]),
            expected_guard_log_path=_lexical_absolute(
                run_root / "audit" / f"forbidden-ascii-{phase}.jsonl"
            ),
            expected_guard_roots=_guard_root_set(
                pack_root=Path(str(self.context["pack_root"])),
                forbidden_roots=tuple(
                    Path(str(value)) for value in self.context["forbidden_roots"]
                ),
                injected_live_root=Path(str(self.context["injected_live_root"])),
            ),
        )
        if _sha256(payload) != envelope.get("result_sha256"):
            raise FoundationV4ReplayError("ASCII child result SHA drifted")
        envelope_ref = self.recorder.write(
            run_root / "envelopes" / f"ascii-{phase}.json",
            _canonical_bytes(envelope),
        )
        child = {
            "nonce": envelope["nonce"],
            "pid": envelope["pid"],
            "interpreter_pid": envelope["interpreter_pid"],
            "launcher_pid": envelope["launcher_pid"],
            "launcher_owner_pid": envelope["launcher_owner_pid"],
            "observed_pid": observed_pid,
            "env_pid": envelope["env_pid"],
            "parent_pid": envelope["parent_pid"],
            "worker": envelope["worker"],
            "projection": envelope["projection"],
            "result": envelope["result"],
            "audit_log_path": envelope["audit_log_path"],
            "popen_argv_sha256": envelope["argv_sha256"],
            "stdout_envelope": envelope_ref,
            **{key: envelope["forbidden_mutation_guard"][key] for key in _GUARD_PROOF_FIELDS},
        }
        self.children.append(child)
        return subprocess.CompletedProcess(argv, 0, stdout=payload, stderr=b"")


def _normalize_bundle(
    *,
    raw_bundle: bytes,
    entrypoint_identity: dict[str, str],
    source_request_sha256: str,
    executed_request_sha256: str,
    spec: _ReplayBlockSpec,
    extension_fields: dict[str, Any] | None = None,
    require_physical_entrypoint: bool = True,
) -> bytes:
    canonical_module = importlib.import_module("xinao.canonical")
    try:
        raw = json.loads(raw_bundle.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationV4ReplayError("raw authority bundle is not JSON") from exc
    if not isinstance(raw, dict) or canonical_module.canonical_dumps(raw) != raw_bundle:
        raise FoundationV4ReplayError("raw authority bundle is not canonical")
    raw_core = dict(raw)
    raw_content_sha256 = raw_core.pop("content_sha256", None)
    if canonical_module.canonical_sha256(raw_core) != raw_content_sha256:
        raise FoundationV4ReplayError("raw authority bundle content drifted")
    raw_entrypoint = raw.get("entrypoint")
    actuals = raw.get("assertion_actuals")
    actual_hashes = raw.get("assertion_actual_content_sha256")
    if (
        raw.get("schema_version") != "xinao.assertion_actual_bundle.v2"
        or raw.get("block_id") != spec.block_id
        or raw.get("request_sha256") != executed_request_sha256
        or not isinstance(raw_entrypoint, dict)
        or not isinstance(actuals, dict)
        or not isinstance(actual_hashes, dict)
        or tuple(sorted(actuals)) != spec.assertion_ids
        or tuple(sorted(actual_hashes)) != spec.assertion_ids
    ):
        raise FoundationV4ReplayError("raw authority bundle identity drifted")
    entrypoint_path_matches = os.path.normcase(
        os.fspath(_lexical_absolute(Path(str(raw_entrypoint.get("source_path")))))
    ) == os.path.normcase(os.fspath(_lexical_absolute(Path(entrypoint_identity["path"]))))
    if raw_entrypoint.get("source_sha256") != entrypoint_identity["sha256"] or (
        require_physical_entrypoint and not entrypoint_path_matches
    ):
        raise FoundationV4ReplayError("raw authority entrypoint escaped its seal")
    for assertion_id in spec.assertion_ids:
        expected = canonical_module.canonical_sha256(
            {"assertion_id": assertion_id, "actual": actuals[assertion_id]}
        )
        if actual_hashes.get(assertion_id) != expected:
            raise FoundationV4ReplayError(f"raw assertion actual hash drifted: {assertion_id}")
    normalized_extensions: dict[str, Any] = {}
    if spec.block_id == "F1_settlement_world":
        if not isinstance(extension_fields, dict) or set(extension_fields) != {"phase_lineage"}:
            raise FoundationV4ReplayError("normalized bundle extension inventory drifted")
        lineage = extension_fields.get("phase_lineage")
        lineage_fields = {
            "seed_output_sha256",
            "final_input_seed_sha256",
            "final_output_sha256",
            "reordered_input_final_sha256",
            "reordered_output_sha256",
        }
        if (
            not isinstance(lineage, dict)
            or set(lineage) != lineage_fields
            or any(not _is_sha256(lineage.get(name)) for name in lineage_fields)
            or lineage["seed_output_sha256"] != lineage["final_input_seed_sha256"]
            or lineage["final_output_sha256"] != lineage["reordered_input_final_sha256"]
        ):
            raise FoundationV4ReplayError("normalized bundle extension lineage drifted")
        normalized_extensions = {"phase_lineage": dict(lineage)}
    elif extension_fields is not None:
        raise FoundationV4ReplayError("normalized bundle extension is forbidden")
    normalized_core = {
        "schema_version": REPLAY_BUNDLE_SCHEMA,
        "protocol_version": raw["protocol_version"],
        "block_id": spec.block_id,
        "source_request_sha256": source_request_sha256,
        "relocated_request_sha256": executed_request_sha256,
        "request_sha256": executed_request_sha256,
        "entrypoint": {
            "module_name": raw_entrypoint["module_name"],
            "authority_relative_path": spec.authority_entrypoint_relative_path,
            "source_sha256": raw_entrypoint["source_sha256"],
            "checker_id": raw_entrypoint["checker_id"],
            "checker_version": raw_entrypoint["checker_version"],
        },
        "assertion_actuals": {key: actuals[key] for key in sorted(actuals)},
        "assertion_actual_content_sha256": {
            key: actual_hashes[key] for key in sorted(actual_hashes)
        },
        **normalized_extensions,
    }
    return canonical_module.canonical_dumps(
        {
            **normalized_core,
            "content_sha256": canonical_module.canonical_sha256(normalized_core),
        }
    )


def _normalize_f1_bundle(
    *,
    raw_bundle: bytes,
    entrypoint_identity: dict[str, str],
    source_request_sha256: str,
    executed_request_sha256: str,
    assertion_ids: Sequence[str],
    phase_lineage: dict[str, str],
) -> bytes:
    spec = _replay_block_spec("F1_settlement_world")
    if tuple(assertion_ids) != spec.assertion_ids:
        raise FoundationV4ReplayError("F1 assertion inventory drifted")
    return _normalize_bundle(
        raw_bundle=raw_bundle,
        entrypoint_identity=entrypoint_identity,
        source_request_sha256=source_request_sha256,
        executed_request_sha256=executed_request_sha256,
        spec=spec,
        extension_fields={"phase_lineage": phase_lineage},
    )


def _execute_outer_role(args: argparse.Namespace) -> dict[str, Any]:
    spec = _replay_block_spec(args.block_id)
    if spec.block_id == "F4_research_factory":
        raise FoundationV4ReplayError("F4 execution belongs to the sealed OCI carrier")
    pack_root = _lexical_absolute(Path(args.pack_root))
    output_root = _lexical_absolute(Path(args.output_root))
    dependency_roots = _parse_json_string_list(args.dependency_roots_json, label="dependency roots")
    forbidden_roots = _parse_json_string_list(args.forbidden_roots_json, label="forbidden roots")
    injected_live_root = _lexical_absolute(Path(args.injected_live_root))
    guard_roots = _guard_root_set(
        pack_root=pack_root,
        forbidden_roots=forbidden_roots,
        injected_live_root=injected_live_root,
    )
    run_root = _lexical_absolute(output_root / f"run-{args.run_index}")
    guard_log_path = _lexical_absolute(run_root / "audit" / "forbidden-outer.jsonl")
    _validate_guard_output_locations(
        roots=guard_roots,
        locations=(
            ("output root", output_root),
            ("run root", run_root),
            ("guard event log", guard_log_path),
        ),
    )
    run_root.mkdir(parents=True, exist_ok=False)
    _write_outer_start_record(args=args, run_root=run_root)
    guard = _ForbiddenMutationGuard(
        pack_root=pack_root,
        forbidden_roots=forbidden_roots,
        injected_live_root=injected_live_root,
        event_log_path=guard_log_path,
        nonce=args.nonce,
        role="outer",
    )
    guard.install()
    capsule, source_request, source_request_raw = _execution_preflight(
        pack_root=pack_root, spec=spec
    )
    pack_inventory_before_sha256 = _tree_inventory_sha256(pack_root)
    seal = _entrypoint_seal(
        pack_root=pack_root,
        sealed_entrypoint_path=_lexical_absolute(Path(__file__)),
        sealed_entrypoint_manifest_path=Path(args.entrypoint_manifest),
    )
    recorder = _AuditRecorder(path=run_root / "audit" / "outer.jsonl", nonce=args.nonce)
    resolver = _resolve_import_roots(
        pack_root=pack_root,
        dependency_roots=dependency_roots,
        forbidden_roots=forbidden_roots,
        injected_live_root=injected_live_root,
    )
    authority = _bootstrap_authority(pack_root=pack_root, resolver=resolver)
    request_materialization = _materialize_path_neutral_request(
        pack_root=pack_root,
        capsule=capsule,
        source_request=source_request,
        source_request_raw=source_request_raw,
        destination=run_root / "executed_request.json",
        recorder=recorder,
        spec=spec,
    )
    recorder.read(
        Path(request_materialization["executed_request_path"]),
        expected_sha256=request_materialization["executed_request_sha256"],
    )
    authority_manifest = authority["manifest"]
    required_authority = tuple(
        _authority_identity(
            pack_root=pack_root,
            authority_manifest=authority_manifest,
            suffix=suffix,
        )
        for suffix in (
            "xinao/foundation/assertion_bundle_runner.py",
            "xinao/foundation/assertion_verifier_registry.py",
            "xinao/foundation/assertion_verifiers/common.py",
            spec.authority_entrypoint_relative_path,
        )
    )
    required_materials = tuple(
        _binding_identity(
            pack_root=pack_root,
            capsule=capsule,
            kind=str(item["kind"]),
            name=str(item["name"]),
        )
        for item in capsule["reference_bindings"]
        if isinstance(item, dict) and item.get("kind") in {"artifact", "input"}
    )
    for identity in (*required_authority, *required_materials):
        recorder.read(Path(identity["path"]), expected_sha256=identity["sha256"])

    registry_module = authority["registry_module"]
    bundle_runner = importlib.import_module("xinao.foundation.assertion_bundle_runner")
    phase_proofs: dict[str, dict[str, Any]] = {}
    phase_proxy: _PhaseSubprocessProxy | None = None
    if spec.actuals_mode == "F1_NESTED":
        common_module = importlib.import_module("xinao.foundation.assertion_verifiers.common")
        child_context = {
            "entrypoint_path": seal["path"],
            "entrypoint_manifest_path": seal["manifest_path"],
            "entrypoint_sha256": seal["sha256"],
            "pack_root": str(pack_root),
            "output_root": str(output_root),
            "run_root": str(run_root),
            "nonce": args.nonce,
            "run_index": args.run_index,
            "dependency_roots": [str(path) for path in dependency_roots],
            "forbidden_roots": [str(path) for path in forbidden_roots],
            "injected_live_root": str(injected_live_root),
            "source_request_sha256": request_materialization["source_request_sha256"],
            "executed_request_path": request_materialization["executed_request_path"],
            "executed_request_sha256": request_materialization["executed_request_sha256"],
        }
        phase_proxy = _PhaseSubprocessProxy(
            context=child_context, recorder=recorder, proof_sink=phase_proofs
        )
        common_module.subprocess = phase_proxy
    registry_module.load_canonical_actuals_callable(spec.block_id)
    previous_cwd = Path.cwd()
    try:
        os.chdir(pack_root / "foundation")
        raw_bundle = bundle_runner.build_bundle_bytes_v2(
            request=request_materialization["request"],
            block_id=spec.block_id,
        )
    finally:
        os.chdir(previous_cwd)
    if not isinstance(raw_bundle, bytes):
        raise FoundationV4ReplayError("assertion bundle runner returned non-bytes")
    raw_bundle_name = (
        "f1-bundle.v2.json"
        if spec.block_id == "F1_settlement_world"
        else f"{spec.block_id}-bundle.v2.json"
    )
    raw_bundle_ref = recorder.write(run_root / "raw" / raw_bundle_name, raw_bundle)
    phase_lineage: dict[str, str] | None = None
    if phase_proxy is not None:
        seed_output = phase_proxy.content_outputs.get("seed")
        final_output = phase_proxy.content_outputs.get("final")
        reordered_output = phase_proxy.content_outputs.get("reordered")
        if seed_output is None or final_output is None or reordered_output is None:
            raise FoundationV4ReplayError("F1 phase lineage is incomplete")
        phase_lineage = {
            "seed_output_sha256": seed_output["sha256"],
            "final_input_seed_sha256": seed_output["sha256"],
            "final_output_sha256": final_output["sha256"],
            "reordered_input_final_sha256": final_output["sha256"],
            "reordered_output_sha256": reordered_output["sha256"],
        }
    assertion_ids = request_materialization["request"].get("assertion_ids")
    if not isinstance(assertion_ids, list) or not all(
        isinstance(value, str) and value for value in assertion_ids
    ):
        raise FoundationV4ReplayError("executed request assertion IDs are invalid")
    if tuple(assertion_ids) != spec.assertion_ids:
        raise FoundationV4ReplayError("executed request assertion inventory drifted")
    normalized_bundle = _normalize_bundle(
        raw_bundle=raw_bundle,
        entrypoint_identity=required_authority[-1],
        source_request_sha256=request_materialization["source_request_sha256"],
        executed_request_sha256=request_materialization["executed_request_sha256"],
        spec=spec,
        extension_fields=(
            {"phase_lineage": phase_lineage}
            if spec.include_phase_lineage and phase_lineage is not None
            else None
        ),
    )
    bundle_name = (
        "f1-replay-bundle.json"
        if spec.block_id == "F1_settlement_world"
        else f"{spec.block_id}-replay-bundle.json"
    )
    bundle_ref = recorder.write(run_root / bundle_name, normalized_bundle)
    outer_proof_base = _proof_base(
        nonce=args.nonce,
        resolver=resolver,
        authority_sources=authority["authority_sources"],
        source_request_sha256=request_materialization["source_request_sha256"],
        executed_request_sha256=request_materialization["executed_request_sha256"],
    )
    outer_interpreter_pid = os.getpid()
    outer_launcher_pid = os.getppid()
    if outer_interpreter_pid == outer_launcher_pid:
        raise FoundationV4ReplayError("outer redirector PID chain is absent")
    outer_proof = {
        **outer_proof_base,
        "interpreter_pid": outer_interpreter_pid,
        "launcher_pid": outer_launcher_pid,
        "launcher_owner_pid": _launcher_owner_pid(),
        "env_pid": outer_interpreter_pid,
        "parent_pid": outer_launcher_pid,
        "runtime_identity": authority["runtime_identity"],
        "audit_log_path": str(recorder.path),
        "required_source_touches": [
            *required_authority,
            {
                "path": request_materialization["executed_request_path"],
                "sha256": request_materialization["executed_request_sha256"],
            },
            *required_materials,
        ],
        "raw_bundle": raw_bundle_ref,
        "forbidden_mutation_guard_declaration": guard.declaration(),
    }
    ordered_phase_proofs = {"outer": outer_proof}
    if spec.actuals_mode == "F1_NESTED":
        ordered_phase_proofs.update(
            {
                "seed": phase_proofs["seed"],
                "final": phase_proofs["final"],
                "reordered": phase_proofs["reordered"],
            }
        )
    pack_inventory_after_sha256 = _tree_inventory_sha256(pack_root)
    if pack_inventory_after_sha256 != pack_inventory_before_sha256:
        raise FoundationV4ReplayError("sealed pack inventory changed during replay")
    run_core = {
        "schema_version": RUN_RECEIPT_SCHEMA,
        "status": "VERIFIED",
        "role": "outer",
        "block_id": spec.block_id,
        "nonce": args.nonce,
        "run_index": args.run_index,
        "outer_pid": outer_interpreter_pid,
        "outer_launcher_pid": outer_launcher_pid,
        "launcher_owner_pid": _launcher_owner_pid(),
        "parent_pid": outer_launcher_pid,
        "outer_entrypoint_path": seal["path"],
        "outer_entrypoint_sha256": seal["sha256"],
        "source_request_sha256": request_materialization["source_request_sha256"],
        "executed_request_path": request_materialization["executed_request_path"],
        "executed_request_sha256": request_materialization["executed_request_sha256"],
        "bundle_path": bundle_ref["path"],
        "bundle_sha256": bundle_ref["sha256"],
        "raw_bundle_path": raw_bundle_ref["path"],
        "raw_bundle_sha256": raw_bundle_ref["sha256"],
        "assertion_count": len(assertion_ids),
        "assertion_ids": assertion_ids,
        "phase_order": list(spec.phase_order),
        "phase_proofs": ordered_phase_proofs,
        "pack_inventory_before_sha256": pack_inventory_before_sha256,
        "pack_inventory_after_sha256": pack_inventory_after_sha256,
        **(
            {"phase_lineage": phase_lineage}
            if spec.include_phase_lineage and phase_lineage is not None
            else {}
        ),
    }
    return {**run_core, "content_sha256": _canonical_sha256(run_core)}


def _execute_nested_placeholder(role: str, context: dict[str, Any]) -> dict[str, Any]:
    if role == "phase":
        return _execute_phase_role(context)
    if role == "ascii":
        return _execute_ascii_role(context)
    raise FoundationV4ReplayError(f"unknown sealed child role: {role}")


def _full_child_argv_sha256() -> str:
    return _canonical_sha256(
        [
            str(_lexical_absolute(Path(sys.executable))),
            "-X",
            "faulthandler",
            "-I",
            "-S",
            "-B",
            *sys.argv,
        ]
    )


def _launcher_owner_pid() -> int:
    raw = os.environ.get("XINAO_REPLAY_LAUNCHER_OWNER_PID")
    try:
        value = int(raw or "")
    except ValueError as exc:
        raise FoundationV4ReplayError("launcher owner PID is absent") from exc
    if value <= 0:
        raise FoundationV4ReplayError("launcher owner PID is invalid")
    return value


def _base_executable_identity() -> dict[str, Any]:
    path = _lexical_absolute(Path(str(getattr(sys, "_base_executable", sys.executable))))
    raw = path.read_bytes()
    return {"path": str(path), "sha256": _sha256(raw), "size_bytes": len(raw)}


def _nested_context_paths(
    context: dict[str, Any],
) -> tuple[Path, Path, tuple[Path, ...], tuple[Path, ...], Path]:
    pack_root = _lexical_absolute(Path(str(context["pack_root"])))
    run_root = _lexical_absolute(Path(str(context["run_root"])))
    dependency_roots = tuple(
        _lexical_absolute(Path(str(value))) for value in context["dependency_roots"]
    )
    forbidden_roots = tuple(
        _lexical_absolute(Path(str(value))) for value in context["forbidden_roots"]
    )
    injected_live_root = _lexical_absolute(Path(str(context["injected_live_root"])))
    return (
        pack_root,
        run_root,
        dependency_roots,
        forbidden_roots,
        injected_live_root,
    )


def _execute_phase_role(context: dict[str, Any]) -> dict[str, Any]:
    (
        pack_root,
        run_root,
        dependency_roots,
        forbidden_roots,
        injected_live_root,
    ) = _nested_context_paths(context)
    phase = str(context["phase"])
    if phase not in {"seed", "final", "reordered"}:
        raise FoundationV4ReplayError(f"unknown F1 phase: {phase}")
    expected_guard_log_path = _lexical_absolute(
        run_root / "audit" / f"forbidden-phase-{phase}.jsonl"
    )
    guard = _ForbiddenMutationGuard(
        pack_root=pack_root,
        forbidden_roots=forbidden_roots,
        injected_live_root=injected_live_root,
        event_log_path=expected_guard_log_path,
        nonce=str(context["nonce"]),
        role=f"phase:{phase}",
    )
    guard.install()
    seal = _entrypoint_seal(
        pack_root=pack_root,
        sealed_entrypoint_path=_lexical_absolute(Path(__file__)),
        sealed_entrypoint_manifest_path=Path(str(context["entrypoint_manifest_path"])),
    )
    if seal["sha256"] != context["entrypoint_sha256"]:
        raise FoundationV4ReplayError("phase entrypoint identity drifted")
    recorder = _AuditRecorder(
        path=run_root / "audit" / f"{phase}.jsonl", nonce=str(context["nonce"])
    )
    resolver = _resolve_import_roots(
        pack_root=pack_root,
        dependency_roots=dependency_roots,
        forbidden_roots=forbidden_roots,
        injected_live_root=injected_live_root,
    )
    authority = _bootstrap_authority(pack_root=pack_root, resolver=resolver)
    authority_manifest = authority["manifest"]
    required_authority = tuple(
        _authority_identity(
            pack_root=pack_root,
            authority_manifest=authority_manifest,
            suffix=suffix,
        )
        for suffix in (
            "xinao/foundation/assertion_verifiers/_f1_phase_worker.py",
            "xinao/foundation/world_compile.py",
        )
    )
    executed_request = {
        "path": str(_lexical_absolute(Path(str(context["executed_request_path"])))),
        "sha256": str(context["executed_request_sha256"]),
    }
    catalog = {
        "path": str(_lexical_absolute(Path(str(context["catalog_path"])))),
        "sha256": _sha256(_lexical_absolute(Path(str(context["catalog_path"]))).read_bytes()),
    }
    dataset = {
        "path": str(_lexical_absolute(Path(str(context["dataset_path"])))),
        "sha256": _sha256(_lexical_absolute(Path(str(context["dataset_path"]))).read_bytes()),
    }
    for identity in (*required_authority, executed_request, catalog, dataset):
        recorder.read(Path(identity["path"]), expected_sha256=identity["sha256"])
    phase_inputs = [_lexical_absolute(Path(str(value))) for value in context["phase_inputs"]]
    for path in phase_inputs:
        recorder.read(path)

    phase_module = importlib.import_module("xinao.foundation.assertion_verifiers._f1_phase_worker")
    world_module = importlib.import_module("xinao.foundation.world_compile")
    ascii_children: list[dict[str, Any]] = []
    ascii_proxy = _AsciiSubprocessProxy(context=context, recorder=recorder, children=ascii_children)
    world_module.subprocess = ascii_proxy
    phase_output_path = _lexical_absolute(Path(str(context["phase_output"])))
    phase_output_path.parent.mkdir(parents=True, exist_ok=True)
    phase_module._dispatch(
        [
            phase,
            catalog["path"],
            dataset["path"],
            *(str(path) for path in phase_inputs),
            str(phase_output_path),
        ]
    )
    if len(ascii_children) != 1:
        raise FoundationV4ReplayError(f"phase {phase} did not launch exactly one ASCII child")
    phase_output = recorder.attest_write(phase_output_path)
    output_raw = phase_output_path.read_bytes()
    compatibility_output = _lexical_absolute(Path(str(context["compatibility_output"])))
    compatibility_output.parent.mkdir(parents=True, exist_ok=True)
    compatibility_output.write_bytes(output_raw)
    proof = _proof_base(
        nonce=str(context["nonce"]),
        resolver=resolver,
        authority_sources=authority["authority_sources"],
        source_request_sha256=str(context["source_request_sha256"]),
        executed_request_sha256=str(context["executed_request_sha256"]),
    )
    core = {
        "nonce": str(context["nonce"]),
        "pid": os.getpid(),
        "interpreter_pid": os.getpid(),
        "launcher_pid": os.getppid(),
        "launcher_owner_pid": _launcher_owner_pid(),
        "env_pid": os.getpid(),
        "parent_pid": os.getppid(),
        "entrypoint_sha256": seal["sha256"],
        "argv_sha256": _full_child_argv_sha256(),
        "source_request_sha256": str(context["source_request_sha256"]),
        "executed_request_sha256": str(context["executed_request_sha256"]),
        "audit_log_path": str(recorder.path),
        "resolver": proof["resolver"],
        "sys_flags": proof["sys_flags"],
        "python_dont_write_bytecode": proof["python_dont_write_bytecode"],
        "entrypoint_argv_flags": proof["entrypoint_argv_flags"],
        "sys_path": proof["sys_path"],
        "xinao_module_origins": proof["xinao_module_origins"],
        "required_source_touches": [
            *required_authority,
            executed_request,
            catalog,
            dataset,
        ],
        "phase_output": phase_output,
        "ascii_children": ascii_children,
        "base_executable": _base_executable_identity(),
        "runtime_identity": authority["runtime_identity"],
        "forbidden_mutation_guard_declaration": guard.declaration(),
    }
    return json.loads(_nested_envelope(role="phase", phase=phase, payload=b"", core=core))


def _execute_ascii_role(context: dict[str, Any]) -> dict[str, Any]:
    (
        pack_root,
        run_root,
        dependency_roots,
        forbidden_roots,
        injected_live_root,
    ) = _nested_context_paths(context)
    phase = str(context["phase"])
    if phase not in {"seed", "final", "reordered"}:
        raise FoundationV4ReplayError(f"unknown F1 ASCII phase: {phase}")
    expected_guard_log_path = _lexical_absolute(
        run_root / "audit" / f"forbidden-ascii-{phase}.jsonl"
    )
    guard = _ForbiddenMutationGuard(
        pack_root=pack_root,
        forbidden_roots=forbidden_roots,
        injected_live_root=injected_live_root,
        event_log_path=expected_guard_log_path,
        nonce=str(context["nonce"]),
        role=f"ascii:{phase}",
    )
    guard.install()
    seal = _entrypoint_seal(
        pack_root=pack_root,
        sealed_entrypoint_path=_lexical_absolute(Path(__file__)),
        sealed_entrypoint_manifest_path=Path(str(context["entrypoint_manifest_path"])),
    )
    if seal["sha256"] != context["entrypoint_sha256"]:
        raise FoundationV4ReplayError("ASCII entrypoint identity drifted")
    recorder = _AuditRecorder(
        path=run_root / "audit" / f"ascii-{phase}.jsonl",
        nonce=str(context["nonce"]),
    )
    resolver = _resolve_import_roots(
        pack_root=pack_root,
        dependency_roots=dependency_roots,
        forbidden_roots=forbidden_roots,
        injected_live_root=injected_live_root,
    )
    authority_manifest, _ = _read_json_object(
        pack_root / "foundation" / "authority_snapshot" / "authority_manifest.json",
        label="authority manifest",
    )
    worker = _authority_identity(
        pack_root=pack_root,
        authority_manifest=authority_manifest,
        suffix="xinao/foundation/f1_pure_ascii_stream_worker.py",
    )
    projection_path = _lexical_absolute(Path(str(context["projection_path"])))
    projection_raw = recorder.read(
        projection_path, expected_sha256=str(context["projection_sha256"])
    )
    worker_raw = recorder.read(Path(worker["path"]), expected_sha256=worker["sha256"])
    namespace: dict[str, Any] = {
        "__builtins__": __builtins__,
        "__file__": worker["path"],
        "__name__": "xinao_f1_pure_ascii_worker",
    }
    exec(compile(worker_raw, worker["path"], "exec"), namespace)
    compile_worker = namespace.get("_compile")
    if not callable(compile_worker):
        raise FoundationV4ReplayError("ASCII authority _compile is absent")
    result = compile_worker(projection_raw)
    if not isinstance(result, dict):
        raise FoundationV4ReplayError("ASCII authority result is not an object")
    result_raw = _canonical_bytes(result, ensure_ascii=True)
    result_ref = recorder.write(Path(str(context["result_path"])), result_raw)
    projection_ref = {
        "path": str(projection_path),
        "sha256": _sha256(projection_raw),
    }
    core = {
        "nonce": str(context["nonce"]),
        "pid": os.getpid(),
        "interpreter_pid": os.getpid(),
        "launcher_pid": os.getppid(),
        "launcher_owner_pid": _launcher_owner_pid(),
        "env_pid": os.getpid(),
        "parent_pid": os.getppid(),
        "entrypoint_sha256": seal["sha256"],
        "argv_sha256": _full_child_argv_sha256(),
        "source_request_sha256": str(context["source_request_sha256"]),
        "executed_request_sha256": str(context["executed_request_sha256"]),
        "audit_log_path": str(recorder.path),
        "resolver": resolver,
        "sys_flags": _sys_flags(),
        "python_dont_write_bytecode": os.environ.get("PYTHONDONTWRITEBYTECODE"),
        "entrypoint_argv_flags": ["-I", "-S", "-B"],
        "sys_path": list(sys.path),
        "xinao_module_origins": [],
        "required_source_touches": [worker, projection_ref],
        "worker": worker,
        "projection": projection_ref,
        "projection_sha256": projection_ref["sha256"],
        "result": result_ref,
        "result_sha256": result_ref["sha256"],
        "base_executable": _base_executable_identity(),
        "forbidden_mutation_guard_declaration": guard.declaration(),
    }
    return json.loads(_nested_envelope(role="ascii", phase=phase, payload=result_raw, core=core))


def _entrypoint_seal(
    *,
    pack_root: Path,
    sealed_entrypoint_path: Path,
    sealed_entrypoint_manifest_path: Path,
) -> dict[str, str]:
    pack = _lexical_absolute(pack_root)
    entrypoint = _lexical_absolute(sealed_entrypoint_path)
    manifest_path = _lexical_absolute(sealed_entrypoint_manifest_path)
    manifest, manifest_raw = _read_json_object(manifest_path, label="entrypoint seal manifest")
    if manifest.get("schema_version") != "xinao.foundation_v4_replay_entrypoint_seal.v1":
        raise FoundationV4ReplayError("entrypoint seal schema is invalid")
    relative = _safe_relative_path(
        manifest.get("entrypoint_relative_path"), label="entrypoint relative_path"
    )
    expected_entrypoint = _lexical_absolute(pack / relative)
    if entrypoint != expected_entrypoint:
        raise FoundationV4ReplayError("entrypoint seal path binding drifted")
    raw = _verify_file_identity(
        entrypoint,
        expected_size=manifest.get("entrypoint_size"),
        expected_sha256=manifest.get("entrypoint_sha256"),
        drift_label="entrypoint seal SHA drift",
    )
    if entrypoint.parent != pack / "b1_runtime":
        raise FoundationV4ReplayError("entrypoint is outside the sealed b1_runtime root")
    return {
        "path": str(entrypoint),
        "sha256": _sha256(raw),
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(manifest_raw),
    }


def _outer_argv(
    *,
    runtime_python: Path,
    sealed_entrypoint_path: Path,
    sealed_entrypoint_manifest_path: Path,
    pack_root: Path,
    output_root: Path,
    nonce: str,
    run_index: int,
    dependency_roots: Sequence[Path],
    forbidden_roots: Sequence[Path],
    injected_live_root: Path,
    block_id: str = "F1_settlement_world",
) -> tuple[str, ...]:
    dependencies = [str(_lexical_absolute(path)) for path in dependency_roots]
    forbidden = [str(_lexical_absolute(path)) for path in forbidden_roots]
    argv = (
        str(_lexical_absolute(runtime_python)),
        "-X",
        "faulthandler",
        "-I",
        "-S",
        "-B",
        str(_lexical_absolute(sealed_entrypoint_path)),
        "--entrypoint-manifest",
        str(_lexical_absolute(sealed_entrypoint_manifest_path)),
        "--pack-root",
        str(_lexical_absolute(pack_root)),
        "--output-root",
        str(_lexical_absolute(output_root)),
        "--nonce",
        nonce,
        "--run-index",
        str(run_index),
        "--dependency-roots-json",
        _canonical_bytes(dependencies).decode("utf-8"),
        "--forbidden-roots-json",
        _canonical_bytes(forbidden).decode("utf-8"),
        "--injected-live-root",
        str(_lexical_absolute(injected_live_root)),
    )
    if block_id == "F1_settlement_world":
        return argv
    _replay_block_spec(block_id)
    return (*argv, "--block-id", block_id)


def _aggregate_forbidden_mutation_proofs(
    proofs: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate already parent-verified role proofs without assuming topology."""

    return {
        "schema_version": FORBIDDEN_GUARD_AGGREGATE_SCHEMA,
        "role_count": len(proofs),
        "covered_mutation_event_count": sum(
            int(proof["covered_mutation_event_count"]) for proof in proofs
        ),
        "allowed_mutation_event_count": sum(
            int(proof["allowed_mutation_event_count"]) for proof in proofs
        ),
        "denied_mutation_event_count": sum(
            int(proof["denied_mutation_event_count"]) for proof in proofs
        ),
        "proofs": list(proofs),
    }


def _verify_run_forbidden_mutation_evidence(
    *,
    run: dict[str, Any],
    pack_root: Path,
    output_root: Path,
    forbidden_roots: Sequence[Path],
    injected_live_root: Path,
    nonce: str,
) -> dict[str, Any]:
    spec = _replay_block_spec(str(run.get("block_id")))
    roots = _guard_root_set(
        pack_root=pack_root,
        forbidden_roots=forbidden_roots,
        injected_live_root=injected_live_root,
    )
    root_set_sha256 = _guard_root_set_sha256(roots)
    run_root = _lexical_absolute(output_root / f"run-{run['run_index']}")
    phase_proofs = run.get("phase_proofs")
    if (
        not isinstance(phase_proofs, dict)
        or set(phase_proofs) != set(spec.phase_order)
        or run.get("phase_order") != list(spec.phase_order)
    ):
        raise FoundationV4ReplayError("run phase proofs are absent")
    verified: list[dict[str, Any]] = []

    def verify_role(
        *, role: str, proof: dict[str, Any], expected_log_path: Path, nested: bool
    ) -> dict[str, Any]:
        interpreter_pid = proof.get("interpreter_pid")
        if not isinstance(interpreter_pid, int) or interpreter_pid <= 0:
            raise FoundationV4ReplayError("guard proof interpreter PID is invalid")
        parent_proof = _verify_forbidden_mutation_log(
            event_log_path=expected_log_path,
            expected_nonce=nonce,
            expected_role=role,
            expected_interpreter_pid=interpreter_pid,
            expected_roots=roots,
            require_success=True,
        )
        if nested and {key: proof.get(key) for key in _GUARD_PROOF_FIELDS} != parent_proof:
            raise FoundationV4ReplayError("nested guard proof disagrees with parent")
        proof.update(parent_proof)
        verified.append({"role": role, **parent_proof})
        return parent_proof

    outer = phase_proofs.get("outer")
    if not isinstance(outer, dict):
        raise FoundationV4ReplayError("outer phase proof is absent")
    expected_outer_log = run_root / "audit" / "forbidden-outer.jsonl"
    declaration = outer.get("forbidden_mutation_guard_declaration")
    if not isinstance(declaration, dict) or declaration != {
        "guard_schema_version": FORBIDDEN_GUARD_SCHEMA,
        "root_set_sha256": root_set_sha256,
        "event_log_path": str(_lexical_absolute(expected_outer_log)),
        "nonce": nonce,
        "role": "outer",
        "interpreter_pid": outer.get("interpreter_pid"),
    }:
        raise FoundationV4ReplayError("outer forbidden guard declaration drifted")
    verify_role(
        role="outer",
        proof=outer,
        expected_log_path=expected_outer_log,
        nested=False,
    )
    if spec.actuals_mode == "DIRECT":
        return _aggregate_forbidden_mutation_proofs(verified)
    for phase in spec.phase_order[1:]:
        phase_proof = phase_proofs.get(phase)
        if not isinstance(phase_proof, dict):
            raise FoundationV4ReplayError(f"phase guard proof is absent: {phase}")
        verify_role(
            role=f"phase:{phase}",
            proof=phase_proof,
            expected_log_path=(run_root / "audit" / f"forbidden-phase-{phase}.jsonl"),
            nested=True,
        )
        ascii_children = phase_proof.get("ascii_children")
        if not isinstance(ascii_children, list) or len(ascii_children) != 1:
            raise FoundationV4ReplayError(f"ASCII guard proof is absent: {phase}")
        ascii_proof = ascii_children[0]
        if not isinstance(ascii_proof, dict):
            raise FoundationV4ReplayError(f"ASCII guard proof is invalid: {phase}")
        verify_role(
            role=f"ascii:{phase}",
            proof=ascii_proof,
            expected_log_path=(run_root / "audit" / f"forbidden-ascii-{phase}.jsonl"),
            nested=True,
        )
    if len(verified) != 1 + 2 * len(spec.phase_order[1:]):
        raise FoundationV4ReplayError("guard role topology is incomplete")
    return _aggregate_forbidden_mutation_proofs(verified)


def _launch_outer_once(
    *,
    runtime_python: Path,
    sealed_entrypoint_path: Path,
    sealed_entrypoint_manifest_path: Path,
    pack_root: Path,
    output_root: Path,
    nonce: str,
    run_index: int,
    dependency_roots: Sequence[Path],
    forbidden_roots: Sequence[Path],
    injected_live_root: Path,
    block_id: str = "F1_settlement_world",
    failure_capture_root: Path | None = None,
) -> dict[str, Any]:
    argv = _outer_argv(
        runtime_python=runtime_python,
        sealed_entrypoint_path=sealed_entrypoint_path,
        sealed_entrypoint_manifest_path=sealed_entrypoint_manifest_path,
        pack_root=pack_root,
        output_root=output_root,
        nonce=nonce,
        run_index=run_index,
        dependency_roots=dependency_roots,
        forbidden_roots=forbidden_roots,
        injected_live_root=injected_live_root,
        block_id=block_id,
    )
    child_cwd = _lexical_absolute(sealed_entrypoint_path).parent
    process = subprocess.Popen(
        argv,
        shell=False,
        cwd=str(child_cwd),
        env=_clean_child_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    stdout, stderr = process.communicate()
    completed = subprocess.CompletedProcess(
        args=argv,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )

    def raise_preserved_process_failure(*, reason: str) -> None:
        capture_path: Path | None = None
        capture_sha256: str | None = None
        preservation_complete = False
        capture_error: str | None = None
        if failure_capture_root is not None:
            try:
                (
                    capture_path,
                    capture_sha256,
                    preservation_complete,
                ) = _persist_outer_failure_capture(
                    capture_root=failure_capture_root,
                    block_id=block_id,
                    nonce=nonce,
                    run_index=run_index,
                    argv=argv,
                    cwd=child_cwd,
                    returncode=completed.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    launcher_process_pid=process.pid,
                    runtime_python=runtime_python,
                    sealed_entrypoint_path=sealed_entrypoint_path,
                    sealed_entrypoint_manifest_path=sealed_entrypoint_manifest_path,
                    output_root=output_root,
                )
            except (OSError, FoundationV4ReplayError) as exc:
                capture_error = str(exc)
        detail = (stderr or stdout).decode("utf-8", errors="replace")[-4000:]
        capture_detail = (
            f" failure_capture={capture_path} sha256={capture_sha256}"
            if capture_path is not None
            else (
                f" failure_capture_error={capture_error}"
                if capture_error is not None
                else " failure_capture=not_requested"
            )
        )
        raise OuterReplayProcessError(
            (
                f"sealed outer replay failed with exit {completed.returncode}: "
                f"{reason}: {detail}{capture_detail}"
            ),
            returncode=completed.returncode,
            failure_capture_path=capture_path,
            failure_capture_sha256=capture_sha256,
            preservation_complete=preservation_complete,
            original_output_root=_lexical_absolute(output_root),
        )

    if completed.returncode != 0:
        raise_preserved_process_failure(reason="outer process returned nonzero")
    success_start_record = _outer_start_record_path(
        output_root=output_root,
        run_index=run_index,
    )
    if success_start_record.exists():
        raise_preserved_process_failure(reason="start record persisted after successful exit")
    if completed.stderr:
        raise FoundationV4ReplayError("sealed outer replay wrote unexpected stderr")
    try:
        run = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationV4ReplayError("sealed outer replay stdout is not JSON") from exc
    if not isinstance(run, dict) or _canonical_bytes(run) != completed.stdout:
        raise FoundationV4ReplayError("sealed outer replay stdout is not canonical JSON")
    core = dict(run)
    content_sha256 = core.pop("content_sha256", None)
    if content_sha256 != _canonical_sha256(core):
        raise FoundationV4ReplayError("sealed outer replay receipt content drifted")
    if (
        run.get("schema_version") != "xinao.foundation_v4_replay_run_receipt.v1"
        or run.get("status") != "VERIFIED"
        or run.get("role") != "outer"
        or run.get("block_id") != block_id
        or run.get("nonce") != nonce
        or run.get("run_index") != run_index
    ):
        raise FoundationV4ReplayError("sealed outer replay receipt binding drifted")
    pack_inventory_before_sha256 = run.get("pack_inventory_before_sha256")
    pack_inventory_after_sha256 = run.get("pack_inventory_after_sha256")
    if (
        not isinstance(pack_inventory_before_sha256, str)
        or len(pack_inventory_before_sha256) != 64
        or pack_inventory_after_sha256 != pack_inventory_before_sha256
    ):
        raise FoundationV4ReplayError("sealed pack inventory proof is invalid")
    forbidden_mutation_evidence = _verify_run_forbidden_mutation_evidence(
        run=run,
        pack_root=pack_root,
        output_root=output_root,
        forbidden_roots=forbidden_roots,
        injected_live_root=injected_live_root,
        nonce=nonce,
    )
    augmented_core = dict(run)
    augmented_core.pop("content_sha256")
    augmented_core["forbidden_mutation_evidence"] = forbidden_mutation_evidence
    return {
        **augmented_core,
        "content_sha256": _canonical_sha256(augmented_core),
    }


def preflight_relocated_foundation_v4(
    *,
    pack_root: Path,
    block_id: str,
    original_foundation_root: Path | None = None,
    injected_live_root: Path | None = None,
) -> dict[str, Any]:
    """Prove inputs and interpreter origins before any assertion replay starts."""

    # ``original_foundation_root`` is deliberately never inspected.  It exists only
    # to let callers prove that a missing or drifted relocated source cannot fall
    # back to the machine that produced the sealed capsule.
    del original_foundation_root
    if block_id not in FOUNDATION_BLOCK_IDS:
        raise FoundationV4ReplayError(f"unknown foundation block: {block_id}")
    spec = _REPLAY_BLOCK_SPECS.get(block_id)
    if spec is not None:
        _validate_replay_block_spec(spec)
        expected_capsule_schema = spec.capsule_schema_version
    else:
        expected_capsule_schema = "xinao.foundation_v4_relocation_source_capsule.v1"

    pack = _lexical_absolute(pack_root)
    foundation = pack / "foundation"
    actual_files = _scan_payload_tree_nonfollowing(foundation=foundation)
    manifest_path = foundation / "capsule_manifest.json"
    capsule, manifest_raw = _read_json_object(manifest_path, label="capsule manifest")
    if capsule.get("schema_version") != expected_capsule_schema:
        raise FoundationV4ReplayError("relocated capsule manifest schema is invalid")
    request_ref = capsule.get("request")
    payload = capsule.get("payload")
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(request_ref, dict) or not isinstance(files, list):
        raise FoundationV4ReplayError("relocated capsule manifest shape is invalid")
    manifest_block_id = capsule.get("block_id", request_ref.get("block_id"))
    if manifest_block_id != block_id:
        raise FoundationV4ReplayError("relocated request block identity drifted")

    inventory_lines: list[str] = []
    payload_identities: dict[str, tuple[int, str]] = {}
    total_size = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise FoundationV4ReplayError("relocated payload entry is invalid")
        relative = _safe_relative_path(entry.get("relative_path"), label="payload relative_path")
        relative_posix = relative.as_posix()
        if relative_posix in payload_identities:
            raise FoundationV4ReplayError("relocated payload inventory is duplicated")
        size = entry.get("size_bytes")
        digest = entry.get("sha256")
        drift_label = (
            "authority source SHA drift"
            if relative_posix.startswith("authority_snapshot/sources/")
            else "relocated source SHA drift"
        )
        raw = _verify_file_identity(
            foundation / relative,
            expected_size=size,
            expected_sha256=digest,
            drift_label=drift_label,
        )
        assert isinstance(size, int) and isinstance(digest, str)
        payload_identities[relative_posix] = (size, digest)
        total_size += len(raw)
        inventory_lines.append(f"{relative_posix}\t{size}\t{digest}")

    _validate_exact_payload_tree(actual_files=actual_files, payload_paths=set(payload_identities))

    expected_inventory = payload.get("exact_inventory_sha256")
    actual_inventory = _sha256("\n".join(inventory_lines).encode("utf-8"))
    if actual_inventory != expected_inventory:
        raise FoundationV4ReplayError("relocated payload inventory SHA drift")
    if total_size != payload.get("total_size_bytes"):
        raise FoundationV4ReplayError("relocated payload total size drift")

    request_relative = _safe_relative_path(
        request_ref.get("relative_path"), label="request relative_path"
    )
    request_identity = payload_identities.get(request_relative.as_posix())
    if request_identity != (
        request_ref.get("size_bytes"),
        request_ref.get("sha256"),
    ):
        raise FoundationV4ReplayError("relocated request manifest binding drifted")
    request, request_raw = _read_json_object(
        foundation / request_relative, label="assertion request"
    )
    if request.get("block_id") != block_id:
        raise FoundationV4ReplayError("relocated request payload block identity drifted")
    assertion_ids = request.get("assertion_ids")
    if (
        not isinstance(assertion_ids, list)
        or not all(isinstance(item, str) and item for item in assertion_ids)
        or len(assertion_ids) != request_ref.get("assertion_count")
    ):
        raise FoundationV4ReplayError("relocated request assertion inventory drifted")
    if spec is not None:
        input_evidence = request.get("input_evidence")
        input_hashes = request.get("input_hashes")
        artifacts = request.get("artifacts")
        if (
            tuple(assertion_ids) != spec.assertion_ids
            or not isinstance(input_evidence, dict)
            or tuple(sorted(input_evidence)) != spec.input_names
            or not isinstance(input_hashes, dict)
            or tuple(sorted(input_hashes)) != spec.input_names
            or not isinstance(artifacts, dict)
            or tuple(sorted(artifacts)) != spec.artifact_names
        ):
            raise FoundationV4ReplayError(f"relocated request inventory is not exact: {block_id}")

    authority_manifest_path = foundation / "authority_snapshot" / "authority_manifest.json"
    authority, authority_raw = _read_json_object(
        authority_manifest_path, label="authority manifest"
    )
    authority_entries = authority.get("entries")
    if authority.get("schema_version") != "xinao.compiler_code_manifest.v3" or not isinstance(
        authority_entries, list
    ):
        raise FoundationV4ReplayError("relocated authority manifest shape is invalid")
    authority_sources = foundation / "authority_snapshot" / "sources"
    seen_authority: set[str] = set()
    for entry in authority_entries:
        if not isinstance(entry, dict):
            raise FoundationV4ReplayError("relocated authority entry is invalid")
        relative = _safe_relative_path(entry.get("relative_path"), label="authority relative_path")
        relative_posix = relative.as_posix()
        if relative_posix in seen_authority:
            raise FoundationV4ReplayError("relocated authority inventory is duplicated")
        seen_authority.add(relative_posix)
        _verify_file_identity(
            authority_sources / relative,
            expected_size=entry.get("size"),
            expected_sha256=entry.get("sha256"),
            drift_label="authority source SHA drift",
        )

    runtime_ref = authority.get("runtime_buildinfo_ref")
    if not isinstance(runtime_ref, dict):
        raise FoundationV4ReplayError("relocated authority runtime binding is absent")
    runtime_relative = _safe_relative_path(
        runtime_ref.get("relative_path"), label="runtime buildinfo relative_path"
    )
    _verify_file_identity(
        foundation / "authority_snapshot" / runtime_relative,
        expected_size=runtime_ref.get("size"),
        expected_sha256=runtime_ref.get("sha256"),
        drift_label="authority runtime SHA drift",
    )

    return {
        "status": "VERIFIED",
        "block_id": block_id,
        "pack_root": str(pack),
        "capsule_manifest_sha256": _sha256(manifest_raw),
        "authority_manifest_sha256": _sha256(authority_raw),
        "source_request_sha256": _sha256(request_raw),
        "assertion_count": len(assertion_ids),
        "authority_source_count": len(seen_authority),
        "payload_file_count": len(payload_identities),
        "injected_live_root": (
            str(_lexical_absolute(injected_live_root)) if injected_live_root is not None else None
        ),
        "original_fallback_access_count": 0,
    }


def replay_foundation_v4_f4_oci(
    *,
    pack_roots: Sequence[Path],
    output_root: Path,
    nonce: str,
) -> dict[str, Any]:
    """Run two relocated F4 roots twice each through the sealed OCI carrier."""

    if (
        len(pack_roots) != 2
        or not isinstance(nonce, str)
        or len(nonce) != 64
        or any(character not in "0123456789abcdef" for character in nonce)
    ):
        raise FoundationV4ReplayError("F4 OCI replay requires two roots and one valid nonce")
    normalized_roots = tuple(_lexical_absolute(path) for path in pack_roots)
    if normalized_roots[0] == normalized_roots[1]:
        raise FoundationV4ReplayError("F4 OCI replay roots must be physically distinct")
    output = _lexical_absolute(output_root)
    if output.exists():
        raise FoundationV4ReplayError(f"F4 OCI output already exists: {output}")

    from scripts import run_f4_snapshot_oci as oci_runner

    spec = _replay_block_spec("F4_research_factory")
    raw_bundles: list[bytes] = []
    normalized_bundles: list[bytes] = []
    carrier_bindings: list[dict[str, Any]] = []
    preflights: list[dict[str, Any]] = []
    authority_identity: dict[str, str] | None = None
    common_projection_sha256: str | None = None
    common_authority_manifest_sha256: str | None = None
    for root_index, pack in enumerate(normalized_roots):
        preflight = preflight_relocated_foundation_v4(
            pack_root=pack,
            block_id=spec.block_id,
        )
        preflights.append(preflight)
        authority, _ = _read_json_object(
            pack / "foundation" / "authority_snapshot" / "authority_manifest.json",
            label="relocated F4 authority manifest",
        )
        candidate_identity = _authority_identity(
            pack_root=pack,
            authority_manifest=authority,
            suffix=spec.authority_entrypoint_relative_path,
        )
        if authority_identity is None:
            authority_identity = candidate_identity
        elif authority_identity["sha256"] != candidate_identity["sha256"]:
            raise FoundationV4ReplayError("F4 relocated authority identities differ")

        receipt_path = oci_runner.run_fixed(
            output_parent=output / f"carrier-{root_index + 1}",
            data_root=pack / "foundation" / "f4_snapshot",
        )
        receipt = oci_runner.verify_execution_receipt(receipt_path)
        runs = receipt["runs"]
        pack_raw_sha256: str | None = None
        for run in runs:
            run_output = Path(str(run["output_ref"])).resolve()
            bundle_path = run_output / "f4_assertion_actual_bundle.v2.json"
            raw_bundle = bundle_path.read_bytes()
            raw_sha256 = _sha256(raw_bundle)
            if pack_raw_sha256 is None:
                pack_raw_sha256 = raw_sha256
            elif pack_raw_sha256 != raw_sha256:
                raise FoundationV4ReplayError("F4 OCI runs emitted different raw bundles")
            normalized = _normalize_bundle(
                raw_bundle=raw_bundle,
                entrypoint_identity=candidate_identity,
                source_request_sha256=preflight["source_request_sha256"],
                executed_request_sha256=preflight["source_request_sha256"],
                spec=spec,
                require_physical_entrypoint=False,
            )
            raw_bundles.append(raw_bundle)
            normalized_bundles.append(normalized)

            stage0 = json.loads((run_output / "stage0_result.json").read_text(encoding="utf-8"))
            projection = stage0.get("common_authority_projection")
            if not isinstance(projection, dict):
                raise FoundationV4ReplayError("F4 OCI authority projection is absent")
            projection_sha = str(projection.get("content_sha256") or "")
            manifest_sha = str(projection.get("common_authority_manifest_sha256") or "")
            if common_projection_sha256 is None:
                common_projection_sha256 = projection_sha
                common_authority_manifest_sha256 = manifest_sha
            elif (
                common_projection_sha256 != projection_sha
                or common_authority_manifest_sha256 != manifest_sha
            ):
                raise FoundationV4ReplayError("F4 OCI authority projections differ")

        carrier_bindings.append(
            {
                "root_ordinal": root_index + 1,
                "execution_receipt_sha256": _sha256(receipt_path.read_bytes()),
                "execution_receipt_content_sha256": receipt["content_sha256"],
                "image_id": receipt["image"]["id"],
                "data_content_sha256": receipt["data_content_sha256"],
                "semantic_output_set_sha256": receipt["semantic_output_set_sha256"],
                "raw_bundle_sha256": pack_raw_sha256,
                "run_count": receipt["run_count"],
                "fallback_count": receipt["fallback_count"],
            }
        )

    if len(raw_bundles) != 4 or any(raw != raw_bundles[0] for raw in raw_bundles[1:]):
        raise FoundationV4ReplayError("F4 A-by-two and B-by-two raw bundles differ")
    if any(bundle != normalized_bundles[0] for bundle in normalized_bundles[1:]):
        raise FoundationV4ReplayError("F4 A-by-two and B-by-two normalized bundles differ")
    invariant_preflight = (
        "authority_manifest_sha256",
        "source_request_sha256",
        "assertion_count",
    )
    if any(
        preflight[key] != preflights[0][key]
        for preflight in preflights[1:]
        for key in invariant_preflight
    ):
        raise FoundationV4ReplayError("F4 relocated root content identities differ")

    output.mkdir(parents=True, exist_ok=True)
    normalized_path = output / "F4_research_factory-replay-bundle.json"
    normalized_path.write_bytes(normalized_bundles[0])
    assert authority_identity is not None
    receipt_core = {
        "schema_version": "xinao.foundation_v4_f4_oci_replay_receipt.v1",
        "status": "VERIFIED",
        "block_id": spec.block_id,
        "nonce": nonce,
        "execution_carrier": "OCI",
        "relocated_root_count": 2,
        "carrier_run_count": 4,
        "assertion_count": len(spec.assertion_ids),
        "assertion_ids": list(spec.assertion_ids),
        "source_request_sha256": preflights[0]["source_request_sha256"],
        "authority_manifest_sha256": preflights[0]["authority_manifest_sha256"],
        "authority_entrypoint_sha256": authority_identity["sha256"],
        "common_authority_manifest_sha256": common_authority_manifest_sha256,
        "semantic_authority_projection_sha256": common_projection_sha256,
        "raw_bundle_sha256": _sha256(raw_bundles[0]),
        "normalized_bundle_sha256": _sha256(normalized_bundles[0]),
        "carrier_bindings": carrier_bindings,
        "fallback_count": 0,
    }
    common_receipt = {**receipt_core, "content_sha256": _canonical_sha256(receipt_core)}
    (output / "F4_research_factory-replay-receipt.json").write_bytes(
        _canonical_bytes(common_receipt)
    )
    return common_receipt


def replay_foundation_v4_same_host(
    *,
    block_id: str,
    pack_root: Path,
    output_root: Path,
    runtime_python: Path,
    dependency_roots: Sequence[Path],
    forbidden_roots: Sequence[Path],
    injected_live_root: Path,
    sealed_entrypoint_path: Path,
    sealed_entrypoint_manifest_path: Path,
    nonce: str,
    run_count: int = 2,
    failure_capture_root: Path | None = None,
    peer_pack_root: Path | None = None,
) -> dict[str, Any]:
    """Freshly recompute one registered relocated block without live oracles."""

    spec = _replay_block_spec(block_id)
    if (
        not isinstance(run_count, int)
        or isinstance(run_count, bool)
        or run_count < 1
        or not isinstance(nonce, str)
        or len(nonce) != 64
        or any(character not in "0123456789abcdef" for character in nonce)
    ):
        raise FoundationV4ReplayError("replay nonce or run count is invalid")
    if spec.block_id == "F4_research_factory":
        if peer_pack_root is None or run_count != 2:
            raise FoundationV4ReplayError(
                "F4 replay requires one peer root and exactly two runs per root"
            )
        return replay_foundation_v4_f4_oci(
            pack_roots=(pack_root, peer_pack_root),
            output_root=output_root,
            nonce=nonce,
        )
    normalized_pack = _lexical_absolute(pack_root)
    normalized_output = _lexical_absolute(output_root)
    normalized_injected = _lexical_absolute(injected_live_root)
    normalized_forbidden = tuple(_lexical_absolute(path) for path in forbidden_roots)
    guard_roots = _guard_root_set(
        pack_root=normalized_pack,
        forbidden_roots=normalized_forbidden,
        injected_live_root=normalized_injected,
    )
    locations: list[tuple[str, Path]] = [("output root", normalized_output)]
    for run_index in range(run_count):
        run_root = _lexical_absolute(normalized_output / f"run-{run_index}")
        locations.extend(
            (
                ("run root", run_root),
                (
                    "guard event log",
                    run_root / "audit" / "forbidden-outer.jsonl",
                ),
            )
        )
    _validate_guard_output_locations(roots=guard_roots, locations=locations)
    seal = _entrypoint_seal(
        pack_root=pack_root,
        sealed_entrypoint_path=sealed_entrypoint_path,
        sealed_entrypoint_manifest_path=sealed_entrypoint_manifest_path,
    )
    runs = [
        _launch_outer_once(
            runtime_python=runtime_python,
            sealed_entrypoint_path=sealed_entrypoint_path,
            sealed_entrypoint_manifest_path=sealed_entrypoint_manifest_path,
            pack_root=normalized_pack,
            output_root=normalized_output,
            nonce=nonce,
            run_index=run_index,
            dependency_roots=dependency_roots,
            forbidden_roots=normalized_forbidden,
            injected_live_root=normalized_injected,
            block_id=spec.block_id,
            failure_capture_root=failure_capture_root,
        )
        for run_index in range(run_count)
    ]
    first = runs[0]
    invariant_keys = (
        "block_id",
        "source_request_sha256",
        "executed_request_sha256",
        "bundle_sha256",
        "assertion_count",
        "assertion_ids",
    )
    for run in runs[1:]:
        if any(run.get(key) != first.get(key) for key in invariant_keys):
            raise FoundationV4ReplayError("independent replay runs are not identical")
    receipt_core = {
        "schema_version": "xinao.foundation_v4_replay_receipt.v1",
        "status": "VERIFIED",
        "block_id": spec.block_id,
        "nonce": nonce,
        "assertion_count": first["assertion_count"],
        "assertion_ids": first["assertion_ids"],
        "source_request_sha256": first["source_request_sha256"],
        "relocated_request_sha256": first["executed_request_sha256"],
        "execution_entrypoint": seal,
        "forbidden_mutation_evidence_by_run": [run["forbidden_mutation_evidence"] for run in runs],
        "runs": runs,
        **(
            {"phase_lineage_by_run": [run["phase_lineage"] for run in runs]}
            if spec.include_phase_lineage
            else {}
        ),
    }
    return {**receipt_core, "content_sha256": _canonical_sha256(receipt_core)}


def replay_foundation_v4_f1_same_host(
    *,
    pack_root: Path,
    output_root: Path,
    runtime_python: Path,
    dependency_roots: Sequence[Path],
    forbidden_roots: Sequence[Path],
    injected_live_root: Path,
    sealed_entrypoint_path: Path,
    sealed_entrypoint_manifest_path: Path,
    nonce: str,
    run_count: int = 2,
    failure_capture_root: Path | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper retaining the frozen F1 public call surface."""

    return replay_foundation_v4_same_host(
        block_id="F1_settlement_world",
        pack_root=pack_root,
        output_root=output_root,
        runtime_python=runtime_python,
        dependency_roots=dependency_roots,
        forbidden_roots=forbidden_roots,
        injected_live_root=injected_live_root,
        sealed_entrypoint_path=sealed_entrypoint_path,
        sealed_entrypoint_manifest_path=sealed_entrypoint_manifest_path,
        nonce=nonce,
        run_count=run_count,
        failure_capture_root=failure_capture_root,
    )


def _parse_json_string_list(raw: str, *, label: str) -> tuple[Path, ...]:
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FoundationV4ReplayError(f"{label} is not JSON") from exc
    if not isinstance(loaded, list) or not all(isinstance(item, str) and item for item in loaded):
        raise FoundationV4ReplayError(f"{label} must be a JSON string array")
    return tuple(_lexical_absolute(Path(item)) for item in loaded)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--entrypoint-manifest", required=True)
    parser.add_argument("--pack-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--run-index", required=True, type=int)
    parser.add_argument("--dependency-roots-json", required=True)
    parser.add_argument("--forbidden-roots-json", required=True)
    parser.add_argument("--injected-live-root", required=True)
    parser.add_argument("--block-id", default="F1_settlement_world")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    global _OUTER_STDOUT_COMMITTED
    values = list(sys.argv[1:] if argv is None else argv)
    if values[:1] == ["--child-role"]:
        if not faulthandler.is_enabled():
            raise FoundationV4ReplayError("nested replay faulthandler is not enabled")
        nested_parser = argparse.ArgumentParser(add_help=False)
        nested_parser.add_argument("--child-role", choices=("phase", "ascii"), required=True)
        nested_parser.add_argument("--context-json", required=True)
        nested = nested_parser.parse_args(values)
        try:
            context = json.loads(nested.context_json)
        except json.JSONDecodeError as exc:
            raise FoundationV4ReplayError("nested context is not JSON") from exc
        if not isinstance(context, dict):
            raise FoundationV4ReplayError("nested context must be an object")
        receipt = _execute_nested_placeholder(nested.child_role, context)
    else:
        args = _argument_parser().parse_args(values)
        receipt = _execute_outer_role(args)
    sys.stdout.buffer.write(_canonical_bytes(receipt))
    sys.stdout.buffer.flush()
    if values[:1] != ["--child-role"]:
        _OUTER_STDOUT_COMMITTED = True
    return 0


__all__ = [
    "F1_ISOLATED_PHASES",
    "FOUNDATION_BLOCK_IDS",
    "LEGACY_OUTPUT_NAMES",
    "FoundationV4ReplayError",
    "OuterReplayProcessError",
    "preflight_relocated_foundation_v4",
    "replay_foundation_v4_f1_same_host",
    "replay_foundation_v4_f4_oci",
    "replay_foundation_v4_same_host",
]


if __name__ == "__main__":
    raise SystemExit(main())
