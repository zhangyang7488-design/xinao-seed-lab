"""Fixed registry, dispositions, and public-safety constants for G4 families."""

from __future__ import annotations

from typing import Final

GENERATOR_ID: Final = "xinao.g4.hidden_benchmark_generator.v1"
GENERATOR_PROFILE_ID: Final = "g4_full_family_hidden_v1"
SCHEMA_VERSION: Final = "xinao.g4.hidden_benchmark.generator.v1"
HASH_PROFILE: Final = "canonical-json-v1+sha256"
STREAM_DOMAIN: Final = b"xinao.g4.hidden_benchmark.stream.v1"
MIN_SECRET_BYTES: Final = 32

TERMINAL_POSITIVE: Final = "REAL_HIDDEN_BENCHMARK_GENERATOR_READY_HOLD"

FAMILY_IDS: Final[tuple[str, ...]] = tuple(f"H{i:02d}" for i in range(1, 15))

FAMILY_SPECS: Final[dict[str, dict[str, str]]] = {
    "H01": {
        "name": "weak_single_variable_signal",
        "summary": "Weak single-variable signal embedded among distractors",
    },
    "H02": {
        "name": "lag_window_time_direction",
        "summary": "Lag/window and time-direction structure",
    },
    "H03": {
        "name": "pure_interaction_xor",
        "summary": "Pure interaction/XOR with no title or name hint",
    },
    "H04": {
        "name": "multiscale_convergence",
        "summary": "Multiscale convergence without wave/phase/overlap wording",
    },
    "H05": {
        "name": "regime_switching_duration",
        "summary": "Regime switching and duration dependence",
    },
    "H06": {
        "name": "graph_cross_object_propagation",
        "summary": "Graph/cross-object propagation with wrong-graph control",
    },
    "H07": {
        "name": "emergence_decay_reversal",
        "summary": "Emergence/decay/reversal under prequential order",
    },
    "H08": {
        "name": "confounding_spurious_correlation",
        "summary": "Confounding/spurious correlation; bounded language and cross-env failure",
    },
    "H09": {
        "name": "leakage_revision_selection_bias",
        "summary": "Leakage/revision/selection bias requiring INVALID disposition",
    },
    "H10": {
        "name": "pure_random_null",
        "summary": "Pure random null requiring NO_ACTION/stopping",
    },
    "H11": {
        "name": "evaluator_exploit_reward_hacking",
        "summary": "Evaluator exploit/reward-hacking trap requiring quarantine/invalidity",
    },
    "H12": {
        "name": "unobserved_key_variable",
        "summary": "Unobserved key variable requiring UNIDENTIFIABLE/partial bounds",
    },
    "H13": {
        "name": "non_predeclared_representation",
        "summary": "Non-predeclared representation construction",
    },
    "H14": {
        "name": "locked_knowledge_cutoff_novelty",
        "summary": "Locked knowledge-cutoff novelty/memory/reproduction distinction",
    },
}

assert tuple(FAMILY_SPECS.keys()) == FAMILY_IDS

# Expected disposition tokens for private evaluator view.
DISPOSITION_BOUNDED: Final = "BOUNDED"
DISPOSITION_INVALID: Final = "INVALID"
DISPOSITION_NO_ACTION: Final = "NO_ACTION"
DISPOSITION_QUARANTINE_OR_INVALID: Final = "QUARANTINE_OR_INVALID"
DISPOSITION_UNIDENTIFIABLE: Final = "UNIDENTIFIABLE"
DISPOSITION_IDENTIFY_STRUCTURE: Final = "IDENTIFY_STRUCTURE"
DISPOSITION_CONSTRUCT_REPRESENTATION: Final = "CONSTRUCT_REPRESENTATION"
DISPOSITION_NOVELTY_VS_MEMORY: Final = "NOVELTY_VS_MEMORY"

SCORING_POLICY_NULL: Final = "scoring_policy.null.v1"
SCORING_POLICY_STRUCTURE: Final = "scoring_policy.structure_match.v1"
SCORING_POLICY_BOUNDED: Final = "scoring_policy.bounded_language.v1"
SCORING_POLICY_INVALID: Final = "scoring_policy.invalid_disposition.v1"
SCORING_POLICY_QUARANTINE: Final = "scoring_policy.quarantine_invalid.v1"
SCORING_POLICY_UNIDENTIFIABLE: Final = "scoring_policy.unidentifiable.v1"
SCORING_POLICY_REPRESENTATION: Final = "scoring_policy.representation.v1"
SCORING_POLICY_NOVELTY: Final = "scoring_policy.novelty_memory.v1"

SPLIT_TRAINING: Final = "training"
SPLIT_HELDOUT: Final = "heldout"
SPLITS: Final[tuple[str, ...]] = (SPLIT_TRAINING, SPLIT_HELDOUT)

# Keys never allowed in public case views or public manifests.
FORBIDDEN_PUBLIC_KEYS: Final[frozenset[str]] = frozenset(
    {
        "seed",
        "secret",
        "secret_bytes",
        "secret_hex",
        "secret_b64",
        "raw_secret",
        "hidden_parameters",
        "parameters",
        "truth",
        "answer",
        "sealed_answer",
        "family_id",
        "family_identity",
        "family_name",
        "family_slot",
        "schedule_slot",
        "schedule_class",
        "rejection_label",
        "scorer_features",
        "scorer_rules",
        "scoring_rule",
        "scoring_rule_private",
        "ground_truth",
        "answer_key",
        "heldout_truth",
        "vault_path",
        "vault_locator",
        "expected_disposition",
        "scoring_policy_id",
        "split",
        "xor",
        "interaction_term",
        "wave",
        "phase",
        "overlap",
    }
)

# Substrings forbidden in H03/H04 public text/payloads (case-insensitive).
H03_PROHIBITED_HINTS: Final[tuple[str, ...]] = (
    "xor",
    "exclusive or",
    "interaction",
    "multiplicative",
    "cross term",
    "crossterm",
    "parity bit",
)
H04_PROHIBITED_HINTS: Final[tuple[str, ...]] = (
    "wave",
    "phase",
    "overlap",
    "interference",
    "fourier",
    "sinusoid",
    "harmonic",
    "multiscale",
    "scale free",
    "periodic",
    "component",
    "decompose",
)

NON_CLAIMS: Final[dict[str, bool]] = {
    "authority": False,
    "completion_claim_allowed": False,
    "provider_calls": False,
    "outcome_access": False,
    "scoring_executed": False,
    "g4_closed": False,
    "g5_closed": False,
    "admission_closed": False,
    "parent_complete": False,
}
