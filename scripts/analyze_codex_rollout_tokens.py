from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.codex_rollout_token_analyzer import (
    CodexRolloutAnalysisError,
    analyze_codex_rollout,
    write_codex_rollout_analysis,
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure Codex rollout token, tool, wait, and compaction evidence."
    )
    parser.add_argument("--rollout", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        analysis = analyze_codex_rollout(args.rollout)
    except CodexRolloutAnalysisError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "authority": False,
                    "completion_claim_allowed": False,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    analysis_sha256 = write_codex_rollout_analysis(args.output, analysis)
    print(
        json.dumps(
            {
                "ok": True,
                "authority": False,
                "completion_claim_allowed": False,
                "output": str(args.output.resolve()),
                "analysis_sha256": analysis_sha256,
                "input_sha256": analysis["input"]["sha256"],
                "charged_total_tokens": analysis["tokens"]["charged_spend"]["total_tokens"],
                "model_rounds": analysis["tokens"]["model_rounds_by_unique_counter_advance"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
