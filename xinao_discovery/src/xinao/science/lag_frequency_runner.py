"""Deterministic runner for one hash-pinned lag-frequency ResearchEpisode.

The module is deliberately domain-specific.  It reuses the current science
admission, world replay, settlement, canonical hashing, and TrialLedger writer;
it is not a scheduler, workflow engine, or second ledger.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from xinao.canonical import canonical_sha256
from xinao.catalog.compiler import sha256_file, write_atomic
from xinao.science.episode_admission import verify_science_episode_admission_file
from xinao.science.trial_ledger import (
    append_science_trial_entry,
    load_science_trial_journal,
)
from xinao.settlement import settle_special_number
from xinao.world.builder import DrawRecord, load_draws, replay_science_episode_world

RESULT_SCHEMA_VERSION = "xinao.science_lag_frequency_blind_score.v1"
DETAILS_SCHEMA_VERSION = "xinao.research_protocol_details.v2"
SEED_SCHEMA_VERSION = "xinao.science_randomization_seed_receipt.v2"
SPLIT_SCHEMA_VERSION = "xinao.dataset_split_version.v1"
RESULT_FILE_NAME = "blind_score.v2.json"
PRIMARY_FAMILY_ID = "special-number-lagged-frequency-six-variant-v1"
NULL_FAMILY_ID = "whole-pipeline-null-v1"
TERMINAL_LABELS = (
    "E2_HISTORICAL_EXPLORATORY_SUPPORT",
    "REFUTED",
    "UNIDENTIFIABLE",
    "UNDERPOWERED",
)


class LagFrequencyRunnerError(ValueError):
    """Raised when the frozen runner cannot proceed without inventing a choice."""


def _read_json(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise LagFrequencyRunnerError(f"{label} is missing: {path}")
    observed = sha256_file(path)
    if observed != expected_sha256:
        raise LagFrequencyRunnerError(f"{label} sha256 mismatch")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LagFrequencyRunnerError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise LagFrequencyRunnerError(f"{label} must be a JSON object")
    return payload


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LagFrequencyRunnerError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise LagFrequencyRunnerError(f"{label} must be an array")
    return value


def _rng(root_entropy: int, spawn_key: tuple[int, ...]) -> np.random.Generator:
    sequence = np.random.SeedSequence(root_entropy, spawn_key=spawn_key)
    return np.random.Generator(np.random.PCG64DXSM(sequence))


def _number(value: float) -> str:
    if not math.isfinite(value):
        raise LagFrequencyRunnerError("runner produced a non-finite statistic")
    return format(float(value), ".17g")


def _validate_frozen_variants(details: Mapping[str, Any]) -> list[dict[str, Any]]:
    family = _mapping(details.get("candidate_family"), "candidate_family")
    if (
        family.get("family_id") != PRIMARY_FAMILY_ID
        or family.get("variant_order_is_frozen") is not True
    ):
        raise LagFrequencyRunnerError("candidate family identity is not frozen")
    variants = [
        dict(_mapping(item, "candidate_family.variant"))
        for item in _sequence(family.get("variants"), "candidate_family.variants")
    ]
    expected = [
        (0, 30, "least_frequent"),
        (1, 30, "most_frequent"),
        (2, 90, "least_frequent"),
        (3, 90, "most_frequent"),
        (4, 180, "least_frequent"),
        (5, 180, "most_frequent"),
    ]
    observed = [
        (item.get("variant_index"), item.get("rolling_window_draws"), item.get("direction"))
        for item in variants
    ]
    if observed != expected:
        raise LagFrequencyRunnerError("candidate family is not the frozen six-variant order")
    required = {
        "trial_id",
        "work_key",
        "registration_event_id",
        "equivalence_cluster_id",
    }
    if any(
        item.get("path_kind") != "PRIMARY"
        or any(not isinstance(item.get(name), str) or not item[name] for name in required)
        for item in variants
    ):
        raise LagFrequencyRunnerError("candidate Trial identity is incomplete")
    if len({str(item["work_key"]) for item in variants}) != 6:
        raise LagFrequencyRunnerError("candidate work_key identities are not unique")
    return variants


def _validate_seed_receipt(seed: Mapping[str, Any], details: Mapping[str, Any]) -> None:
    if seed.get("schema_version") != SEED_SCHEMA_VERSION:
        raise LagFrequencyRunnerError("unsupported seed receipt schema")
    root = int(_mapping(seed.get("root_entropy"), "root_entropy").get("decimal"))
    runtime = _mapping(seed.get("runtime_pin"), "runtime_pin")
    if (
        runtime.get("numpy_version") != np.__version__
        or runtime.get("bit_generator") != "numpy.random.PCG64DXSM"
        or runtime.get("seed_sequence") != "numpy.random.SeedSequence"
    ):
        raise LagFrequencyRunnerError("random runtime does not match the frozen receipt")
    lock_ref = Path(str(runtime.get("uv_lock_ref")))
    lock_sha = str(runtime.get("uv_lock_sha256"))
    if not lock_ref.is_file() or sha256_file(lock_ref) != lock_sha:
        raise LagFrequencyRunnerError("frozen uv.lock identity is unavailable")
    for stream in _sequence(seed.get("named_streams"), "named_streams"):
        item = _mapping(stream, "named_stream")
        spawn_key = tuple(int(value) for value in _sequence(item.get("spawn_key"), "spawn_key"))
        raw = np.random.PCG64DXSM(np.random.SeedSequence(root, spawn_key=spawn_key)).random_raw(8)
        observed = [str(int(value)) for value in raw]
        expected = list(
            _sequence(item.get("raw_uint64_canary_first_8"), "raw_uint64_canary_first_8")
        )
        if observed != expected:
            raise LagFrequencyRunnerError(f"random stream canary mismatch: {item.get('stream_id')}")
    null_receipt = _mapping(seed.get("whole_pipeline_null"), "whole_pipeline_null")
    offsets = [
        int(value)
        for value in _sequence(null_receipt.get("circular_shift_offsets"), "circular_shift_offsets")
    ]
    regenerated = [
        int(value) for value in _rng(root, (0,)).integers(1, 913, size=256, dtype=np.uint64)
    ]
    if (
        null_receipt.get("replicates") != 256
        or null_receipt.get("draw_count") != 913
        or offsets != regenerated
        or any(value < 1 or value > 912 for value in offsets)
    ):
        raise LagFrequencyRunnerError("whole-pipeline null offsets do not replay")
    randomization = _mapping(details.get("randomization"), "randomization")
    if (
        str(randomization.get("root_entropy_decimal")) != str(root)
        or randomization.get("numpy_version") != np.__version__
        or _mapping(
            randomization.get("whole_pipeline_null"), "randomization.whole_pipeline_null"
        ).get("replicates")
        != 256
    ):
        raise LagFrequencyRunnerError("protocol and seed receipt randomization disagree")
    bootstrap = _mapping(
        randomization.get("moving_circular_block_bootstrap"),
        "moving_circular_block_bootstrap",
    )
    if (
        list(_sequence(bootstrap.get("block_lengths"), "block_lengths")) != [7, 14, 28]
        or bootstrap.get("resamples_per_variant_per_block") != 4096
    ):
        raise LagFrequencyRunnerError("bootstrap contract is not the frozen 7/14/28 x 4096")


def verify_lag_frequency_materials(
    protocol_pin_path: Path,
    *,
    expected_protocol_pin_sha256: str,
    expected_active_parent_sha256: str,
    protocol_details_path: Path,
    expected_protocol_details_sha256: str,
    seed_receipt_path: Path,
    expected_seed_receipt_sha256: str,
    dataset_split_path: Path,
    expected_dataset_split_sha256: str,
) -> dict[str, Any]:
    """Verify the exact pin and every runner-owned sibling before scoring."""

    protocol_pin_path = Path(protocol_pin_path)
    siblings = {
        Path(protocol_details_path).parent,
        Path(seed_receipt_path).parent,
        Path(dataset_split_path).parent,
        protocol_pin_path.parent,
    }
    if len({path.resolve() for path in siblings}) != 1:
        raise LagFrequencyRunnerError("runner materials must share one Episode directory")
    admission = verify_science_episode_admission_file(
        protocol_pin_path,
        expected_file_sha256=expected_protocol_pin_sha256,
        expected_active_parent_sha256=expected_active_parent_sha256,
    )
    details = _read_json(
        Path(protocol_details_path),
        expected_protocol_details_sha256,
        "protocol details",
    )
    seed = _read_json(Path(seed_receipt_path), expected_seed_receipt_sha256, "seed receipt")
    split = _read_json(Path(dataset_split_path), expected_dataset_split_sha256, "dataset split")
    if details.get("schema_version") != DETAILS_SCHEMA_VERSION:
        raise LagFrequencyRunnerError("unsupported protocol details schema")
    if split.get("schema_version") != SPLIT_SCHEMA_VERSION:
        raise LagFrequencyRunnerError("unsupported dataset split schema")
    episode_id = str(admission["episode_id"])
    if details.get("episode_id") != episode_id or seed.get("episode_id") != episode_id:
        raise LagFrequencyRunnerError("Episode identity differs across frozen materials")
    bindings = _mapping(details.get("frozen_bindings"), "frozen_bindings")
    if bindings.get("dataset_split_sha256") != expected_dataset_split_sha256 or bindings.get(
        "dataset_split_id"
    ) != split.get("split_id"):
        raise LagFrequencyRunnerError("dataset split is not bound by protocol details")
    randomization = _mapping(details.get("randomization"), "randomization")
    if randomization.get("seed_receipt_sha256") != expected_seed_receipt_sha256:
        raise LagFrequencyRunnerError("seed receipt is not bound by protocol details")
    if (
        _mapping(details.get("prospective_boundary"), "prospective_boundary").get(
            "evaluation_outcome_access"
        )
        is not False
    ):
        raise LagFrequencyRunnerError("protocol permits prospective outcome access")
    _validate_frozen_variants(details)
    _validate_seed_receipt(seed, details)
    windows = list(_sequence(split.get("windows"), "dataset_split.windows"))
    if len(windows) != 4 or split.get("historical_confirmation_claim_allowed") is not False:
        raise LagFrequencyRunnerError("dataset split is not the frozen four-window exploration")
    return {
        "admission": admission,
        "details": details,
        "seed_receipt": seed,
        "dataset_split": split,
        "protocol_pin_path": str(protocol_pin_path),
        "protocol_pin_sha256": expected_protocol_pin_sha256,
        "protocol_details_path": str(Path(protocol_details_path)),
        "protocol_details_sha256": expected_protocol_details_sha256,
        "seed_receipt_path": str(Path(seed_receipt_path)),
        "seed_receipt_sha256": expected_seed_receipt_sha256,
        "dataset_split_path": str(Path(dataset_split_path)),
        "dataset_split_sha256": expected_dataset_split_sha256,
    }


def canonical_ordered_draws(draws: Sequence[DrawRecord]) -> list[DrawRecord]:
    """Return the frozen `(openTime, expect)` order and reject identity drift."""

    ordered = sorted(draws, key=lambda draw: (draw.openTime, draw.expect))
    if len(ordered) != 913:
        raise LagFrequencyRunnerError("lag-frequency protocol requires exactly 913 draws")
    if len({draw.expect for draw in ordered}) != 913:
        raise LagFrequencyRunnerError("draw identities are not unique")
    if ordered[0].expect != "2024001" or ordered[-1].expect != "2026182":
        raise LagFrequencyRunnerError("draw range does not match the frozen world")
    if any(left.openTime >= right.openTime for left, right in pairwise(ordered)):
        raise LagFrequencyRunnerError("draw openTime order is not strictly increasing")
    return ordered


def lag_predictions(
    outcomes: np.ndarray[Any, np.dtype[np.int64]],
    *,
    window: int,
    direction: str,
) -> tuple[np.ndarray[Any, np.dtype[np.int64]], np.ndarray[Any, np.dtype[np.bool_]]]:
    """Compute lag-only predictions with the smallest-number tie break."""

    values = np.asarray(outcomes, dtype=np.int64)
    if values.ndim != 1 or len(values) <= window or np.any((values < 1) | (values > 49)):
        raise LagFrequencyRunnerError("lag prediction input is outside 1..49 or too short")
    if direction not in {"least_frequent", "most_frequent"}:
        raise LagFrequencyRunnerError("unsupported lag-frequency direction")
    predictions = np.zeros(len(values), dtype=np.int64)
    eligible = np.zeros(len(values), dtype=np.bool_)
    counts = np.bincount(values[:window], minlength=50).astype(np.int64)
    for index in range(window, len(values)):
        frequencies = counts[1:50]
        target = frequencies.min() if direction == "least_frequent" else frequencies.max()
        predictions[index] = int(np.flatnonzero(frequencies == target)[0]) + 1
        eligible[index] = True
        if index + 1 < len(values):
            counts[int(values[index - window])] -= 1
            counts[int(values[index])] += 1
    return predictions, eligible


def _payoff_constants() -> tuple[float, float]:
    hit = settle_special_number(
        selected_number=1,
        actual_special_number=1,
        panel="A",
        stake="1.0000",
    )
    miss = settle_special_number(
        selected_number=1,
        actual_special_number=2,
        panel="A",
        stake="1.0000",
    )
    hit_value = Decimal(hit.realized_gain) - Decimal(hit.realized_loss)
    miss_value = Decimal(miss.realized_gain) - Decimal(miss.realized_loss)
    return float(hit_value), float(miss_value)


def payoff_vector(
    predictions: np.ndarray[Any, np.dtype[np.int64]],
    targets: np.ndarray[Any, np.dtype[np.int64]],
    eligible: np.ndarray[Any, np.dtype[np.bool_]],
) -> np.ndarray[Any, np.dtype[np.float64]]:
    """Settle a prediction vector at the current A/default unit coordinate."""

    if predictions.shape != targets.shape or targets.shape != eligible.shape:
        raise LagFrequencyRunnerError("prediction, target, and eligibility shapes differ")
    hit_value, miss_value = _payoff_constants()
    return np.where(predictions[eligible] == targets[eligible], hit_value, miss_value).astype(
        np.float64
    )


def moving_circular_block_lower_bound(
    values: np.ndarray[Any, np.dtype[np.float64]],
    *,
    root_entropy: int,
    variant_index: int,
    block_length: int,
    resamples: int = 4096,
) -> tuple[float, str]:
    """Return the frozen one-sided 90% lower bound and bootstrap-vector hash."""

    vector = np.asarray(values, dtype=np.float64)
    if vector.ndim != 1 or len(vector) < 1:
        raise LagFrequencyRunnerError("bootstrap vector must be nonempty")
    if block_length not in {7, 14, 28} or resamples != 4096:
        raise LagFrequencyRunnerError("bootstrap call differs from the frozen contract")
    block_count = math.ceil(len(vector) / block_length)
    generator = _rng(root_entropy, (2, variant_index, block_length))
    starts = generator.integers(
        0,
        len(vector),
        size=(resamples, block_count),
        dtype=np.int64,
    )
    offsets = np.arange(block_length, dtype=np.int64)
    indices = (starts[:, :, None] + offsets[None, None, :]) % len(vector)
    indices = indices.reshape(resamples, -1)[:, : len(vector)]
    means = vector[indices].mean(axis=1)
    lower_bound = float(np.quantile(means, 0.10, method="linear"))
    return lower_bound, canonical_sha256([_number(value) for value in means])


def concentration_share(values: np.ndarray[Any, np.dtype[np.float64]]) -> float:
    """Return the frozen positive-contribution concentration statistic."""

    positive = np.asarray(values, dtype=np.float64)
    positive = positive[positive > 0]
    if len(positive) == 0:
        return 1.0
    return float(positive.max() / positive.sum())


def family_null_decision(
    observed_primary: float,
    null_family_maxima: Sequence[float],
) -> tuple[float, float, bool]:
    """Apply the frozen finite-Monte-Carlo p-value and higher-quantile gate."""

    maxima = np.asarray(null_family_maxima, dtype=np.float64)
    if maxima.shape != (256,) or not np.all(np.isfinite(maxima)):
        raise LagFrequencyRunnerError("family null must contain 256 finite maxima")
    threshold = float(np.quantile(maxima, 0.90, method="higher"))
    pvalue = (1 + int(np.count_nonzero(maxima >= observed_primary))) / 257
    return pvalue, threshold, pvalue <= 0.10 and observed_primary >= threshold


def ordered_terminal_label(
    candidates: Sequence[Mapping[str, Any]],
    *,
    any_empty_window: bool,
) -> str:
    """Return the first matching family label in the frozen priority order."""

    if any(bool(item["support_pass"]) for item in candidates):
        return TERMINAL_LABELS[0]
    refuted = all(
        float(item["primary_statistic"]) <= 0
        or (
            float(item["primary_statistic"]) > 0
            and (not bool(item["block_pass"]) or float(item["concentration_share"]) > 0.25)
        )
        for item in candidates
    )
    if refuted:
        return TERMINAL_LABELS[1]
    if any_empty_window:
        return TERMINAL_LABELS[2]
    return TERMINAL_LABELS[3]


def historical_window_means(
    *,
    draws: Sequence[DrawRecord],
    eligible: np.ndarray[Any, np.dtype[np.bool_]],
    values: np.ndarray[Any, np.dtype[np.float64]],
    dataset_split: Mapping[str, Any],
) -> dict[str, float | None]:
    """Map eligible primary increments into the four inclusive frozen windows."""

    eligible_indices = np.flatnonzero(eligible)
    if len(eligible_indices) != len(values):
        raise LagFrequencyRunnerError("eligible rows and metric vector disagree")
    dates = np.asarray([draw.openTime[:10] for draw in draws], dtype=object)
    result: dict[str, float | None] = {}
    for raw_window in _sequence(dataset_split.get("windows"), "dataset_split.windows"):
        window = _mapping(raw_window, "dataset_split.window")
        window_id = str(window.get("window_id"))
        start = str(window.get("start_date"))
        end = str(window.get("end_date"))
        mask = (dates[eligible_indices] >= start) & (dates[eligible_indices] <= end)
        result[window_id] = float(values[mask].mean()) if np.any(mask) else None
    return result


def _identity_rows(
    details: Mapping[str, Any],
    seed_receipt: Mapping[str, Any],
) -> list[dict[str, Any]]:
    variants = _validate_frozen_variants(details)
    rows = [
        {
            "identity_kind": "PRIMARY",
            "work_key": str(variant["work_key"]),
            "registration_event_id": str(variant["registration_event_id"]),
            "family_id": PRIMARY_FAMILY_ID,
            "equivalence_cluster_id": str(variant["equivalence_cluster_id"]),
            "path_kind": "PRIMARY",
            "trial_id": str(variant["trial_id"]),
            "variant_index": int(variant["variant_index"]),
            "rolling_window_draws": int(variant["rolling_window_draws"]),
            "direction": str(variant["direction"]),
        }
        for variant in variants
    ]
    offsets = [
        int(value)
        for value in _sequence(
            _mapping(seed_receipt.get("whole_pipeline_null"), "whole_pipeline_null").get(
                "circular_shift_offsets"
            ),
            "circular_shift_offsets",
        )
    ]
    episode_id = str(details["episode_id"])
    for index, offset in enumerate(offsets, start=1):
        work_key = f"science-trial:{episode_id}:null-shift-{index:03d}"
        rows.append(
            {
                "identity_kind": "NEGATIVE_CONTROL",
                "work_key": work_key,
                "registration_event_id": f"{work_key}:REGISTERED",
                "family_id": NULL_FAMILY_ID,
                "equivalence_cluster_id": NULL_FAMILY_ID,
                "path_kind": "NEGATIVE_CONTROL",
                "null_replicate_index": index,
                "circular_shift_offset": offset,
            }
        )
    if len(rows) != 262:
        raise LagFrequencyRunnerError("runner identity set must contain 6 + 256 work keys")
    return rows


def _identity_meta(
    identity: Mapping[str, Any],
    *,
    materials: Mapping[str, Any],
    world_root: Path,
    world_content_hash: str,
    historical_score_accessed: bool,
    event_id: str,
    result_ref: str | None = None,
    result_file_sha256: str | None = None,
    result_content_hash: str | None = None,
) -> dict[str, Any]:
    meta = {
        key: value
        for key, value in identity.items()
        if key
        not in {
            "identity_kind",
            "work_key",
            "registration_event_id",
            "family_id",
            "equivalence_cluster_id",
            "path_kind",
        }
    }
    meta.update(
        {
            "event_id": event_id,
            "protocol_pin_ref": materials["protocol_pin_path"],
            "protocol_pin_sha256": materials["protocol_pin_sha256"],
            "protocol_details_ref": materials["protocol_details_path"],
            "protocol_details_sha256": materials["protocol_details_sha256"],
            "seed_receipt_ref": materials["seed_receipt_path"],
            "seed_receipt_sha256": materials["seed_receipt_sha256"],
            "world_root": str(world_root),
            "world_content_hash": world_content_hash,
            "historical_score_accessed": historical_score_accessed,
            "evaluation_outcome_access": False,
        }
    )
    if result_ref is not None:
        meta.update(
            {
                "result_ref": result_ref,
                "result_file_sha256": result_file_sha256,
                "result_content_hash": result_content_hash,
            }
        )
    return meta


def _latest_statuses(entries: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for entry in entries:
        statuses[str(entry["work_key"])] = str(entry["status"])
    return statuses


def _assert_registration_entries(
    *,
    entries: Sequence[Mapping[str, Any]],
    identities: Sequence[Mapping[str, Any]],
    materials: Mapping[str, Any],
    world_root: Path,
    world_content_hash: str,
) -> None:
    registrations = {
        str(entry["work_key"]): entry for entry in entries if entry.get("status") == "REGISTERED"
    }
    for identity in identities:
        work_key = str(identity["work_key"])
        entry = registrations.get(work_key)
        if entry is None:
            raise LagFrequencyRunnerError(f"missing REGISTERED entry: {work_key}")
        if (
            entry.get("family_id") != identity["family_id"]
            or entry.get("equivalence_cluster_id") != identity["equivalence_cluster_id"]
            or entry.get("path_kind") != identity["path_kind"]
        ):
            raise LagFrequencyRunnerError(f"registered Trial identity mismatch: {work_key}")
        event_id = str(identity["registration_event_id"])
        expected_meta = _identity_meta(
            identity,
            materials=materials,
            world_root=world_root,
            world_content_hash=world_content_hash,
            historical_score_accessed=False,
            event_id=event_id,
        )
        observed_meta = _mapping(entry.get("meta"), "registered entry meta")
        if any(observed_meta.get(key) != value for key, value in expected_meta.items()):
            raise LagFrequencyRunnerError(f"registered Trial payload mismatch: {work_key}")


def ensure_null_trials_registered(
    *,
    materials: Mapping[str, Any],
    world_root: Path,
    world_content_hash: str,
) -> dict[str, Any]:
    """Append the 256 exact negative-control registrations under the sole writer."""

    details = _mapping(materials.get("details"), "materials.details")
    seed = _mapping(materials.get("seed_receipt"), "materials.seed_receipt")
    contract = _mapping(details.get("trial_journal_contract"), "trial_journal_contract")
    anchor = Path(str(contract.get("anchor_ref")))
    anchor_sha = str(contract.get("anchor_sha256"))
    episode_id = str(details["episode_id"])
    identities = _identity_rows(details, seed)
    head = load_science_trial_journal(
        anchor,
        expected_anchor_sha256=anchor_sha,
        episode_id=episode_id,
    )
    statuses = _latest_statuses(head["entries"])
    primary_identities = identities[:6]
    for identity in primary_identities:
        if statuses.get(str(identity["work_key"])) != "REGISTERED":
            raise LagFrequencyRunnerError("all six PRIMARY trials must be REGISTERED first")
    _assert_registration_entries(
        entries=head["entries"],
        identities=primary_identities,
        materials=materials,
        world_root=world_root,
        world_content_hash=world_content_hash,
    )
    for identity in identities[6:]:
        work_key = str(identity["work_key"])
        observed = statuses.get(work_key)
        if observed is not None:
            if observed != "REGISTERED":
                raise LagFrequencyRunnerError(f"null trial already advanced: {work_key}")
            continue
        event_id = str(identity["registration_event_id"])
        append_science_trial_entry(
            anchor,
            expected_anchor_sha256=anchor_sha,
            episode_id=episode_id,
            event_id=event_id,
            work_key=work_key,
            status="REGISTERED",
            family_id=str(identity["family_id"]),
            equivalence_cluster_id=str(identity["equivalence_cluster_id"]),
            path_kind=str(identity["path_kind"]),
            failure_reason=None,
            meta=_identity_meta(
                identity,
                materials=materials,
                world_root=world_root,
                world_content_hash=world_content_hash,
                historical_score_accessed=False,
                event_id=event_id,
            ),
            expected_entry_count=int(head["entry_count"]),
            expected_entries_sha256=str(head["entries_sha256"]),
            terminal=False,
        )
        head = load_science_trial_journal(
            anchor,
            expected_anchor_sha256=anchor_sha,
            episode_id=episode_id,
        )
        statuses[work_key] = "REGISTERED"
    _assert_registration_entries(
        entries=head["entries"],
        identities=identities,
        materials=materials,
        world_root=world_root,
        world_content_hash=world_content_hash,
    )
    return head


def transition_lag_frequency_trials(
    *,
    materials: Mapping[str, Any],
    world_root: Path,
    world_content_hash: str,
    status: str,
    result_ref: str | None = None,
    result_file_sha256: str | None = None,
    result_content_hash: str | None = None,
    failure_reason: str | None = None,
    historical_score_accessed: bool | None = None,
) -> dict[str, Any]:
    """Advance all 262 frozen identities through one idempotent CAS transition."""

    target = status.upper()
    if target not in {"RUNNING", "SUCCEEDED", "FAILED"}:
        raise LagFrequencyRunnerError("unsupported family transition")
    terminal = target in {"SUCCEEDED", "FAILED"}
    if target == "SUCCEEDED" and (
        not result_ref or not result_file_sha256 or not result_content_hash
    ):
        raise LagFrequencyRunnerError("SUCCEEDED requires the exact result identities")
    if target == "SUCCEEDED":
        result_path = Path(str(result_ref))
        if not result_path.is_file() or sha256_file(result_path) != result_file_sha256:
            raise LagFrequencyRunnerError("SUCCEEDED result file identity does not replay")
        try:
            result_payload = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LagFrequencyRunnerError("SUCCEEDED result is not valid JSON") from exc
        if not isinstance(result_payload, dict):
            raise LagFrequencyRunnerError("SUCCEEDED result must be a JSON object")
        claimed_content_hash = result_payload.pop("content_hash", None)
        if (
            claimed_content_hash != result_content_hash
            or canonical_sha256(result_payload) != result_content_hash
        ):
            raise LagFrequencyRunnerError("SUCCEEDED result content identity does not replay")
    if target == "FAILED" and not failure_reason:
        raise LagFrequencyRunnerError("FAILED requires a deterministic failure reason")
    if target == "FAILED" and not isinstance(historical_score_accessed, bool):
        raise LagFrequencyRunnerError(
            "FAILED requires an explicit historical_score_accessed boolean"
        )
    if target != "FAILED" and historical_score_accessed is not None:
        raise LagFrequencyRunnerError(
            "historical_score_accessed is caller-selectable only for FAILED"
        )
    score_accessed = target == "SUCCEEDED" or (
        target == "FAILED" and bool(historical_score_accessed)
    )
    details = _mapping(materials.get("details"), "materials.details")
    seed = _mapping(materials.get("seed_receipt"), "materials.seed_receipt")
    contract = _mapping(details.get("trial_journal_contract"), "trial_journal_contract")
    anchor = Path(str(contract.get("anchor_ref")))
    anchor_sha = str(contract.get("anchor_sha256"))
    episode_id = str(details["episode_id"])
    identities = _identity_rows(details, seed)
    head = load_science_trial_journal(
        anchor,
        expected_anchor_sha256=anchor_sha,
        episode_id=episode_id,
    )
    statuses = _latest_statuses(head["entries"])
    _assert_registration_entries(
        entries=head["entries"],
        identities=identities,
        materials=materials,
        world_root=world_root,
        world_content_hash=world_content_hash,
    )
    required_previous = "REGISTERED" if target == "RUNNING" else "RUNNING"
    for identity in identities:
        work_key = str(identity["work_key"])
        observed = statuses.get(work_key)
        if observed not in {required_previous, target}:
            raise LagFrequencyRunnerError(
                f"{work_key} must be {required_previous} before {target}; got {observed}"
            )
        event_id = f"{work_key}:{target}"
        append_science_trial_entry(
            anchor,
            expected_anchor_sha256=anchor_sha,
            episode_id=episode_id,
            event_id=event_id,
            work_key=work_key,
            status=target,
            family_id=str(identity["family_id"]),
            equivalence_cluster_id=str(identity["equivalence_cluster_id"]),
            path_kind=str(identity["path_kind"]),
            failure_reason=failure_reason if target == "FAILED" else None,
            meta=_identity_meta(
                identity,
                materials=materials,
                world_root=world_root,
                world_content_hash=world_content_hash,
                historical_score_accessed=score_accessed,
                event_id=event_id,
                result_ref=result_ref,
                result_file_sha256=result_file_sha256,
                result_content_hash=result_content_hash,
            ),
            expected_entry_count=int(head["entry_count"]),
            expected_entries_sha256=str(head["entries_sha256"]),
            terminal=terminal,
        )
        head = load_science_trial_journal(
            anchor,
            expected_anchor_sha256=anchor_sha,
            episode_id=episode_id,
        )
        statuses[work_key] = target
    return head


def _score_family(
    *,
    draws: Sequence[DrawRecord],
    details: Mapping[str, Any],
    seed_receipt: Mapping[str, Any],
    dataset_split: Mapping[str, Any],
) -> dict[str, Any]:
    ordered = canonical_ordered_draws(draws)
    outcomes = np.asarray([draw.special_number for draw in ordered], dtype=np.int64)
    root_entropy = int(_mapping(seed_receipt.get("root_entropy"), "root_entropy").get("decimal"))
    uniform = (
        _rng(root_entropy, (1,))
        .integers(
            1,
            50,
            size=len(outcomes),
            dtype=np.uint64,
        )
        .astype(np.int64)
    )
    variants = _validate_frozen_variants(details)
    prepared: list[dict[str, Any]] = []
    for variant in variants:
        predictions, eligible = lag_predictions(
            outcomes,
            window=int(variant["rolling_window_draws"]),
            direction=str(variant["direction"]),
        )
        primary = payoff_vector(predictions, outcomes, eligible)
        uniform_payoff = payoff_vector(uniform, outcomes, eligible)
        prepared.append(
            {
                "variant": variant,
                "predictions": predictions,
                "eligible": eligible,
                "primary": primary,
                "uniform_payoff": uniform_payoff,
            }
        )

    offsets = [
        int(value)
        for value in _sequence(
            _mapping(seed_receipt.get("whole_pipeline_null"), "whole_pipeline_null").get(
                "circular_shift_offsets"
            ),
            "circular_shift_offsets",
        )
    ]
    null_maxima: list[float] = []
    null_paired: list[list[str]] = []
    for offset in offsets:
        null_target = np.roll(outcomes, offset)
        candidate_statistics: list[float] = []
        paired_statistics: list[str] = []
        for item in prepared:
            candidate = payoff_vector(item["predictions"], null_target, item["eligible"])
            uniform_null = payoff_vector(uniform, null_target, item["eligible"])
            candidate_statistics.append(float(candidate.mean()))
            paired_statistics.append(_number(float((candidate - uniform_null).mean())))
        null_maxima.append(max(candidate_statistics))
        null_paired.append(paired_statistics)
    threshold = float(np.quantile(np.asarray(null_maxima), 0.90, method="higher"))

    candidate_results: list[dict[str, Any]] = []
    any_empty_window = False
    for item in prepared:
        variant = item["variant"]
        primary = item["primary"]
        eligible = item["eligible"]
        predictions = item["predictions"]
        lower_bounds: dict[str, str] = {}
        bootstrap_hashes: dict[str, str] = {}
        for block_length in (7, 14, 28):
            lower, vector_hash = moving_circular_block_lower_bound(
                primary,
                root_entropy=root_entropy,
                variant_index=int(variant["variant_index"]),
                block_length=block_length,
            )
            lower_bounds[str(block_length)] = _number(lower)
            bootstrap_hashes[str(block_length)] = vector_hash
        windows = historical_window_means(
            draws=ordered,
            eligible=eligible,
            values=primary,
            dataset_split=dataset_split,
        )
        empty_window = any(value is None for value in windows.values())
        any_empty_window = any_empty_window or empty_window
        primary_statistic = float(primary.mean())
        concentration = concentration_share(primary)
        pvalue, candidate_threshold, family_pass = family_null_decision(
            primary_statistic,
            null_maxima,
        )
        if candidate_threshold != threshold:
            raise LagFrequencyRunnerError("family threshold changed across candidates")
        block_pass = all(float(value) > 0 for value in lower_bounds.values())
        window_pass = not empty_window and all(
            value is not None and value > 0 for value in windows.values()
        )
        support = (
            primary_statistic >= 0.02
            and block_pass
            and family_pass
            and concentration <= 0.25
            and window_pass
        )
        candidate_results.append(
            {
                "trial_id": variant["trial_id"],
                "work_key": variant["work_key"],
                "variant_index": variant["variant_index"],
                "rolling_window_draws": variant["rolling_window_draws"],
                "direction": variant["direction"],
                "eligible_count": int(np.count_nonzero(eligible)),
                "prediction_sha256": canonical_sha256([int(value) for value in predictions]),
                "primary_increment_sha256": canonical_sha256([_number(value) for value in primary]),
                "primary_statistic": _number(primary_statistic),
                "hit_rate": _number(float((predictions[eligible] == outcomes[eligible]).mean())),
                "paired_minus_uniform_mean": _number(
                    float((primary - item["uniform_payoff"]).mean())
                ),
                "block_lower_bounds": lower_bounds,
                "bootstrap_means_sha256": bootstrap_hashes,
                "block_pass": block_pass,
                "concentration_share": _number(concentration),
                "historical_window_primary_means": {
                    key: _number(value) if value is not None else None
                    for key, value in windows.items()
                },
                "window_stability_pass": window_pass,
                "family_pvalue": _number(pvalue),
                "family_threshold_090": _number(threshold),
                "family_null_pass": family_pass,
                "support_pass": support,
                "dependence_proxy_floor_n_over_28": int(len(primary) // 28),
            }
        )

    terminal_label = ordered_terminal_label(
        candidate_results,
        any_empty_window=any_empty_window,
    )

    return {
        "draw_count": len(ordered),
        "observed_special_number_sha256": canonical_sha256([int(value) for value in outcomes]),
        "uniform_prediction_sha256": canonical_sha256([int(value) for value in uniform]),
        "candidate_count": len(candidate_results),
        "candidates": candidate_results,
        "whole_pipeline_null": {
            "replicate_count": len(null_maxima),
            "family_maxima": [_number(value) for value in null_maxima],
            "family_maxima_sha256": canonical_sha256([_number(value) for value in null_maxima]),
            "paired_candidate_minus_uniform_matrix_sha256": canonical_sha256(null_paired),
            "threshold_090_method_higher": _number(threshold),
        },
        "terminal_label": terminal_label,
        "maximum_claim_grade": "E2_HISTORICAL_EXPLORATORY",
        "historical_score_accessed": True,
        "future_outcome_accessed": False,
        "research_result_claimed": False,
    }


def run_lag_frequency_protocol(
    protocol_pin_path: Path,
    *,
    expected_protocol_pin_sha256: str,
    expected_active_parent_sha256: str,
    protocol_details_path: Path,
    expected_protocol_details_sha256: str,
    seed_receipt_path: Path,
    expected_seed_receipt_sha256: str,
    dataset_split_path: Path,
    expected_dataset_split_sha256: str,
    world_root: Path,
    expected_world_content_hash: str,
) -> dict[str, Any]:
    """Verify, score, and atomically publish one deterministic blind-score artifact."""

    materials = verify_lag_frequency_materials(
        protocol_pin_path,
        expected_protocol_pin_sha256=expected_protocol_pin_sha256,
        expected_active_parent_sha256=expected_active_parent_sha256,
        protocol_details_path=protocol_details_path,
        expected_protocol_details_sha256=expected_protocol_details_sha256,
        seed_receipt_path=seed_receipt_path,
        expected_seed_receipt_sha256=expected_seed_receipt_sha256,
        dataset_split_path=dataset_split_path,
        expected_dataset_split_sha256=expected_dataset_split_sha256,
    )
    world_root = Path(world_root)
    replay = replay_science_episode_world(
        world_root,
        protocol_pin_path=Path(protocol_pin_path),
        protocol_pin_sha256=expected_protocol_pin_sha256,
    )
    if (
        replay.get("ok") is not True
        or replay.get("world_content_hash") != expected_world_content_hash
    ):
        raise LagFrequencyRunnerError("science world replay or content identity failed")
    details = _mapping(materials["details"], "materials.details")
    contract = _mapping(details.get("trial_journal_contract"), "trial_journal_contract")
    head = load_science_trial_journal(
        Path(str(contract.get("anchor_ref"))),
        expected_anchor_sha256=str(contract.get("anchor_sha256")),
        episode_id=str(details["episode_id"]),
    )
    expected_work_keys = {
        str(identity["work_key"])
        for identity in _identity_rows(details, _mapping(materials["seed_receipt"], "seed"))
    }
    statuses = _latest_statuses(head["entries"])
    identities = _identity_rows(details, _mapping(materials["seed_receipt"], "seed"))
    _assert_registration_entries(
        entries=head["entries"],
        identities=identities,
        materials=materials,
        world_root=world_root,
        world_content_hash=expected_world_content_hash,
    )
    if set(statuses) != expected_work_keys or any(
        statuses[work_key] != "RUNNING" for work_key in expected_work_keys
    ):
        raise LagFrequencyRunnerError(
            "all 262 frozen identities must be RUNNING before score access"
        )
    score = _score_family(
        draws=load_draws(),
        details=details,
        seed_receipt=_mapping(materials["seed_receipt"], "seed_receipt"),
        dataset_split=_mapping(materials["dataset_split"], "dataset_split"),
    )
    body: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "episode_id": details["episode_id"],
        "protocol_pin_ref": materials["protocol_pin_path"],
        "protocol_pin_sha256": materials["protocol_pin_sha256"],
        "protocol_details_ref": materials["protocol_details_path"],
        "protocol_details_sha256": materials["protocol_details_sha256"],
        "seed_receipt_ref": materials["seed_receipt_path"],
        "seed_receipt_sha256": materials["seed_receipt_sha256"],
        "dataset_split_ref": materials["dataset_split_path"],
        "dataset_split_sha256": materials["dataset_split_sha256"],
        "world_root": str(world_root),
        "world_content_hash": expected_world_content_hash,
        "trial_ledger_entry_count_before_score": head["entry_count"],
        "trial_ledger_entries_sha256_before_score": head["entries_sha256"],
        **score,
    }
    body["content_hash"] = canonical_sha256(body)
    output_path = Path(protocol_pin_path).parent / RESULT_FILE_NAME
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        if existing != body:
            raise LagFrequencyRunnerError("existing blind-score artifact conflicts with replay")
    else:
        write_atomic(output_path, body)
    return {
        "result": body,
        "result_ref": str(output_path),
        "result_file_sha256": sha256_file(output_path),
        "result_content_hash": body["content_hash"],
    }


__all__ = [
    "RESULT_FILE_NAME",
    "RESULT_SCHEMA_VERSION",
    "LagFrequencyRunnerError",
    "canonical_ordered_draws",
    "concentration_share",
    "ensure_null_trials_registered",
    "family_null_decision",
    "historical_window_means",
    "lag_predictions",
    "moving_circular_block_lower_bound",
    "ordered_terminal_label",
    "payoff_vector",
    "run_lag_frequency_protocol",
    "transition_lag_frequency_trials",
    "verify_lag_frequency_materials",
]
