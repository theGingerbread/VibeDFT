"""Calculator-neutral result contracts used by the v2 platform."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


CleanedStatus = Literal["pass", "warn", "block", "failed", "running", "no_data"]
ReviewStatus = Literal["PASS", "WARN", "BLOCK"]


@dataclass(frozen=True)
class Evidence:
    """Structured evidence for traceability across parser and review stages."""

    source: str
    field: str
    value: Any
    interpretation: str
    line_number: int | None = None


@dataclass(frozen=True)
class Provenance:
    """Execution provenance for a single cleaned result."""

    calculator: str | None = None
    task: str | None = None
    version: str | None = None
    command: str | None = None
    working_directory: str | None = None
    hostname: str | None = None
    user: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Diagnostics:
    """Supplementary diagnostic payload for quality triage and audit."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CleanedResult:
    """Calculator-neutral result contract emitted by task clean stages."""

    calculator: str
    task: str
    status: CleanedStatus = "running"
    source_files: list[str] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    observables: dict[str, Any] = field(default_factory=dict)
    diagnostics: Diagnostics = field(default_factory=Diagnostics)
    readiness: dict[str, bool] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    # Backward-compatible legacy fields used by existing call sites/tests.
    schema_version: str = "0.1"
    source_artifacts: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        status = self.status.lower()
        if status not in {"pass", "warn", "block", "failed", "running", "no_data"}:
            raise ValueError(f"Unsupported cleaned status: {self.status}")
        object.__setattr__(self, "status", status)

        source_files = list(self.source_files or [])
        if self.source_artifacts:
            for artifact in self.source_artifacts:
                if artifact not in source_files:
                    source_files.append(artifact)
        if not source_files and self.source_artifacts:
            source_files = list(self.source_artifacts)
        object.__setattr__(self, "source_files", source_files)
        object.__setattr__(self, "source_artifacts", list(source_files))

        if self.payload and not self.outputs:
            object.__setattr__(self, "outputs", dict(self.payload))
        if self.outputs and not self.payload:
            object.__setattr__(self, "payload", dict(self.outputs))
        if self.payload and self.outputs:
            object.__setattr__(self, "payload", dict(self.outputs))

        if self.payload is None:
            object.__setattr__(self, "payload", dict(self.outputs))
        if self.schema_version is None:
            object.__setattr__(self, "schema_version", "0.1")


@dataclass(frozen=True)
class ReviewResult:
    """Structured PASS/WARN/BLOCK review output."""

    status: ReviewStatus
    reasons: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    allowed_downstream: list[str] = field(default_factory=list)
    blocked_downstream: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "WARN", "BLOCK"}:
            raise ValueError(f"Unsupported review status: {self.status}")
