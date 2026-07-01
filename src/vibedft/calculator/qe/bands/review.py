"""Review policy for Quantum ESPRESSO bands outputs."""

from __future__ import annotations

from vibedft._shared.contracts import Evidence, ReviewResult

from vibedft.calculator.qe.bands.parse import BandsOutput
from vibedft.calculator.qe.bands.schemas import BANDS_BASE_DOWNSTREAMS, BANDS_DOWNSTREAMS

_SEVERE_ISSUE_CATEGORIES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}


def review_bands_output(output: BandsOutput) -> ReviewResult:
    """Evaluate a parsed bands output into PASS/WARN/BLOCK."""

    evidence = _build_evidence(output)
    reasons: list[str] = []

    severe = [issue for issue in output.issues if issue.category in _SEVERE_ISSUE_CATEGORIES]
    truncated = any(issue.category == "truncated_output" for issue in output.issues)
    if severe:
        reasons.append(
            "Bands output contains severe issue(s): " + ", ".join(sorted({issue.category for issue in severe}))
        )
    if truncated:
        reasons.append("Bands output was truncated before JOB DONE.")

    if severe or truncated:
        return ReviewResult(
            status="BLOCK",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(BANDS_DOWNSTREAMS),
            recommendations=["Rerun bands calculation and confirm output integrity before electronic follow-up."],
        )

    if not output.job_done:
        reasons.append("Bands calculation has not reached JOB DONE.")
        return ReviewResult(
            status="BLOCK",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(BANDS_DOWNSTREAMS),
            recommendations=["Wait for completion or rerun bands run."],
        )

    if not output.band_data_present:
        reasons.append("No band eigenvalue data available.")
    if output.band_count is None and output.eigenvalue_row_count is None:
        reasons.append("Bands payload is missing: no band_count and no eigenvalue rows.")
    if output.band_count is not None and output.band_count <= 0:
        reasons.append("Bands payload reports non-positive band count.")
    if (output.k_point_count is None or output.k_point_count <= 0) and not output.k_point_path:
        reasons.append("Band structure k-point path metadata is unavailable.")
    if output.reference_energy_ev is None and output.fermi_energy_ev is None:
        reasons.append("Energy reference is not available (Fermi/reference not found).")
    if not output.high_symmetry_labels and not output.k_point_path:
        reasons.append("k-point path metadata is incomplete; high-symmetry labels are missing.")

    if any(event.category == "warning" for event in output.issues):
        reasons.append("Non-fatal warnings were observed in bands parsing.")

    if reasons:
        return ReviewResult(
            status="WARN",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=evidence,
            allowed_downstream=list(BANDS_BASE_DOWNSTREAMS),
            blocked_downstream=[name for name in BANDS_DOWNSTREAMS if name not in BANDS_BASE_DOWNSTREAMS],
            recommendations=[
                "Proceed with caution; verify band path and metadata before scientific interpretation.",
            ],
        )

    return ReviewResult(
        status="PASS",
        reasons=[],
        evidence=evidence,
        allowed_downstream=list(BANDS_BASE_DOWNSTREAMS),
        blocked_downstream=[name for name in BANDS_DOWNSTREAMS if name not in BANDS_BASE_DOWNSTREAMS],
        recommendations=[],
    )


def _build_evidence(output: BandsOutput) -> list[Evidence]:
    return [
        Evidence(
            source=output.source,
            field="job_done",
            value=output.job_done,
            interpretation="Bands run finished with JOB DONE." if output.job_done else "Bands run incomplete.",
            line_number=_first_issue_line(output, "job_done"),
        ),
        Evidence(
            source=output.source,
            field="band_count",
            value=output.band_count,
            interpretation="Parsed number of bands from stdout or data file.",
            line_number=_first_issue_line(output, "nbnd"),
        ),
        Evidence(
            source=output.source,
            field="k_point_count",
            value=output.k_point_count,
            interpretation="Parsed number of k-points from stdout or data file.",
            line_number=_first_issue_line(output, "nks"),
        ),
        Evidence(
            source=output.source,
            field="band_data_present",
            value=output.band_data_present,
            interpretation="Whether band eigenvalue table was parsed.",
            line_number=_first_issue_line(output, "band"),
        ),
        Evidence(
            source=output.source,
            field="fermi_energy_ev",
            value=output.fermi_energy_ev,
            interpretation="Parsed Fermi energy in eV.",
            line_number=_first_issue_line(output, "fermi"),
        ),
        Evidence(
            source=output.source,
            field="high_symmetry_labels",
            value=list(output.high_symmetry_labels),
            interpretation="Parsed high-symmetry labels from bands source text.",
            line_number=_first_issue_line(output, "sym"),
        ),
        Evidence(
            source=output.source,
            field="energy_range",
            value=(output.energy_min_ev, output.energy_max_ev),
            interpretation="Parsed min/max band energy values.",
            line_number=_first_issue_line(output, "energy"),
        ),
        Evidence(
            source=output.source,
            field="issues",
            value=[event.category for event in output.issues],
            interpretation="Parser issues collected from bands output and file parsing.",
            line_number=None,
        ),
    ]


def _first_issue_line(output: BandsOutput, marker: str) -> int | None:
    for issue in output.issues:
        if marker.lower() in issue.message.lower() or marker.lower() in issue.category.lower():
            return issue.line_number
    return None


__all__ = ["review_bands_output"]
