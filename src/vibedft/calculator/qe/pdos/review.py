"""Review policy for Quantum ESPRESSO projwfc.x (PDOS) outputs."""

from __future__ import annotations

from vibedft._shared.contracts import Evidence, ReviewResult

from vibedft.calculator.qe.pdos.parse import PdosOutput
from vibedft.calculator.qe.pdos.schemas import PDOS_BASE_DOWNSTREAMS, PDOS_DOWNSTREAMS


_SEVERE_ISSUE_CATEGORIES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}


def review_pdos_output(output: PdosOutput) -> ReviewResult:
    """Evaluate a parsed PDOS output into a PASS/WARN/BLOCK result."""

    evidence = _build_evidence(output)
    reasons: list[str] = []
    severe = [issue for issue in output.issues if issue.category in _SEVERE_ISSUE_CATEGORIES]

    if severe:
        reasons.append(
            "PDOS output contains severe issue(s): "
            + ", ".join(sorted({issue.category for issue in severe}))
        )
        return ReviewResult(
            status="BLOCK",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(PDOS_DOWNSTREAMS),
            recommendations=["Fix severe PDOS issues and rerun projwfc.x before dependent steps."],
        )

    if any(issue.category == "truncated_output" for issue in output.issues):
        reasons.append("PDOS output was truncated before JOB DONE.")
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(PDOS_DOWNSTREAMS),
            recommendations=["Rerun projwfc.x to obtain a complete output."],
        )

    if not output.job_done:
        reasons.append("PDOS calculation has not reached JOB DONE.")
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(PDOS_DOWNSTREAMS),
            recommendations=["Wait for PDOS completion or rerun projwfc.x."],
        )

    if output.projection_file_count <= 0:
        reasons.append("No readable PDOS projection files were found.")

    if output.fermi_energy_ev is None:
        reasons.append("Fermi energy could not be extracted.")

    if output.energy_grid_count is None or output.energy_grid_count <= 0:
        reasons.append("Energy grid metadata is incomplete.")

    if output.energy_min_ev is None or output.energy_max_ev is None:
        reasons.append("PDOS energy bounds are incomplete.")

    if not output.orbital_channels:
        reasons.append("Orbital channel metadata is incomplete.")

    if not output.pdos_total_present:
        reasons.append("PDOS total projection payload appears empty.")

    if output.spin_channels is None:
        reasons.append("Spin channel metadata is unavailable.")

    if any(issue.category not in _SEVERE_ISSUE_CATEGORIES and issue.category != "truncated_output" for issue in output.issues):
        reasons.append("Non-fatal parser warnings detected.")

    if reasons:
        return ReviewResult(
            status="WARN",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=evidence,
            allowed_downstream=list(PDOS_BASE_DOWNSTREAMS),
            blocked_downstream=[name for name in PDOS_DOWNSTREAMS if name not in PDOS_BASE_DOWNSTREAMS],
            recommendations=[
                "Review PDOS metadata completeness before interpretation or cross-stage use.",
            ],
        )

    return ReviewResult(
        status="PASS",
        reasons=[],
        evidence=evidence,
        allowed_downstream=list(PDOS_BASE_DOWNSTREAMS),
        blocked_downstream=[name for name in PDOS_DOWNSTREAMS if name not in PDOS_BASE_DOWNSTREAMS],
        recommendations=[],
    )


def _build_evidence(output: PdosOutput) -> list[Evidence]:
    return [
        Evidence(
            source=output.source,
            field="job_done",
            value=output.job_done,
            interpretation="PDOS completed." if output.job_done else "PDOS incomplete.",
            line_number=_first_issue_line(output, "job"),
        ),
        Evidence(
            source=output.source,
            field="projection_file_count",
            value=output.projection_file_count,
            interpretation="Number of readable PDOS projection files.",
            line_number=_first_issue_line(output, "pdos"),
        ),
        Evidence(
            source=output.source,
            field="orbital_channels",
            value=list(output.orbital_channels),
            interpretation="Projected orbital channels discovered from filenames/content.",
            line_number=_first_issue_line(output, "wfc"),
        ),
        Evidence(
            source=output.source,
            field="energy_grid_count",
            value=output.energy_grid_count,
            interpretation="Per-file PDOS grid count merged to aggregate range.",
            line_number=_first_issue_line(output, "fermi"),
        ),
        Evidence(
            source=output.source,
            field="spin_channels",
            value=output.spin_channels,
            interpretation="Spin-polarization metadata from projwfc.x output.",
            line_number=_first_issue_line(output, "spin"),
        ),
        Evidence(
            source=output.source,
            field="fermi_energy_ev",
            value=output.fermi_energy_ev,
            interpretation="Fermi energy parsed from projection output.",
            line_number=_first_issue_line(output, "fermi"),
        ),
        Evidence(
            source=output.source,
            field="issues",
            value=sorted({event.category for event in output.issues}),
            interpretation="Parser issue categories collected from output and files.",
            line_number=None,
        ),
    ]


def _first_issue_line(output: PdosOutput, marker: str) -> int | None:
    for issue in output.issues:
        if marker.lower() in issue.message.lower() or marker.lower() in issue.category.lower():
            return issue.line_number
    return None


__all__ = ["review_pdos_output"]
