"""Review policy for Quantum ESPRESSO dos.x outputs."""

from __future__ import annotations

from vibedft._shared.contracts import Evidence, ReviewResult

from vibedft.calculator.qe.dos.parse import DosOutput
from vibedft.calculator.qe.dos.schemas import DOS_BASE_DOWNSTREAMS, DOS_DOWNSTREAMS

_SEVERE_ISSUE_CATEGORIES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}


def review_dos_output(output: DosOutput) -> ReviewResult:
    """Evaluate a parsed DOS output into a PASS/WARN/BLOCK result."""

    evidence = _build_evidence(output)
    reasons: list[str] = []
    severe = [issue for issue in output.issues if issue.category in _SEVERE_ISSUE_CATEGORIES]

    if severe:
        reasons.append(
            "DOS output contains severe issue(s): " + ", ".join(sorted({issue.category for issue in severe}))
        )
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(DOS_DOWNSTREAMS),
            recommendations=["Rerun DOS with complete runtime and parser inputs before follow-up."],
        )

    if any(issue.category == "truncated_output" for issue in output.issues):
        reasons.append("DOS output was truncated before JOB DONE.")
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(DOS_DOWNSTREAMS),
            recommendations=["Rerun DOS calculation for full stdout."],
        )

    if not output.job_done:
        reasons.append("DOS calculation has not reached JOB DONE.")
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(DOS_DOWNSTREAMS),
            recommendations=["Wait for DOS completion or rerun dos.x."],
        )

    has_data_grid = output.energy_grid_count is not None and output.energy_grid_count > 0
    has_range = output.energy_min_ev is not None and output.energy_max_ev is not None
    has_dos_envelope = output.dos_min is not None and output.dos_max is not None
    has_fermi = output.fermi_energy_ev is not None

    if not has_data_grid:
        reasons.append("DOS grid metadata is missing or empty.")

    if not has_range:
        reasons.append("DOS energy range metadata is incomplete.")

    if not has_dos_envelope:
        reasons.append("DOS min/max envelope values are missing.")

    if output.data_file is None:
        reasons.append("DOS data file was not provided or could not be read.")

    if not has_fermi:
        reasons.append("Fermi energy could not be extracted.")

    if any(issue.category == "warning" for issue in output.issues) and reasons:
        reasons.append("Non-fatal warnings present in DOS parsing.")

    if reasons:
        return ReviewResult(
            status="WARN",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=evidence,
            allowed_downstream=list(DOS_BASE_DOWNSTREAMS),
            blocked_downstream=[name for name in DOS_DOWNSTREAMS if name not in DOS_BASE_DOWNSTREAMS],
            recommendations=[
                "Verify DOS data completeness and source consistency before downstream workflows.",
            ],
        )

    return ReviewResult(
        status="PASS",
        reasons=[],
        evidence=evidence,
        allowed_downstream=list(DOS_BASE_DOWNSTREAMS),
        blocked_downstream=[name for name in DOS_DOWNSTREAMS if name not in DOS_BASE_DOWNSTREAMS],
        recommendations=[],
    )


def _build_evidence(output: DosOutput) -> list[Evidence]:
    return [
        Evidence(
            source=output.source,
            field="job_done",
            value=output.job_done,
            interpretation="DOS reached JOB DONE." if output.job_done else "DOS did not reach JOB DONE.",
            line_number=_first_issue_line(output, "job_done"),
        ),
        Evidence(
            source=output.source,
            field="energy_grid_count",
            value=output.energy_grid_count,
            interpretation="Parsed DOS sample count from output and/or data file.",
            line_number=_first_issue_line(output, "n"),
        ),
        Evidence(
            source=output.source,
            field="energy_min_ev",
            value=output.energy_min_ev,
            interpretation="Parsed DOS minimum energy.",
            line_number=_first_issue_line(output, "emin"),
        ),
        Evidence(
            source=output.source,
            field="energy_max_ev",
            value=output.energy_max_ev,
            interpretation="Parsed DOS maximum energy.",
            line_number=_first_issue_line(output, "emax"),
        ),
        Evidence(
            source=output.source,
            field="dos_range",
            value=(output.dos_min, output.dos_max),
            interpretation="Parsed DOS value range.",
            line_number=_first_issue_line(output, "dos"),
        ),
        Evidence(
            source=output.source,
            field="data_file",
            value=output.data_file,
            interpretation="DOS data file used by parser.",
            line_number=_first_issue_line(output, "dos"),
        ),
        Evidence(
            source=output.source,
            field="issues",
            value=[event.category for event in output.issues],
            interpretation="Parser event categories collected from DOS parsing.",
            line_number=None,
        ),
    ]


def _first_issue_line(output: DosOutput, marker: str) -> int | None:
    for issue in output.issues:
        if marker.lower() in issue.message.lower() or marker.lower() in issue.category.lower():
            return issue.line_number
    return None


__all__ = ["review_dos_output"]
