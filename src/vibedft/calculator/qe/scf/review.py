"""SCF review policy and pass/warn/block judgment."""

from __future__ import annotations

from typing import Any

from vibedft._shared.contracts import Evidence, ReviewResult

from vibedft.calculator.qe.scf.parse import ScfOutput
from vibedft.calculator.qe.scf.schemas import SCF_BASE_DOWNSTREAMS, SCF_DOWNSTREAMS


_SEVERE_ISSUE_CATEGORIES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}


def review_scf_output(output: ScfOutput) -> ReviewResult:
    """Evaluate a parsed SCF output into PASS/WARN/BLOCK review result."""

    evidence = _build_evidence(output)
    reasons: list[str] = []
    severe_issues = [
        issue for issue in output.issues if issue.category in _SEVERE_ISSUE_CATEGORIES
    ]
    blocked_markers = [issue for issue in output.issues if issue.category == "truncated_output"]

    allowed_downstream, blocked_downstream = _derive_downstream_decision(output)

    if blocked_markers:
        reasons.append("Output was truncated or missing clear completion markers.")
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=allowed_downstream,
            blocked_downstream=blocked_downstream,
            recommendations=[
                "Do not use this SCF for follow-up; rerun with complete QE stdout."
            ],
        )

    if not output.job_done:
        reasons.append("SCF job has not reached JOB DONE.")
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=allowed_downstream,
            blocked_downstream=blocked_downstream,
            recommendations=[
                "Wait for QE completion or rerun SCF with stable runtime settings."
            ],
        )

    if not output.converged:
        reasons.append("SCF did not converge before termination.")
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=allowed_downstream,
            blocked_downstream=blocked_downstream,
            recommendations=[
                "Increase SCF robustness (mixing/broadening/cutoff) before dependent tasks."
            ],
        )

    if severe_issues:
        reasons.append(
            "Fatal event detected in SCF output: "
            + ", ".join(sorted({issue.category for issue in severe_issues}))
        )
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=allowed_downstream,
            blocked_downstream=blocked_downstream,
            recommendations=[
                "Fix severe QE/runtime issue and rerun SCF before downstream calculations."
            ],
        )

    stable_for_followup = output.stability_assessment.suitable_for_followup if (
        output.stability_assessment is not None
    ) else False

    if stable_for_followup:
        return ReviewResult(
            status="PASS",
            reasons=[],
            evidence=evidence,
            allowed_downstream=allowed_downstream,
            blocked_downstream=blocked_downstream,
            recommendations=[],
        )

    reasons.append("Converged but stability/readiness indicates non-ideal quality.")
    if output.workflow_readiness is not None:
        reasons.append(f"Downstream readiness reason: {output.workflow_readiness.reason}")
    return ReviewResult(
        status="WARN",
        reasons=sorted({reason for reason in reasons}),
        evidence=evidence,
        allowed_downstream=allowed_downstream,
        blocked_downstream=blocked_downstream,
        recommendations=[
            "Review diagnostic signals and rerun SCF with tighter convergence settings for production use."
        ],
    )


def _derive_downstream_decision(output: ScfOutput) -> tuple[list[str], list[str]]:
    """Derive allowed and blocked downstream workflow IDs from parsed output readiness."""

    readiness = _readiness_mapping(output)
    allowed = [name for name in SCF_DOWNSTREAMS if readiness.get(name, False)]
    blocked = [name for name in SCF_DOWNSTREAMS if name not in readiness or not readiness.get(name, False)]

    # Relax, VC-relax, nscf, pdos, and pp are downstream but not in WorkflowReadiness model;
    # gate on converged+job_done.
    if output.job_done and output.converged and (output.convergence_iterations is not None or output.iterations):
        for name in ("relax", "vc_relax", "nscf", "pp", "pdos"):
            if name not in allowed:
                allowed.append(name)
            if name in blocked:
                blocked.remove(name)

    ordered_blocked = [name for name in SCF_DOWNSTREAMS if name in blocked]
    ordered_allowed = [name for name in SCF_DOWNSTREAMS if name in allowed]
    return ordered_allowed, ordered_blocked


def _readiness_mapping(output: ScfOutput) -> dict[str, bool]:
    base = {name: False for name in SCF_DOWNSTREAMS}
    if output.workflow_readiness is None:
        return base

    base["dos"] = bool(output.workflow_readiness.dos)
    base["bands"] = bool(output.workflow_readiness.bands)
    base["phonon"] = bool(output.workflow_readiness.phonon)
    base["dielectric"] = bool(output.workflow_readiness.dielectric)
    return base


def _build_evidence(output: ScfOutput) -> list[Evidence]:
    evidence: list[Evidence] = [
        Evidence(
            source=output.source,
            field="job_done",
            value=output.job_done,
            interpretation=(
                "SCF workflow reached JOB DONE."
                if output.job_done else
                "No JOB DONE marker found."
            ),
            line_number=_first_issue_line(output, "job_done"),
        ),
        Evidence(
            source=output.source,
            field="converged",
            value=output.converged,
            interpretation=(
                "SCF reached convergence."
                if output.converged else
                "SCF did not report convergence."
            ),
            line_number=_first_issue_line(output, "convergence"),
        ),
        Evidence(
            source=output.source,
            field="final_total_energy_ry",
            value=output.final_total_energy_ry,
            interpretation="Final total energy from parsed SCF trajectory.",
            line_number=None,
        ),
        Evidence(
            source=output.source,
            field="final_scf_accuracy_ry",
            value=output.final_scf_accuracy_ry,
            interpretation="Final estimated SCF accuracy in Ry.",
            line_number=_last_accuracy_line(output),
        ),
        Evidence(
            source=output.source,
            field="convergence_iterations",
            value=output.convergence_iterations,
            interpretation="Convergence iteration count if reported.",
            line_number=None,
        ),
        Evidence(
            source=output.source,
            field="fermi_energy_ev",
            value=output.fermi_energy_ev,
            interpretation="Parsed Fermi energy from QE stdout.",
            line_number=_first_line_with_marker(output, "the Fermi energy is"),
        ),
        Evidence(
            source=output.source,
            field="ecutwfc_ry",
            value=output.ecutwfc_ry,
            interpretation="Kinetic-energy cutoff parsed from SCF input/output.",
            line_number=None,
        ),
        Evidence(
            source=output.source,
            field="ecutrho_ry",
            value=output.ecutrho_ry,
            interpretation="Charge-density cutoff parsed from SCF input/output.",
            line_number=None,
        ),
        Evidence(
            source=output.source,
            field="k_point_count",
            value=output.k_point_count,
            interpretation="Configured k-point mesh count.",
            line_number=None,
        ),
        Evidence(
            source=output.source,
            field="issues_categories",
            value=sorted({issue.category for issue in output.issues}),
            interpretation="Collected QE issue categories extracted from stdout.",
            line_number=None,
        ),
    ]

    return evidence


def _first_issue_line(output: ScfOutput, category: str) -> int | None:
    for issue in output.issues:
        if issue.category == category:
            return issue.line_number
    return None


def _last_accuracy_line(output: ScfOutput) -> int | None:
    for issue in reversed(output.issues):
        if issue.category == "scf_accuracy":
            return issue.line_number
    return None


def _first_line_with_marker(output: ScfOutput, marker: str) -> int | None:
    for issue in output.issues:
        if marker in issue.message:
            return issue.line_number
    return None


__all__ = ["review_scf_output"]
