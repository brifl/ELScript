"""Shared secret-safe representation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

REDACTED = "<redacted>"
_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)


def is_sensitive_key(key: object) -> bool:
    normalized = str(key).casefold().replace("-", "_")
    return (
        normalized in _SENSITIVE_KEYS
        or normalized.startswith("authorization_")
        or normalized.endswith(("_api_key", "_password", "_secret", "_token"))
    )


def redact(value: Any, *, replacement: str = REDACTED) -> Any:
    """Return a recursively redacted representation suitable for diagnostics."""

    if isinstance(value, SecretValue):
        return replacement
    if isinstance(value, Mapping):
        return {
            str(key): (
                replacement if is_sensitive_key(key) else redact(item, replacement=replacement)
            )
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact(item, replacement=replacement) for item in value)
    if isinstance(value, list):
        return [redact(item, replacement=replacement) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class SecretValue:
    """Credential wrapper whose ordinary string representations are always redacted."""

    _value: str = field(repr=False)

    def reveal(self) -> str:
        """Return the credential only at the provider transport boundary."""

        return self._value

    def __repr__(self) -> str:
        return f"{type(self).__name__}({REDACTED!r})"

    def __str__(self) -> str:
        return REDACTED
