"""Clean QE SCF outputs into calculator-neutral contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibedft._shared.contracts import (
    CleanedResult,
    Diagnostics,
    Evidence,
    Provenance,
    ReviewResult,
)
from vibedft.calculator.qe.scf.parse import ScfOutput, parse_scf_output
from vibedft.calculator.qe.scf.review import review_scf_output
from vibedft.calculator.qe.scf.schemas import SCF_TASK_LEGACY


def clean_scf_output(output: ScfOutput) -> CleanedResult:
    """Convert a parsed SCF output into a normalized `CleanedResult`."""

    review_result = review_scf_output(output)

    allowed = {name for name in review_result.allowed_downstream}
    blocked = {name for name in review_result.blocked_downstream}

    issue_errors = [event.message for event in output.issues if event.category == "error"]
    issue_warnings = [
        event.message for event in output.issues if event.category not in {"error", "truncated_output"}
    ]
    issue_notes: list[str] = []
    if output.stability_assessment is not None:
        issue_notes.append(output.stability_assessment.likely_root_cause or "no major root-cause annotation")
        issue_notes.append(output.stability_assessment.impact_on_observables or "no impact note")

    diagnostics = Diagnostics(
        errors=issue_errors,
        warnings=issue_warnings,
        notes=issue_notes,
        metrics={
            "parse_payload": _select_metrics(output),
            "stability": _to_schema(output.stability_assessment),
            "convergence_dynamics": output.convergence_dynamics.to_schema()
            if output.convergence_dynamics is not None
            else None,
            "workflow_readiness": output.workflow_readiness.to_schema()
            if output.workflow_readiness is not None
            else None,
            "review": {
                "status": review_result.status,
                "reasons": review_result.reasons,
            },
        },
        evidence=[_to_evidence(event) for event in output.issues[:8]],
    )

    return CleanedResult(
        calculator="qe",
        task=SCF_TASK_LEGACY,
        status=_cleaned_status_from_review(review_result),
        source_files=[output.source] if output.source else [],
        source_artifacts=[output.source] if output.source else [],
        provenance=Provenance(
            calculator="qe",
            task=SCF_TASK_LEGACY,
            version=output.version,
            command="pw.x",
            working_directory=None,
            hostname=None,
            user=None,
            started_at=None,
            completed_at=None,
            extra={"source": output.source},
        ),
        inputs=_build_input_payload(output),
        outputs=_build_output_payload(output),
        observables=_build_observables(output),
        diagnostics=diagnostics,
        readiness={
            "job_done": output.job_done,
            "converged": output.converged,
            "workflow_readiness": (
                output.workflow_readiness.to_schema()
                if output.workflow_readiness is not None
                else None
            ),
            "allowed_downstream": sorted(allowed),
            "blocked_downstream": sorted(blocked),
        },
        warnings=_build_warnings(review_result, output),
        next_actions=list(review_result.recommendations),
        payload=_build_output_payload(output),
    )


def clean_scf_text(text_or_path: str | Path, *, source: str | Path | None = None) -> CleanedResult:
    """Parse SCF text / path and return cleaned SCF contract in one call."""

    output = parse_scf_output(text_or_path, source=source)
    return clean_scf_output(output)


def _cleaned_status_from_review(review_result: ReviewResult) -> str:
    return {"PASS": "pass", "WARN": "warn", "BLOCK": "block"}[review_result.status]


def _build_input_payload(output: ScfOutput) -> dict[str, Any]:
    return {
        "input_parameters": output.input_parameters,
        "ecutwfc_ry": output.ecutwfc_ry,
        "ecutrho_ry": output.ecutrho_ry,
        "k_point_count": output.k_point_count,
        "k_point_mesh": output.k_point_mesh,
        "number_of_electrons": output.number_of_electrons,
        "number_of_bands": output.number_of_bands,
    }


def _build_output_payload(output: ScfOutput) -> dict[str, Any]:
    return {
        "program": output.program,
        "version": output.version,
        "job_done": output.job_done,
        "converged": output.converged,
        "convergence_iterations": output.convergence_iterations,
        "final_total_energy_ry": output.final_total_energy_ry,
        "final_total_energy_ev": output.final_total_energy_ev,
        "final_scf_accuracy_ry": output.final_scf_accuracy_ry,
        "fermi_energy_ev": output.fermi_energy_ev,
    }


def _build_observables(output: ScfOutput) -> dict[str, Any]:
    return {
        "cpu_seconds": output.cpu_seconds,
        "wall_seconds": output.wall_seconds,
        "total_iterations": len(output.iterations),
        "fft_grids": dict(output.fft_grids),
    }


def _build_warnings(review_result: ReviewResult, output: ScfOutput) -> list[str]:
    warnings = list(review_result.reasons)
    if output.stability_assessment is not None and output.stability_assessment.recommendations:
        warnings.extend(output.stability_assessment.recommendations)
    return warnings


def _to_schema(value: Any) -> dict[str, Any] | None:
    schema_fn = getattr(value, "to_schema", None)
    if callable(schema_fn):
        return schema_fn()
    return None


def _select_metrics(output: ScfOutput) -> dict[str, Any]:
    return {
        "issues_count": len(output.issues),
        "ready_for_followup": output.suitable_for_followup,
        "workflow_readiness_reason": (
            output.workflow_readiness.reason if output.workflow_readiness is not None else None
        ),
        "stability_severity": (
            output.stability_assessment.severity
            if output.stability_assessment is not None
            else None
        ),
    }


def _to_evidence(event: Any) -> Evidence:
    return Evidence(
        source=getattr(event, "source", ""),
        line_number=getattr(event, "line_number", None),
        field="issue",
        value=getattr(event, "message", None),
        interpretation=getattr(event, "category", ""),
    )


__all__ = ["clean_scf_output", "clean_scf_text"]
