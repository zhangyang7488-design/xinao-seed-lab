"""Typed public errors for CLI and MCP adapters."""

from __future__ import annotations


class CoordinationError(RuntimeError):
    """A deterministic domain error that is safe to return to callers."""

    code = "coordination_error"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}

    def as_dict(self) -> dict[str, object]:
        return {"ok": False, "error": self.code, "message": str(self), "details": self.details}


class AuthorizationError(CoordinationError):
    code = "authorization_denied"


class ConflictError(CoordinationError):
    code = "conflict"


class InvalidTransitionError(CoordinationError):
    code = "invalid_transition"


class LeaseError(CoordinationError):
    code = "invalid_or_expired_lease"


class NotFoundError(CoordinationError):
    code = "not_found"


class ValidationError(CoordinationError):
    code = "validation_error"
