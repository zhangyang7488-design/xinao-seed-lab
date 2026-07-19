"""Fail-closed error types with stable machine codes."""

from __future__ import annotations


class SingleHomeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class DualHomeDenyError(SingleHomeError):
    """Raised when dual ledger classes or forbidden parallel homes appear."""


class FieldDriftDenyError(SingleHomeError):
    """Raised when required field sets silently drift from the frozen contract."""
