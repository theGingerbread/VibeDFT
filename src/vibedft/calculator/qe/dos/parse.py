"""Parse Quantum ESPRESSO dos.x stdout and optional DOS data file."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from vibedft.calculator.qe.common import QEOutputEvent, parse_qe_output_events


_FLOAT_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"


@dataclass(frozen=True)
class DosOutput:
    """Structured DOS task parse artifact."""

    program: str | None
    version: str | None
    issues: list[QEOutputEvent]
    source: str

    job_done: bool
    fermi_energy_ev: float | None
    energy_grid_count: int | None
    energy_min_ev: float | None
    energy_max_ev: float | None
    dos_min: float | None
    dos_max: float | None
    integrated_dos_present: bool
    data_columns: list[str]
    data_file: str | None

    def to_schema(self) -> dict[str, object]:
        return {
            "program": self.program,
            "version": self.version,
            "source": self.source,
            "job_done": self.job_done,
            "fermi_energy_ev": self.fermi_energy_ev,
            "energy_grid_count": self.energy_grid_count,
            "energy_min_ev": self.energy_min_ev,
            "energy_max_ev": self.energy_max_ev,
            "dos_min": self.dos_min,
            "dos_max": self.dos_max,
            "integrated_dos_present": self.integrated_dos_present,
            "data_columns": list(self.data_columns),
            "data_file": self.data_file,
            "issues_count": len(self.issues),
        }


def parse_dos_output(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
    data_file: str | Path | None = None,
) -> DosOutput:
    """Parse dos.x stdout text/path and optional .dos data file."""

    text, source_label = _read_text(text_or_path, source=source)
    lines = text.splitlines()

    scan = parse_qe_output_events(text, source=source_label)
    issues = list(scan.issues)

    program, version = _parse_program(lines)
    if program is None and _appears_dos_output(lines):
        program = "DOS"
    elif program is None:
        issues.append(
            QEOutputEvent(
                line_number=1,
                category="invalid_output",
                severity="warning",
                message="Output does not look like dos.x stdout.",
                source=source_label,
            )
        )

    job_done = any("JOB DONE" in line for line in lines)
    fermi_energy_ev = _parse_fermi(lines)
    energy_min_ev, energy_max_ev, _energy_delta_ev = _parse_energy_range(lines)
    energy_grid_count = _parse_data_grid_count(lines)

    data_columns: list[str] = []
    integrated_dos_present = False
    dos_min = None
    dos_max = None

    resolve_source = source if source is not None else (text_or_path if isinstance(text_or_path, Path) else None)
    resolved_data_file = _resolve_data_file(data_file, resolve_source)

    if resolved_data_file is not None:
        data_result = _parse_dos_data_file(resolved_data_file)
        if data_result["count"] is not None:
            energy_grid_count = data_result["count"]
        if energy_min_ev is None and data_result["energy_min"] is not None:
            energy_min_ev = data_result["energy_min"]
        if energy_max_ev is None and data_result["energy_max"] is not None:
            energy_max_ev = data_result["energy_max"]
        if data_result["dos_min"] is not None:
            dos_min = data_result["dos_min"]
        if data_result["dos_max"] is not None:
            dos_max = data_result["dos_max"]
        if data_result["columns"]:
            data_columns = data_result["columns"]
        integrated_dos_present = data_result["integrated_present"]

    if energy_grid_count is None and data_file is not None and resolved_data_file is None:
        issues.append(
            QEOutputEvent(
                line_number=1,
                category="file_not_found",
                severity="error",
                message=f"DOS data file not found: {data_file!s}",
                source=source_label,
            )
        )

    if not job_done and _appears_dos_output(lines):
        issues.append(
            QEOutputEvent(
                line_number=_last_content_line(lines),
                category="truncated_output",
                severity="error",
                message="DOS output did not reach JOB DONE.",
                source=source_label,
            )
        )

    if job_done and energy_grid_count is None and data_file is None:
        # Best effort: keep as warning-level signal rather than hard failure.
        issues.append(
            QEOutputEvent(
                line_number=1,
                category="warning",
                severity="warning",
                message="DOS output appears complete but no DOS data source was supplied.",
                source=source_label,
            )
        )

    if resolved_data_file is not None:
        data_file_value: str | None = str(resolved_data_file)
    elif data_file is not None:
        data_file_value = str(data_file)
    else:
        data_file_value = None

    return DosOutput(
        program=program,
        version=version,
        issues=issues,
        source=source_label,
        job_done=job_done,
        fermi_energy_ev=fermi_energy_ev,
        energy_grid_count=energy_grid_count,
        energy_min_ev=energy_min_ev,
        energy_max_ev=energy_max_ev,
        dos_min=dos_min,
        dos_max=dos_max,
        integrated_dos_present=integrated_dos_present,
        data_columns=data_columns,
        data_file=data_file_value,
    )


def _read_text(text_or_path: str | Path, *, source: str | Path | None) -> tuple[str, str]:
    if isinstance(text_or_path, Path):
        return text_or_path.read_text(encoding="utf-8", errors="replace"), _source_label(
            source if source is not None else text_or_path
        )
    return text_or_path, _source_label(source if source is not None else "text")


def _source_label(value: str | Path | None) -> str:
    if value is None:
        return "text"
    if isinstance(value, Path):
        return value.name
    text = str(value)
    if "/" in text or "\\" in text:
        normalized = text.replace("\\", "/")
        return normalized.rsplit("/", 1)[-1]
    return text


def _parse_program(lines: list[str]) -> tuple[str | None, str | None]:
    for line in lines:
        line_strip = line.strip()
        if "Program" not in line_strip:
            continue
        m = re.search(r"Program\s+([A-Za-z0-9_.-]+)\s+v\.?([\w.]+)", line_strip, re.IGNORECASE)
        if m:
            return m.group(1).upper(), m.group(2)
        if line_strip.upper().startswith("PROGRAM") and "DOS" in line_strip.upper():
            return "DOS", None
    return None, None


def _appears_dos_output(lines: list[str]) -> bool:
    for line in lines:
        if "dos.x" in line.lower() or "program dos" in line.lower() or "dos output" in line.lower():
            return True
        if line.startswith(" E(") or "Emin" in line and "Emax" in line:
            return True
    return False


def _parse_fermi(lines: list[str]) -> float | None:
    for line in lines:
        if "fermi" not in line.lower():
            continue
        m = re.search(rf"({_FLOAT_RE})", line, re.IGNORECASE)
        if m:
            return _to_float(m.group(1))
    return None


def _parse_energy_range(lines: list[str]) -> tuple[float | None, float | None, float | None]:
    for line in lines:
        if "Emin" not in line or "Emax" not in line:
            continue
        m = re.search(
            rf"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?)\s+"
            rf"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?)\s+"
            rf"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?)",
            line,
        )
        if m:
            return _to_float(m.group(1)), _to_float(m.group(2)), _to_float(m.group(3))
    return None, None, None


def _parse_data_grid_count(lines: list[str]) -> int | None:
    patterns = (
        re.compile(r"(?:number\s+of\s+)?points\s*[:=]\s*(\d+)", re.IGNORECASE),
        re.compile(r"n\s*points\s*[:=]\s*(\d+)", re.IGNORECASE),
        re.compile(r"n\s*points\s*=\s*(\d+)", re.IGNORECASE),
    )
    for line in lines:
        for pattern in patterns:
            m = pattern.search(line)
            if m:
                value = int(m.group(1))
                if value >= 0:
                    return value
    return None


def _to_float(value: str) -> float | None:
    try:
        return float(value.replace("D", "E").replace("d", "E"))
    except ValueError:
        return None


def _resolve_data_file(
    data_file: str | Path | None,
    source: str | Path | None,
) -> Path | None:
    if data_file is None:
        return None

    candidate = Path(data_file)
    if not candidate.is_absolute():
        candidate = Path(data_file)
    if candidate.is_file():
        return candidate

    if source is not None and source != "text":
        source_path = Path(source)
        if source_path.exists():
            candidate2 = source_path.parent / candidate
            if candidate2.is_file():
                return candidate2

    return None


def _parse_dos_data_file(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {
            "count": None,
            "energy_min": None,
            "energy_max": None,
            "dos_min": None,
            "dos_max": None,
            "columns": [],
            "integrated_present": False,
        }

    rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
    energy_values: list[float] = []
    dos_values: list[float] = []
    columns: list[str] = []
    integrated_present = False

    for line in rows:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not columns and _is_header_like(stripped):
            parts = stripped.split()
            if all(part.lower().isalpha() for part in parts):
                columns = parts
            continue

        try:
            parts = [float(part.replace("D", "E").replace("d", "E")) for part in stripped.split()]
        except ValueError:
            continue
        if len(parts) >= 2:
            energy_values.append(parts[0])
            dos_values.append(parts[1])
            if len(parts) >= 3:
                integrated_present = True

    if not columns and dos_values:
        columns = ["energy_ev", "dos", "int_dos"]

    return {
        "count": len(dos_values),
        "energy_min": min(energy_values) if energy_values else None,
        "energy_max": max(energy_values) if energy_values else None,
        "dos_min": min(dos_values) if dos_values else None,
        "dos_max": max(dos_values) if dos_values else None,
        "columns": columns,
        "integrated_present": integrated_present,
    }


def _is_header_like(line: str) -> bool:
    lower = line.lower()
    return "energy" in lower and ("dos" in lower or "int" in lower)


def _last_content_line(lines: list[str]) -> int:
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip():
            return index + 1
    return 1


__all__ = [
    "DosOutput",
    "parse_dos_output",
]
