"""Clean Quantum ESPRESSO NSCF outputs into calculator-neutral contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibedft._shared.contracts import (
    CleanedResult,
    Diagnostics,
    Evidence,
    Provenance,
    Readiness,
    DownstreamReadiness,
    ReviewResult,
)
from vibedft.calculator.qe.nscf.parse import NscfOutput, parse_nscf_output
from vibedft.calculator.qe.nscf.review import review_nscf_output
from vibedft.calculator.qe.nscf.schemas import NSCF_DOWNSTREAMS, NSCF_TASK_LEGACY


def clean_nscf_output(output: NscfOutput) -> CleanedResult:
    """Convert a parsed NSCF output into a normalized `CleanedResult`."""

    review_result = review_nscf_output(output)

    issue_errors = [event.message for event in output.issues if event.category in _SEVERE_ISSUES]
    issue_warnings = [
        event.message
        for event in output.issues
        if event.category not in _SEVERE_ISSUES and event.category != "truncated_output"
    ]

    diagnostics = Diagnostics(
        errors=issue_errors,
        warnings=issue_warnings,
        notes=_diagnostic_notes(output, review_result),
        evidence=[_to_evidence(event) for event in output.issues[:8]],
        metrics=_select_metrics(output),
        parser={
            "source": output.source,
            "source_summary": output.source,
            "program": output.program,
            "version": output.version,
            "iterations": len(output.iterations),
        },
        qe_messages={
            "issues_count": len(output.issues),
            "k_point_count": output.k_point_count,
        },
        numerical_risk={
            "workflow_readiness": (
                output.workflow_readiness.to_schema() if output.workflow_readiness is not None else None
            ),
            "stability_suitable_for_followup": (
                output.suitable_for_followup if output.stability_assessment is not None else False
            ),
            "suitable": output.stability_assessment.suitable_for_followup
            if output.stability_assessment is not None
            else None,
        },
        workflow_risk={
            "blocked_downstream": review_result.blocked_downstream,
            "allowed_downstream": review_result.allowed_downstream,
            "issues_count": len(output.issues),
        },
    )

    downstream = _build_downstream_readiness(output, review_result)

    return CleanedResult(
        calculator="qe",
        task=NSCF_TASK_LEGACY,
        status=_cleaned_status_from_review(review_result),
        review=review_result,
        source_files=[output.source] if output.source else [],
        provenance=Provenance(
            calculator="qe",
            task=NSCF_TASK_LEGACY,
            version=output.version,
            command="pw.x",
            started_at=None,
            completed_at=None,
            extra={"source": output.source},
        ),
        inputs=_build_input_payload(output),
        outputs=_build_output_payload(output),
        observables=_build_observables(output),
        diagnostics=diagnostics,
        readiness=Readiness(
            downstream=downstream,
            summary=_readiness_summary(output, review_result),
        ),
        warnings=list(review_result.reasons),
        next_actions=list(review_result.recommendations),
        payload=_build_output_payload(output),
    )


def clean_nscf_text(text_or_path: str | Path, *, source: str | Path | None = None) -> CleanedResult:
    """Parse raw text/path and return NSCF cleaned result contract in one call."""

    output = parse_nscf_output(text_or_path, source=source)
    return clean_nscf_output(output)


def _cleaned_status_from_review(review_result: ReviewResult) -> str:
    return {"PASS": "pass", "WARN": "warn", "BLOCK": "block"}[review_result.status]


def _build_input_payload(output: NscfOutput) -> dict[str, Any]:
    return {
        "input_parameters": output.input_parameters,
        "ecutwfc_ry": output.ecutwfc_ry,
        "ecutrho_ry": output.ecutrho_ry,
        "k_point_count": output.k_point_count,
        "k_point_mesh": output.k_point_mesh,
        "number_of_electrons": output.number_of_electrons,
        "number_of_bands": output.number_of_bands,
    }


def _build_output_payload(output: NscfOutput) -> dict[str, Any]:
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
        "k_point_count": output.k_point_count,
        "k_point_mesh": output.k_point_mesh,
        "number_of_bands": output.number_of_bands,
        "number_of_electrons": output.number_of_electrons,
    }


def _build_observables(output: NscfOutput) -> dict[str, Any]:
    return {
        "total_iterations": len(output.iterations),
        "final_energy_drift": _latest_energy_delta(output),
        "final_accuracy": output.final_scf_accuracy_ry,
        "fft_grids": dict(output.fft_grids),
    }


def _build_downstream_readiness(
    output: NscfOutput,
    review_result: ReviewResult,
) -> dict[str, DownstreamReadiness]:
    downstream: dict[str, DownstreamReadiness] = {}
    allowed = set(review_result.allowed_downstream)
    evidence_refs = sorted(
        event.evidence_id for event in review_result.evidence if event.evidence_id is not None
    )
    for task in NSCF_DOWNSTREAMS:
        if task in allowed:
            downstream[task] = DownstreamReadiness(
                task=task,
                allowed=True,
                reason="NSCF is accepted for this downstream branch.",
                evidence_refs=evidence_refs,
            )
        else:
            downstream[task] = DownstreamReadiness(
                task=task,
                allowed=False,
                reason=_downstream_block_reason(task, review_result),
                evidence_refs=evidence_refs,
            )
    return downstream


def _readiness_summary(output: NscfOutput, review_result: ReviewResult) -> str:
    if not output.job_done:
        return "NSCF output not finished."
    if review_result.status == "PASS":
        return "NSCF completed and accepted for constrained electronic follow-up."
    if review_result.status == "WARN":
        return "NSCF completed with cautions; downstream electronic workflows remain allowed."
    return "NSCF blocked due to execution or quality issues."


def _select_metrics(output: NscfOutput) -> dict[str, Any]:
    return {
        "issues_count": len(output.issues),
        "ready_for_followup": output.suitable_for_followup,
        "convergence_iterations": output.convergence_iterations,
        "convergence_threshold_ry": output.convergence_threshold_ry,
        "workflow_readiness_reason": (
            output.workflow_readiness.reason if output.workflow_readiness is not None else None
        ),
    }


def _diagnostic_notes(output: NscfOutput, review_result: ReviewResult) -> list[str]:
    notes: list[str] = [
        f"job_done={output.job_done}",
        f"converged={output.converged}",
        f"k_point_count={output.k_point_count}",
    ]
    if review_result.reasons:
        notes.append(" | ".join(review_result.reasons))
    return notes


def _latest_energy_delta(output: NscfOutput) -> float | None:
    if len(output.iterations) < 2:
        return None
    last = output.iterations[-1].total_energy_ry
    prev = output.iterations[-2].total_energy_ry
    if last is None or prev is None:
        return None
    return last - prev


def _downstream_block_reason(task: str, review_result: ReviewResult) -> str:
    if review_result.status != "BLOCK":
        return f"NSCF policy currently blocks {task} downstream path."
    return f"{task} blocked by NSCF review policy."


def _to_evidence(event: object) -> Evidence:
    return Evidence(
        source=getattr(event, "source", ""),
        field="issue",
        value=getattr(event, "message", None),
        interpretation=str(getattr(event, "category", "")),
        line_number=getattr(event, "line_number", None),
        artifact=getattr(event, "artifact", None),
        section=getattr(event, "section", None),
        evidence_id=getattr(event, "evidence_id", None),
    )


_SEVERE_ISSUES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}


__all__ = ["clean_nscf_output", "clean_nscf_text"]
