"""Pure, fail-closed qualification for cold contrastive Taste candidates.

This module deliberately performs no retrieval, model invocation, mutation, or
trajectory I/O.  It only validates caller-supplied, content-addressed evidence.
Candidate, outcome, and receipt self-hashes are SHA-256 over the repository's
canonical JSON encoding with only the corresponding self-hash field omitted.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from services.agent_runtime.execution_contract import canonical_json_bytes

TASTE_CANDIDATE_SCHEMA = "xinao.taste_qualification_candidate.v1"
TASTE_OUTCOME_SCHEMA = "xinao.taste_qualification_outcome.v1"
TASTE_RECEIPT_SCHEMA = "xinao.taste_qualification_receipt.v1"
TASTE_RUBRIC_SCHEMA = "xinao.taste_qualification_rubric.v1"

_MODE = "cold_contrastive_same_prefix_twins"
_ARMS = frozenset({"baseline", "treatment"})
_NON_DEGRADATION_METRICS = (
    "required_tool_use",
    "bounded_action",
    "open_representation_revision",
    "world_revision",
)
_ALL_METRICS = ("target_failure", *_NON_DEGRADATION_METRICS)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RUBRIC = {
    "schema_version": TASTE_RUBRIC_SCHEMA,
    "scores": {
        "target_failure": "non-negative integer; lower is better",
        "required_tool_use": "non-negative ordinal; higher is better",
        "bounded_action": "non-negative ordinal; higher is better",
        "open_representation_revision": "non-negative ordinal; higher is better",
        "world_revision": "non-negative ordinal; higher is better",
    },
}
TASTE_RUBRIC_SHA256 = hashlib.sha256(canonical_json_bytes(_RUBRIC)).hexdigest()


class TasteQualificationError(ValueError):
    """A candidate, sealed outcome, or comparison failed closed."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(reason_code: str, message: str) -> None:
    raise TasteQualificationError(reason_code, message)


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("INPUT_INVALID", f"{field} must be an object")
    return dict(value)


def _exact_keys(
    value: Mapping[str, object], expected: set[str] | frozenset[str], field: str
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        _fail("EVIDENCE_MISSING", f"{field} is missing fields: {', '.join(missing)}")
    if extra:
        _fail("INPUT_INVALID", f"{field} has unsupported fields: {', '.join(extra)}")


def _identity_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _fail("INPUT_INVALID", f"{field} must be a non-empty exact string")
    return value


def _continuation_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        _fail("INPUT_INVALID", f"{field} must be non-empty text")
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        _fail("INPUT_INVALID", f"{field} must be a lowercase SHA-256")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail("INPUT_INVALID", f"{field} must be an integer >= {minimum}")
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        _fail("EVIDENCE_MISSING", f"{field} must be an explicit boolean")
    return value


def _content_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _verify_self_hash(value: Mapping[str, object], field: str) -> str:
    observed = _sha256(value.get(field), field)
    unsigned = dict(value)
    unsigned.pop(field, None)
    if _content_sha256(unsigned) != observed:
        _fail("HASH_MISMATCH", f"{field} does not seal the canonical record")
    return observed


def _seal(value: Mapping[str, object], field: str) -> dict[str, Any]:
    sealed = dict(value)
    sealed[field] = _content_sha256(sealed)
    return sealed


_SOURCE_REF_KEYS = frozenset(
    {"source_ref", "byte_sha256", "byte_length", "rollout_locator", "ordinal"}
)


def _source_ref(value: object, field: str) -> dict[str, object]:
    raw = _mapping(value, field)
    _exact_keys(raw, _SOURCE_REF_KEYS, field)
    return {
        "source_ref": _identity_text(raw["source_ref"], f"{field}.source_ref"),
        "byte_sha256": _sha256(raw["byte_sha256"], f"{field}.byte_sha256"),
        "byte_length": _integer(raw["byte_length"], f"{field}.byte_length", minimum=1),
        "rollout_locator": _identity_text(raw["rollout_locator"], f"{field}.rollout_locator"),
        "ordinal": _integer(raw["ordinal"], f"{field}.ordinal", minimum=1),
    }


def _prefix_from_sources(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        _fail("EVIDENCE_MISSING", f"{field} must contain ordered exact source refs")
    sources = [_source_ref(item, f"{field}[{index}]") for index, item in enumerate(value)]
    identities = [(row["rollout_locator"], row["ordinal"]) for row in sources]
    if len(set(identities)) != len(identities):
        _fail("INPUT_INVALID", f"{field} contains duplicate rollout locator/ordinal refs")
    return {"sources": sources, "prefix_sha256": _content_sha256(sources)}


def _prefix_envelope(value: object, field: str) -> dict[str, object]:
    raw = _mapping(value, field)
    _exact_keys(raw, frozenset({"sources", "prefix_sha256"}), field)
    normalized = _prefix_from_sources(raw["sources"], f"{field}.sources")
    if _sha256(raw["prefix_sha256"], f"{field}.prefix_sha256") != normalized["prefix_sha256"]:
        _fail("HASH_MISMATCH", f"{field}.prefix_sha256 does not bind its ordered refs")
    return normalized


def _continuation_input(value: object, field: str) -> tuple[dict[str, str], dict[str, object]]:
    raw = _mapping(value, field)
    expected = frozenset({"text", "source"})
    _exact_keys(raw, expected, field)
    text = _continuation_text(raw["text"], f"{field}.text")
    continuation = {"text": text, "utf8_sha256": hashlib.sha256(text.encode()).hexdigest()}
    return continuation, _source_ref(raw["source"], f"{field}.source")


def _continuation(value: object, field: str) -> dict[str, str]:
    raw = _mapping(value, field)
    _exact_keys(raw, frozenset({"text", "utf8_sha256"}), field)
    text = _continuation_text(raw["text"], f"{field}.text")
    observed = _sha256(raw["utf8_sha256"], f"{field}.utf8_sha256")
    if hashlib.sha256(text.encode()).hexdigest() != observed:
        _fail("HASH_MISMATCH", f"{field}.utf8_sha256 does not bind its UTF-8 text")
    return {"text": text, "utf8_sha256": observed}


def _identities(value: object, field: str) -> dict[str, str]:
    raw = _mapping(value, field)
    _exact_keys(raw, frozenset({"model", "body", "config"}), field)
    return {key: _identity_text(raw[key], f"{field}.{key}") for key in ("model", "body", "config")}


def _conditions(value: object, field: str) -> dict[str, str]:
    raw = _mapping(value, field)
    _exact_keys(raw, frozenset({"baseline", "treatment"}), field)
    result = {arm: _sha256(raw[arm], f"{field}.{arm}") for arm in ("baseline", "treatment")}
    if result["baseline"] == result["treatment"]:
        _fail("CONDITION_MISMATCH", "baseline and treatment cold conditions must be distinct")
    return result


def build_taste_candidate(
    *,
    baseline_prefix: Sequence[Mapping[str, object]],
    treatment_prefix: Sequence[Mapping[str, object]],
    bad_continuation: Mapping[str, object],
    desired_continuation: Mapping[str, object],
    model_identity: str,
    body_identity: str,
    config_identity: str,
    baseline_condition_sha256: str,
    treatment_condition_sha256: str,
) -> dict[str, Any]:
    """Build a sealed candidate without executing or modifying either arm."""

    bad, bad_source = _continuation_input(bad_continuation, "bad_continuation")
    desired, desired_source = _continuation_input(desired_continuation, "desired_continuation")
    core: dict[str, object] = {
        "schema_version": TASTE_CANDIDATE_SCHEMA,
        "authority": False,
        "completion_claim_allowed": False,
        "mode": _MODE,
        "live_retrieval_allowed": False,
        "hot_mutation_allowed": False,
        "identities": {
            "model": model_identity,
            "body": body_identity,
            "config": config_identity,
        },
        "conditions": {
            "baseline": baseline_condition_sha256,
            "treatment": treatment_condition_sha256,
        },
        "baseline_prefix": _prefix_from_sources(baseline_prefix, "baseline_prefix"),
        "treatment_prefix": _prefix_from_sources(treatment_prefix, "treatment_prefix"),
        "offline_oracle": {
            "mode": "offline_only",
            "available_to_baseline": False,
            "available_to_treatment": False,
            "bad_continuation": bad,
            "desired_continuation": desired,
            "source_provenance": {
                "bad_continuation": bad_source,
                "desired_continuation": desired_source,
            },
        },
        "evaluation_rubric": {
            "schema_version": TASTE_RUBRIC_SCHEMA,
            "rubric_sha256": TASTE_RUBRIC_SHA256,
        },
    }
    return validate_taste_candidate(_seal(core, "candidate_sha256"))


def validate_taste_candidate(value: Mapping[str, object]) -> dict[str, Any]:
    """Validate content identity and the cold same-prefix candidate contract."""

    raw = _mapping(value, "candidate")
    _exact_keys(
        raw,
        frozenset(
            {
                "schema_version",
                "authority",
                "completion_claim_allowed",
                "mode",
                "live_retrieval_allowed",
                "hot_mutation_allowed",
                "identities",
                "conditions",
                "baseline_prefix",
                "treatment_prefix",
                "offline_oracle",
                "evaluation_rubric",
                "candidate_sha256",
            }
        ),
        "candidate",
    )
    candidate_sha256 = _verify_self_hash(raw, "candidate_sha256")
    if raw["schema_version"] != TASTE_CANDIDATE_SCHEMA or raw["mode"] != _MODE:
        _fail("INPUT_INVALID", "unsupported Taste candidate schema or mode")
    if (
        _boolean(raw["authority"], "candidate.authority")
        or _boolean(raw["completion_claim_allowed"], "candidate.completion_claim_allowed")
        or _boolean(raw["live_retrieval_allowed"], "candidate.live_retrieval_allowed")
        or _boolean(raw["hot_mutation_allowed"], "candidate.hot_mutation_allowed")
    ):
        _fail("POLICY_VIOLATION", "candidate must remain non-authoritative and cold-only")

    identities = _identities(raw["identities"], "candidate.identities")
    conditions = _conditions(raw["conditions"], "candidate.conditions")
    baseline_prefix = _prefix_envelope(raw["baseline_prefix"], "candidate.baseline_prefix")
    treatment_prefix = _prefix_envelope(raw["treatment_prefix"], "candidate.treatment_prefix")
    if baseline_prefix != treatment_prefix:
        _fail("PREFIX_MISMATCH", "baseline and treatment prefixes are not byte-identical twins")

    oracle = _mapping(raw["offline_oracle"], "candidate.offline_oracle")
    _exact_keys(
        oracle,
        frozenset(
            {
                "mode",
                "available_to_baseline",
                "available_to_treatment",
                "bad_continuation",
                "desired_continuation",
                "source_provenance",
            }
        ),
        "candidate.offline_oracle",
    )
    if oracle["mode"] != "offline_only":
        _fail("ORACLE_LEAK", "the correction oracle must be offline-only")
    if _boolean(
        oracle["available_to_baseline"], "candidate.offline_oracle.available_to_baseline"
    ) or _boolean(
        oracle["available_to_treatment"], "candidate.offline_oracle.available_to_treatment"
    ):
        _fail("ORACLE_LEAK", "the later correction cannot be exposed to either arm")
    bad = _continuation(oracle["bad_continuation"], "candidate.offline_oracle.bad_continuation")
    desired = _continuation(
        oracle["desired_continuation"], "candidate.offline_oracle.desired_continuation"
    )
    if bad["utf8_sha256"] == desired["utf8_sha256"]:
        _fail("INPUT_INVALID", "bad and desired continuations must differ")
    provenance = _mapping(oracle["source_provenance"], "candidate.offline_oracle.source_provenance")
    _exact_keys(
        provenance,
        frozenset({"bad_continuation", "desired_continuation"}),
        "candidate.offline_oracle.source_provenance",
    )
    normalized_provenance = {
        key: _source_ref(provenance[key], f"candidate.offline_oracle.source_provenance.{key}")
        for key in ("bad_continuation", "desired_continuation")
    }
    if normalized_provenance["bad_continuation"] == normalized_provenance["desired_continuation"]:
        _fail("INPUT_INVALID", "bad and desired continuation provenance must differ")

    rubric = _mapping(raw["evaluation_rubric"], "candidate.evaluation_rubric")
    _exact_keys(rubric, frozenset({"schema_version", "rubric_sha256"}), "evaluation_rubric")
    if (
        rubric["schema_version"] != TASTE_RUBRIC_SCHEMA
        or _sha256(rubric["rubric_sha256"], "evaluation_rubric.rubric_sha256")
        != TASTE_RUBRIC_SHA256
    ):
        _fail("RUBRIC_MISMATCH", "candidate does not bind the fixed Taste rubric")

    return {
        "schema_version": TASTE_CANDIDATE_SCHEMA,
        "authority": False,
        "completion_claim_allowed": False,
        "mode": _MODE,
        "live_retrieval_allowed": False,
        "hot_mutation_allowed": False,
        "identities": identities,
        "conditions": conditions,
        "baseline_prefix": baseline_prefix,
        "treatment_prefix": treatment_prefix,
        "offline_oracle": {
            "mode": "offline_only",
            "available_to_baseline": False,
            "available_to_treatment": False,
            "bad_continuation": bad,
            "desired_continuation": desired,
            "source_provenance": normalized_provenance,
        },
        "evaluation_rubric": {
            "schema_version": TASTE_RUBRIC_SCHEMA,
            "rubric_sha256": TASTE_RUBRIC_SHA256,
        },
        "candidate_sha256": candidate_sha256,
    }


def _metric(value: object, field: str) -> dict[str, object]:
    raw = _mapping(value, field)
    _exact_keys(raw, frozenset({"score", "evidence_refs"}), field)
    evidence_raw = raw["evidence_refs"]
    if not isinstance(evidence_raw, list) or not evidence_raw:
        _fail("EVIDENCE_MISSING", f"{field}.evidence_refs must be non-empty")
    evidence = [
        _source_ref(item, f"{field}.evidence_refs[{index}]")
        for index, item in enumerate(evidence_raw)
    ]
    return {"score": _integer(raw["score"], f"{field}.score"), "evidence_refs": evidence}


def _metrics(value: object, field: str) -> dict[str, dict[str, object]]:
    raw = _mapping(value, field)
    _exact_keys(raw, frozenset(_ALL_METRICS), field)
    return {name: _metric(raw[name], f"{field}.{name}") for name in _ALL_METRICS}


def _trajectory(value: object, field: str) -> dict[str, object]:
    raw = _mapping(value, field)
    _exact_keys(raw, frozenset({"sealed", "ref"}), field)
    if not _boolean(raw["sealed"], f"{field}.sealed"):
        _fail("TRAJECTORY_UNSEALED", f"{field} is not sealed")
    return {"sealed": True, "ref": _source_ref(raw["ref"], f"{field}.ref")}


def _hot_mutations(value: object, field: str) -> dict[str, bool]:
    raw = _mapping(value, field)
    _exact_keys(raw, frozenset({"prompt", "skill", "agents"}), field)
    result = {key: _boolean(raw[key], f"{field}.{key}") for key in ("prompt", "skill", "agents")}
    if any(result.values()):
        _fail("HOT_MUTATION", "prompt, Skill, and AGENTS mutations are forbidden in a cold run")
    return result


def build_sealed_taste_outcome(
    *,
    candidate: Mapping[str, object],
    arm: str,
    condition_sha256: str,
    run_id: str,
    fresh_run: bool,
    cache_used: bool,
    observed_prefix: Sequence[Mapping[str, object]],
    model_identity: str,
    body_identity: str,
    config_identity: str,
    hooks_enabled: bool,
    oracle_exposed: bool,
    live_retrieval_used: bool,
    hot_mutations: Mapping[str, object],
    trajectory: Mapping[str, object],
    metrics: Mapping[str, object],
) -> dict[str, Any]:
    """Seal one already-completed arm outcome; this function never runs an arm."""

    validated_candidate = validate_taste_candidate(candidate)
    core: dict[str, object] = {
        "schema_version": TASTE_OUTCOME_SCHEMA,
        "authority": False,
        "completion_claim_allowed": False,
        "candidate_sha256": validated_candidate["candidate_sha256"],
        "arm": arm,
        "condition_sha256": condition_sha256,
        "run": {"run_id": run_id, "fresh_run": fresh_run, "cache_used": cache_used},
        "observed_prefix": _prefix_from_sources(observed_prefix, "observed_prefix"),
        "identities": {
            "model": model_identity,
            "body": body_identity,
            "config": config_identity,
        },
        "input_controls": {
            "hooks_enabled": hooks_enabled,
            "oracle_exposed": oracle_exposed,
            "live_retrieval_used": live_retrieval_used,
            "hot_mutations": dict(hot_mutations),
        },
        "trajectory": dict(trajectory),
        "evaluation_rubric": dict(validated_candidate["evaluation_rubric"]),
        "metrics": dict(metrics),
    }
    return validate_sealed_taste_outcome(
        _seal(core, "outcome_sha256"), candidate=validated_candidate
    )


def validate_sealed_taste_outcome(
    value: Mapping[str, object],
    *,
    candidate: Mapping[str, object],
    expected_arm: str | None = None,
) -> dict[str, Any]:
    """Validate one sealed outcome against the immutable candidate."""

    validated_candidate = validate_taste_candidate(candidate)
    raw = _mapping(value, "outcome")
    _exact_keys(
        raw,
        frozenset(
            {
                "schema_version",
                "authority",
                "completion_claim_allowed",
                "candidate_sha256",
                "arm",
                "condition_sha256",
                "run",
                "observed_prefix",
                "identities",
                "input_controls",
                "trajectory",
                "evaluation_rubric",
                "metrics",
                "outcome_sha256",
            }
        ),
        "outcome",
    )
    outcome_sha256 = _verify_self_hash(raw, "outcome_sha256")
    if raw["schema_version"] != TASTE_OUTCOME_SCHEMA:
        _fail("INPUT_INVALID", "unsupported Taste outcome schema")
    if _boolean(raw["authority"], "outcome.authority") or _boolean(
        raw["completion_claim_allowed"], "outcome.completion_claim_allowed"
    ):
        _fail("POLICY_VIOLATION", "Taste outcomes are evidence only")
    if raw["candidate_sha256"] != validated_candidate["candidate_sha256"]:
        _fail("CANDIDATE_MISMATCH", "outcome is bound to another candidate")
    arm = _identity_text(raw["arm"], "outcome.arm")
    if arm not in _ARMS or (expected_arm is not None and arm != expected_arm):
        _fail("ARM_MISMATCH", f"unexpected Taste outcome arm: {arm}")
    condition_sha256 = _sha256(raw["condition_sha256"], "outcome.condition_sha256")
    if condition_sha256 != validated_candidate["conditions"][arm]:
        _fail("CONDITION_MISMATCH", f"{arm} outcome used another cold condition")

    run = _mapping(raw["run"], "outcome.run")
    _exact_keys(run, frozenset({"run_id", "fresh_run", "cache_used"}), "outcome.run")
    normalized_run = {
        "run_id": _identity_text(run["run_id"], "outcome.run.run_id"),
        "fresh_run": _boolean(run["fresh_run"], "outcome.run.fresh_run"),
        "cache_used": _boolean(run["cache_used"], "outcome.run.cache_used"),
    }
    if not normalized_run["fresh_run"]:
        _fail("RUN_NOT_FRESH", f"{arm} outcome is not from a fresh run")
    if normalized_run["cache_used"]:
        _fail("CACHE_USED", f"{arm} outcome used cached execution")

    observed_prefix = _prefix_envelope(raw["observed_prefix"], "outcome.observed_prefix")
    if observed_prefix != validated_candidate[f"{arm}_prefix"]:
        _fail("PREFIX_MISMATCH", f"{arm} did not observe the exact candidate prefix")
    identities = _identities(raw["identities"], "outcome.identities")
    if identities != validated_candidate["identities"]:
        _fail("IDENTITY_MISMATCH", f"{arm} model/body/config identity drifted")

    controls = _mapping(raw["input_controls"], "outcome.input_controls")
    _exact_keys(
        controls,
        frozenset({"hooks_enabled", "oracle_exposed", "live_retrieval_used", "hot_mutations"}),
        "outcome.input_controls",
    )
    hooks_enabled = _boolean(controls["hooks_enabled"], "outcome.input_controls.hooks_enabled")
    oracle_exposed = _boolean(controls["oracle_exposed"], "outcome.input_controls.oracle_exposed")
    live_retrieval_used = _boolean(
        controls["live_retrieval_used"], "outcome.input_controls.live_retrieval_used"
    )
    if hooks_enabled:
        _fail("HOOKS_ENABLED", f"{arm} ran with hooks enabled")
    if oracle_exposed:
        _fail("ORACLE_LEAK", f"{arm} saw the later correction oracle")
    if live_retrieval_used:
        _fail("LIVE_RETRIEVAL_USED", f"{arm} used live retrieval")
    hot_mutations = _hot_mutations(
        controls["hot_mutations"], "outcome.input_controls.hot_mutations"
    )
    trajectory = _trajectory(raw["trajectory"], "outcome.trajectory")

    rubric = _mapping(raw["evaluation_rubric"], "outcome.evaluation_rubric")
    _exact_keys(rubric, frozenset({"schema_version", "rubric_sha256"}), "evaluation_rubric")
    if rubric != validated_candidate["evaluation_rubric"]:
        _fail("RUBRIC_MISMATCH", f"{arm} outcome used another rubric")
    metrics = _metrics(raw["metrics"], "outcome.metrics")

    return {
        "schema_version": TASTE_OUTCOME_SCHEMA,
        "authority": False,
        "completion_claim_allowed": False,
        "candidate_sha256": validated_candidate["candidate_sha256"],
        "arm": arm,
        "condition_sha256": condition_sha256,
        "run": normalized_run,
        "observed_prefix": observed_prefix,
        "identities": identities,
        "input_controls": {
            "hooks_enabled": False,
            "oracle_exposed": False,
            "live_retrieval_used": False,
            "hot_mutations": hot_mutations,
        },
        "trajectory": trajectory,
        "evaluation_rubric": dict(validated_candidate["evaluation_rubric"]),
        "metrics": metrics,
        "outcome_sha256": outcome_sha256,
    }


def _qualified_receipt(
    candidate: Mapping[str, object],
    baseline: Mapping[str, object],
    treatment: Mapping[str, object],
) -> dict[str, Any]:
    if baseline["run"]["run_id"] == treatment["run"]["run_id"]:  # type: ignore[index]
        _fail("RUN_NOT_INDEPENDENT", "baseline and treatment must be distinct fresh runs")

    baseline_metrics = baseline["metrics"]
    treatment_metrics = treatment["metrics"]
    baseline_failure = int(baseline_metrics["target_failure"]["score"])  # type: ignore[index]
    treatment_failure = int(treatment_metrics["target_failure"]["score"])  # type: ignore[index]
    if treatment_failure >= baseline_failure:
        _fail("TARGET_FAILURE_NOT_REDUCED", "treatment did not reduce the target failure")

    comparisons: dict[str, dict[str, object]] = {
        "target_failure": {
            "baseline_score": baseline_failure,
            "treatment_score": treatment_failure,
            "improvement": baseline_failure - treatment_failure,
            "criterion": "strictly_reduced",
        }
    }
    for name in _NON_DEGRADATION_METRICS:
        baseline_score = int(baseline_metrics[name]["score"])  # type: ignore[index]
        treatment_score = int(treatment_metrics[name]["score"])  # type: ignore[index]
        if treatment_score < baseline_score:
            _fail("CAPABILITY_DEGRADED", f"treatment degraded {name}")
        comparisons[name] = {
            "baseline_score": baseline_score,
            "treatment_score": treatment_score,
            "delta": treatment_score - baseline_score,
            "criterion": "non_degraded",
        }

    core: dict[str, object] = {
        "schema_version": TASTE_RECEIPT_SCHEMA,
        "authority": False,
        "completion_claim_allowed": False,
        "qualified": True,
        "candidate_sha256": candidate["candidate_sha256"],
        "baseline_outcome_sha256": baseline["outcome_sha256"],
        "treatment_outcome_sha256": treatment["outcome_sha256"],
        "bindings": {
            "prefix_sha256": candidate["baseline_prefix"]["prefix_sha256"],  # type: ignore[index]
            "identities": dict(candidate["identities"]),  # type: ignore[arg-type]
            "conditions": dict(candidate["conditions"]),  # type: ignore[arg-type]
            "evaluation_rubric": dict(candidate["evaluation_rubric"]),  # type: ignore[arg-type]
        },
        "comparisons": comparisons,
        "cold_controls": {
            "fresh_distinct_runs": True,
            "cache_used": False,
            "hooks_enabled": False,
            "oracle_exposed": False,
            "live_retrieval_used": False,
            "hot_mutation_used": False,
            "trajectories_sealed": True,
        },
    }
    return _seal(core, "receipt_sha256")


def qualify_taste_candidate(
    *,
    candidate: Mapping[str, object],
    baseline_outcome: Mapping[str, object],
    treatment_outcome: Mapping[str, object],
) -> dict[str, Any]:
    """Emit a qualified receipt or raise; no unqualified receipt is produced."""

    validated_candidate = validate_taste_candidate(candidate)
    baseline = validate_sealed_taste_outcome(
        baseline_outcome, candidate=validated_candidate, expected_arm="baseline"
    )
    treatment = validate_sealed_taste_outcome(
        treatment_outcome, candidate=validated_candidate, expected_arm="treatment"
    )
    receipt = _qualified_receipt(validated_candidate, baseline, treatment)
    return validate_taste_qualification_receipt(
        receipt,
        candidate=validated_candidate,
        baseline_outcome=baseline,
        treatment_outcome=treatment,
    )


def validate_taste_qualification_receipt(
    value: Mapping[str, object],
    *,
    candidate: Mapping[str, object],
    baseline_outcome: Mapping[str, object],
    treatment_outcome: Mapping[str, object],
) -> dict[str, Any]:
    """Recompute the comparison and validate the receipt's content address."""

    raw = _mapping(value, "receipt")
    _exact_keys(
        raw,
        frozenset(
            {
                "schema_version",
                "authority",
                "completion_claim_allowed",
                "qualified",
                "candidate_sha256",
                "baseline_outcome_sha256",
                "treatment_outcome_sha256",
                "bindings",
                "comparisons",
                "cold_controls",
                "receipt_sha256",
            }
        ),
        "receipt",
    )
    _verify_self_hash(raw, "receipt_sha256")
    if raw["schema_version"] != TASTE_RECEIPT_SCHEMA:
        _fail("INPUT_INVALID", "unsupported Taste qualification receipt schema")
    if (
        _boolean(raw["authority"], "receipt.authority")
        or _boolean(raw["completion_claim_allowed"], "receipt.completion_claim_allowed")
        or not _boolean(raw["qualified"], "receipt.qualified")
    ):
        _fail("POLICY_VIOLATION", "a Taste receipt must be qualified and non-authoritative")

    validated_candidate = validate_taste_candidate(candidate)
    baseline = validate_sealed_taste_outcome(
        baseline_outcome, candidate=validated_candidate, expected_arm="baseline"
    )
    treatment = validate_sealed_taste_outcome(
        treatment_outcome, candidate=validated_candidate, expected_arm="treatment"
    )
    expected = _qualified_receipt(validated_candidate, baseline, treatment)
    if raw != expected:
        _fail("RECEIPT_MISMATCH", "receipt does not match the sealed contrastive evidence")
    return expected
