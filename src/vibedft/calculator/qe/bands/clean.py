"""Clean Quantum ESPRESSO bands outputs into calculator-neutral contract."""

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
from vibedft.calculator.qe.bands.parse import BandsOutput, parse_bands_output
from vibedft.calculator.qe.bands.review import review_bands_output
from vibedft.calculator.qe.bands.schemas import BANDS_DOWNSTREAMS, BANDS_TASK_LEGACY


def clean_bands_output(output: BandsOutput) -> CleanedResult:
    """Convert a parsed bands output into a normalized `CleanedResult`."""

    review_result = review_bands_output(output)

    issue_errors = [event.message for event in output.issues if event.category in _SEVERE_ISSUES]
    issue_warnings = [
        event.message
        for event in output.issues
        if event.category not in _SEVERE_ISSUES and event.category != "truncated_output"
    ]

    outputs = _build_output_payload(output)
    observables = _build_observables(output)
    downstream = _build_downstream_readiness(review_result)

    diagnostics = Diagnostics(
        errors=issue_errors,
        warnings=issue_warnings,
        notes=["Bands clean pass completed."],
        evidence=[_to_evidence(event) for event in output.issues[:8]],
        metrics={
            "output_flags": {
                "job_done": output.job_done,
                "band_data_present": output.band_data_present,
                "high_symmetry_label_count": len(output.high_symmetry_labels),
                "k_point_path_points": len(output.k_point_path),
            },
            "review": {
                "status": review_result.status,
                "reasons": review_result.reasons,
            },
        },
        parser={
            "source": output.source,
            "data_file": output.data_file,
            "program_detected": output.program,
        },
        qe_messages={
            "source": output.source,
            "issues_count": len(output.issues),
        },
        numerical_risk={
            "k_point_count": output.k_point_count,
            "band_count": output.band_count,
            "energy_range_valid": output.energy_min_ev is not None and output.energy_max_ev is not None,
            "eigenvalue_row_count": output.eigenvalue_row_count,
        },
        workflow_risk={
            "allowed_downstream": review_result.allowed_downstream,
            "blocked_downstream": review_result.blocked_downstream,
        },
    )

    return CleanedResult(
        calculator="qe",
        task=BANDS_TASK_LEGACY,
        status=_cleaned_status_from_review(review_result),
        review=review_result,
        source_files=[output.source] if output.source else [],
        source_artifacts=[output.source] if output.source else [],
        provenance=Provenance(
            calculator="qe",
            task=BANDS_TASK_LEGACY,
            version=output.version,
            command="bands.x",
            started_at=None,
            completed_at=None,
            extra={"source": output.source, "program": output.program},
        ),
        inputs={
            "program": output.program,
            "version": output.version,
            "source": output.source,
            "data_file": output.data_file,
            "fermi_energy_ev": output.fermi_energy_ev,
            "reference_energy_ev": output.reference_energy_ev,
        },
        outputs=outputs,
        observables=observables,
        diagnostics=diagnostics,
        readiness=Readiness(
            downstream=downstream,
            summary=_readiness_summary(output, review_result),
        ),
        warnings=list(review_result.reasons),
        next_actions=list(review_result.recommendations),
        payload=outputs,
    )


def clean_bands_text(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
    data_file: str | Path | None = None,
) -> CleanedResult:
    """Parse bands text/path and return cleaned bands contract in one call."""

    output = parse_bands_output(text_or_path, source=source, data_file=data_file)
    return clean_bands_output(output)


def _cleaned_status_from_review(review_result: ReviewResult) -> str:
    return {"PASS": "pass", "WARN": "warn", "BLOCK": "block"}[review_result.status]


def _build_output_payload(output: BandsOutput) -> dict[str, Any]:
    return {
        "program": output.program,
        "version": output.version,
        "source": output.source,
        "job_done": output.job_done,
        "band_data_present": output.band_data_present,
        "k_point_count": output.k_point_count,
        "band_count": output.band_count,
        "high_symmetry_labels": list(output.high_symmetry_labels),
        "data_file": output.data_file,
    }


def _build_observables(output: BandsOutput) -> dict[str, Any]:
    return {
        "fermi_energy_ev": output.fermi_energy_ev,
        "reference_energy_ev": output.reference_energy_ev,
        "energy_min_ev": output.energy_min_ev,
        "energy_max_ev": output.energy_max_ev,
        "estimated_band_gap_ev": _estimate_band_gap(output),
        "band_data_points": output.eigenvalue_row_count,
    }


def _estimate_band_gap(output: BandsOutput) -> float | None:
    if output.energy_min_ev is None or output.energy_max_ev is None:
        return None
    if output.fermi_energy_ev is None and output.reference_energy_ev is None:
        return None

    # Conservative estimation rule: only infer when both bands boundaries and reference are available.
    if output.reference_energy_ev is not None:
        ref = output.reference_energy_ev
    elif output.fermi_energy_ev is not None:
        ref = output.fermi_energy_ev
    else:
        return None

    if output.energy_min_ev <= ref <= output.energy_max_ev:
        # If range spans the reference, gap estimate can be non-robust.
        return None

    return abs(output.energy_max_ev - output.energy_min_ev)


def _build_downstream_readiness(review_result: ReviewResult) -> dict[str, DownstreamReadiness]:
    downstream: dict[str, DownstreamReadiness] = {}
    allowed = set(review_result.allowed_downstream)
    evidence_refs = sorted(
        event.evidence_id for event in review_result.evidence if event.evidence_id is not None
    )

    for task in BANDS_DOWNSTREAMS:
        if task in allowed:
            downstream[task] = DownstreamReadiness(
                task=task,
                allowed=True,
                reason="Bands result accepted for this analysis branch.",
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
        return f"analysis gate blocks {task} for this bands result."
    if review_result.status == "WARN":
        return "Bands review completed with caveats; analysis-only downstream is allowed only."
    return f"bands review blocked downstream task {task}."


def _readiness_summary(output: BandsOutput, review_result: ReviewResult) -> str:
    if not output.job_done:
        return "Bands calculation did not complete."
    if review_result.status == "PASS":
        return "Bands completed and accepted for analysis.bands and analysis.bandgap."
    if review_result.status == "WARN":
        return "Bands completed with caveats; downstream restricted to analysis domains."
    return "Bands result is not usable for downstream workflows."


def _to_evidence(event: Any) -> Evidence:
    return Evidence(
        source=getattr(event, "source", ""),
        line_number=getattr(event, "line_number", None),
        line_start=getattr(event, "line_start", None),
        line_end=getattr(event, "line_end", None),
        artifact=getattr(event, "artifact", None),
        section=getattr(event, "section", None),
        evidence_id=getattr(event, "evidence_id", None),
        field="issue",
        value=getattr(event, "message", None),
        interpretation=getattr(event, "category", ""),
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


__all__ = ["clean_bands_output", "clean_bands_text"]
