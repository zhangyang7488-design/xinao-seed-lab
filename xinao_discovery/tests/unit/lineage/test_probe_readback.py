from __future__ import annotations

from types import SimpleNamespace

import pytest

from xinao.lineage import read_marquez_run


def response(state: str):
    return SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "jobs": [
                {
                    "id": {
                        "namespace": "xinao",
                        "name": "xinao-discovery.settlement-lineage",
                    },
                    "latestRun": {"id": "run-1", "state": state},
                }
            ]
        },
    )


def test_marquez_readback_requires_completed_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "xinao.lineage.adapters.requests.get", lambda *args, **kwargs: response("RUNNING")
    )
    with pytest.raises(AssertionError, match="not COMPLETED"):
        read_marquez_run("http://marquez.test", "run-1")

    monkeypatch.setattr(
        "xinao.lineage.adapters.requests.get", lambda *args, **kwargs: response("COMPLETED")
    )
    assert read_marquez_run("http://marquez.test", "run-1")["state"] == "COMPLETED"
