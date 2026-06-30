"""Compare and rank multiple relax / vc-relax outputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibedft.calculator.qe.relax.monitor import monitor_relax_output
from vibedft.calculator.qe.relax.parse import (
    RelaxOutput,
    parse_relax_output,
)


RY_TO_EV = 13.605703976


def _as_float(x: float | None) -> float:
    return float("inf") if x is None else x


def _display_source(path_or_text: str | Path, index: int) -> str:
    if isinstance(path_or_text, Path):
        return path_or_text.name

    candidate = Path(path_or_text)
    if candidate.exists():
        return candidate.name

    return f"text:{index}"


_SEVERE_FAILURE_CATEGORIES = {
    "mpi_abort",
    "segmentation_fault",
    "out_of_memory",
    "time_limit",
    "traceback",
    "file_not_found",
    "error",
}


@dataclass(frozen=True)
class RelaxRunComparisonEntry:
    """Per-run summary used by multi-file comparison."""

    source: str
    status: str
    rank: int
    total_steps: int
    last_step: int | None
    final_energy_ry: float | None
    final_energy_ev: float | None
    delta_to_best_energy_ry: float | None
    delta_to_best_energy_ev: float | None
    final_pressure_kbar: float | None
    final_volume: float | None
    final_enthalpy_ry: float | None
    scf_converged_all_steps: bool
    ionic_converged: bool
    geometry_converged: bool
    last_max_force: float | None
    force_threshold: float | None
    risk_level: str
    likely_failure_modes: list[str]
    severe_issue_categories: list[str]
    monotonic_oscillating: bool
    has_job_done: bool

    def to_schema(self) -> dict[str, object]:
        return {
            "source": self.source,
            "status": self.status,
            "rank": self.rank,
            "total_steps": self.total_steps,
            "last_step": self.last_step,
            "final_energy_ry": self.final_energy_ry,
            "final_energy_ev": self.final_energy_ev,
            "delta_to_best_energy_ry": self.delta_to_best_energy_ry,
            "delta_to_best_energy_ev": self.delta_to_best_energy_ev,
            "final_pressure_kbar": self.final_pressure_kbar,
            "final_volume": self.final_volume,
            "final_enthalpy_ry": self.final_enthalpy_ry,
            "scf_converged_all_steps": self.scf_converged_all_steps,
            "ionic_converged": self.ionic_converged,
            "geometry_converged": self.geometry_converged,
            "last_max_force": self.last_max_force,
            "force_threshold": self.force_threshold,
            "risk_level": self.risk_level,
            "likely_failure_modes": list(self.likely_failure_modes),
            "severe_issue_categories": list(self.severe_issue_categories),
            "monotonic_oscillating": self.monotonic_oscillating,
            "has_job_done": self.has_job_done,
        }


@dataclass(frozen=True)
class RelaxOutputsComparison:
    """Structured comparison result for multiple relax runs."""

    status_counts: dict[str, int]
    runs: list[RelaxRunComparisonEntry]
    best_source: str | None
    best_energy_gap_ry: float | None

    def to_schema(self) -> dict[str, object]:
        return {
            "status_counts": dict(self.status_counts),
            "best_source": self.best_source,
            "best_energy_gap_ry": self.best_energy_gap_ry,
            "runs": [entry.to_schema() for entry in self.runs],
        }


def compare_relax_outputs(
    outputs: list[str | Path],
) -> RelaxOutputsComparison:
    """Parse and rank multiple relax output streams."""

    parsed = [parse_relax_output(output) for output in outputs]
    entries = [
        _build_entry(
            output,
            _display_source(path_or_text, index),
            path_or_text,
        )
        for index, (path_or_text, output) in enumerate(zip(outputs, parsed))
    ]

    best = _pick_best_entry(entries)
    if best is not None:
        entries = _annotate_energy_delta(entries, best)

    runs = sorted(entries, key=_rank_key)
    ranked = [
        RelaxRunComparisonEntry(**{**entry.__dict__, "rank": rank})
        for rank, entry in enumerate(runs, start=1)
    ]
    status_counts: dict[str, int] = {status: 0 for status in _status_order()}
    for entry in ranked:
        status_counts[entry.status] += 1

    best_source = ranked[0].source if ranked else None
    best_energy_gap = 0.0 if (ranked and ranked[0].final_energy_ry is not None) else None

    return RelaxOutputsComparison(
        status_counts=status_counts,
        runs=ranked,
        best_source=best_source,
        best_energy_gap_ry=best_energy_gap,
    )


def _build_entry(
    output: RelaxOutput,
    source: str,
    source_input: str | Path,
) -> RelaxRunComparisonEntry:
    snapshot = monitor_relax_output(source_input, source=source)
    stable = output.diagnostics.get("stability_report", {})
    risk_level = str(stable.get("overall_risk_level", "low"))
    likely_failure_modes = list(stable.get("likely_failure_modes", []))

    total_steps = len(output.relaxation_trajectory)
    last_step = (
        output.relaxation_trajectory[-1].step_index if output.relaxation_trajectory else None
    )
    last_entry = output.relaxation_trajectory[-1] if output.relaxation_trajectory else None
    last_max_force = last_entry.forces.max_force if last_entry is not None else None
    force_threshold = last_entry.forces.force_threshold if last_entry is not None else None

    severe_issues = [
        issue.category
        for issue in output.issues
        if issue.category in _SEVERE_FAILURE_CATEGORIES
    ]

    last_energy = output.final_observables.get("total_energy")
    final_enthalpy = output.final_observables.get("enthalpy")
    final_pressure = output.final_observables.get("pressure")
    final_volume = output.final_observables.get("volume")
    final_energy_ev = last_energy * RY_TO_EV if last_energy is not None else None

    if last_entry is not None:
        monotonic_oscillating = _is_oscillating(output)
    else:
        monotonic_oscillating = False

    return RelaxRunComparisonEntry(
        source=source,
        status=snapshot.status,
        rank=0,
        total_steps=total_steps,
        last_step=last_step,
        final_energy_ry=last_energy,
        final_energy_ev=final_energy_ev,
        delta_to_best_energy_ry=None,
        delta_to_best_energy_ev=None,
        final_pressure_kbar=final_pressure,
        final_volume=final_volume,
        final_enthalpy_ry=final_enthalpy,
        scf_converged_all_steps=bool(output.global_convergence.get("scf_converged_all_steps", False)),
        ionic_converged=bool(output.global_convergence.get("ionic_converged", False)),
        geometry_converged=bool(output.global_convergence.get("geometry_converged", False)),
        last_max_force=last_max_force,
        force_threshold=force_threshold,
        risk_level=risk_level,
        likely_failure_modes=likely_failure_modes,
        severe_issue_categories=sorted(set(severe_issues)),
        monotonic_oscillating=monotonic_oscillating,
        has_job_done=bool(output.job_done),
    )


def _pick_best_entry(entries: list[RelaxRunComparisonEntry]) -> RelaxRunComparisonEntry | None:
    if not entries:
        return None
    ranked = sorted(entries, key=_rank_key)
    return ranked[0]


def _annotate_energy_delta(
    entries: list[RelaxRunComparisonEntry],
    baseline: RelaxRunComparisonEntry,
) -> list[RelaxRunComparisonEntry]:
    if baseline.final_energy_ry is None:
        return entries

    updated: list[RelaxRunComparisonEntry] = []
    for entry in entries:
        delta_ry = (
            None if entry.final_energy_ry is None else entry.final_energy_ry - baseline.final_energy_ry
        )
        delta_ev = delta_ry * RY_TO_EV if delta_ry is not None else None
        updated.append(
            RelaxRunComparisonEntry(
                **{**entry.__dict__, "delta_to_best_energy_ry": delta_ry, "delta_to_best_energy_ev": delta_ev}
            )
        )
    return updated


def _rank_key(entry: RelaxRunComparisonEntry) -> tuple:
    status_order = _status_rank()
    status_rank = status_order.get(entry.status, 99)
    energy = _as_float(entry.final_energy_ry)
    force = _as_float(entry.last_max_force)
    risk = {"low": 0, "medium": 1, "high": 2}.get(entry.risk_level, 1)
    return (status_rank, energy, risk, force, entry.source)


def _status_rank() -> dict[str, int]:
    return {
        "completed": 0,
        "running": 1,
        "oscillating": 2,
        "blocked": 3,
        "failed": 4,
        "no_data": 5,
    }


def _status_order() -> tuple[str, ...]:
    return ("completed", "running", "oscillating", "blocked", "failed", "no_data")


def _is_oscillating(output: RelaxOutput) -> bool:
    values: list[float] = []
    for step in output.relaxation_trajectory:
        if not step.scf_trajectory:
            continue
        energies = [entry.total_energy for entry in step.scf_trajectory if entry.total_energy is not None]
        if energies:
            values.append(energies[-1])
    if len(values) < 3:
        return False
    deltas = [curr - prev for prev, curr in zip(values, values[1:])]
    return any(prev * curr < 0 for prev, curr in zip(deltas, deltas[1:]))


__all__ = [
    "compare_relax_outputs",
    "RelaxOutputsComparison",
    "RelaxRunComparisonEntry",
]
