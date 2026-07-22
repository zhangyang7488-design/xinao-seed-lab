"""Repository-owned deterministic counter/hash stream.

Randomness is derived only from caller-supplied secret bytes and an explicit
domain tag. The secret is held only in process memory on this object and is
never exposed by public methods as hex/base64/raw bytes.
"""

from __future__ import annotations

import hashlib
import hmac
import struct
from collections.abc import Sequence
from typing import TypeVar

from .constants import MIN_SECRET_BYTES, STREAM_DOMAIN

T = TypeVar("T")


class DeterministicStream:
    """HMAC-SHA256 counter stream bound to secret + domain + label."""

    __slots__ = ("_counter", "_domain", "_key", "_label")

    def __init__(self, secret: bytes, *, label: str, domain: bytes = STREAM_DOMAIN) -> None:
        if not isinstance(secret, (bytes, bytearray)):
            raise TypeError("secret must be bytes")
        secret_b = bytes(secret)
        if len(secret_b) < MIN_SECRET_BYTES:
            raise ValueError(f"secret must be at least {MIN_SECRET_BYTES} bytes")
        if not label:
            raise ValueError("stream label must be non-empty")
        # Derive a working key so the original secret is not retained longer than needed
        # for construction; only the derived key remains on the instance.
        label_bytes = label.encode("utf-8")
        self._key = hmac.new(secret_b, domain + b"\0" + label_bytes, hashlib.sha256).digest()
        self._domain = domain
        self._label = label
        self._counter = 0

    @property
    def label(self) -> str:
        return self._label

    @property
    def counter(self) -> int:
        return self._counter

    def _block(self) -> bytes:
        msg = self._domain + b"\0ctr\0" + self._counter.to_bytes(8, "big")
        self._counter += 1
        return hmac.new(self._key, msg, hashlib.sha256).digest()

    def rand_bytes(self, n: int) -> bytes:
        if n < 0:
            raise ValueError("n must be non-negative")
        out = bytearray()
        while len(out) < n:
            out.extend(self._block())
        return bytes(out[:n])

    def rand_uint64(self) -> int:
        return int.from_bytes(self.rand_bytes(8), "big")

    def rand_float(self) -> float:
        """Uniform float in [0.0, 1.0)."""
        # 53-bit mantissa path for stable double construction
        x = self.rand_uint64() >> 11
        return x / float(1 << 53)

    def rand_int(self, low: int, high: int) -> int:
        """Inclusive integer in [low, high]."""
        if high < low:
            raise ValueError("high must be >= low")
        span = high - low + 1
        # Rejection sampling to avoid modulo bias
        limit = (1 << 64) - ((1 << 64) % span)
        while True:
            v = self.rand_uint64()
            if v < limit:
                return low + (v % span)

    def choice(self, items: Sequence[T]) -> T:
        if not items:
            return self._empty_choice()
        return items[self.rand_int(0, len(items) - 1)]

    def _empty_choice(self) -> T:  # pragma: no cover - defensive
        raise ValueError("cannot choice from empty sequence")

    def shuffle(self, items: Sequence[T]) -> list[T]:
        result = list(items)
        for i in range(len(result) - 1, 0, -1):
            j = self.rand_int(0, i)
            result[i], result[j] = result[j], result[i]
        return result

    def rand_signed_unit(self) -> float:
        """Uniform float in (-1.0, 1.0)."""
        return self.rand_float() * 2.0 - 1.0

    def hex_token(self, nbytes: int = 16) -> str:
        return self.rand_bytes(nbytes).hex()

    def fork(self, label: str) -> DeterministicStream:
        """Derive an independent child stream without consuming parent bytes."""
        if not label:
            raise ValueError("fork label must be non-empty")
        return DeterministicStream(
            self._key,
            label=f"{self._label}/{label}",
            domain=self._domain + b"\0fork-v1",
        )

    def __repr__(self) -> str:
        return f"DeterministicStream(label={self._label!r}, counter={self._counter})"

    def __getstate__(self) -> object:
        # Block pickling to reduce accidental secret/key leakage surfaces.
        raise TypeError("DeterministicStream is not serializable")


def derive_split_label(split: str, family_id: str, case_index: int) -> str:
    return f"{split}:{family_id}:{case_index:04d}"


def digest_label_bytes(*parts: bytes) -> bytes:
    h = hashlib.sha256()
    for p in parts:
        h.update(len(p).to_bytes(4, "big"))
        h.update(p)
    return h.digest()


def opaque_case_id(*, commitment_material_digest: str, suite_label: str, ordinal: int) -> str:
    """Content-addressed opaque public case id (no family/split tokens)."""
    raw = hashlib.sha256(
        b"xinao.g4.public_case_id.v1\0"
        + commitment_material_digest.encode("ascii")
        + b"\0"
        + suite_label.encode("utf-8")
        + b"\0"
        + struct.pack(">I", ordinal)
    ).hexdigest()
    return f"pc_{raw[:40]}"
