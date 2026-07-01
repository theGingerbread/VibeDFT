"""Shared response envelopes for v2 CLI command handlers."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field, is_dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CommandError:
    """Machine-readable command error payload."""

    type: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandEnvelope:
    """Canonical command output envelope."""

    command: str
    ok: bool
    result: Any | None = None
    error: CommandError | None = None


def ok_envelope(command: str, result: Any) -> CommandEnvelope:
    """Build an envelope for successful command execution."""

    return CommandEnvelope(command=command, ok=True, result=result)


def error_envelope(command: str, exc: Exception) -> CommandEnvelope:
    """Build an envelope for failed command execution."""

    return CommandEnvelope(
        command=command,
        ok=False,
        error=CommandError(type=exc.__class__.__name__, message=str(exc)),
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Unsupported JSON type: {type(value)!r}")


def envelope_to_json_text(envelope: CommandEnvelope, *, pretty: bool) -> str:
    """Serialize a command envelope to JSON text."""

    payload = asdict(envelope)
    return json.dumps(
        payload,
        indent=2 if pretty else None,
        default=_json_default,
        ensure_ascii=False,
    )


__all__ = ["CommandError", "CommandEnvelope", "error_envelope", "ok_envelope", "envelope_to_json_text"]
