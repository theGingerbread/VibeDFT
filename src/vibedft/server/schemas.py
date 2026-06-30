"""Pydantic request/response models for the VibeDFT API.

All models are flat and stable — they mirror the internal dataclasses
without duplicating their logic.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════════
# Generic
# ═══════════════════════════════════════════════════════════════════════════════


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.2.0"


class ErrorResponse(BaseModel):
    detail: str


# ═══════════════════════════════════════════════════════════════════════════════
# Inspect
# ═══════════════════════════════════════════════════════════════════════════════


class InspectResponse(BaseModel):
    files: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Review
# ═══════════════════════════════════════════════════════════════════════════════


class ReviewRequest(BaseModel):
    case_id: Optional[str] = None


class ReviewResponse(BaseModel):
    case_dir: str = ""
    files_scanned: int = 0
    files_inspected: int = 0
    summary: str = ""
    next_step: str = ""
    n_errors: int = 0
    n_warnings: int = 0
    best_workflow: Optional[dict[str, Any]] = None
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    inspection: dict[str, Any] = Field(default_factory=dict)
    validation_issues: list[dict[str, Any]] = Field(default_factory=list)
    workflow_matches: list[dict[str, Any]] = Field(default_factory=list)
    physics: Optional[dict[str, Any]] = None


# ═══════════════════════════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════════════════════════


class ReportRequest(BaseModel):
    title: str = "VibeDFT Materials Report"


class ReportResponse(BaseModel):
    artifact_id: str
    format: str = "html"


# ═══════════════════════════════════════════════════════════════════════════════
# Convergence
# ═══════════════════════════════════════════════════════════════════════════════


class ConvergenceRequest(BaseModel):
    title: str = "VibeDFT Convergence Report"


class ConvergenceResponse(BaseModel):
    n_cases: int = 0
    overall_confidence: str = "unknown"
    varying_params: list[str] = Field(default_factory=list)
    converged: list[str] = Field(default_factory=list)
    unconverged: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Plan
# ═══════════════════════════════════════════════════════════════════════════════


class PlanRequest(BaseModel):
    prefix: str = "material"
    ecutwfc: int = 60
    ecutrho: int = 480
    tot_charge: float = 0.0
    profile: str = "cluster_debug"
    engine: str = "qe"


class PlanResponse(BaseModel):
    plan_id: str
    n_stages: int = 0
    stages: list[dict[str, Any]] = Field(default_factory=list)
    artifact_id: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# Artifact
# ═══════════════════════════════════════════════════════════════════════════════


class ArtifactListResponse(BaseModel):
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
