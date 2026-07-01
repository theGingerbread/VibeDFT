"""Clean Quantum ESPRESSO pp.x outputs into calculator-neutral contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibedft._shared.contracts import (
    CleanedResult,
    Diagnostics,
    DownstreamReadiness,
    Evidence,
    Provenance,
    Readiness,
    ReviewResult,
)
from vibedft.calculator.qe.pp.parse import PpOutput, parse_pp_output
from vibedft.calculator.qe.pp.review import review_pp_output
from vibedft.calculator.qe.pp.schemas import PP_DOWNSTREAMS, PP_TASK, PP_TASK_LEGACY


_SEVERE_ISSUES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}


def clean_pp_output(output: PpOutput) -> CleanedResult:
    """Convert a parsed pp.x output into a normalized `CleanedResult`."""

    review_result = review_pp_output(output)
    outputs = _build_output_payload(output)
    observables = _build_observables(output)

    issue_errors = [
        event.message
        for event in output.issues
        if event.category in _SEVERE_ISSUES or event.category == "truncated_output"
    ]
    issue_warnings = [
        event.message
        for event in output.issues
        if event.category not in _SEVERE_ISSUES and event.category != "truncated_output"
    ]

    diagnostics = Diagnostics(
        errors=issue_errors,
        warnings=issue_warnings,
        notes=["pp.x clean pass completed."],
        evidence=[_to_evidence(event) for event in output.issues[:8]],
        metrics={
            "artifact_counts": {
                "output_file_count": len(output.output_files),
                "existing_output_file_count": len(output.existing_output_files),
                "nonempty_output_file_count": len(output.nonempty_output_files),
                "data_file_count": output.data_file_count,
            },
            "review": {
                "status": review_result.status,
                "reasons": review_result.reasons,
            },
        },
        parser={
            "source": output.source,
            "program": output.program,
            "version": output.version,
            "job_done": output.job_done,
            "stdout_output_hints": list(output.stdout_output_hints),
        },
        qe_messages={
            "issues_count": len(output.issues),
            "issues": [event.category for event in output.issues],
        },
        numerical_risk={
            "data_sample_count": output.data_sample_count,
            "data_min": output.data_min,
            "data_max": output.data_max,
            "data_columns": list(output.data_columns),
        },
        workflow_risk={
            "field_kind": output.field_kind,
            "output_format": output.output_format,
            "allowed_downstream": list(review_result.allowed_downstream),
            "blocked_downstream": list(review_result.blocked_downstream),
        },
    )

    source_items = _source_items(output)

    return CleanedResult(
        calculator="qe",
        task=PP_TASK_LEGACY,
        status=_cleaned_status_from_review(review_result),
        review=review_result,
        source_files=source_items,
        source_artifacts=source_items,
        provenance=Provenance(
            calculator="qe",
            task=PP_TASK_LEGACY,
            version=output.version,
            command="pp.x",
            started_at=None,
            completed_at=None,
            extra={"source": output.source, "source_task": PP_TASK, "program": output.program},
        ),
        inputs={
            "program": output.program,
            "version": output.version,
            "source": output.source,
            "plot_num": output.plot_num,
            "stdout_output_hints": list(output.stdout_output_hints),
        },
        outputs=outputs,
        observables=observables,
        diagnostics=diagnostics,
        readiness=Readiness(
            downstream=_build_downstream_readiness(review_result),
            summary=_readiness_summary(output, review_result),
        ),
        warnings=list(review_result.reasons),
        next_actions=list(review_result.recommendations),
        payload=outputs,
    )


def clean_pp_text(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
    data_files: list[str | Path] | None = None,
) -> CleanedResult:
    """Parse pp.x text/path and return cleaned pp.x contract in one call."""

    output = parse_pp_output(text_or_path, source=source, data_files=data_files)
    return clean_pp_output(output)


def _cleaned_status_from_review(review_result: ReviewResult) -> str:
    return {"PASS": "pass", "WARN": "warn", "BLOCK": "block"}[review_result.status]


def _build_output_payload(output: PpOutput) -> dict[str, Any]:
    return {
        "job_done": output.job_done,
        "plot_num": output.plot_num,
        "field_kind": output.field_kind,
        "output_format": output.output_format,
        "output_files": list(output.output_files),
        "existing_output_files": list(output.existing_output_files),
        "nonempty_output_files": list(output.nonempty_output_files),
        "data_file_count": output.data_file_count,
    }


def _build_observables(output: PpOutput) -> dict[str, Any]:
    return {
        "data_sample_count": output.data_sample_count,
        "data_min": output.data_min,
        "data_max": output.data_max,
        "data_columns": list(output.data_columns),
        "artifact_extensions": list(output.artifact_extensions),
    }


def _build_downstream_readiness(review_result: ReviewResult) -> dict[str, DownstreamReadiness]:
    downstream: dict[str, DownstreamReadiness] = {}
    allowed = set(review_result.allowed_downstream)
    evidence_refs = sorted(
        event.evidence_id for event in review_result.evidence if event.evidence_id is not None
    )

    for task in PP_DOWNSTREAMS:
        if task in allowed:
            downstream[task] = DownstreamReadiness(
                task=task,
                allowed=True,
                reason="pp.x result accepted for this analysis branch.",
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
    if review_result.status == "BLOCK":
        return f"pp.x review blocked downstream task {task}."
    if task in {"bader", "workfunction"}:
        return f"pp.x contract does not release {task} by default."
    if task in {"scf", "relax", "vc_relax", "nscf", "bands", "dos", "pdos", "phonon", "dielectric", "epc", "tc"}:
        return f"pp.x is analysis-facing and blocks compute downstream task {task}."
    return f"pp.x field kind or artifact evidence does not release {task}."


def _readiness_summary(output: PpOutput, review_result: ReviewResult) -> str:
    if not output.job_done:
        return "pp.x output did not complete."
    if review_result.status == "PASS":
        return "pp.x artifact completed and accepted for analysis.pp plus eligible field analysis."
    if review_result.status == "WARN":
        return "pp.x output completed with caveats; downstream remains analysis-limited."
    return "pp.x result is not suitable for downstream tasks."


def _source_items(output: PpOutput) -> list[str]:
    items: list[str] = []
    if output.source:
        items.append(output.source)
    for item in list(output.output_files) + list(output.existing_output_files):
        if item not in items:
            items.append(item)
    return items


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


__all__ = ["clean_pp_output", "clean_pp_text"]
