import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from xinao_seedlab.adapters.deepseek_parallel_draft import DeepSeekParallelDraftAdapter
from xinao_seedlab.adapters.local_fs import LocalFsEvidenceStore, utf8_safe

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNTIME_PATH = REPO_ROOT / "services" / "agent_runtime" / "agent_runtime.py"
RESPONSES_ADAPTER_PATH = REPO_ROOT / "scripts" / "hardmode" / "DeepSeek-Codex-Responses-Adapter.py"


def _load_module(path: Path, name: str):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_utf8_safe_recursively_replaces_lone_surrogates() -> None:
    payload = {"bad\udcaf": ["x\udcafy", {"nested": "\ud800"}]}
    safe = utf8_safe(payload)

    encoded = json.dumps(safe, ensure_ascii=False).encode("utf-8")
    assert b"?" in encoded
    assert "\udcaf" not in json.dumps(safe)


def test_local_fs_evidence_store_writes_surrogate_payload(tmp_path: Path) -> None:
    store = LocalFsEvidenceStore(tmp_path)

    path = Path(store.write_artifact("episode-surrogate-001", "surrogate.json", {"text": "x\udcafy"}))

    text = path.read_text(encoding="utf-8")
    text.encode("utf-8")
    assert "x?y" in text


def test_deepseek_parallel_draft_adapter_sanitizes_subprocess_boundaries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured["input"] = kwargs["input"]
        assert isinstance(kwargs["input"], bytes)
        decoded = kwargs["input"].decode("utf-8")
        decoded.encode("utf-8")
        json.loads(decoded)
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=(
                '{"ok":true,"status":"DRAFT_READY","task_id":"seedcortex-surrogate-001",'
                '"draft_path":"draft.md","delegation_path":"delegation.json",'
                '"draft_sha256":"sha256-test","review_id":"review_123","review_status":"pending",'
                '"text":"\\udcaf"}'
            ).encode("utf-8"),
            stderr="warn \\udcaf".encode("utf-8"),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    adapter = DeepSeekParallelDraftAdapter(tmp_path)

    result = adapter.invoke(
        task_id="seedcortex-surrogate-001",
        objective="repair \udcaf blocker",
        source_text="source \udcafevidence",
    )

    assert result["ok"] is True
    assert "?" in captured["input"].decode("utf-8")
    json.dumps(result, ensure_ascii=False).encode("utf-8")
    assert result["response"]["text"] == "?"


def test_agent_runtime_draft_deepseek_sanitizes_request_response_and_written_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module(AGENT_RUNTIME_PATH, "agent_runtime_surrogate_test")

    monkeypatch.setattr(module, "call_deepseek", lambda prompt: "draft body \udcaf")

    result = module.create_deepseek_draft(
        tmp_path,
        {
            "task_id": "seedcortex-surrogate-002",
            "objective": "repair \udcaf blocker",
            "source_text": "source \udcafevidence",
            "draft_quality_target": "70-80%",
            "final_owner": "codex",
        },
    )

    json.dumps(result, ensure_ascii=False).encode("utf-8")
    draft_text = Path(result["draft_path"]).read_text(encoding="utf-8")
    draft_text.encode("utf-8")
    assert "draft body ?" in draft_text

    delegation = json.loads(Path(result["delegation_path"]).read_text(encoding="utf-8"))
    json.dumps(delegation, ensure_ascii=False).encode("utf-8")
    assert delegation["objective"] == "repair ? blocker"


def test_agent_runtime_deepseek_response_parser_repairs_windows_path_backslashes() -> None:
    module = _load_module(AGENT_RUNTIME_PATH, "agent_runtime_deepseek_response_parser_test")
    malformed = (
        '{"choices":[{"message":{"content":"draft path C:'
        + "\\"
        + "Users"
        + "\\"
        + "xx363"
        + "\\"
        + 'draft.md"}}]}'
    )

    payload = module.load_provider_json_response(malformed)

    assert payload["choices"][0]["message"]["content"] == r"draft path C:\Users\xx363\draft.md"


def test_agent_runtime_deepseek_response_parser_repairs_odd_backslash_run_before_path() -> None:
    module = _load_module(AGENT_RUNTIME_PATH, "agent_runtime_odd_backslash_parser_test")
    malformed = (
        '{"source_text":"C:'
        + "\\\\"
        + "Users"
        + "\\\\"
        + "xx363"
        + "\\\\"
        + "Desktop"
        + "\\\\"
        + "新系统"
        + "\\"
        + 'XINAO_333_固定锚点.txt"}'
    )

    payload = module.load_provider_json_response(malformed)

    assert payload["source_text"].endswith(r"新系统\XINAO_333_固定锚点.txt")


def test_responses_adapter_json_bytes_and_stream_sanitize_surrogates() -> None:
    module = _load_module(RESPONSES_ADAPTER_PATH, "deepseek_responses_adapter_surrogate_test")

    body = module.json_bytes({"input": "x\udcafy", "nested": {"bad": "\ud800"}})
    body.decode("utf-8")
    assert b"?" in body

    stream = module.encode_responses_stream(
        {"instructions": "i\udcaf", "tools": []},
        {"content": "answer \udcaf"},
        {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    )
    stream.decode("utf-8")
    assert b"answer ?" in stream
