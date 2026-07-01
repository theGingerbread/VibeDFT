"""Clean Quantum ESPRESSO relax outputs into calculator-neutral contract."""

from __future__ import annotations

from pathlib import Path

from vibedft._shared.contracts import CleanedResult, Diagnostics, Evidence, Provenance, Readiness
from vibedft._shared.contracts import ReviewResult, DownstreamReadiness
from vibedft.calculator.qe.relax.parse import RelaxOutput, parse_relax_output
from vibedft.calculator.qe.relax.review import review_relax_output
from vibedft.calculator.qe.relax.schemas import RELAX_DOWNSTREAMS, RELAX_TASK_LEGACY


def clean_relax_output(output: RelaxOutput) -> CleanedResult:
    """Convert a parsed relax output into a normalized `CleanedResult`."""

    review_result = review_relax_output(output)

    issue_errors = [event.message for event in output.issues if event.category in _SEVERE_ISSUES]
    issue_warnings = [
        event.message
        for event in output.issues
        if event.category not in _SEVERE_ISSUES and event.category != "truncated_output"
    ]

    diagnostics = Diagnostics(
        errors=issue_errors,
        warnings=issue_warnings,
        notes=_diagnostic_notes(output),
        evidence=[_to_evidence(event) for event in output.issues[:8]],
        metrics=_select_metrics(output),
        parser={
            "source_summary": output.source_summary,
            "source": output.source,
            "system": dict(output.system),
            "trajectory_steps": len(output.relaxation_trajectory),
        },
        qe_messages={
            "source": output.source,
            "issues_count": len(output.issues),
        },
        numerical_risk=_numerical_risk_metrics(output),
        workflow_risk=_workflow_risk_metrics(output),
    )

    downstream = _build_downstream_readiness(review_result)
    outputs = _build_output_payload(output)
    observables = _build_observables(output)

    return CleanedResult(
        calculator="qe",
        task=RELAX_TASK_LEGACY,
        status=_cleaned_status_from_review(review_result),
        review=review_result,
        source_files=[output.source] if output.source else [],
        provenance=Provenance(
            calculator="qe",
            task=RELAX_TASK_LEGACY,
            version=output.system.get("version"),
            command="pw.x",
            started_at=None,
            completed_at=None,
            extra={"source": output.source, "trajectory_steps": len(output.relaxation_trajectory)},
        ),
        inputs={
            "input_parameters": output.input_parameters,
            "numerical_setup": output.numerical_setup,
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


def clean_relax_text(text_or_path: str | Path, *, source: str | Path | None = None) -> CleanedResult:
    """Parse raw text/path and return cleaned relax output contract in one call."""

    output = parse_relax_output(text_or_path, source=source)
    return clean_relax_output(output)


def _cleaned_status_from_review(review_result: ReviewResult) -> str:
    return {"PASS": "pass", "WARN": "warn", "BLOCK": "block"}[review_result.status]


def _build_output_payload(output: RelaxOutput) -> dict[str, object]:
    return {
        "program": output.system.get("program"),
        "version": output.system.get("version"),
        "job_done": output.job_done,
        "global_convergence": dict(output.global_convergence),
        "final_structure": output.final_structure,
    }


def _build_observables(output: RelaxOutput) -> dict[str, object]:
    latest_step = output.relaxation_trajectory[-1] if output.relaxation_trajectory else None
    observables = {
        "total_energy": output.final_observables.get("total_energy"),
        "enthalpy": output.final_observables.get("enthalpy"),
        "pressure": output.final_observables.get("pressure"),
        "volume": output.final_observables.get("volume"),
    }
    if latest_step is not None:
        observables["max_force"] = latest_step.forces.max_force
        observables["rms_force"] = latest_step.forces.rms_force
    else:
        observables["max_force"] = None
        observables["rms_force"] = None

    observables["trajectory_length"] = len(output.relaxation_trajectory)
    observables["steps_with_convergence"] = sum(
        1 for step in output.relaxation_trajectory if step.step_convergence.get("scf_converged")
    )
    return observables


def _build_downstream_readiness(review_result: ReviewResult) -> dict[str, DownstreamReadiness]:
    downstream: dict[str, DownstreamReadiness] = {}
    allowed = set(review_result.allowed_downstream)
    evidence_refs = sorted(
        event.evidence_id for event in review_result.evidence if event.evidence_id is not None
    )

    for task in RELAX_DOWNSTREAMS:
        if task in allowed:
            downstream[task] = DownstreamReadiness(
                task=task,
                allowed=True,
                reason="Relaxation accepted for this downstream path.",
                evidence_refs=evidence_refs,
            )
        else:
            downstream[task] = DownstreamReadiness(
                task=task,
                allowed=False,
                reason=_downstream_reason(task, review_result),
                evidence_refs=evidence_refs,
            )
    return downstream


def _readiness_summary(output: RelaxOutput, review_result: ReviewResult) -> str:
    if output.job_done is False:
        return "Relaxation output not complete."
    if review_result.status == "PASS":
        return "Relaxation converged and geometry is accepted for safe follow-up tasks."
    if review_result.status == "WARN":
        return "Relaxation converged with caveats; some downstream workflows are blocked."
    return "Relaxation blocked; follow-up requires re-run or policy override."


def _diagnostic_notes(output: RelaxOutput) -> list[str]:
    notes: list[str] = []
    final_structure = output.final_structure
    if final_structure:
        if final_structure.get("atomic_positions"):
            notes.append("final_structure: atomic positions recovered")
        if final_structure.get("cell_parameters"):
            notes.append("final_structure: cell parameters recovered")
    notes.append(
        f"trajectory_steps={len(output.relaxation_trajectory)}; "
        f"issues={len(output.issues)}; "
        f"source={output.source or 'text'}"
    )
    return notes


def _select_metrics(output: RelaxOutput) -> dict[str, object]:
    return {
        "issues_count": len(output.issues),
        "warnings_count": len([issue for issue in output.issues if issue.category == "warning"]),
        "trajectory_steps": len(output.relaxation_trajectory),
        "final_energy": output.final_observables.get("total_energy"),
        "final_pressure": output.final_observables.get("pressure"),
        "final_volume": output.final_observables.get("volume"),
    }


def _numerical_risk_metrics(output: RelaxOutput) -> dict[str, object]:
    stability = output.diagnostics.get("stability_report") if isinstance(output.diagnostics, dict) else None
    if isinstance(stability, dict):
        return {
            "overall_risk_level": stability.get("overall_risk_level"),
            "electronic_modes": stability.get("electronic_stability", {}).get("modes", []),
            "ionic_modes": stability.get("ionic_stability", {}).get("modes", []),
            "structural_modes": stability.get("structural_stability", {}).get("modes", []),
            "symmetry_modes": stability.get("symmetry_stability", {}).get("modes", []),
        }
    return {"overall_risk_level": "unknown"}


def _workflow_risk_metrics(output: RelaxOutput) -> dict[str, object]:
    return {
        "global_convergence": dict(output.global_convergence),
        "variable_cell": output.variable_cell,
        "source_summary": output.source_summary,
    }


def _to_evidence(event: object) -> Evidence:
    source = getattr(event, "source", "")
    return Evidence(
        source=source,
        field="issue",
        value=getattr(event, "message", None),
        interpretation=str(getattr(event, "category", "")),
        line_number=getattr(event, "line_number", None),
        artifact=getattr(event, "artifact", None),
        section=getattr(event, "section", None),
        evidence_id=getattr(event, "evidence_id", None),
    )


def _downstream_reason(task: str, review_result: ReviewResult) -> str:
    if task in {"phonon", "dielectric", "epc", "tc", "vc_relax"}:
        return "Relaxation policy keeps this branch blocked unless explicitly extended."
    return "Not included in current relax readiness policy."


_SEVERE_ISSUES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}


__all__ = ["clean_relax_output", "clean_relax_text"]
