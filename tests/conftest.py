"""Pytest defaults: legacy hand-rolled modules stay testable unless thin-glue tests opt in."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _disable_thin_glue_by_default(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    if request.node.get_closest_marker("thin_glue"):
        return
    monkeypatch.setenv("XINAO_THIN_GLUE_PROVIDER", "0")
    monkeypatch.setenv("XINAO_THIN_GLUE_INTAKE", "0")
    monkeypatch.setenv("XINAO_THIN_GLUE_SEARCH", "0")
    monkeypatch.setenv("XINAO_THIN_GLUE_LEDGER", "0")
    monkeypatch.setenv("XINAO_THIN_GLUE_WORKER_POOL", "0")