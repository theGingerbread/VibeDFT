"""Calculator-neutral result contracts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CleanedResult:
    """Uniform result contract emitted by calculator backends."""

    calculator: str
    task: str
    schema_version: str
    source_artifacts: list[str] = field(default_factory=list)
    payload: dict[str, object] = field(default_factory=dict)
