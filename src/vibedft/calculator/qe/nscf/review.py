"""NSCF review policy and pass/warn/block judgment."""

from __future__ import annotations

from vibedft._shared.contracts import Evidence, ReviewResult

from vibedft.calculator.qe.nscf.parse import NscfOutput
from vibedft.calculator.qe.nscf.schemas import NSCF_BASE_DOWNSTREAMS, NSCF_DOWNSTREAMS


_SEVERE_ISSUE_CATEGORIES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}


def review_nscf_output(output: NscfOutput) -> ReviewResult:
    """Evaluate parsed NSCF output into PASS/WARN/BLOCK review result."""

    evidence = _build_evidence(output)
    reasons: list[str] = []
    severe_issues = [issue for issue in output.issues if issue.category in _SEVERE_ISSUE_CATEGORIES]
    blocked_markers = [issue for issue in output.issues if issue.category == "truncated_output"]

    if blocked_markers or severe_issues:
        reasons.append(
            "NSCF output is incomplete or contains severe parser events: "
            + ", ".join(sorted({issue.category for issue in severe_issues + blocked_markers}))
        )
        return ReviewResult(
            status="BLOCK",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(NSCF_DOWNSTREAMS),
            recommendations=[
                "Rerun NSCF with complete stdout and valid settings before dependent electronic workflows."
            ],
        )

    if not output.job_done:
        reasons.append("NSCF job has not reached JOB DONE.")
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(NSCF_DOWNSTREAMS),
            recommendations=["Wait for NSCF completion or rerun the NSCF calculation."],
        )

    if not _has_required_output(output):
        reasons.append(
            "NSCF lacks required completion metadata (k-point count and electronic result payload)."
        )
        return ReviewResult(
            status="WARN",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=evidence,
            allowed_downstream=list(NSCF_BASE_DOWNSTREAMS),
            blocked_downstream=[name for name in NSCF_DOWNSTREAMS if name not in NSCF_BASE_DOWNSTREAMS],
            recommendations=[
                "Confirm NSCF wrote k-point and electronic payloads before production use."
            ],
        )

    if not output.converged:
        reasons.append("NSCF reported not converged before termination.")
        return ReviewResult(
            status="WARN",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=evidence,
            allowed_downstream=list(NSCF_BASE_DOWNSTREAMS),
            blocked_downstream=[name for name in NSCF_DOWNSTREAMS if name not in NSCF_BASE_DOWNSTREAMS],
            recommendations=["Review NSCF convergence behavior before downstream band/electronic work."],
        )

    quality_reasons: list[str] = []
    warning_categories = sorted(
        {
            event.category
            for event in output.issues
            if event.category == "warning"
            and event.category not in _SEVERE_ISSUE_CATEGORIES
        }
    )
    if warning_categories:
        quality_reasons.append(
            "Non-fatal warning(s) observed: " + ", ".join(warning_categories)
        )

    if quality_reasons:
        reasons.extend(quality_reasons)
        return ReviewResult(
            status="WARN",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=evidence,
            allowed_downstream=list(NSCF_BASE_DOWNSTREAMS),
            blocked_downstream=[name for name in NSCF_DOWNSTREAMS if name not in NSCF_BASE_DOWNSTREAMS],
            recommendations=[
                "NSCF quality is acceptable for constrained use; verify against production tolerance."
            ],
        )

    return ReviewResult(
        status="PASS",
        reasons=[],
        evidence=evidence,
        allowed_downstream=list(NSCF_BASE_DOWNSTREAMS),
        blocked_downstream=[name for name in NSCF_DOWNSTREAMS if name not in NSCF_BASE_DOWNSTREAMS],
        recommendations=[],
    )


def _build_evidence(output: NscfOutput) -> list[Evidence]:
    return [
        Evidence(
            source=output.source,
            field="job_done",
            value=output.job_done,
            interpretation="NSCF reached JOB DONE." if output.job_done else "JOB DONE marker absent.",
            line_number=_first_issue_line(output, "job_done"),
        ),
        Evidence(
            source=output.source,
            field="converged",
            value=output.converged,
            interpretation=("NSCF converged." if output.converged else "NSCF not converged."),
            line_number=_first_issue_line(output, "convergence"),
        ),
        Evidence(
            source=output.source,
            field="k_point_count",
            value=output.k_point_count,
            interpretation="Parsed k-point count from QE input/output.",
            line_number=_first_issue_line(output, "k-point"),
        ),
        Evidence(
            source=output.source,
            field="number_of_bands",
            value=output.number_of_bands,
            interpretation="Parsed Kohn-Sham band count.",
            line_number=_first_issue_line(output, "Kohn-Sham"),
        ),
        Evidence(
            source=output.source,
            field="final_total_energy_ry",
            value=output.final_total_energy_ry,
            interpretation="Final scalar total energy from NSCF trajectory.",
            line_number=None,
        ),
        Evidence(
            source=output.source,
            field="issues_categories",
            value=sorted({issue.category for issue in output.issues}),
            interpretation="All parsed issue categories seen in NSCF output.",
            line_number=None,
        ),
    ]


def _has_required_output(output: NscfOutput) -> bool:
    has_k_point = output.k_point_count is not None and output.k_point_count > 0
    has_energy = output.final_total_energy_ry is not None or output.final_scf_accuracy_ry is not None
    has_electronic_step = output.convergence_iterations is not None or output.number_of_bands is not None
    return bool(has_k_point and has_energy and has_electronic_step)


def _first_issue_line(output: NscfOutput, category: str) -> int | None:
    for issue in output.issues:
        if category.lower() in issue.message.lower() or category.lower() in issue.category.lower():
            return issue.line_number
    return None


__all__ = ["review_nscf_output"]
