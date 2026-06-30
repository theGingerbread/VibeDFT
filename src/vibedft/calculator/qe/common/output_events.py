"""Common QE stdout/stderr event extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QEOutputEvent:
    """A line-local event or issue extracted from QE output text."""

    line_number: int
    category: str
    severity: str
    message: str
    source: str


@dataclass(frozen=True)
class QEOutputScan:
    """Structured scan result for QE stdout/stderr-like output."""

    events: list[QEOutputEvent]
    issues: list[QEOutputEvent]
    source: str


_FLOAT_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_WINDOWS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\)[^'\",)\n\r]+")
_POSIX_PATH_RE = re.compile(r"(?<!\w)(?:/[^\s:'\",)]+)+")
_ITERATION_RE = re.compile(r"\biteration\s*#\s*(\d+)", re.IGNORECASE)
_ACCURACY_RE = re.compile(
    rf"\bestimated\s+scf\s+accuracy\s*<\s*({_FLOAT_RE})\s*Ry\b",
    re.IGNORECASE,
)
_TOTAL_ENERGY_RE = re.compile(
    rf"!?\s*\btotal\s+energy\s*=\s*({_FLOAT_RE})\s*Ry\b",
    re.IGNORECASE,
)
_CONVERGENCE_RE = re.compile(r"\bconvergence\s+has\s+been\s+achieved\b", re.IGNORECASE)
_JOB_DONE_RE = re.compile(r"\bJOB\s+DONE\b", re.IGNORECASE)
_WARNING_RE = re.compile(r"\bwarning\b", re.IGNORECASE)
_ERROR_RE = re.compile(
    r"\bError\s+in\s+routine\b|^\s*ERROR[:\s]|^\s*Error[:\s]",
    re.IGNORECASE,
)
_Q_POINT_RE = re.compile(r"\bq(?:-point|\s*=)", re.IGNORECASE)

_FAILURE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mpi_abort", re.compile(r"\bMPI_?ABORT\b|MPI_ABORT was invoked", re.IGNORECASE)),
    ("segmentation_fault", re.compile(r"\bsegmentation fault\b|\bsigsegv\b", re.IGNORECASE)),
    (
        "out_of_memory",
        re.compile(r"\bout of memory\b|\bOOM\b|\bkilled process\b", re.IGNORECASE),
    ),
    (
        "time_limit",
        re.compile(r"\bwalltime\b|\btime limit\b|DUE TO TIME LIMIT", re.IGNORECASE),
    ),
    ("traceback", re.compile(r"\bTraceback \(most recent call last\):", re.IGNORECASE)),
    (
        "file_not_found",
        re.compile(
            r"\bfile not found\b|\bno such file\b|No such file or directory|FileNotFoundError",
            re.IGNORECASE,
        ),
    ),
)


def parse_qe_output_events(text_or_path: str | Path, *, source: str | Path | None = None) -> QEOutputScan:
    """Parse QE output text or a path into line-local events and issues.

    Strings are treated as already-loaded text. Pass a :class:`pathlib.Path`
    when the parser should read from disk.
    """

    text, source_label = _load_text_and_source(text_or_path, source)
    events: list[QEOutputEvent] = []
    issues: list[QEOutputEvent] = []
    saw_activity_marker = False
    saw_convergence = False
    saw_job_done = False
    last_activity_line = 0
    last_content_line = 0

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        last_content_line = line_number

        iteration = _ITERATION_RE.search(line)
        if iteration:
            saw_activity_marker = True
            last_activity_line = line_number
            events.append(
                _make_event(
                    line_number,
                    "scf_iteration",
                    "info",
                    f"iteration # {iteration.group(1)}",
                    source_label,
                )
            )

        energy = _TOTAL_ENERGY_RE.search(line)
        if energy:
            saw_activity_marker = True
            last_activity_line = line_number
            events.append(
                _make_event(
                    line_number,
                    "total_energy",
                    "info",
                    f"total energy = {_normalize_number(energy.group(1))} Ry",
                    source_label,
                )
            )

        accuracy = _ACCURACY_RE.search(line)
        if accuracy:
            saw_activity_marker = True
            last_activity_line = line_number
            events.append(
                _make_event(
                    line_number,
                    "scf_accuracy",
                    "info",
                    f"estimated scf accuracy < {_normalize_number(accuracy.group(1))} Ry",
                    source_label,
                )
            )

        if _CONVERGENCE_RE.search(line):
            saw_convergence = True
            events.append(_make_event(line_number, "convergence", "info", line, source_label))

        if _JOB_DONE_RE.search(line):
            saw_job_done = True
            events.append(_make_event(line_number, "job_done", "info", "JOB DONE", source_label))

        if _Q_POINT_RE.search(line):
            saw_activity_marker = True
            last_activity_line = line_number

        if _WARNING_RE.search(line):
            issues.append(_make_event(line_number, "warning", "warning", line, source_label))

        if _ERROR_RE.search(line):
            issues.append(_make_event(line_number, "error", "error", line, source_label))

        for category, pattern in _FAILURE_PATTERNS:
            if pattern.search(line):
                issues.append(_make_event(line_number, category, "error", line, source_label))

    if saw_activity_marker and not saw_convergence and not saw_job_done:
        issues.append(
            _make_event(
                last_content_line or last_activity_line,
                "truncated_output",
                "error",
                "Output has activity markers but no convergence or JOB DONE marker",
                source_label,
            )
        )

    return QEOutputScan(events=events, issues=issues, source=source_label)


def _load_text_and_source(text_or_path: str | Path, source: str | Path | None) -> tuple[str, str]:
    if isinstance(text_or_path, Path):
        text = text_or_path.read_text(encoding="utf-8", errors="replace")
        source_label = _source_label(source if source is not None else text_or_path)
        return text, source_label
    return text_or_path, _source_label(source if source is not None else "text")


def _make_event(
    line_number: int,
    category: str,
    severity: str,
    message: str,
    source: str,
) -> QEOutputEvent:
    return QEOutputEvent(
        line_number=line_number,
        category=category,
        severity=severity,
        message=_sanitize_message(message),
        source=source,
    )


def _source_label(source: str | Path) -> str:
    if isinstance(source, Path):
        return source.name
    source_text = str(source)
    if "/" in source_text or "\\" in source_text:
        normalized = source_text.replace("\\", "/")
        return normalized.rsplit("/", 1)[-1]
    return source_text


def _sanitize_message(message: str) -> str:
    sanitized = _WINDOWS_PATH_RE.sub("<path>", message.strip())
    return _POSIX_PATH_RE.sub("<path>", sanitized)


def _normalize_number(value: str) -> str:
    return value.replace("D", "E").replace("d", "E")


__all__ = ["QEOutputEvent", "QEOutputScan", "parse_qe_output_events"]
