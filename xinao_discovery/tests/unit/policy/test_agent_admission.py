from xinao.policy import evaluate_agent_admission


def _valid() -> dict:
    return {
        "role": "grok_worker",
        "model": "grok-4.5",
        "provider": "grok_acpx_headless",
        "write": False,
        "source_refs": ["evidence://manifest"],
        "flags": {},
        "authorization": {"mode": "task_scoped"},
    }


def test_valid_readonly_grok_worker_is_admitted() -> None:
    assert evaluate_agent_admission(_valid())["admitted"] is True


def test_p9_negative_cases_fail_closed() -> None:
    cases = []
    cases.append({**_valid(), "model": "gpt-5"})
    cases.append(
        {**_valid(), "role": "codex", "model": "gpt-5", "provider": "codex", "write": True}
    )
    cases.append({**_valid(), "source_refs": []})
    cases.append({**_valid(), "flags": {"skip_verifier": True}})
    cases.append({**_valid(), "authorization": {"mode": "auto_all"}})
    results = [evaluate_agent_admission(case) for case in cases]
    assert all(result["admitted"] is False for result in results)
    assert {reason for result in results for reason in result["reasons"]} == {
        "model_identity_mismatch",
        "worker_role_forbidden",
        "worker_write_forbidden",
        "source_refs_required",
        "bypass_flag_forbidden",
        "automatic_blanket_authorization_forbidden",
    }


def test_client_cannot_self_assert_codex_to_gain_write() -> None:
    request = {
        **_valid(),
        "role": "codex",
        "model": "gpt-5",
        "provider": "codex",
        "write": True,
    }
    result = evaluate_agent_admission(request)
    assert result["admitted"] is False
    assert "worker_role_forbidden" in result["reasons"]
    assert "worker_write_forbidden" in result["reasons"]
