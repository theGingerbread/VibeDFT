"""Analysis-layer contracts for reports derived from CleanedResult."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


FindingLevel = Literal["info", "warn", "block"]


@dataclass(frozen=True)
class AnalysisFinding:
    """A lightweight, serializable finding produced by analysis layer."""

    level: FindingLevel
    category: str
    message: str
    evidence_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.level not in {"info", "warn", "block"}:
            raise ValueError(f"Unsupported finding level: {self.level}")


@dataclass(frozen=True)
class AnalysisReport:
    """Task-scoped analysis report.

    This contract is computed only from `CleanedResult` and does not apply new
    scientific policy.
    """

    calculator: str
    task: str
    status: str
    review_status: str | None
    domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=list)
    summary: str = ""
    key_observables: dict[str, Any] = field(default_factory=dict)
    source_artifacts: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    findings: list[AnalysisFinding] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisBundle:
    """Aggregated view over multiple task-cleaned results."""

    reports: list[AnalysisReport] = field(default_factory=list)
    task_order: list[str] = field(default_factory=list)
    available_domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=list)
    findings: list[AnalysisFinding] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "AnalysisFinding",
    "AnalysisReport",
    "AnalysisBundle",
    "FindingLevel",
]

