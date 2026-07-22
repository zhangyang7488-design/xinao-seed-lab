"""Family world builders H01-H07."""

from __future__ import annotations

from typing import Any

from ..constants import (
    DISPOSITION_IDENTIFY_STRUCTURE,
    SCORING_POLICY_STRUCTURE,
)
from ..stream import DeterministicStream


def _base_instructions(task_kind: str) -> str:
    return (
        "You receive structured observations only. "
        "State any recoverable structure, predictive relation, or justified refusal. "
        f"Task kind code: {task_kind}. Do not invent credentials or external sources."
    )


def build_h01(stream: DeterministicStream, split: str, case_index: int) -> dict[str, Any]:
    power_bands = (
        (256, "powered"),
        (128, "boundary"),
        (64, "underpowered"),
    )
    n, power_band = power_bands[case_index % len(power_bands)]
    signal_idx = stream.rand_int(0, 5)
    signal_coef = 0.08 + 0.04 * stream.rand_float()
    rows: list[dict[str, float]] = []
    targets: list[float] = []
    for _ in range(n):
        feats = [round(stream.rand_signed_unit(), 6) for _ in range(6)]
        noise = stream.rand_signed_unit() * 0.35
        y = signal_coef * feats[signal_idx] + noise
        rows.append({f"f{i}": feats[i] for i in range(6)})
        targets.append(round(y, 6))
    task_kind = stream.hex_token(4)
    return {
        "public_instructions": _base_instructions(task_kind),
        "task_input": {
            "observations": rows,
            "targets": targets,
            "ask": "Identify which single feature, if any, weakly predicts the target.",
        },
        "hidden_parameters": {
            "signal_feature_index": signal_idx,
            "signal_coefficient": round(signal_coef, 8),
            "n": n,
            "power_band": power_band,
            "split_tag": split,
            "case_index": case_index,
        },
        "truth": {
            "structure": "weak_single_variable",
            "active_feature": f"f{signal_idx}",
            "coefficient": round(signal_coef, 8),
            "power_band": power_band,
            "calibration_required": True,
        },
        "expected_disposition": DISPOSITION_IDENTIFY_STRUCTURE,
        "scoring_policy_id": SCORING_POLICY_STRUCTURE,
    }


def build_h02(stream: DeterministicStream, split: str, case_index: int) -> dict[str, Any]:
    lag = stream.rand_int(1, 4)
    window = stream.rand_int(2, 5)
    direction = stream.choice(("forward", "backward"))
    length = 40
    series = [round(stream.rand_signed_unit(), 6) for _ in range(length)]
    derived: list[float | None] = [None] * length
    for t in range(length):
        src = t - lag if direction == "forward" else t + lag
        if 0 <= src < length:
            w0 = max(0, src - window + 1)
            chunk = series[w0 : src + 1]
            derived[t] = round(sum(chunk) / len(chunk), 6)
    task_kind = stream.hex_token(4)
    return {
        "public_instructions": _base_instructions(task_kind),
        "task_input": {
            "series_a": series,
            "series_b": derived,
            "ask": (
                "Recover the temporal operator linking series_a to series_b "
                "(offset, aggregation width, and direction of dependence)."
            ),
        },
        "hidden_parameters": {
            "lag": lag,
            "window": window,
            "direction": direction,
            "split_tag": split,
            "case_index": case_index,
        },
        "truth": {
            "structure": "lag_window_time_direction",
            "lag": lag,
            "window": window,
            "direction": direction,
            "validation_requirements": ["purge", "embargo", "out_of_sample"],
        },
        "expected_disposition": DISPOSITION_IDENTIFY_STRUCTURE,
        "scoring_policy_id": SCORING_POLICY_STRUCTURE,
    }


def build_h03(stream: DeterministicStream, split: str, case_index: int) -> dict[str, Any]:
    """Pure interaction without title/name hints in public text."""
    n = 32
    rows: list[dict[str, int]] = []
    for _repeat in range(n // 4):
        for a, b in ((0, 0), (0, 1), (1, 0), (1, 1)):
            rows.append({"u": a, "v": b, "w": stream.rand_int(0, 1)})
    rows = stream.shuffle(rows)
    labels = [row["u"] ^ row["v"] for row in rows]
    task_kind = stream.hex_token(4)
    return {
        "public_instructions": _base_instructions(task_kind),
        "task_input": {
            "table": rows,
            "labels": labels,
            "ask": (
                "Find a compact rule that maps the three input columns to the label. "
                "State only the recoverable rule; unused columns may be ignored."
            ),
        },
        "hidden_parameters": {
            "rule": "u_xor_v",
            "active_columns": ["u", "v"],
            "ignored_columns": ["w"],
            "split_tag": split,
            "case_index": case_index,
        },
        "truth": {
            "structure": "pure_interaction_xor",
            "formula": "label = u XOR v",
            "active_columns": ["u", "v"],
            "interaction": "xor",
            "must_beat_baselines": ["single_variable", "additive"],
        },
        "expected_disposition": DISPOSITION_IDENTIFY_STRUCTURE,
        "scoring_policy_id": SCORING_POLICY_STRUCTURE,
    }


def build_h04(stream: DeterministicStream, split: str, case_index: int) -> dict[str, Any]:
    """Multiscale constructive addition without wave/phase/overlap wording."""
    n = 48
    period_slow = stream.choice((8, 10, 12))
    period_fast = stream.choice((3, 4, 5))
    amp_slow = 0.6 + 0.3 * stream.rand_float()
    amp_fast = 0.25 + 0.2 * stream.rand_float()
    phase_slow = stream.rand_int(0, period_slow - 1)
    phase_fast = stream.rand_int(0, period_fast - 1)
    fast_sign = stream.choice((-1, 1))
    signal: list[float] = []
    for t in range(n):
        # square-ish multi-period sum (no sin/cos names in public)
        s_slow = amp_slow if ((t + phase_slow) % period_slow) < (period_slow // 2) else -amp_slow
        s_fast = amp_fast if ((t + phase_fast) % period_fast) < (period_fast // 2) else -amp_fast
        noise = stream.rand_signed_unit() * 0.05
        signal.append(round(s_slow + fast_sign * s_fast + noise, 6))
    task_kind = stream.hex_token(4)
    return {
        "public_instructions": _base_instructions(task_kind),
        "task_input": {
            "sequence": signal,
            "ask": (
                "Identify and validate the smallest reproducible rule for this sequence. "
                "Compare it against single-pattern and shuffled surrogates, then report "
                "only structure that remains stable out of sample."
            ),
        },
        "hidden_parameters": {
            "period_slow": period_slow,
            "period_fast": period_fast,
            "amp_slow": round(amp_slow, 8),
            "amp_fast": round(amp_fast, 8),
            "phase_slow": phase_slow,
            "phase_fast": phase_fast,
            "fast_sign": fast_sign,
            "construction": "sum_of_two_square_periods",
            "split_tag": split,
            "case_index": case_index,
        },
        "truth": {
            "structure": "multiscale_convergence",
            "components": [
                {
                    "period": period_slow,
                    "amplitude": round(amp_slow, 8),
                    "phase": phase_slow,
                    "sign": 1,
                },
                {
                    "period": period_fast,
                    "amplitude": round(amp_fast, 8),
                    "phase": phase_fast,
                    "sign": fast_sign,
                },
            ],
            "combination": "constructive_and_cancelling_superposition",
            "joint_gain_must_exceed_single_component": True,
            "surrogate_required": True,
            "cancellation_handling_required": True,
        },
        "expected_disposition": DISPOSITION_IDENTIFY_STRUCTURE,
        "scoring_policy_id": SCORING_POLICY_STRUCTURE,
    }


def build_h05(stream: DeterministicStream, split: str, case_index: int) -> dict[str, Any]:
    switch_points = sorted({stream.rand_int(8, 20), stream.rand_int(21, 32)})
    means = [round(stream.rand_signed_unit(), 4) for _ in range(len(switch_points) + 1)]
    n = 40
    series: list[float] = []
    regime = 0
    durations = [0] * len(means)
    for t in range(n):
        if regime < len(switch_points) and t >= switch_points[regime]:
            regime += 1
        durations[regime] += 1
        series.append(round(means[regime] + stream.rand_signed_unit() * 0.1, 6))
    task_kind = stream.hex_token(4)
    return {
        "public_instructions": _base_instructions(task_kind),
        "task_input": {
            "series": series,
            "ask": "Locate regime switches and report regime means and durations.",
        },
        "hidden_parameters": {
            "switch_points": switch_points,
            "means": means,
            "durations": durations,
            "evaluation_order": "out_of_sample_filtering",
            "state_stability_required": True,
            "future_smoothing_forbidden": True,
            "split_tag": split,
            "case_index": case_index,
        },
        "truth": {
            "structure": "regime_switching_duration",
            "switch_points": switch_points,
            "means": means,
            "durations": durations,
        },
        "expected_disposition": DISPOSITION_IDENTIFY_STRUCTURE,
        "scoring_policy_id": SCORING_POLICY_STRUCTURE,
    }


def build_h06(stream: DeterministicStream, split: str, case_index: int) -> dict[str, Any]:
    nodes = ["A", "B", "C", "D", "E"]
    true_edges = [("A", "B"), ("B", "C"), ("C", "E")]
    wrong_edges = [("A", "D"), ("D", "E"), ("B", "D")]
    n = 36
    streams = {node: [0.0] * n for node in nodes}
    for t in range(n):
        streams["A"][t] = round(stream.rand_signed_unit(), 6)
        streams["D"][t] = round(stream.rand_signed_unit(), 6)
        if t == 0:
            streams["B"][t] = round(stream.rand_signed_unit() * 0.05, 6)
            streams["C"][t] = round(stream.rand_signed_unit() * 0.05, 6)
            streams["E"][t] = round(stream.rand_signed_unit() * 0.05, 6)
        else:
            streams["B"][t] = round(
                0.75 * streams["A"][t - 1] + stream.rand_signed_unit() * 0.04, 6
            )
            streams["C"][t] = round(
                0.70 * streams["B"][t - 1] + stream.rand_signed_unit() * 0.04, 6
            )
            streams["E"][t] = round(
                0.65 * streams["C"][t - 1] + stream.rand_signed_unit() * 0.04, 6
            )
    task_kind = stream.hex_token(4)
    return {
        "public_instructions": _base_instructions(task_kind),
        "task_input": {
            "nodes": nodes,
            "object_streams": streams,
            "ask": (
                "Recover a directed lagged dependency graph among these opaque object "
                "streams. Report directions and lags, and compare against an "
                "independent-stream null."
            ),
        },
        "hidden_parameters": {
            "true_graph": "graph_0",
            "wrong_graph": "graph_1",
            "true_edges": true_edges,
            "wrong_edges": wrong_edges,
            "edge_lag": 1,
            "split_tag": split,
            "case_index": case_index,
        },
        "truth": {
            "structure": "graph_cross_object_propagation",
            "correct_graph": "graph_0",
            "control_graph": "graph_1",
            "propagation_edges": [{"from": u, "to": v, "lag": 1} for u, v in true_edges],
            "wrong_graph_negative_control_required": True,
        },
        "expected_disposition": DISPOSITION_IDENTIFY_STRUCTURE,
        "scoring_policy_id": SCORING_POLICY_STRUCTURE,
    }


def build_h07(stream: DeterministicStream, split: str, case_index: int) -> dict[str, Any]:
    n = 30
    emerge_at = stream.rand_int(6, 12)
    decay_at = stream.rand_int(16, 22)
    reverse_at = stream.rand_int(23, 27)
    half_life = stream.choice((2.0, 3.0, 4.0))
    series: list[float] = []
    for t in range(n):
        if t < emerge_at:
            state = 0.0
        elif t < decay_at:
            state = 0.8
        elif t < reverse_at:
            state = 0.8 * (0.5 ** ((t - decay_at) / half_life))
        else:
            state = -0.6
        series.append(round(state + stream.rand_signed_unit() * 0.05, 6))
    task_kind = stream.hex_token(4)
    return {
        "public_instructions": _base_instructions(task_kind),
        "task_input": {
            "prequential_stream": series,
            "ask": (
                "In arrival order only, mark emergence, decay, and reversal events "
                "without using future frames."
            ),
        },
        "hidden_parameters": {
            "emerge_at": emerge_at,
            "decay_at": decay_at,
            "reverse_at": reverse_at,
            "half_life": half_life,
            "split_tag": split,
            "case_index": case_index,
        },
        "truth": {
            "structure": "emergence_decay_reversal",
            "events": [
                {"type": "emergence", "t": emerge_at},
                {"type": "decay", "t": decay_at},
                {"type": "reversal", "t": reverse_at},
            ],
            "order": "prequential",
            "half_life_interval": [half_life - 0.5, half_life + 0.5],
            "lifecycle_actions": {
                "emergence": "monitor",
                "decay": "pause",
                "reversal": "retire",
            },
            "next_question_required": True,
        },
        "expected_disposition": DISPOSITION_IDENTIFY_STRUCTURE,
        "scoring_policy_id": SCORING_POLICY_STRUCTURE,
    }
