"""S7 E4 partial: M1 frequency null on l0_snapshot (N=300 recent draws)."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

SNAPSHOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\l0_snapshot"
    r"\macaujc2_corrected_2023_2026_v2.txt"
)
MANIFEST = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\l0_snapshot\manifest.json")
HYP = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\l0_hypothesis_register_latest.json")
OUT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\codex_L0_backtest_numbers.json")
N_DEFAULT = 300


def load_special_numbers(path: Path, n: int) -> list[int]:
    if n <= 0:
        return []
    rows: list[int] = []
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        # The pinned source currently starts with one empty line.  Skip blank
        # records so DictReader sees the real TSV header instead of [].
        reader = csv.DictReader((line for line in fh if line.strip()), delimiter="\t")
        if not reader.fieldnames or "openCode" not in reader.fieldnames:
            raise ValueError("snapshot must be a TSV with an openCode column")
        for row in reader:
            codes = [item.strip() for item in str(row.get("openCode") or "").split(",")]
            if len(codes) != 7:
                continue
            try:
                special = int(codes[-1])
            except ValueError:
                continue
            if 1 <= special <= 49:
                rows.append(special)
    return rows[-n:]


def main() -> int:
    if not SNAPSHOT.exists():
        raise SystemExit(f"missing snapshot: {SNAPSHOT}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    specials = load_special_numbers(SNAPSHOT, N_DEFAULT)
    if not specials:
        raise SystemExit("snapshot produced no valid special numbers")
    counts = Counter(specials)
    observed = [counts.get(i, 0) for i in range(1, 50)]
    expected = len(specials) / 49.0
    chi2 = sum((o - expected) ** 2 / expected for o in observed if expected > 0)
    # Wilson-Hilferty approximation for chi-square CDF (df=48)
    df = 48
    z = ((chi2 / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    p_value = 1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))
    holdout_n = max(1, int(len(specials) * 0.25))
    oos_part = specials[-holdout_n:]
    oos_counts = Counter(oos_part)
    baseline_oos = max(oos_counts.values()) / len(oos_part) if oos_part else 0.0

    payload = {
        "schema_version": "xinao.kaigong_wave.codex_L0_backtest_numbers.v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "executor": "composer_admin_night_run",
        "completion_claim_allowed": False,
        "partial_e4": True,
        "note_cn": "M1 only on l0_snapshot N=300; full walk-forward M2-M4 not closed",
        "data_pin": manifest,
        "hypothesis_register": str(HYP) if HYP.exists() else None,
        "sample": {"N": len(specials), "holdout_n": holdout_n},
        "H1_M1_frequency_null": {
            "pearson_chi_square": float(chi2),
            "p_value": float(p_value),
            "df": 48,
            "null": "uniform_1_49",
            "verdict": "fail_reject_uniform" if p_value < 0.01 else "fail_reject_uniform_not_at_alpha",
        },
        "walkforward_stub": {
            "hit_rate_OOS": None,
            "baseline_hit_rate": float(baseline_oos),
            "lift": None,
            "n_trials_OOS": len(oos_part),
            "IS_vs_OOS_decay": None,
            "min_oos_cycles_met": False,
        },
        "commands": [
            f"uv run python {Path(__file__).as_posix()}",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(OUT), "p_value": p_value}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
