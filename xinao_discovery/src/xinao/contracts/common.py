"""Common envelope shared by domain objects, events, and typed handoffs."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from xinao.canonical.hashing import canonical_sha256
from xinao.canonical.identifiers import UUID7_PATTERN, require_uuid7
from xinao.canonical.time_profile import format_utc

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
UUID7String = Annotated[str, Field(pattern=UUID7_PATTERN)]
GitShaString = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Sha256String = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class CommonEnvelope(BaseModel):
    """Hash-bearing metadata required on first-class Xinao records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="xinao.common_envelope.v1", frozen=True)
    entity_id: UUID7String
    entity_type: str = Field(min_length=1)
    parent_ids: tuple[UUID7String, ...] = ()
    correlation_id: UUID7String
    causation_id: UUID7String | None = None
    created_at: datetime
    effective_at: datetime | None = None
    knowledge_cutoff_at: datetime | None = None
    source_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    git_sha: GitShaString
    config_hash: Sha256String
    rule_version: str | None = None
    content_hash: Sha256String | None = None
    idempotency_key: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    status: str = Field(min_length=1)

    @field_validator("entity_id", "correlation_id", "causation_id")
    @classmethod
    def validate_uuid7_field(cls, value: str | None) -> str | None:
        return None if value is None else require_uuid7(value)

    @field_validator("parent_ids")
    @classmethod
    def validate_parent_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("parent_ids must be unique")
        return tuple(require_uuid7(item) for item in value)

    @field_validator("git_sha")
    @classmethod
    def validate_git_sha(cls, value: str) -> str:
        if GIT_SHA_PATTERN.fullmatch(value) is None:
            raise ValueError("git_sha must be 40 lowercase hexadecimal characters")
        return value

    @field_validator("config_hash", "content_hash")
    @classmethod
    def validate_sha256(cls, value: str | None) -> str | None:
        if value is not None and SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("hash must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("created_at", "effective_at", "knowledge_cutoff_at")
    @classmethod
    def validate_timestamp_profile(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            format_utc(value)
        return value

    @field_serializer("created_at", "effective_at", "knowledge_cutoff_at")
    def serialize_timestamp(self, value: datetime | None) -> str | None:
        return None if value is None else format_utc(value)

    @model_validator(mode="after")
    def verify_content_hash(self) -> Self:
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match canonical envelope content")
        return self

    def canonical_content(self) -> dict[str, object]:
        """Return the JSON-compatible digest view, excluding the self hash."""

        return self.model_dump(mode="python", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> Self:
        """Return an immutable copy carrying its verified canonical hash."""

        return self.model_copy(update={"content_hash": self.compute_content_hash()})
