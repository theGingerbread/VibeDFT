"""Monitor Quantum ESPRESSO PWscf SCF stdout status."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibedft.calculator.qe.common import QEOutputEvent, parse_qe_output_events
from vibedft.calculator.qe.scf.parse import ScfOutput, parse_scf_output


_FLOAT_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_TOTAL_ENERGY_RE = re.compile(rf"total\s+energy\s*=\s*({_FLOAT_RE})\s*Ry\b", re.IGNORECASE)
_ACCURACY_RE = re.compile(
    rf"estimated\s+scf\s+accuracy\s*<\s*({_FLOAT_RE})\s*Ry\b",
    re.IGNORECASE,
)
_ITERATION_RE = re.compile(r"\biteration\s*#\s*(\d+)", re.IGNORECASE)
_SEVERE_FAILURE_CATEGORIES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}
_BLOCKED_MARKER_RE = re.compile(
    r"\bbfgs\s+failed\b|\bconvergence\s+(?:not|NOT)\s+achieved\b|\bhistory\s+already\s+reset\b",
    re.IGNORECASE,
)


@dataclass
class ScfMonitorEvent:
    """Structured monitor event consumed by the SCF state machine."""

    type: str
    timestamp_or_index: int | None
    payload: dict[str, Any]


@dataclass
class ScfMonitorSnapshot:
    """Point-in-time SCF monitor state."""

    status: str
    job_done: bool
    converged: bool
    last_iteration: int | None
    last_total_energy_ry: float | None
    last_scf_accuracy_ry: float | None
    issues: list[QEOutputEvent]
    summary: str
    suggested_actions: list[str]


@dataclass
class SCFStateMachine:
    """Event-driven SCF monitor state."""

    status: str = "no_data"
    job_done: bool = False
    converged: bool = False
    last_iteration: int | None = None
    last_total_energy_ry: float | None = None
    last_scf_accuracy_ry: float | None = None
    issues: list[QEOutputEvent] = field(default_factory=list)
    events: list[ScfMonitorEvent] = field(default_factory=list)
    blocked_marker_seen: bool = False

    def update(self, event: QEOutputEvent) -> "SCFStateMachine":
        """Update state from one parsed QE event."""

        if event.category in _SEVERE_FAILURE_CATEGORIES:
            self.issues.append(event)
        elif event.category == "warning":
            self.issues.append(event)

        if event.category == "scf_iteration":
            self.last_iteration = _parse_int_group(_ITERATION_RE.search(event.message))
            if self.last_iteration is not None:
                self.events.append(
                    ScfMonitorEvent(
                        type="iteration",
                        timestamp_or_index=self.last_iteration,
                        payload={"iteration": self.last_iteration},
                    )
                )
            return self

        if event.category == "total_energy":
            self.last_total_energy_ry = _parse_float(event.message)
            self.events.append(
                ScfMonitorEvent(
                    type="energy",
                    timestamp_or_index=event.line_number,
                    payload={"energy": self.last_total_energy_ry},
                )
            )
            return self

        if event.category == "scf_accuracy":
            self.last_scf_accuracy_ry = _parse_float(event.message)
            self.events.append(
                ScfMonitorEvent(
                    type="accuracy",
                    timestamp_or_index=event.line_number,
                    payload={"scf_accuracy": self.last_scf_accuracy_ry},
                )
            )
            return self

        if event.category == "convergence":
            self.converged = True
            self.events.append(
                ScfMonitorEvent(
                    type="convergence",
                    timestamp_or_index=event.line_number,
                    payload={"converged": True},
                )
            )
            return self

        if event.category == "job_done":
            self.job_done = True
            self.events.append(
                ScfMonitorEvent(
                    type="job_done",
                    timestamp_or_index=event.line_number,
                    payload={"job_done": True},
                )
            )
            return self

        if event.category == "truncated_output":
            self.events.append(
                ScfMonitorEvent(
                    type="truncated_output",
                    timestamp_or_index=event.line_number,
                    payload={"message": event.message},
                )
            )
            return self
        return self

    def mark_blocked_marker(self) -> "SCFStateMachine":
        self.blocked_marker_seen = True
        return self

    def merge_issues(self, issues: list[QEOutputEvent]) -> None:
        seen_keys = {
            (issue.line_number, issue.category, issue.message) for issue in self.issues
        }
        for issue in issues:
            key = (issue.line_number, issue.category, issue.message)
            if key not in seen_keys:
                self.issues.append(issue)
                seen_keys.add(key)

    def finalize(self) -> None:
        """Compute final status after all events are ingested."""

        severe = any(issue.category in _SEVERE_FAILURE_CATEGORIES for issue in self.issues)
        if severe:
            self.status = "failed"
            return
        if self.blocked_marker_seen and not (self.converged and self.job_done):
            self.status = "blocked"
            return
        if self.job_done and self.converged:
            self.status = "completed"
            return
        if self.job_done and not self.converged:
            self.status = "blocked"
            return
        if self.last_iteration is not None or self.last_total_energy_ry is not None:
            self.status = "running"
            return
        self.status = "no_data"

    def to_snapshot(self, *, output: ScfOutput | None = None) -> ScfMonitorSnapshot:
        self.finalize()
        summary = _status_summary(self.status, self.last_iteration)
        if output is not None and self.status == "completed":
            if output.convergence_iterations is not None:
                summary = f"SCF completed after {output.convergence_iterations} iterations."
            elif output.iterations:
                summary = f"SCF completed after {output.iterations[-1].number} iterations."
            else:
                summary = "SCF completed."
        if output is not None and self.status == "blocked":
            if output.job_done and not output.converged:
                summary = "SCF reached JOB DONE without convergence."
            elif output.converged and output.job_done and self.blocked_marker_seen:
                summary = "SCF reached a non-success terminal marker."
        if self.status == "failed":
            categories = {issue.category for issue in self.issues if issue.category in _SEVERE_FAILURE_CATEGORIES}
            if categories:
                summary = (
                    "SCF failed with severe QE output issue(s): "
                    + ", ".join(sorted(categories))
                    + "."
                )

        return ScfMonitorSnapshot(
            status=self.status,
            job_done=self.job_done,
            converged=self.converged,
            last_iteration=self.last_iteration,
            last_total_energy_ry=self.last_total_energy_ry,
            last_scf_accuracy_ry=self.last_scf_accuracy_ry,
            issues=self.issues,
            summary=summary,
            suggested_actions=_status_actions(self.status),
        )


def monitor_scf_output(
    text_or_path: str | Path, *, source: str | Path | None = None
) -> ScfMonitorSnapshot:
    """Classify SCF output progress through an event-driven state machine."""

    output = parse_scf_output(text_or_path, source=source)
    text = _load_text(text_or_path)
    scan = parse_qe_output_events(text, source=output.source)

    machine = SCFStateMachine()
    for event in scan.events:
        machine.update(event)
    machine.merge_issues(scan.issues)
    if _BLOCKED_MARKER_RE.search(text) is not None:
        machine.mark_blocked_marker()

    _sync_with_parsed_output(machine, output)
    return machine.to_snapshot(output=output)


def _sync_with_parsed_output(machine: SCFStateMachine, output: ScfOutput) -> None:
    machine.job_done = machine.job_done or output.job_done
    machine.converged = machine.converged or output.converged
    if output.iterations:
        machine.last_iteration = (
            output.iterations[-1].number
            if machine.last_iteration is None
            else machine.last_iteration
        )
        machine.last_total_energy_ry = (
            machine.last_total_energy_ry
            if machine.last_total_energy_ry is not None
            else output.iterations[-1].total_energy_ry
        )
        if machine.last_scf_accuracy_ry is None:
            machine.last_scf_accuracy_ry = output.final_scf_accuracy_ry


def _load_text(text_or_path: str | Path) -> str:
    if isinstance(text_or_path, Path):
        return text_or_path.read_text(encoding="utf-8", errors="replace")
    candidate_path = Path(text_or_path)
    if "\n" not in text_or_path and candidate_path.is_file():
        return candidate_path.read_text(encoding="utf-8", errors="replace")
    return text_or_path


def _parse_float(message: str) -> float | None:
    match = _TOTAL_ENERGY_RE.search(message) or _ACCURACY_RE.search(message)
    if match is None:
        return None
    value = match.group(1).replace("D", "E").replace("d", "E")
    return float(value)


def _parse_int_group(match: re.Match[str] | None) -> int | None:
    if match is None:
        return None
    return int(match.group(1))


def _status_summary(status: str, last_iteration: int | None) -> str:
    if status == "completed":
        return "SCF completed."
    if status == "failed":
        return "SCF failed with severe QE output issue(s)."
    if status == "blocked":
        return "SCF reached a blocking terminal state."
    if status == "running":
        if last_iteration is not None:
            return f"SCF still running at iteration {last_iteration}."
        return "SCF still running with partial progress markers."
    return "No useful SCF progress markers found."


def _status_actions(status: str) -> list[str]:
    if status == "completed":
        return []
    if status == "failed":
        return [
            "Inspect the first severe error and rerun only after correcting the input or runtime failure."
        ]
    if status == "blocked":
        return [
            "Do not treat JOB DONE alone as success; inspect SCF convergence and restart policy."
        ]
    if status == "running":
        return ["Wait for convergence or a terminal failure marker."]
    return ["Check that the monitored file is the PWscf stdout file."]


__all__ = [
    "ScfMonitorEvent",
    "SCFStateMachine",
    "ScfMonitorSnapshot",
    "monitor_scf_output",
]
