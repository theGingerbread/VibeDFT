"""Clean Quantum ESPRESSO DOS outputs into calculator-neutral contract."""

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
from vibedft.calculator.qe.dos.parse import DosOutput, parse_dos_output
from vibedft.calculator.qe.dos.review import review_dos_output
from vibedft.calculator.qe.dos.schemas import DOS_DOWNSTREAMS, DOS_TASK, DOS_TASK_LEGACY


def clean_dos_output(output: DosOutput) -> CleanedResult:
    """Convert a parsed DOS output into a normalized `CleanedResult`."""

    review_result = review_dos_output(output)

    issue_errors = [event.message for event in output.issues if event.category in _SEVERE_ISSUES]
    issue_warnings = [
        event.message
        for event in output.issues
        if event.category not in _SEVERE_ISSUES and event.category != "truncated_output"
    ]

    diagnostics = Diagnostics(
        errors=issue_errors,
        warnings=issue_warnings,
        notes=["DOS clean pass completed."],
        evidence=[_to_evidence(event) for event in output.issues[:8]],
        metrics={
            "output_flags": {
                "job_done": output.job_done,
                "integrated_dos_present": output.integrated_dos_present,
                "data_columns": output.data_columns,
            },
            "review": {
                "status": review_result.status,
                "reasons": review_result.reasons,
            },
        },
        parser={},
        qe_messages={
            "source": output.source,
            "issues_count": len(output.issues),
        },
        numerical_risk={
            "energy_grid_count": output.energy_grid_count,
            "dos_range_valid": output.dos_min is not None and output.dos_max is not None,
        },
        workflow_risk={
            "allowed_downstream": review_result.allowed_downstream,
            "blocked_downstream": review_result.blocked_downstream,
        },
    )

    downstream = _build_downstream_readiness(review_result)
    outputs = _build_output_payload(output)

    return CleanedResult(
        calculator="qe",
        task=DOS_TASK_LEGACY,
        status=_cleaned_status_from_review(review_result),
        review=review_result,
        source_files=[output.source] if output.source else [],
        source_artifacts=[output.source] if output.source else [],
        provenance=Provenance(
            calculator="qe",
            task=DOS_TASK_LEGACY,
            version=output.version,
            command="dos.x",
            started_at=None,
            completed_at=None,
            extra={"source": output.source, "source_task": DOS_TASK},
        ),
        inputs={
            "program": output.program,
            "version": output.version,
            "source": output.source,
            "data_file": output.data_file,
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


def clean_dos_text(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
    data_file: str | Path | None = None,
) -> CleanedResult:
    """Parse DOS text/path and return cleaned DOS contract in one call."""

    output = parse_dos_output(text_or_path, source=source, data_file=data_file)
    return clean_dos_output(output)


def _cleaned_status_from_review(review_result: ReviewResult) -> str:
    return {"PASS": "pass", "WARN": "warn", "BLOCK": "block"}[review_result.status]


def _build_output_payload(output: DosOutput) -> dict[str, Any]:
    return {
        "program": output.program,
        "version": output.version,
        "source": output.source,
        "job_done": output.job_done,
        "energy_grid_count": output.energy_grid_count,
        "energy_min_ev": output.energy_min_ev,
        "energy_max_ev": output.energy_max_ev,
        "dos_min": output.dos_min,
        "dos_max": output.dos_max,
        "data_file": output.data_file,
        "integrated_dos_present": output.integrated_dos_present,
    }


def _build_observables(output: DosOutput) -> dict[str, Any]:
    return {
        "fermi_energy_ev": output.fermi_energy_ev,
        "energy_min_ev": output.energy_min_ev,
        "energy_max_ev": output.energy_max_ev,
        "dos_min": output.dos_min,
        "dos_max": output.dos_max,
        "data_column_count": len(output.data_columns),
        "data_columns": list(output.data_columns),
    }


def _build_downstream_readiness(review_result: ReviewResult) -> dict[str, DownstreamReadiness]:
    downstream: dict[str, DownstreamReadiness] = {}
    allowed = set(review_result.allowed_downstream)
    evidence_refs = sorted(
        event.evidence_id for event in review_result.evidence if event.evidence_id is not None
    )

    for task in DOS_DOWNSTREAMS:
        if task in allowed:
            downstream[task] = DownstreamReadiness(
                task=task,
                allowed=True,
                reason="DOS result accepted for this analysis branch.",
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
        return f"analysis gate blocks {task} for this DOS result."
    return f"DOS review blocked downstream task {task}."


def _readiness_summary(output: DosOutput, review_result: ReviewResult) -> str:
    if not output.job_done:
        return "DOS calculation did not complete."
    if review_result.status == "PASS":
        return "DOS data completed and accepted for analysis.dos."
    if review_result.status == "WARN":
        return "DOS output completed with caveats."
    return "DOS result is not usable for downstream tasks."


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


__all__ = ["clean_dos_output", "clean_dos_text"]
