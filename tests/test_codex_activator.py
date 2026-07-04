from services.codex_activator import codex_activator


def test_choose_target_accepts_codex_s_without_legacy_fallback() -> None:
    selection, blocker = codex_activator.choose_target({"target": "codex-s"})

    assert blocker == ""
    assert selection == {
        "original_target": "codex-s",
        "effective_target": "codex-s",
        "fallback_reason": "",
    }


def test_choose_target_keeps_blank_legacy_default_to_codex_a() -> None:
    selection, blocker = codex_activator.choose_target({})

    assert blocker == ""
    assert selection["effective_target"] == "codex-a"
    assert selection["fallback_reason"] == "legacy_hardmode_codex_a_default"


def test_choose_target_rejects_unknown_target() -> None:
    selection, blocker = codex_activator.choose_target({"target": "codex-z"})

    assert selection is None
    assert blocker == "CODEX_ACTIVATOR_UNKNOWN_TARGET"
