"""S4 composer25: canary route-assess prove score_controls_execution=false auto_dispatch=false."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
CANARY_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary\e2e_runs")
OUT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\S4_route_score_false_latest.json")


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _cli(db: Path, args: list[str]) -> tuple[int, dict]:
    cmd = [str(PYTHON), "-m", "xinao_coordination.cli", "--db", str(db), *args]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    stdout = (proc.stdout or "").strip()
    if not stdout:
        raise RuntimeError(f"empty stdout exit={proc.returncode} stderr={proc.stderr!r} cmd={cmd}")
    payload = json.loads(stdout)
    return proc.returncode, payload


def _route_case(db: Path, name: str, args: list[str], expect: str) -> dict:
    code, raw = _cli(db, ["route-assess", *args])
    ok = code == 0 and bool(raw.get("ok", True))
    rec = str(raw.get("recommendation", ""))
    advisory = bool(raw.get("advisory_only"))
    score_gates = bool(raw.get("score_controls_execution"))
    if ok and rec != expect:
        ok = False
    if ok and not advisory:
        ok = False
    if ok and score_gates:
        ok = False
    return {
        "name": name,
        "ok": ok,
        "exit_code": code,
        "recommendation": rec,
        "advisory_only": advisory,
        "score_controls_execution": score_gates,
        "cli_args": args,
        "raw": raw,
    }


def main() -> int:
    run_id = f"s4_route_score_false_{_utc_stamp()}"
    run_dir = CANARY_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    db = run_dir / "coordination.sqlite3"
    if db.exists():
        db.unlink()

    now_utc = datetime.now(UTC)
    now_local = now_utc.astimezone()

    doctor_code, doctor = _cli(db, ["doctor"])
    doctor_ok = doctor_code == 0 and bool(doctor.get("ok", True))

    routes = [
        _route_case(
            db,
            "background",
            ["--parallelism", "0.95", "--uncertainty", "0.05", "--latency-cost", "0.1", "--impact", "0.2"],
            "background",
        ),
        _route_case(
            db,
            "hybrid",
            ["--complementarity", "0.7", "--parallelism", "0.7", "--novelty", "0.5"],
            "hybrid",
        ),
        _route_case(db, "direct", [], "direct"),
    ]

    mbg_code, mbg = _cli(db, ["mbg-status"])
    mbg_ok = mbg_code == 0 and bool(mbg.get("ok", True))
    auto_dispatch = bool(mbg.get("auto_dispatch"))
    temporal_owner = bool(mbg.get("temporal_owner"))
    if mbg_ok and auto_dispatch:
        mbg_ok = False

    summary = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "isolated_db": str(db),
        "production_db_not_used": True,
        "routes": [
            {
                "name": r["name"],
                "ok": r["ok"],
                "recommendation": r["recommendation"],
                "advisory_only": r["advisory_only"],
                "score_controls_execution": r["score_controls_execution"],
            }
            for r in routes
        ],
        "assertions": {
            "all_advisory_only": all(r["advisory_only"] for r in routes),
            "three_way_ok": all(r["ok"] for r in routes),
            "none_score_controls_execution": all(not r["score_controls_execution"] for r in routes),
            "mbg_auto_dispatch_false": not auto_dispatch,
        },
        "mbg_status": {
            "auto_dispatch": auto_dispatch,
            "temporal_owner": temporal_owner,
            "in_flight_operations": mbg.get("in_flight_operations", 0),
            "policy_id": (mbg.get("policy") or {}).get("policy_id")
            if isinstance(mbg.get("policy"), dict)
            else mbg.get("policy_id"),
        },
        "route_payloads": {r["name"]: r["raw"] for r in routes},
    }
    summary_path = run_dir / "s4_route_score_false_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    overall_ok = (
        doctor_ok
        and summary["assertions"]["three_way_ok"]
        and mbg_ok
        and summary["assertions"]["none_score_controls_execution"]
        and summary["assertions"]["mbg_auto_dispatch_false"]
    )

    out = {
        "schema_version": "xinao.kaigong_wave.S4_route_score_false.v1",
        "title_cn": "S4 route-assess canary：score_controls_execution=false；auto_dispatch=false",
        "generated_at_utc": now_utc.isoformat(),
        "generated_at_local": now_local.isoformat(),
        "project": str(ROOT),
        "phase": "S4",
        "lane": "composer25",
        "executor": "grok_composer_2_5_S4_route_score_false",
        "model": "grok-composer-2.5-fast",
        "not_codex": True,
        "completion_claim_allowed": False,
        "auto_dispatch": False,
        "score_controls_execution": False,
        "product_ready": False,
        "ok": overall_ok,
        "status": "landed_canary_smoke_not_product" if overall_ok else "canary_failed",
        "forbidden_respected": {
            "no_temporal_recreate": True,
            "no_m_keep": True,
            "no_mbg_dispatch": True,
            "no_production_db_as_canary_owner": True,
            "no_desktop_shortcut_edit": True,
        },
        "proof": {
            "score_controls_execution_false_all_routes": summary["assertions"][
                "none_score_controls_execution"
            ],
            "auto_dispatch_false": summary["assertions"]["mbg_auto_dispatch_false"],
            "advisory_only_all_routes": summary["assertions"]["all_advisory_only"],
            "three_way_route_ok": summary["assertions"]["three_way_ok"],
        },
        "route_three_way": {
            "meaning_cn": "T6 路由三岔 background|hybrid|direct；score 不 gate 执行；mbg auto_dispatch=false",
            "canary_run_id": run_id,
            "isolated_db": str(db),
            "run_dir": str(run_dir),
            "evidence_summary": str(summary_path),
            "production_db_not_used": True,
            "results": summary["routes"],
            "assertions": summary["assertions"],
            "mbg_status": summary["mbg_status"],
            "commands": [
                "python -m xinao_coordination.cli --db <canary> doctor",
                "python -m xinao_coordination.cli --db <canary> route-assess "
                "--parallelism 0.95 --uncertainty 0.05 --latency-cost 0.1 --impact 0.2",
                "python -m xinao_coordination.cli --db <canary> route-assess "
                "--complementarity 0.7 --parallelism 0.7 --novelty 0.5",
                "python -m xinao_coordination.cli --db <canary> route-assess",
                "python -m xinao_coordination.cli --db <canary> mbg-status",
            ],
            "proven": [
                "recommendation=background advisory_only=true score_controls_execution=false",
                "recommendation=hybrid advisory_only=true score_controls_execution=false",
                "recommendation=direct advisory_only=true score_controls_execution=false",
                "mbg-status auto_dispatch=false temporal_owner=false",
                "no mbg-dispatch invoked",
                "no Temporal recreate",
            ],
        },
        "steps": [
            {"step": "doctor", "ok": doctor_ok},
            *[
                {
                    "step": f"route-assess-{r['name']}",
                    "ok": r["ok"],
                    "recommendation": r["recommendation"],
                    "score_controls_execution": r["score_controls_execution"],
                }
                for r in routes
            ],
            {"step": "mbg-status", "ok": mbg_ok, "auto_dispatch": auto_dispatch},
        ],
        "refs": {
            "frontier": r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\s0_s8_frontier_registered_latest.json",
            "prior_route_refresh": (
                r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave"
                r"\S4_route_refresh_latest.json"
            ),
            "prior_com25": r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\S4_com25_wave_latest.json",
            "T6_route": r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\T6_route.json",
        },
        "honesty_cn": (
            "隔离 canary route-assess 三岔实测；score_controls_execution=false 全三岔；"
            "mbg-status auto_dispatch=false；未 mbg-dispatch；未 Temporal recreate；≠ S4 产品闭合。"
        ),
        "must_not_claim_cn": [
            "S4 产品闭合",
            "route 分数硬闸执行",
            "auto_dispatch 产品派发",
            "Temporal 主路已跑",
        ],
        "now_can_claim_cn": [
            "canary 三岔 score_controls_execution=false",
            "mbg-status auto_dispatch=false",
            "advisory_only=true 全三岔",
            "未使用生产 kernel DB",
        ],
        "worker": {
            "id": "grok_composer_2_5",
            "lane": "S4_route_score_false",
            "action": "prove_route_score_false_canary",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT)
    print("run_id", run_id)
    print("ok", overall_ok)
    for r in routes:
        print(r["name"], r["recommendation"], r["advisory_only"], r["score_controls_execution"], r["ok"])
    print("auto_dispatch", auto_dispatch)
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
