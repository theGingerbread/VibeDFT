"""Structure-layer placeholders."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StructureJob:
    """Minimal structure-side job definition."""

    source: str
    operations: list[str] = field(default_factory=list)
