"""Clean Quantum ESPRESSO PDOS outputs into calculator-neutral contract."""

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
from vibedft.calculator.qe.pdos.parse import PdosOutput, parse_pdos_output
from vibedft.calculator.qe.pdos.review import review_pdos_output
from vibedft.calculator.qe.pdos.schemas import PDOS_DOWNSTREAMS, PDOS_TASK, PDOS_TASK_LEGACY


def clean_pdos_output(output: PdosOutput) -> CleanedResult:
    """Convert a parsed PDOS output into a normalized `CleanedResult`."""

    review_result = review_pdos_output(output)

    issue_errors = [event.message for event in output.issues if event.category in _SEVERE_ISSUES]
    issue_warnings = [
        event.message
        for event in output.issues
        if event.category not in _SEVERE_ISSUES and event.category != "truncated_output"
    ]

    diagnostics = Diagnostics(
        errors=issue_errors,
        warnings=issue_warnings,
        notes=["PDOS clean pass completed."],
        evidence=[_to_evidence(event) for event in output.issues[:8]],
        metrics={
            "pdos_readers": {
                "projection_file_count": output.projection_file_count,
                "atom_projector_count": output.atom_projector_count,
                "spin_channels": output.spin_channels,
            },
            "review": {
                "status": review_result.status,
                "reasons": review_result.reasons,
            },
        },
        parser={
            "source": output.source,
            "job_done": output.job_done,
            "version": output.version,
        },
        qe_messages={
            "issues_count": len(output.issues),
            "projection_files": output.projection_files,
        },
        numerical_risk={
            "energy_grid_count": output.energy_grid_count,
            "pdos_total_present": output.pdos_total_present,
        },
        workflow_risk={
            "allowed_downstream": review_result.allowed_downstream,
            "blocked_downstream": review_result.blocked_downstream,
            "orbital_channels": output.orbital_channels,
        },
    )

    downstream = _build_downstream_readiness(review_result)
    outputs = _build_output_payload(output)

    return CleanedResult(
        calculator="qe",
        task=PDOS_TASK_LEGACY,
        status=_cleaned_status_from_review(review_result),
        review=review_result,
        source_files=[output.source] if output.source else [],
        source_artifacts=[output.source] if output.source else [],
        provenance=Provenance(
            calculator="qe",
            task=PDOS_TASK_LEGACY,
            version=output.version,
            command="projwfc.x",
            started_at=None,
            completed_at=None,
            extra={"source": output.source, "source_task": PDOS_TASK},
        ),
        inputs={
            "program": output.program,
            "version": output.version,
            "source": output.source,
            "projection_files": output.projection_files,
        },
        outputs=outputs,
        observables=_build_observables(output),
        diagnostics=diagnostics,
        readiness=Readiness(
            downstream=downstream,
            summary=_readiness_summary(output, review_result),
        ),
        warnings=list(review_result.reasons),
        next_actions=list(review_result.recommendations),
        payload=outputs,
    )


def clean_pdos_text(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
    pdos_files: list[str | Path] | None = None,
) -> CleanedResult:
    """Parse PDOS text/path and return cleaned PDOS contract in one call."""

    output = parse_pdos_output(text_or_path, source=source, pdos_files=pdos_files)
    return clean_pdos_output(output)


def _cleaned_status_from_review(review_result: ReviewResult) -> str:
    return {"PASS": "pass", "WARN": "warn", "BLOCK": "block"}[review_result.status]


def _build_output_payload(output: PdosOutput) -> dict[str, Any]:
    return {
        "program": output.program,
        "version": output.version,
        "source": output.source,
        "job_done": output.job_done,
        "projection_files": list(output.projection_files),
        "projection_file_count": output.projection_file_count,
        "fermi_energy_ev": output.fermi_energy_ev,
        "energy_grid_count": output.energy_grid_count,
        "energy_min_ev": output.energy_min_ev,
        "energy_max_ev": output.energy_max_ev,
        "pdos_total_present": output.pdos_total_present,
        "atom_projector_count": output.atom_projector_count,
        "orbital_channels": list(output.orbital_channels),
    }


def _build_observables(output: PdosOutput) -> dict[str, Any]:
    return {
        "fermi_energy_ev": output.fermi_energy_ev,
        "energy_min_ev": output.energy_min_ev,
        "energy_max_ev": output.energy_max_ev,
        "spin_channels": output.spin_channels,
        "atom_projector_count": output.atom_projector_count,
        "orbital_channels": list(output.orbital_channels),
    }


def _build_downstream_readiness(review_result: ReviewResult) -> dict[str, DownstreamReadiness]:
    downstream: dict[str, DownstreamReadiness] = {}
    allowed = set(review_result.allowed_downstream)
    evidence_refs = sorted(
        event.evidence_id for event in review_result.evidence if event.evidence_id is not None
    )

    for task in PDOS_DOWNSTREAMS:
        if task in allowed:
            downstream[task] = DownstreamReadiness(
                task=task,
                allowed=True,
                reason="PDOS result accepted for this downstream branch.",
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


def _downstream_block_reason(task: str, review_result: ReviewResult) -> str:
    if review_result.status == "PASS":
        return f"PDOS analysis currently blocks {task}."
    return f"PDOS review blocked downstream task {task}."


def _readiness_summary(output: PdosOutput, review_result: ReviewResult) -> str:
    if not output.job_done:
        return "PDOS output did not complete."
    if review_result.status == "PASS":
        return "PDOS projections completed and accepted for analysis chains."
    if review_result.status == "WARN":
        return "PDOS output completed with caveats."
    return "PDOS result not suitable for downstream tasks."


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


__all__ = ["clean_pdos_output", "clean_pdos_text"]
