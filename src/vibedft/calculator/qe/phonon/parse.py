"""Parse Quantum ESPRESSO ph.x stdout."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from vibedft.calculator.qe.common import QEOutputEvent, parse_qe_output_events


@dataclass(frozen=True)
class PhononState:
    """Canonical per-q-point phonon progress state."""

    q_index: int
    q_point: tuple[float, float, float] | None
    line_number: int
    representation_count: int
    frequency_count: int
    converged: bool
    blocked: bool
    min_frequency_cm1: float | None
    max_frequency_cm1: float | None

    def to_schema(self) -> dict[str, object]:
        return {
            "q_index": self.q_index,
            "q_point": list(self.q_point) if self.q_point is not None else None,
            "line_number": self.line_number,
            "representation_count": self.representation_count,
            "frequency_count": self.frequency_count,
            "converged": self.converged,
            "blocked": self.blocked,
            "min_frequency_cm1": self.min_frequency_cm1,
            "max_frequency_cm1": self.max_frequency_cm1,
        }


@dataclass(frozen=True)
class PhononRepresentation:
    """A ph.x irreducible representation progress marker."""

    number: int
    mode_number: int
    line_number: int


@dataclass(frozen=True)
class PhononFrequency:
    """A ph.x frequency reported in inverse centimeters."""

    mode_number: int | None
    frequency_cm1: float
    line_number: int


@dataclass(frozen=True)
class PhononOutput:
    """Structured view of QE ph.x progress."""

    source: str
    program: str | None
    version: str | None
    q_points: list[tuple[float, float, float]]
    dynamical_matrix_markers: list[int]
    representations: list[PhononRepresentation]
    frequencies: list[PhononFrequency]
    convergence_achieved_lines: list[int]
    job_done: bool
    cpu_seconds: float | None
    wall_seconds: float | None
    issues: list[QEOutputEvent]
    blocked_lines: list[int] = field(default_factory=list)
    state_sequence: list[PhononState] = field(default_factory=list)
    source_summary: str = "phonon run"

    def to_schema(self) -> dict[str, object]:
        """Return a compact structured schema for downstream orchestration."""

        freqs = [frequency.frequency_cm1 for frequency in self.frequencies]
        return {
            "source": self.source,
            "system": {
                "program": self.program,
                "version": self.version,
            },
            "numerical": {
                "q_points": [list(q_point) for q_point in self.q_points],
                "dynamical_matrix_markers": list(self.dynamical_matrix_markers),
            },
            "state_sequence": [state.to_schema() for state in self.state_sequence],
            "convergence": {
                "convergence_achieved_lines": list(self.convergence_achieved_lines),
                "blocked_lines": list(self.blocked_lines),
                "job_done": self.job_done,
            },
            "frequencies": {
                "count": len(self.frequencies),
                "min_cm1": min(freqs, default=None),
                "max_cm1": max(freqs, default=None),
            },
            "timing": {
                "cpu_seconds": self.cpu_seconds,
                "wall_seconds": self.wall_seconds,
            },
            "issues": [
                {
                    "line_number": issue.line_number,
                    "category": issue.category,
                    "severity": issue.severity,
                    "message": issue.message,
                    "source": issue.source,
                }
                for issue in self.issues
            ],
            "source_summary": self.source_summary,
        }


_FLOAT_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_PROGRAM_RE = re.compile(
    r"\bProgram\s+([A-Za-z0-9_.-]+)(?:\s+v\.?\s*([A-Za-z0-9_.-]+))?",
    re.IGNORECASE,
)
_Q_POINT_RE = re.compile(
    rf"\bq\s*=\s*\(?\s*({_FLOAT_RE})\s+({_FLOAT_RE})\s+({_FLOAT_RE})\s*\)?",
    re.IGNORECASE,
)
_DYNAMICAL_RE = re.compile(r"\bdynamical\s+matrix\b", re.IGNORECASE)
_REPRESENTATION_RE = re.compile(
    r"\bRepresentation\s*#\s*(\d+)\s+mode\s*#\s*(\d+)",
    re.IGNORECASE,
)
_FREQUENCY_RE = re.compile(r"\b(?:freq|omega)\s*(?:\(\s*(\d+)\s*\))?", re.IGNORECASE)
_CM1_VALUE_RE = re.compile(rf"=\s*({_FLOAT_RE})\s*(?:\[?\s*cm\s*-?\s*1\s*\]?)", re.IGNORECASE)
_CONVERGENCE_RE = re.compile(r"\bconvergence\s+has\s+been\s+achieved\b", re.IGNORECASE)
_JOB_DONE_RE = re.compile(r"\bJOB\s+DONE\b", re.IGNORECASE)
_BLOCKED_RE = re.compile(r"\bconvergence\s+NOT\s+achieved|stopping|diverging", re.IGNORECASE)
_TIMING_RE = re.compile(
    rf":\s*({_FLOAT_RE})s\s+CPU\s+({_FLOAT_RE})s\s+WALL\b",
    re.IGNORECASE,
)


def parse_phonon_output(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
) -> PhononOutput:
    """Parse QE ph.x stdout text or a file path into progress data."""

    text, source_label = _load_text_and_source(text_or_path, source)
    scan = parse_qe_output_events(text, source=source_label)

    program: str | None = None
    version: str | None = None
    q_points: list[tuple[float, float, float]] = []
    dynamical_matrix_markers: list[int] = []
    representations: list[PhononRepresentation] = []
    frequencies: list[PhononFrequency] = []
    state_sequence: list[PhononState] = []
    convergence_achieved_lines: list[int] = []
    blocked_lines: list[int] = []
    job_done = False
    cpu_seconds: float | None = None
    wall_seconds: float | None = None

    current_q_index = 0
    current_q_point: tuple[float, float, float] | None = None
    state_started_at: int | None = None
    state_seen_activity = False
    rep_count = 0
    freq_count = 0
    state_converged = False
    state_blocked = False
    state_min_freq: float | None = None
    state_max_freq: float | None = None

    def _begin_state(line_number: int, q_point: tuple[float, float, float] | None = None) -> None:
        nonlocal current_q_index, current_q_point, state_started_at, state_seen_activity
        if state_started_at is None:
            current_q_index += 1
            state_started_at = line_number
            current_q_point = q_point
            state_seen_activity = True
        elif q_point is not None:
            current_q_point = q_point

    def _commit_state() -> None:
        nonlocal current_q_index, state_started_at, current_q_point, rep_count, freq_count
        nonlocal state_converged, state_blocked, state_min_freq, state_max_freq, state_seen_activity

        if not state_seen_activity:
            return
        state_sequence.append(
            PhononState(
                q_index=current_q_index,
                q_point=current_q_point,
                line_number=state_started_at or 0,
                representation_count=rep_count,
                frequency_count=freq_count,
                converged=state_converged,
                blocked=state_blocked,
                min_frequency_cm1=state_min_freq,
                max_frequency_cm1=state_max_freq,
            )
        )
        current_q_point = None
        state_started_at = None
        rep_count = 0
        freq_count = 0
        state_converged = False
        state_blocked = False
        state_min_freq = None
        state_max_freq = None
        state_seen_activity = False

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        if program is None:
            program_match = _PROGRAM_RE.search(line)
            if program_match:
                program = program_match.group(1).upper()
                version = program_match.group(2)

        q_match = _Q_POINT_RE.search(line)
        if q_match:
            _commit_state()
            q_point = (
                _to_float(q_match.group(1)),
                _to_float(q_match.group(2)),
                _to_float(q_match.group(3)),
            )
            q_points.append(q_point)
            _begin_state(line_number, q_point=q_point)

        if _DYNAMICAL_RE.search(line):
            dynamical_matrix_markers.append(line_number)
            _begin_state(line_number)

        representation_match = _REPRESENTATION_RE.search(line)
        if representation_match:
            representations.append(
                PhononRepresentation(
                    number=int(representation_match.group(1)),
                    mode_number=int(representation_match.group(2)),
                    line_number=line_number,
                )
            )
            rep_count += 1
            _begin_state(line_number)

        frequency_match = _FREQUENCY_RE.search(line)
        if frequency_match:
            cm1_match = _last_cm1_value(line)
            mode_number = (
                int(frequency_match.group(1))
                if frequency_match.group(1) is not None
                else None
            )
            _begin_state(line_number)
            if cm1_match is not None:
                frequency_value = _to_float(cm1_match)
                frequencies.append(
                    PhononFrequency(
                        mode_number=mode_number,
                        frequency_cm1=frequency_value,
                        line_number=line_number,
                    )
                )
                freq_count += 1
                state_min_freq = (
                    frequency_value
                    if state_min_freq is None
                    else min(state_min_freq, frequency_value)
                )
                state_max_freq = (
                    frequency_value
                    if state_max_freq is None
                    else max(state_max_freq, frequency_value)
                )
            else:
                # Frequency line detected but no cm^-1 unit; keep state semantics.
                frequencies.append(
                    PhononFrequency(
                        mode_number=mode_number,
                        frequency_cm1=float("nan"),
                        line_number=line_number,
                    )
                )

        if _CONVERGENCE_RE.search(line):
            convergence_achieved_lines.append(line_number)
            state_converged = True
            _begin_state(line_number)

        if _BLOCKED_RE.search(line):
            blocked_lines.append(line_number)
            state_blocked = True
            _begin_state(line_number)

        if _JOB_DONE_RE.search(line):
            job_done = True

        timing_match = _TIMING_RE.search(line)
        if timing_match:
            cpu_seconds = _to_float(timing_match.group(1))
            wall_seconds = _to_float(timing_match.group(2))

    _commit_state()

    return PhononOutput(
        source=scan.source,
        program=program,
        version=version,
        q_points=q_points,
        dynamical_matrix_markers=dynamical_matrix_markers,
        representations=representations,
        frequencies=[freq for freq in frequencies if not _is_nan(freq.frequency_cm1)],
        state_sequence=state_sequence,
        blocked_lines=blocked_lines,
        convergence_achieved_lines=convergence_achieved_lines,
        job_done=job_done,
        cpu_seconds=cpu_seconds,
        wall_seconds=wall_seconds,
        issues=scan.issues,
        source_summary=f"phonon q-points={len(q_points)} representations={len(representations)} frequencies={len(frequencies)}",
    )


def _load_text_and_source(text_or_path: str | Path, source: str | Path | None) -> tuple[str, str]:
    if isinstance(text_or_path, Path):
        return (
            text_or_path.read_text(encoding="utf-8", errors="replace"),
            _source_label(source if source is not None else text_or_path),
        )
    candidate_path = Path(text_or_path)
    if "\n" not in text_or_path and candidate_path.is_file():
        return (
            candidate_path.read_text(encoding="utf-8", errors="replace"),
            _source_label(source if source is not None else candidate_path),
        )
    return text_or_path, _source_label(source if source is not None else "text")


def _source_label(source: str | Path) -> str:
    if isinstance(source, Path):
        return source.name
    source_text = str(source)
    if "/" in source_text or "\\" in source_text:
        normalized = source_text.replace("\\", "/")
        return normalized.rsplit("/", 1)[-1]
    return source_text


def _last_cm1_value(line: str) -> str | None:
    matches = list(_CM1_VALUE_RE.finditer(line))
    if not matches:
        return None
    return matches[-1].group(1)


def _to_float(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "E"))


def _is_nan(value: float) -> bool:
    return value != value


__all__ = [
    "PhononState",
    "PhononFrequency",
    "PhononOutput",
    "PhononRepresentation",
    "parse_phonon_output",
]
