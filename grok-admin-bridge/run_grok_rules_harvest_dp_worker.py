"""DP semantic rules index — LiteLLM background, writes 03 txt."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(r"C:\Users\xx363\CodexWorkspaces\B\nianhua")
BRIDGE_ROOT = pathlib.Path(__file__).resolve().parent
RUNTIME_ROOT = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME")
DEFAULT_OUTPUT_ROOT = pathlib.Path(r"C:\Users\xx363\Desktop\GROK_GLOBAL_RULES_HARVEST_20260626")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BRIDGE_ROOT) not in sys.path:
    sys.path.insert(0, str(BRIDGE_ROOT))

from services.agent_runtime import litellm_live_gateway_canary, private_env, task_intake_side_audit_report_generator as gen  # noqa: E402


def raw_digest(raw_dir: pathlib.Path, max_files: int = 25, max_chars: int = 4000) -> list:
    items = []
    if not raw_dir.is_dir():
        return items
    for path in sorted(raw_dir.iterdir())[:max_files]:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        items.append({"path": str(path), "name": path.name, "excerpt": text[:max_chars]})
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()

    output_root = pathlib.Path(args.output_root)
    raw_dir = output_root / "raw"
    out_path = output_root / "03_DP_语义规则_人类可读索引.txt"
    readme_path = output_root / "00_README_规则地图.txt"

    b_path = output_root / "01_B_工程规则_L0仓库运行时.txt"
    c_path = output_root / "02_C_工程规则_备用仓.txt"
    extras = {}
    for label, p in [("B_harvest", b_path), ("C_harvest", c_path)]:
        if p.is_file():
            extras[label] = p.read_text(encoding="utf-8", errors="replace")[:8000]

    state = {
        "task": "global_rules_harvest_semantic_index",
        "raw_digest": raw_digest(raw_dir),
        "b_c_excerpts": extras,
        "audit_scope_cn": [
            "把所有规则按：唯一事务 / L0启动 / 执行框架 / 完成门 / Grok分工 / Git边界 分类",
            "标出重复、冲突、过时（如 L8 canary 当下一跳）",
            "中文目录，给人讨论用，不宣布完成",
        ],
        "forbidden": ["claim_user_completion", "elevate_git_to_mainline"],
    }

    prompt = (
        "输出纯文本（不要 JSON）。写一份中文《全局规则语义索引》给人阅读讨论。\n"
        "结构：\n"
        "1. 一句话：规则栈主要在干什么\n"
        "2. 分类目录（每类列来源路径+3条要点）\n"
        "3. 冲突与重复（Top10）\n"
        "4. 与唯一事务对齐/偏离\n"
        "5. Git/GitHub/本地仓 在规则里出现的位置（应否主线）\n"
        "6. 建议讨论顺序（不给执行命令）\n"
        f"证据 JSON:\n{json.dumps(state, ensure_ascii=False, indent=2)}"
    )

    try:
        endpoint = private_env.get_private_env_value("LITELLM_ENDPOINT", runtime_root=RUNTIME_ROOT, env_file="litellm.env") or litellm_live_gateway_canary.DEFAULT_ENDPOINT
        model = private_env.get_private_env_value("LITELLM_MODEL", runtime_root=RUNTIME_ROOT, env_file="litellm.env") or litellm_live_gateway_canary.DEFAULT_MODEL
        master_key = private_env.get_private_env_value("LITELLM_MASTER_KEY", runtime_root=RUNTIME_ROOT, env_file="litellm.env")
        if not master_key:
            legacy = litellm_live_gateway_canary.read_env(RUNTIME_ROOT / "services" / "litellm" / ".env")
            master_key = legacy.get("LITELLM_MASTER_KEY", "")
        status_code, payload = litellm_live_gateway_canary.chat_completion(
            endpoint,
            master_key,
            {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0},
            args.timeout_seconds,
        )
        if status_code != 200:
            raise RuntimeError(f"LITELLM_{status_code}")
        text = litellm_live_gateway_canary.extract_answer(payload)
    except Exception as exc:
        text = f"DP harvest index failed: {exc}"

    header = (
        "DP/DeepSeek 语义规则索引\n"
        f"生成: {gen.now()}\n"
        "说明: 供人类讨论；非完成声明；Git 脏非主线\n"
        "=" * 40 + "\n\n"
    )
    out_path.write_text(header + text, encoding="utf-8")

    if readme_path.is_file():
        readme = readme_path.read_text(encoding="utf-8")
        if "DP 已更新" not in readme:
            readme_path.write_text(
                readme + "\n\n[DP worker 已更新 03_DP_语义规则_人类可读索引.txt]\n",
                encoding="utf-8",
            )

    print(json.dumps({"output_path": str(out_path), "bytes": out_path.stat().st_size}, ensure_ascii=False))
    return 0 if out_path.stat().st_size > 300 else 2


if __name__ == "__main__":
    raise SystemExit(main())