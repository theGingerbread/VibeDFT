"""Relax review policy and pass/warn/block judgment."""

from __future__ import annotations

from vibedft._shared.contracts import Evidence, ReviewResult

from vibedft.calculator.qe.relax.parse import RelaxOutput
from vibedft.calculator.qe.relax.schemas import (
    RELAX_BASE_DOWNSTREAMS,
    RELAX_DOWNSTREAMS,
)


_SEVERE_ISSUE_CATEGORIES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}


def review_relax_output(output: RelaxOutput) -> ReviewResult:
    """Evaluate a parsed relax output into a deterministic review result."""

    evidence = _build_evidence(output)
    reasons: list[str] = []
    severe_issues = [issue for issue in output.issues if issue.category in _SEVERE_ISSUE_CATEGORIES]

    if severe_issues:
        reasons.append(
            "Fatal event detected: "
            + ", ".join(sorted({issue.category for issue in severe_issues}))
        )
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(RELAX_DOWNSTREAMS),
            recommendations=[
                "Fix severe QE/runtime issue and rerun relax before downstream workflows."
            ],
        )

    if not output.job_done:
        reasons.append("Relaxation job has not reached JOB DONE.")
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(RELAX_DOWNSTREAMS),
            recommendations=["Run the relaxation to completion and regenerate output."],
        )

    if not _has_final_structure(output):
        reasons.append("No final structure was recovered from output.")
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(RELAX_DOWNSTREAMS),
            recommendations=["Re-run relaxation with trajectory output enabled."],
        )

    convergence = output.global_convergence
    if not bool(convergence.get("ionic_converged")):
        reasons.append("Ionic convergence did not complete.")
    if not bool(convergence.get("scf_converged_all_steps")):
        reasons.append("SCF did not converge in every ionic step.")

    if reasons:
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(RELAX_DOWNSTREAMS),
            recommendations=[
                "Relaxation trajectory is not fully converged; rerun with stricter thresholds."
            ],
        )

    geometry_ok, geometry_detail = _is_geometry_quality_ok(output)
    issue_level = _issue_level(output)
    warning_categories = sorted(
        {issue.category for issue in output.issues if issue.category not in _SEVERE_ISSUE_CATEGORIES}
    )

    if geometry_ok and issue_level not in {"medium", "high"}:
        return ReviewResult(
            status="PASS",
            reasons=[],
            evidence=evidence,
            allowed_downstream=list(RELAX_BASE_DOWNSTREAMS),
            blocked_downstream=[
                name for name in RELAX_DOWNSTREAMS if name not in RELAX_BASE_DOWNSTREAMS
            ],
            recommendations=[],
        )

    warn_reasons = list(reversed([geometry_detail])) if geometry_detail else []
    if warning_categories:
        warn_reasons.append(
            "Non-fatal warnings or events: " + ", ".join(warning_categories)
        )

    if issue_level == "medium":
        warn_reasons.append("Numerical risk is medium-level after relaxation trajectory analysis.")
    if issue_level == "high":
        warn_reasons.append("Numerical risk is elevated after relaxation trajectory analysis.")

    if not warn_reasons:
        warn_reasons.append("Convergence was reached but workflow risk is conservative.")

    reasons.extend(warn_reasons)

    return ReviewResult(
        status="WARN",
        reasons=sorted(dict.fromkeys(reasons)),
        evidence=evidence,
        allowed_downstream=list(RELAX_BASE_DOWNSTREAMS),
        blocked_downstream=[
            name for name in RELAX_DOWNSTREAMS if name not in RELAX_BASE_DOWNSTREAMS
        ],
        recommendations=[
            "Review force/stress trajectory and non-fatal warnings before phonon/dielectric/EPC/tc."
        ],
    )


def _build_evidence(output: RelaxOutput) -> list[Evidence]:
    return [
        Evidence(
            source=output.source,
            field="job_done",
            value=output.job_done,
            interpretation=(
                "Relaxation reached JOB DONE." if output.job_done else "Relaxation missing completion marker."
            ),
            line_number=_first_issue_line(output, "job_done"),
        ),
        Evidence(
            source=output.source,
            field="global_convergence",
            value=output.global_convergence,
            interpretation="Per-step ionic/SCF/geometry convergence summary.",
        ),
        Evidence(
            source=output.source,
            field="final_structure.atomic_positions",
            value=_final_structure_has_atoms(output),
            interpretation="Final atomic geometry extracted from parsed relaxation steps.",
        ),
        Evidence(
            source=output.source,
            field="final_observables",
            value=output.final_observables,
            interpretation="Final energy/pressure/volume observables from trajectory tail.",
        ),
        Evidence(
            source=output.source,
            field="issues_categories",
            value=sorted({issue.category for issue in output.issues}),
            interpretation="Raw parser issue categories for science review gating.",
        ),
    ]


def _is_geometry_quality_ok(output: RelaxOutput) -> tuple[bool, str]:
    geometry_converged = bool(output.global_convergence.get("geometry_converged", False))
    if geometry_converged:
        return True, "Geometry convergence satisfied."

    if output.relaxation_trajectory:
        last_forces = output.relaxation_trajectory[-1].forces
        if last_forces.force_threshold is None:
            return False, "Force threshold not available; geometry convergence cannot be confirmed."
        if last_forces.max_force is None:
            return False, "Final max-force value unavailable; geometry convergence cannot be confirmed."

    return False, "Geometry convergence condition not met."


def _has_final_structure(output: RelaxOutput) -> bool:
    final_structure = output.final_structure or {}
    atomic_positions = final_structure.get("atomic_positions", [])
    return bool(atomic_positions)


def _first_issue_line(output: RelaxOutput, category: str) -> int | None:
    for issue in output.issues:
        if issue.category == category:
            return issue.line_number
    return None


def _issue_level(output: RelaxOutput) -> str:
    stability = output.diagnostics.get("stability_report", {}) if output.diagnostics else {}
    overall_risk = str(stability.get("overall_risk_level", "")).lower()
    if overall_risk in {"high"}:
        return "high"
    if overall_risk in {"medium"}:
        return "medium"
    if not stability:
        return "clean"
    return "clean"


def _final_structure_has_atoms(output: RelaxOutput) -> bool:
    return _has_final_structure(output)


__all__ = ["review_relax_output"]
