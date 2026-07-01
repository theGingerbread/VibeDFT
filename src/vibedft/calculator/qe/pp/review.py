"""Review policy for Quantum ESPRESSO pp.x outputs."""

from __future__ import annotations

from vibedft._shared.contracts import Evidence, ReviewResult
from vibedft.calculator.qe.pp.parse import PpOutput
from vibedft.calculator.qe.pp.schemas import PP_BASE_DOWNSTREAMS, PP_DOWNSTREAMS


_FATAL_ISSUE_CATEGORIES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}

_FIELD_DOWNSTREAM = {
    "charge_density": "analysis.charge_density",
    "potential": "analysis.potential",
    "spin_density": "analysis.spin_density",
}

_MANDATORY_BLOCKED_DOWNSTREAMS = {
    "bader",
    "workfunction",
    "scf",
    "relax",
    "vc_relax",
    "nscf",
    "bands",
    "dos",
    "pdos",
    "phonon",
    "dielectric",
    "epc",
    "tc",
}


def review_pp_output(output: PpOutput) -> ReviewResult:
    """Evaluate a parsed pp.x output into a PASS/WARN/BLOCK result."""

    evidence = _build_evidence(output)
    severe = [issue for issue in output.issues if issue.category in _FATAL_ISSUE_CATEGORIES]

    if not _looks_like_pp_workflow(output):
        return ReviewResult(
            status="BLOCK",
            reasons=["Output is not recognizable as a pp.x workflow."],
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(PP_DOWNSTREAMS),
            recommendations=["Review the stdout source and pass pp.x output to the PP parser."],
        )

    if severe:
        reasons = [
            "pp.x output contains fatal issue(s): "
            + ", ".join(sorted({issue.category for issue in severe}))
        ]
        return ReviewResult(
            status="BLOCK",
            reasons=reasons,
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(PP_DOWNSTREAMS),
            recommendations=["Fix fatal pp.x/runtime issues and rerun pp.x before analysis."],
        )

    if any(issue.category == "truncated_output" for issue in output.issues):
        return ReviewResult(
            status="BLOCK",
            reasons=["pp.x output was truncated before JOB DONE."],
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(PP_DOWNSTREAMS),
            recommendations=["Rerun pp.x to obtain complete stdout and artifacts."],
        )

    if not output.job_done:
        return ReviewResult(
            status="BLOCK",
            reasons=["pp.x calculation has not reached JOB DONE."],
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(PP_DOWNSTREAMS),
            recommendations=["Wait for pp.x completion or rerun the post-processing task."],
        )

    if not output.output_files and not output.stdout_output_hints:
        return ReviewResult(
            status="BLOCK",
            reasons=["pp.x output artifact is completely untracked and no data_files were supplied."],
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(PP_DOWNSTREAMS),
            recommendations=["Provide pp.x output artifacts through data_files or preserve fileout stdout hints."],
        )

    reasons: list[str] = []
    artifact_nonempty = bool(output.nonempty_output_files)

    if not artifact_nonempty:
        reasons.append("No pp.x artifact could be confirmed as existing and nonempty.")

    if output.field_kind == "unknown_field":
        reasons.append("pp.x field kind could not be inferred.")

    if output.field_kind == "generic_field" and output.plot_num not in {0, 1}:
        reasons.append("Generic pp.x field is not explained by plot_num metadata.")

    if output.plot_num is None:
        reasons.append("pp.x plot_num metadata is missing.")

    if output.output_format is None:
        reasons.append("pp.x output format metadata is missing.")

    if any(issue.category in {"warning", "artifact_missing", "artifact_untracked", "empty_artifact"} for issue in output.issues):
        reasons.append("Non-fatal pp.x parser warnings detected.")

    allowed_downstream = _allowed_downstream(output, artifact_nonempty)
    blocked_downstream = [name for name in PP_DOWNSTREAMS if name not in set(allowed_downstream)]

    if reasons:
        return ReviewResult(
            status="WARN",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=evidence,
            allowed_downstream=allowed_downstream,
            blocked_downstream=blocked_downstream,
            recommendations=[
                "Review pp.x artifact availability, field kind, and metadata before field-specific analysis.",
            ],
        )

    return ReviewResult(
        status="PASS",
        reasons=[],
        evidence=evidence,
        allowed_downstream=allowed_downstream,
        blocked_downstream=blocked_downstream,
        recommendations=[],
    )


def _looks_like_pp_workflow(output: PpOutput) -> bool:
    if output.program is not None:
        return output.program.upper().rstrip(".") in {"PP", "PP.X"}
    return output.plot_num is not None or bool(output.stdout_output_hints)


def _allowed_downstream(output: PpOutput, artifact_nonempty: bool) -> list[str]:
    allowed = list(PP_BASE_DOWNSTREAMS)
    if artifact_nonempty:
        field_downstream = _FIELD_DOWNSTREAM.get(output.field_kind)
        if field_downstream is not None and field_downstream not in allowed:
            allowed.append(field_downstream)

    return [name for name in allowed if name not in _MANDATORY_BLOCKED_DOWNSTREAMS]


def _build_evidence(output: PpOutput) -> list[Evidence]:
    return [
        Evidence(
            source=output.source,
            field="job_done",
            value=output.job_done,
            interpretation="pp.x reached JOB DONE." if output.job_done else "pp.x did not reach JOB DONE.",
            line_number=_first_issue_line(output, "job"),
            evidence_id="pp.job_done",
        ),
        Evidence(
            source=output.source,
            field="plot_num",
            value=output.plot_num,
            interpretation="pp.x plot_num selected field metadata.",
            line_number=_first_issue_line(output, "plot"),
            evidence_id="pp.plot_num",
        ),
        Evidence(
            source=output.source,
            field="field_kind",
            value=output.field_kind,
            interpretation="Conservative field-kind inference from stdout and plot_num.",
            line_number=None,
            evidence_id="pp.field_kind",
        ),
        Evidence(
            source=output.source,
            field="nonempty_output_files",
            value=list(output.nonempty_output_files),
            interpretation="pp.x artifacts confirmed as existing and nonempty.",
            artifact=output.nonempty_output_files[0] if output.nonempty_output_files else None,
            evidence_id="pp.artifacts",
        ),
        Evidence(
            source=output.source,
            field="data_sample_count",
            value=output.data_sample_count,
            interpretation="Lightweight numeric row count from simple text artifacts.",
            evidence_id="pp.data_sample_count",
        ),
        Evidence(
            source=output.source,
            field="issues",
            value=[event.category for event in output.issues],
            interpretation="Parser issue categories collected from pp.x stdout and artifacts.",
            evidence_id="pp.issues",
        ),
    ]


def _first_issue_line(output: PpOutput, marker: str) -> int | None:
    for issue in output.issues:
        if marker.lower() in issue.message.lower() or marker.lower() in issue.category.lower():
            return issue.line_number
    return None


__all__ = ["review_pp_output"]
