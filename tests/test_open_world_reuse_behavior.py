from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


def _decode_expected_digest(value: str) -> str:
    parts = value.split(":")
    assert len(parts) == 2
    assert all(len(part) == 32 for part in parts)
    assert all(set(part.lower()) <= set("0123456789abcdef") for part in parts)
    return "".join(parts)


def _run_js_assertion(
    assertion_path: Path,
    output: dict[str, object],
    context: dict[str, object],
) -> dict[str, object]:
    node = shutil.which("node")
    assert node, "Node.js is required to execute Promptfoo JavaScript assertions"
    program = """
const fs = require("fs");
const assertion = require(process.argv[1]);
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const result = assertion(JSON.stringify(payload.output), payload.context);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "-e", program, str(assertion_path)],
        input=json.dumps({"output": output, "context": context}),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return json.loads(completed.stdout)


def _grounded_recall_payload() -> tuple[Path, dict[str, object], dict[str, object]]:
    root = REPO_ROOT / "evals/mature_capability_recall"
    repo_cwd = str(REPO_ROOT)
    cases = yaml.safe_load((root / "cases.yaml").read_text(encoding="utf-8"))
    variables = next(
        case["vars"]
        for case in cases
        if case["vars"]["case_id"] == "REG_KNOWN_GOOD_LOCAL_ROUTE_RECALLED"
    )
    local_path = root / "fixtures/local/REG_KNOWN_GOOD_LOCAL_ROUTE_RECALLED.json"
    search_path = root / "fixtures/search/REG_KNOWN_GOOD_LOCAL_ROUTE_RECALLED.json"
    local_raw = local_path.read_bytes()
    search_raw = search_path.read_bytes()
    local_evidence = json.loads(local_raw)
    search_evidence = json.loads(search_raw)
    candidates = [
        {
            "candidate_id": candidate["candidate_id"],
            "source_kind": candidate["source_kind"],
            "url": candidate.get("url") or candidate["source_url"],
            "fit": "observed fit",
        }
        for candidate in [*local_evidence["capabilities"], *search_evidence["candidates"]]
    ]
    output = {
        "case_id": variables["case_id"],
        "parent_outcome": variables["parent_outcome"],
        "local_evidence_nonce": variables["expected_local_evidence_nonce"],
        "search_evidence_nonce": variables["expected_search_evidence_nonce"],
        "local_fixture_sha256": hashlib.sha256(local_raw).hexdigest(),
        "search_fixture_sha256": hashlib.sha256(search_raw).hexdigest(),
        "candidate_sources_considered": ["verified_local", "official", "community"],
        "candidates_considered": candidates,
        "selected_candidate_id": variables["expected_selected_candidate_id"],
        "selected_candidate_url": variables["expected_selected_candidate_url"],
        "selected_source_kind": variables["expected_selected_source_kind"],
        "selected_route": variables["expected_selected_route"],
        "binding_recommended": variables["expected_binding_recommended"],
        "mutation_performed": variables["expected_mutation_performed"],
        "new_runtime": variables["expected_new_runtime"],
        "status": variables["expected_status"],
        "reason": "The verified local route is the closest fit.",
    }
    local_envelope = {
        "fixture_sha256_parts": variables["expected_local_fixture_digest"],
        "evidence": local_evidence,
    }
    search_envelope = {
        "fixture_sha256_parts": variables["expected_search_fixture_digest"],
        "search": search_evidence,
    }
    items = [
        {"type": "userMessage"},
        {
            "type": "commandExecution",
            "command": (
                "python -I -S -B evals/mature_capability_recall/read_local_evidence.py "
                f"--case {variables['case_id']}"
            ),
            "aggregatedOutput": json.dumps(local_envelope),
            "cwd": repo_cwd,
            "exitCode": 0,
        },
        {
            "type": "commandExecution",
            "command": (
                "python -I -S -B evals/mature_capability_recall/replay_candidate_search.py "
                f"--case {variables['case_id']}"
            ),
            "aggregatedOutput": json.dumps(search_envelope),
            "cwd": repo_cwd,
            "exitCode": 0,
        },
        {"type": "agentMessage"},
    ]
    context = {
        "vars": variables,
        "metadata": {
            "codexAppServer": {
                "threadId": "thread-grounded",
                "turnId": "turn-grounded",
                "cwd": repo_cwd,
                "sandboxMode": "read-only",
                "approvalPolicy": "never",
                "items": items,
            }
        },
    }
    return root / "assert_grounded_recall.js", output, context


def _live_recall_payload() -> tuple[Path, dict[str, object], dict[str, object]]:
    root = REPO_ROOT / "evals/mature_capability_recall"
    config = yaml.safe_load((root / "promptfooconfig.live.yaml").read_text(encoding="utf-8"))
    variables = config["tests"][0]["vars"]
    selected_url = "https://github.com/example/declarative-vendor"
    candidates = [
        {
            "candidate_id": "example/declarative-vendor",
            "source_kind": "official",
            "url": selected_url,
            "fit": "git release http image lock support",
            "evidence": "git release http image lock support",
        },
        {
            "candidate_id": "community/acquirer",
            "source_kind": "community",
            "url": "https://github.com/community/acquirer",
            "fit": "partial",
            "evidence": "git and http only",
        },
        {
            "candidate_id": "personal/cache",
            "source_kind": "personal",
            "url": "https://github.com/personal/cache",
            "fit": "partial",
            "evidence": "image cache only",
        },
    ]
    output = {
        "case_id": variables["case_id"],
        "parent_outcome": variables["parent_outcome"],
        "discovery_cache_sha256": _decode_expected_digest(
            variables["expected_discovery_cache_digest"]
        ),
        "candidate_sources_considered": ["official", "community", "personal"],
        "candidates_considered": candidates,
        "selected_candidate_id": candidates[0]["candidate_id"],
        "selected_candidate_url": selected_url,
        "selected_source_kind": "official",
        "selected_route": "bind_external",
        "binding_recommended": True,
        "mutation_performed": False,
        "new_runtime": False,
        "status": "select_external",
        "reason": "Observed exact capability coverage in current search.",
    }
    items = [
        {
            "type": "commandExecution",
            "command": (
                "$h=(Get-FileHash github_external_mature_all_repos.json "
                "-Algorithm SHA256).Hash; Write-Output "
                "('fixture_sha256_parts='+$h.Substring(0,32)+':'"
                "+$h.Substring(32,32))"
            ),
            "aggregatedOutput": (
                f"fixture_sha256_parts={variables['expected_discovery_cache_digest']}"
            ),
            "exitCode": 0,
        },
        {
            "type": "webSearch",
            "query": "git release http image lock",
            "result": f"git release http image lock {selected_url}",
            "status": "completed",
        },
        {"type": "agentMessage"},
    ]
    context = {
        "vars": variables,
        "metadata": {
            "codexAppServer": {
                "threadId": "thread-live",
                "turnId": "turn-live",
                "sandboxMode": "read-only",
                "approvalPolicy": "never",
                "items": items,
            }
        },
    }
    return root / "assert_live_recall.js", output, context


def _thin_localization_payload() -> tuple[Path, dict[str, object], dict[str, object]]:
    assertion = REPO_ROOT / "evals/thin_localization/assert_thin_localization.js"
    selected = "python/json.tool"
    search_envelope = {
        "schema_version": "xinao.external_candidate_probe.v1",
        "probe_nonce": "THIN-SEARCH-OBSERVED-6C210A",
        "candidates": [
            {"candidate_id": selected, "source_kind": "official"},
            {"candidate_id": "jqlang/jq", "source_kind": "community"},
            {"candidate_id": "mikefarah/yq", "source_kind": "personal"},
        ],
    }
    receipt = {
        "schema_version": "xinao.external_invocation_receipt.v1",
        "provider_id": selected,
        "source_kind": "official",
        "exit_code": 0,
        "fallback_used": False,
        "upstream_invoked": True,
        "invocation_nonce": "REAL-UPSTREAM-INVOKE-520E7B",
    }
    verifier = {
        "schema_version": "xinao.thin_localization_verification.v1",
        "passed": True,
        "selected_candidate": selected,
        "selected_source_kind": "official",
        "candidate_source_kinds_observed": ["community", "official", "personal"],
        "changed_source_paths": ["config/binding.json"],
        "selection_valid": True,
        "mutation_scope_valid": True,
        "roles_valid": True,
        "fallback_zero": True,
        "canonical_invocation_count": 2,
        "real_invocations": True,
        "deterministic": True,
        "swap_verified": True,
        "missing_upstream_lesion_rejected": True,
    }
    output = {
        "case_id": "POS_PARAMETER_ONLY_EXTERNAL_BINDING",
        "candidate_sources_considered": ["official", "community", "personal"],
        "selected_candidate": selected,
        "selected_source_kind": "official",
        "changed_source_paths": ["config/binding.json"],
        "canonical_invocation_count": 2,
        "upstream_invoked": True,
        "swap_verified": True,
        "missing_upstream_lesion_rejected": True,
        "fallback_used": False,
        "new_runtime": False,
        "status": "verified",
        "reason": "Only the binding changed and the external path passed all lesions.",
    }
    items = [
        {
            "type": "commandExecution",
            "command": "python tools/search_candidates.py",
            "aggregatedOutput": json.dumps(search_envelope),
            "exitCode": 0,
        },
        {
            "type": "fileChange",
            "changes": [{"path": "config/binding.json", "kind": "update"}],
        },
        {
            "type": "commandExecution",
            "command": "python run_canonical.py",
            "aggregatedOutput": json.dumps(receipt),
            "exitCode": 0,
        },
        {
            "type": "commandExecution",
            "command": "python run_canonical.py",
            "aggregatedOutput": json.dumps(receipt),
            "exitCode": 0,
        },
        {
            "type": "commandExecution",
            "command": "uv run python verify_localization.py",
            "aggregatedOutput": json.dumps(verifier),
            "exitCode": 0,
        },
        {"type": "agentMessage"},
    ]
    context = {
        "vars": {"case_id": "POS_PARAMETER_ONLY_EXTERNAL_BINDING"},
        "metadata": {
            "codexAppServer": {
                "threadId": "thread-thin",
                "turnId": "turn-thin",
                "cwd": r"D:\evidence\thin-localization-workspace",
                "sandboxMode": "workspace-write",
                "approvalPolicy": "never",
                "items": items,
            }
        },
    }
    return assertion, output, context


def _load_contract_module():
    path = REPO_ROOT / "evals/thin_localization/evaluate_contract_cases.py"
    spec = importlib.util.spec_from_file_location("thin_localization_contract", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_grounded_recall_requires_observed_local_and_candidate_commands() -> None:
    root = REPO_ROOT / "evals/mature_capability_recall"
    cases = yaml.safe_load((root / "cases.yaml").read_text(encoding="utf-8"))
    assert len(cases) == 2
    assert {case["vars"]["case_id"] for case in cases} == {
        "REG_KNOWN_GOOD_LOCAL_ROUTE_RECALLED",
        "POS_PERSONAL_REPO_CAN_WIN",
    }
    personal = next(
        case for case in cases if case["vars"]["case_id"] == "POS_PERSONAL_REPO_CAN_WIN"
    )
    assert personal["vars"]["expected_selected_source_kind"] == "personal"
    for case in cases:
        for key in ("expected_local_fixture_digest", "expected_search_fixture_digest"):
            assert len(_decode_expected_digest(case["vars"][key])) == 64
    assertion = (root / "assert_grounded_recall.js").read_text(encoding="utf-8")
    for required in (
        "commandExecution",
        "replay_candidate_search.py",
        "expected_local_evidence_nonce",
        "expected_search_evidence_nonce",
        "mutatingTrace",
        'appServer.sandboxMode === "read-only"',
    ):
        assert required in assertion
    prompt = (root / "prompt.txt").read_text(encoding="utf-8")
    assert "Read only the repository-root AGENTS.md" in prompt
    assert "After the\ntwo required evidence readers" in prompt
    assert "inspect tests, assertions, configs, fixtures" in prompt
    assert "exactly the unique source_kind values" in prompt
    assert "empty evidence stream" in prompt


def test_grounded_fixture_readers_emit_sanitizer_safe_exact_digests() -> None:
    root = REPO_ROOT / "evals/mature_capability_recall"
    attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "evals/mature_capability_recall/** text eol=lf" in attributes
    assert "evals/thin_localization/** text eol=lf" in attributes
    case_id = "REG_KNOWN_GOOD_LOCAL_ROUTE_RECALLED"
    for script_name, fixture_kind in (
        ("read_local_evidence.py", "local"),
        ("replay_candidate_search.py", "search"),
    ):
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(root / script_name), "--case", case_id],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        envelope = json.loads(completed.stdout)
        observed = _decode_expected_digest(envelope["fixture_sha256_parts"])
        fixture = root / f"fixtures/{fixture_kind}/{case_id}.json"
        assert observed == hashlib.sha256(fixture.read_bytes()).hexdigest()


def test_grounded_recall_assertion_rejects_duplicate_or_extra_source_kinds() -> None:
    assertion, output, context = _grounded_recall_payload()
    assert _run_js_assertion(assertion, output, context)["pass"] is True

    duplicate = deepcopy(output)
    duplicate["candidate_sources_considered"].append("official")
    assert _run_js_assertion(assertion, duplicate, context)["pass"] is False

    extra = deepcopy(output)
    extra["candidate_sources_considered"].append("personal")
    assert _run_js_assertion(assertion, extra, context)["pass"] is False


def test_grounded_recall_assertion_is_repo_root_path_neutral() -> None:
    assertion, output, context = _grounded_recall_payload()
    relocated = deepcopy(context)
    app_server = relocated["metadata"]["codexAppServer"]
    relocated_cwd = r"D:\relocated\fresh-worktree"
    app_server["cwd"] = relocated_cwd
    for item in app_server["items"]:
        if item["type"] == "commandExecution":
            item["cwd"] = relocated_cwd
    assert _run_js_assertion(assertion, output, relocated)["pass"] is True

    command = next(item for item in app_server["items"] if item["type"] == "commandExecution")
    command["cwd"] = r"D:\other-root"
    assert _run_js_assertion(assertion, output, relocated)["pass"] is False


def test_grounded_recall_assertion_rejects_live_fallback_trace() -> None:
    assertion, output, context = _grounded_recall_payload()
    attacked = deepcopy(context)
    attacked["metadata"]["codexAppServer"]["items"].insert(
        -1,
        {
            "type": "webSearch",
            "query": "live fallback that frozen replay must not use",
            "status": "completed",
        },
    )
    assert _run_js_assertion(assertion, output, attacked)["pass"] is False


def test_live_recall_hashes_the_existing_broad_cache_and_requires_real_search() -> None:
    root = REPO_ROOT / "evals/mature_capability_recall"
    config = yaml.safe_load((root / "promptfooconfig.live.yaml").read_text(encoding="utf-8"))
    case = config["tests"][0]
    assert config["providers"][0]["config"]["network_access_enabled"] is True
    assert _decode_expected_digest(case["vars"]["expected_discovery_cache_digest"]) == (
        "AED3CACBF27CA2048E371396780B664847B786F1D87E6A7C95C86EDA6C5DF970"
    )
    assertion = (root / "assert_live_recall.js").read_text(encoding="utf-8")
    assert "hashIndex" in assertion
    assert "searchIndex" in assertion
    assert "selectedObserved" in assertion
    assert "selectedCapabilityCoverage" in assertion
    assert "noMutation" in assertion
    assert "hashOutputSuppressed" in assertion
    prompt = (root / "prompt_live.txt").read_text(encoding="utf-8")
    assert "fixture_sha256_parts=" in prompt
    assert "directly open the selected canonical `https://github.com/...` URL" in prompt


def test_live_recall_assertion_rejects_non_search_toolcall() -> None:
    assertion, output, context = _live_recall_payload()
    assert _run_js_assertion(assertion, output, context)["pass"] is True

    attacked = deepcopy(context)
    attacked["metadata"]["codexAppServer"]["items"][1] = {
        "type": "mcpToolCall",
        "name": "not-a-search",
        "arguments": "git release http image lock",
        "result": output["selected_candidate_url"],
        "status": "completed",
    }
    assert _run_js_assertion(assertion, output, attacked)["pass"] is False

    echo_attack = deepcopy(context)
    echoed = f"git release http image lock {output['selected_candidate_url']}"
    echo_attack["metadata"]["codexAppServer"]["items"][1] = {
        "type": "mcpToolCall",
        "server": "web",
        "tool": "echo",
        "arguments": {"text": echoed},
        "result": {"content": [{"type": "text", "text": echoed}]},
        "status": "completed",
    }
    assert _run_js_assertion(assertion, output, echo_attack)["pass"] is False


def test_live_recall_assertion_rejects_duplicate_source_report() -> None:
    assertion, output, context = _live_recall_payload()
    attacked = deepcopy(output)
    attacked["candidate_sources_considered"].append("official")
    assert _run_js_assertion(assertion, attacked, context)["pass"] is False


def test_thin_localization_contract_is_noncompensating() -> None:
    module = _load_contract_module()
    cases = module.load_cases()
    assert len(cases) == 6
    actual = {case["id"]: module.evaluate(case["evidence"]) for case in cases}
    expected = {case["id"]: case["expected"] for case in cases}
    assert actual == expected
    assert actual["POS_PARAMETER_ONLY_REAL_INVOKE"] == "verified"
    assert all(
        status == "rejected" for case_id, status in actual.items() if case_id.startswith("NEG_")
    )


def test_disposable_fixture_limits_source_changes_and_proves_external_invocation() -> None:
    root = REPO_ROOT / "evals/thin_localization"
    request = json.loads(
        (root / "fixture_template/capability_request.json").read_text(encoding="utf-8")
    )
    assert request["allowed_source_mutations"] == ["config/binding.json"]
    assert set(request["candidate_source_kinds_required"]) == {
        "official",
        "community",
        "personal",
    }
    search = (root / "fixture_template/tools/search_candidates.py").read_text(encoding="utf-8")
    assert "https://github.com/jqlang/jq" in search
    assert "https://github.com/mikefarah/yq" in search
    runner = (root / "fixture_template/run_canonical.py").read_text(encoding="utf-8")
    verifier = (root / "fixture_template/verify_localization.py").read_text(encoding="utf-8")
    for required in ("subprocess.run", "shutil.which", "provider pin mismatch", "upstream_invoked"):
        assert required in runner
    for required in (
        "mutations == ALLOWED_MUTATIONS",
        'receipts = [invoke(binding, ROOT / "input.json") for _ in range(2)]',
        "swap_verified",
        "missing_upstream_lesion_rejected",
    ):
        assert required in verifier


def test_thin_localization_assertion_cross_binds_real_command_reports() -> None:
    assertion, output, context = _thin_localization_payload()
    assert _run_js_assertion(assertion, output, context)["pass"] is True

    absolute_path = deepcopy(context)
    cwd = absolute_path["metadata"]["codexAppServer"]["cwd"]
    absolute_path["metadata"]["codexAppServer"]["items"][1]["changes"][0]["path"] = (
        f"{cwd}\\config\\binding.json"
    )
    assert _run_js_assertion(assertion, output, absolute_path)["pass"] is True

    for index in (0, 2, 4):
        failed_command = deepcopy(context)
        failed_command["metadata"]["codexAppServer"]["items"][index]["exitCode"] = 1
        assert _run_js_assertion(assertion, output, failed_command)["pass"] is False

    selected_mismatch = deepcopy(context)
    verifier = json.loads(
        selected_mismatch["metadata"]["codexAppServer"]["items"][4]["aggregatedOutput"]
    )
    verifier["selected_candidate"] = "jqlang/jq"
    selected_mismatch["metadata"]["codexAppServer"]["items"][4]["aggregatedOutput"] = json.dumps(
        verifier
    )
    assert _run_js_assertion(assertion, output, selected_mismatch)["pass"] is False

    fake_reports = deepcopy(context)
    items = fake_reports["metadata"]["codexAppServer"]["items"]
    items[0]["aggregatedOutput"] = "echo THIN-SEARCH-OBSERVED-6C210A"
    items[2]["aggregatedOutput"] = "echo REAL-UPSTREAM-INVOKE-520E7B"
    items[3]["aggregatedOutput"] = "echo REAL-UPSTREAM-INVOKE-520E7B"
    items[4]["aggregatedOutput"] = 'not JSON but says "passed": true'
    assert _run_js_assertion(assertion, output, fake_reports)["pass"] is False

    extra_mutation = deepcopy(context)
    extra_mutation["metadata"]["codexAppServer"]["items"][1]["changes"].append(
        {"path": "run_canonical.py", "kind": "update"}
    )
    assert _run_js_assertion(assertion, output, extra_mutation)["pass"] is False


def test_thin_localization_assertion_requires_canonical_before_verifier() -> None:
    assertion, output, context = _thin_localization_payload()
    attacked = deepcopy(context)
    items = attacked["metadata"]["codexAppServer"]["items"]
    items[2], items[4] = items[4], items[2]
    assert _run_js_assertion(assertion, output, attacked)["pass"] is False


def test_isolated_codex_app_server_configs_forward_proxy_environment() -> None:
    config_paths = [
        REPO_ROOT / "evals/mature_capability_recall/promptfooconfig.yaml",
        REPO_ROOT / "evals/mature_capability_recall/promptfooconfig.live.yaml",
        REPO_ROOT / "evals/thin_localization/promptfooconfig.yaml",
    ]
    checked = []
    for path in config_paths:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        for provider in config.get("providers") or []:
            if provider.get("id") != "openai:codex-app-server":
                continue
            provider_config = provider.get("config") or {}
            if provider_config.get("inherit_process_env") is not False:
                continue
            relative = path.relative_to(REPO_ROOT).as_posix()
            minimum_timeout = {
                "evals/mature_capability_recall/promptfooconfig.live.yaml": 600000,
                "evals/mature_capability_recall/promptfooconfig.yaml": 360000,
                "evals/thin_localization/promptfooconfig.yaml": 360000,
            }[relative]
            assert provider_config.get("turn_timeout_ms", 0) >= minimum_timeout, path
            cli_env = provider_config.get("cli_env") or {}
            assert cli_env.get("CODEX_HOME") == "{{env.CODEX_HOME}}", path
            for key in PROXY_ENV_KEYS:
                assert cli_env.get(key) == f"{{{{env.{key}}}}}", path
            if relative == "evals/thin_localization/promptfooconfig.yaml":
                assert cli_env.get("PYTHONDONTWRITEBYTECODE") == "1", path
                assert cli_env.get("UV_NO_CACHE") == "1", path
            checked.append(relative)
    assert set(checked) == {
        "evals/mature_capability_recall/promptfooconfig.live.yaml",
        "evals/mature_capability_recall/promptfooconfig.yaml",
        "evals/thin_localization/promptfooconfig.yaml",
    }


def test_reuse_runner_binds_runtime_sources_to_evidence() -> None:
    runner = (REPO_ROOT / "scripts/run_behavior_regression.ps1").read_text(encoding="utf-8")
    for required in (
        "source-manifest.json",
        "source_manifest_sha256",
        "source_manifest_unchanged",
        "evals\\mature_capability_recall",
        "evals\\thin_localization",
        "Get-FileHash",
    ):
        assert required in runner


def test_reuse_profile_runs_existing_promptfoo_without_a_second_platform() -> None:
    runner = (REPO_ROOT / "scripts/run_behavior_regression.ps1").read_text(encoding="utf-8")
    wrapper = (REPO_ROOT / "scripts/run_open_world_reuse_eval.ps1").read_text(encoding="utf-8")
    assert "'reuse'" in runner
    assert "mature_capability_recall_replay" in runner
    assert "thin_localization_live" in runner
    assert "mature_capability_recall_live" in runner
    assert "Copy-Item -LiteralPath $thinTemplate" in runner
    assert "-Profile reuse" in wrapper
    assert "promptfoo" not in wrapper.lower()
