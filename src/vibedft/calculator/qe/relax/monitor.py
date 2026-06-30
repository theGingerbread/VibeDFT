"""Monitor Quantum ESPRESSO relax / vc-relax output streams."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibedft.calculator.qe.common import QEOutputEvent

from .parse import RelaxOutput, parse_relax_output


@dataclass(frozen=True)
class RelaxMonitorSnapshot:
    """State summary for a relax / vc-relax stdout stream."""

    status: str
    job_done: bool
    ionic_converged: bool
    scf_converged: bool
    oscillating: bool
    active_steps: int
    last_step: int | None
    last_total_energy_ry: float | None
    last_max_force: float | None
    issues: list[QEOutputEvent]
    summary: str
    suggested_actions: list[str]


_SEVERE_FAILURE_CATEGORIES = {
    "mpi_abort",
    "segmentation_fault",
    "out_of_memory",
    "time_limit",
    "traceback",
    "file_not_found",
    "error",
}


def monitor_relax_output(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
) -> RelaxMonitorSnapshot:
    """Classify a relax output stream into a strict, deterministic state."""

    output = parse_relax_output(text_or_path, source=source)
    issues = output.issues
    has_job_done = any(event.category == "job_done" for event in output.events)
    severe_issues = [
        issue for issue in issues if issue.category in _SEVERE_FAILURE_CATEGORIES
    ]

    last_step = output.relaxation_trajectory[-1] if output.relaxation_trajectory else None
    last_energy = output.final_observables.get("total_energy")
    last_force = output.relaxation_trajectory[-1].forces.max_force if output.relaxation_trajectory else None
    oscillating = _is_oscillating(output)

    if severe_issues:
        status = "failed"
        summary = _summary_for_failed(severe_issues)
        actions = [
            "Inspect the first severe issue with file path and line context before re-running",
            "Confirm input sanity and rerun with validated restart settings",
        ]

    elif (
        output.global_convergence.get("ionic_converged", False)
        and output.global_convergence.get("scf_converged_all_steps", False)
        and has_job_done
    ):
        status = "completed"
        summary = (
            f"Relaxation completed: {output.relaxation_trajectory[-1].step_index + 1} ionic step(s), "
            "all embedded SCF loops converged and JOB DONE seen"
        )
        actions = []

    elif oscillating:
        status = "oscillating"
        summary = "Relaxation trajectory shows non-monotonic energy/force behavior and may need restart review"
        actions = [
            "Check ionic geometry/force continuity across steps",
            "Verify convergence thresholds are not too strict for this system",
        ]

    elif (
        not output.global_convergence.get("scf_converged_all_steps", True)
        and output.relaxation_trajectory
        and _is_ionic_progressing(output)
    ):
        status = "blocked"
        summary = "SCF is not converged yet while ionic progression is still updating"
        actions = [
            "Review last few SCF traces for divergence signals",
            "Tune mixing / diagonalization and restart from the latest trajectory point",
        ]

    elif _is_ionic_stuck(output):
        status = "blocked"
        summary = "Ionic updates appear stalled while forces do not decrease sufficiently"
        actions = [
            "Check BFGS history-reset or trust-radius constraints",
            "Consider restarting with more conservative relax settings",
        ]

    elif output.relaxation_trajectory:
        status = "running"
        summary = (
            f"Relaxation is active ({len(output.relaxation_trajectory)} ionic steps, "
            f"{len(last_step.scf_trajectory) if last_step else 0} SCF iterations in last step)"
        )
        actions = [
            "Wait for additional ionic and SCF convergence markers",
            "Monitor for convergence not achieved / warning markers",
        ]

    else:
        status = "no_data"
        summary = "No relax ionic or SCF markers detected yet"
        actions = [
            "Point monitor to the pw.x relax stdout (not a wrapper log)",
            "Check whether the output file is being populated",
        ]

    return RelaxMonitorSnapshot(
        status=status,
        job_done=has_job_done,
        ionic_converged=bool(output.global_convergence.get("ionic_converged")),
        scf_converged=bool(
            output.global_convergence.get("scf_converged_all_steps")
            and not severe_issues
        ),
        oscillating=bool(oscillating),
        active_steps=len(output.relaxation_trajectory),
        last_step=last_step.step_index if last_step is not None else None,
        last_total_energy_ry=last_energy,
        last_max_force=last_force,
        issues=issues,
        summary=summary,
        suggested_actions=actions,
    )


def _is_oscillating(output: RelaxOutput) -> bool:
    steps = [
        _last_step_energy(step)
        for step in output.relaxation_trajectory
        if _last_step_energy(step) is not None
    ]
    if len(steps) < 3:
        return False
    deltas = [cur - prev for prev, cur in zip(steps, steps[1:])]
    return any(prev * curr < 0 for prev, curr in zip(deltas, deltas[1:]))


def _is_ionic_progressing(output: RelaxOutput) -> bool:
    if len(output.relaxation_trajectory) <= 1:
        return False
    force_values = [
        step.forces.max_force
        for step in output.relaxation_trajectory
        if step.forces.max_force is not None
    ]
    return len(force_values) >= 2 and any(
        earlier > later for earlier, later in zip(force_values, force_values[1:])
    )


def _is_ionic_stuck(output: RelaxOutput, *, window: int = 3) -> bool:
    if len(output.relaxation_trajectory) < max(window + 1, 3):
        return False

    force_values = [
        step.forces.max_force
        for step in output.relaxation_trajectory
        if step.forces.max_force is not None
    ]
    if len(force_values) < window + 1:
        return False

    tail = force_values[-window:]
    scale = max(abs(tail[0]), 1e-12)
    return all(abs(value - tail[0]) <= 0.1 * scale for value in tail[1:]) and not any(
        tail[i] > tail[i - 1] for i in range(1, len(tail))
    )


def _last_step_energy(step: Any) -> float | None:
    return step.scf_trajectory[-1].total_energy if step.scf_trajectory else None


def _summary_for_failed(severe_issues: list[QEOutputEvent]) -> str:
    categories = sorted({issue.category for issue in severe_issues})
    return f"relax failed with severity markers: {', '.join(categories)}"


__all__ = [
    "RelaxMonitorSnapshot",
    "monitor_relax_output",
]
