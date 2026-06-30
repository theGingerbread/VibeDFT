"""QE ph.x stdout monitor."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibedft.calculator.qe.common import QEOutputEvent

from .parse import PhononOutput, parse_phonon_output


@dataclass(frozen=True)
class PhononMonitorEvent:
    """Structured monitor event consumed by the phonon state machine."""

    type: str
    timestamp_or_index: int | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class PhononMonitorSnapshot:
    """Point-in-time phonon monitor state."""

    status: str
    job_done: bool
    q_points_seen: int
    representations_seen: int
    frequencies_seen: int
    min_frequency_cm1: float | None
    max_frequency_cm1: float | None
    issues: list[QEOutputEvent]
    summary: str
    suggested_actions: list[str]


@dataclass
class PhononStateMachine:
    """Event-driven phonon monitor state machine."""

    status: str = "no_data"
    job_done: bool = False
    converged: bool = False
    q_points_seen: int = 0
    representations_seen: int = 0
    frequencies_seen: int = 0
    min_frequency_cm1: float | None = None
    max_frequency_cm1: float | None = None
    issues: list[QEOutputEvent] = field(default_factory=list)
    events: list[PhononMonitorEvent] = field(default_factory=list)
    blocked_marker_seen: bool = False

    def update(self, event: PhononMonitorEvent) -> "PhononStateMachine":
        """Update machine state from a monitor event."""

        if event.type == "q_point":
            self.q_points_seen += 1
            self.events.append(event)
            return self

        if event.type == "representation":
            self.representations_seen += 1
            self.events.append(event)
            return self

        if event.type == "frequency":
            self.frequencies_seen += 1
            frequency = event.payload.get("frequency_cm1")
            if isinstance(frequency, (int, float)):
                self._update_frequency_range(float(frequency))
            self.events.append(event)
            return self

        if event.type == "convergence":
            self.converged = bool(event.payload.get("converged", False))
            self.events.append(event)
            return self

        if event.type == "job_done":
            self.job_done = True
            self.events.append(event)
            return self

        if event.type == "blocked_marker":
            self.blocked_marker_seen = True
            self.events.append(event)
            return self

        return self

    def mark_blocked_marker(self) -> "PhononStateMachine":
        self.blocked_marker_seen = True
        return self

    def merge_issues(self, issues: list[QEOutputEvent]) -> None:
        seen_keys = {(issue.line_number, issue.category, issue.message) for issue in self.issues}
        for issue in issues:
            key = (issue.line_number, issue.category, issue.message)
            if key not in seen_keys:
                self.issues.append(issue)
                seen_keys.add(key)

    def finalize(self) -> None:
        """Compute final status from all observed markers."""

        severe = any(
            issue.category in _SEVERE_FAILURE_CATEGORIES for issue in self.issues
        )
        has_progress = (
            self.q_points_seen
            + self.representations_seen
            + self.frequencies_seen
            > 0
        )

        if severe:
            self.status = "failed"
            return

        if self.job_done:
            has_progress = (
                self.q_points_seen
                + self.representations_seen
                + self.frequencies_seen
                > 0
            )
            if self.blocked_marker_seen:
                self.status = "blocked"
                return
            if self.converged or has_progress:
                self.status = "completed"
                return
            self.status = "blocked"
            return

        if self.blocked_marker_seen and not self.converged:
            self.status = "blocked"
            return

        if has_progress:
            self.status = "running"
            return

        if self.job_done:
            # Completed marker without parseable content.
            self.status = "blocked"
            return

        self.status = "no_data"

    def to_snapshot(self, *, output: PhononOutput | None = None) -> PhononMonitorSnapshot:
        self.finalize()
        q_points_seen = self.q_points_seen
        representations_seen = self.representations_seen
        frequencies_seen = self.frequencies_seen
        min_freq = self.min_frequency_cm1
        max_freq = self.max_frequency_cm1

        if output is not None:
            q_points_seen = len(output.q_points) if q_points_seen == 0 else q_points_seen
            representations_seen = (
                len(output.representations)
                if representations_seen == 0
                else representations_seen
            )
            frequencies_seen = (
                len(output.frequencies)
                if frequencies_seen == 0
                else frequencies_seen
            )
            if min_freq is None and output.frequencies:
                freqs = [frequency.frequency_cm1 for frequency in output.frequencies]
                min_freq = min(freqs) if freqs else None
                max_freq = max(freqs) if freqs else None

        return PhononMonitorSnapshot(
            status=self.status,
            job_done=self.job_done,
            q_points_seen=q_points_seen,
            representations_seen=representations_seen,
            frequencies_seen=frequencies_seen,
            min_frequency_cm1=min_freq,
            max_frequency_cm1=max_freq,
            issues=self.issues,
            summary=_status_summary(self.status, output, self.blocked_marker_seen),
            suggested_actions=_status_actions(self.status),
        )

    def _update_frequency_range(self, frequency: float) -> None:
        if self.min_frequency_cm1 is None:
            self.min_frequency_cm1 = frequency
            self.max_frequency_cm1 = frequency
            return
        self.min_frequency_cm1 = min(self.min_frequency_cm1, frequency)
        self.max_frequency_cm1 = max(self.max_frequency_cm1, frequency)


_SEVERE_FAILURE_CATEGORIES = {
    "mpi_abort",
    "segmentation_fault",
    "out_of_memory",
    "time_limit",
    "traceback",
    "file_not_found",
    "error",
}
_BLOCKED_MARKER_RE = re.compile(
    r"\bconvergence\s+not\s+achieved|stopping|diverging",
    re.IGNORECASE,
)
_JOB_DONE_RE = re.compile(r"\bJOB\s+DONE\b", re.IGNORECASE)
_CONVERGENCE_RE = re.compile(r"\bconvergence\s+has\s+been\s+achieved\b", re.IGNORECASE)


def monitor_phonon_output(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
) -> PhononMonitorSnapshot:
    """Classify a QE ph.x stdout stream into a deterministic status."""

    output = parse_phonon_output(text_or_path, source=source)
    text = _load_text(text_or_path)

    machine = PhononStateMachine()
    _consume_output_as_events(output, machine)
    _consume_text_markers(text, machine)
    machine.merge_issues(output.issues)

    if _has_phonon_progress(output):
        machine.q_points_seen = max(machine.q_points_seen, len(output.q_points))
        machine.representations_seen = max(
            machine.representations_seen, len(output.representations)
        )
        machine.frequencies_seen = max(
            machine.frequencies_seen, len(output.frequencies)
        )
        machine.job_done = machine.job_done or output.job_done
        machine.converged = machine.converged or bool(output.convergence_achieved_lines)

    if output.frequencies and machine.min_frequency_cm1 is None:
        frequencies = [frequency.frequency_cm1 for frequency in output.frequencies]
        if frequencies:
            machine.min_frequency_cm1 = min(frequencies)
            machine.max_frequency_cm1 = max(frequencies)

    snapshot = machine.to_snapshot(output=output)
    return snapshot


def _consume_output_as_events(output: PhononOutput, machine: PhononStateMachine) -> None:
    """Project parsed structures into monitor events."""

    for index, point in enumerate(output.q_points, start=1):
        machine.update(
            PhononMonitorEvent(
                type="q_point",
                timestamp_or_index=index,
                payload={"q_point": point},
            )
        )

    for representation in output.representations:
        machine.update(
            PhononMonitorEvent(
                type="representation",
                timestamp_or_index=representation.line_number,
                payload={
                    "representation_number": representation.number,
                    "mode_number": representation.mode_number,
                },
            )
        )

    for frequency in output.frequencies:
        machine.update(
            PhononMonitorEvent(
                type="frequency",
                timestamp_or_index=frequency.line_number,
                payload={
                    "mode_number": frequency.mode_number,
                    "frequency_cm1": frequency.frequency_cm1,
                },
            )
        )

    for line in output.convergence_achieved_lines:
        machine.update(
            PhononMonitorEvent(
                type="convergence",
                timestamp_or_index=line,
                payload={"converged": True},
            )
        )

    for line in output.blocked_lines:
        machine.update(
            PhononMonitorEvent(
                type="blocked_marker",
                timestamp_or_index=line,
                payload={"reason": "phonon convergence blocked"},
            )
        )


def _consume_text_markers(text: str, machine: PhononStateMachine) -> None:
    """Derive terminal/bounded markers from raw phonon text."""

    for raw_line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if _BLOCKED_MARKER_RE.search(line):
            machine.update(
                PhononMonitorEvent(
                    type="blocked_marker",
                    timestamp_or_index=raw_line_number,
                    payload={"reason": line},
                )
            )
        if _JOB_DONE_RE.search(line):
            machine.update(
                PhononMonitorEvent(
                    type="job_done",
                    timestamp_or_index=raw_line_number,
                    payload={},
                )
            )
        if _CONVERGENCE_RE.search(line):
            machine.update(
                PhononMonitorEvent(
                    type="convergence",
                    timestamp_or_index=raw_line_number,
                    payload={"converged": True},
                )
            )


def _has_phonon_progress(output: PhononOutput) -> bool:
    return bool(
        output.q_points
        or output.representations
        or output.dynamical_matrix_markers
        or output.frequencies
    )


def _load_text(text_or_path: str | Path) -> str:
    if isinstance(text_or_path, Path):
        return text_or_path.read_text(encoding="utf-8", errors="replace")
    candidate_path = Path(text_or_path)
    if "\n" not in text_or_path and candidate_path.is_file():
        return candidate_path.read_text(encoding="utf-8", errors="replace")
    return text_or_path


def _status_summary(status: str, output: PhononOutput | None, blocked_marker_seen: bool) -> str:
    if status == "completed":
        return "QE phonon output completed with phonon convergence achieved."
    if status == "failed":
        return "Phonon failed with QE/environment failure marker."
    if status == "blocked":
        if output is not None and output.job_done and not output.convergence_achieved_lines:
            if _has_phonon_progress(output):
                return "Phonon reached a non-success terminal marker."
            return "JOB DONE reached with no phonon progress."
        if blocked_marker_seen:
            return "Phonon output reached a non-success terminal marker."
    if status == "running":
        if output is not None:
            return (
                f"QE phonon output running; {len(output.q_points)} q-points, "
                f"{len(output.representations)} representations, {len(output.frequencies)} frequencies."
            )
        return "QE phonon output is running."
    if status == "no_data":
        return "No QE phonon output body detected"
    return "No actionable phonon state detected"


def _status_actions(status: str) -> list[str]:
    if status == "completed":
        return []
    if status == "failed":
        return [
            "Inspect severe QE failure markers in context and rerun after fixing input/runtime dependencies.",
        ]
    if status == "blocked":
        return ["Inspect the phonon convergence failure before downstream use."]
    if status == "running":
        return ["Wait for more phonon stdout or a terminal JOB DONE/failure marker."]
    return ["Point the monitor at the phonon stdout file rather than the scheduler wrapper."]


__all__ = [
    "PhononMonitorEvent",
    "PhononMonitorSnapshot",
    "PhononStateMachine",
    "monitor_phonon_output",
]
