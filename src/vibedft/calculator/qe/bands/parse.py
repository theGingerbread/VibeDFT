"""Parse Quantum ESPRESSO bands task outputs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vibedft.calculator.qe.common import QEOutputEvent, parse_qe_output_events


_FLOAT_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_PROGRAM_RE = re.compile(r"\bProgram\s+([A-Za-z0-9_.-]+)\s+v\.?(?:\s*([\w.]+))?", re.IGNORECASE)
_HEADER_RE = re.compile(r"&plot\s+nbnd\s*=\s*(\d+)\s*,\s*nks\s*=\s*(\d+)", re.IGNORECASE)
_KPOINT_RE = re.compile(r"^\s{8,}(.+)")
_FERMI_RE = re.compile(rf"the\s+fermi\s+energy\s+is\s+({_FLOAT_RE})\s*eV", re.IGNORECASE)
_REFERENCE_RE = re.compile(rf"reference\s+energy\s*=\s*({_FLOAT_RE})", re.IGNORECASE)
_BANDS_COUNT_RE = re.compile(r"nbnd\s*=\s*(\d+)", re.IGNORECASE)
_KPOINT_COUNT_RE = re.compile(r"nks\s*=\s*(\d+)", re.IGNORECASE)
_JOB_DONE_RE = re.compile(r"\bJOB\s+DONE\b", re.IGNORECASE)
_HS_LABEL_SECTION_RE = re.compile(r"high\s*[-_]?sym\b", re.IGNORECASE)
_HS_LABEL_TOKEN_RE = re.compile(r"\(([^()]+)\)")


@dataclass(frozen=True)
class BandsOutput:
    """Structured bands task summary."""

    program: str | None
    version: str | None
    issues: list[QEOutputEvent]
    source: str

    job_done: bool
    fermi_energy_ev: float | None
    reference_energy_ev: float | None
    k_point_count: int | None
    band_count: int | None
    data_file: str | None
    band_data_present: bool
    eigenvalue_row_count: int | None
    energy_min_ev: float | None
    energy_max_ev: float | None
    high_symmetry_labels: list[str]
    k_point_path: list[float]
    energy_samples: tuple[float, ...]

    def to_schema(self) -> dict[str, Any]:
        return {
            "program": self.program,
            "version": self.version,
            "source": self.source,
            "job_done": self.job_done,
            "fermi_energy_ev": self.fermi_energy_ev,
            "reference_energy_ev": self.reference_energy_ev,
            "k_point_count": self.k_point_count,
            "band_count": self.band_count,
            "data_file": self.data_file,
            "band_data_present": self.band_data_present,
            "eigenvalue_row_count": self.eigenvalue_row_count,
            "energy_min_ev": self.energy_min_ev,
            "energy_max_ev": self.energy_max_ev,
            "high_symmetry_labels": list(self.high_symmetry_labels),
            "energy_samples": len(self.energy_samples),
            "issues_count": len(self.issues),
        }


def parse_bands_output(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
    data_file: str | Path | None = None,
) -> BandsOutput:
    """Parse QE bands stdout text/path with optional bands data file."""

    text, source_label = _read_text(text_or_path, source=source)
    lines = text.splitlines()
    scan = parse_qe_output_events(text, source=source_label)
    issues = list(scan.issues)

    program, version = _parse_program(lines, source_label)
    if program is None:
        program = "BANDS"

    job_done = bool(_JOB_DONE_RE.search(text))
    if not job_done and not issues and _looks_like_bands_output(lines):
        issues.append(
            QEOutputEvent(
                line_number=_last_content_line(lines),
                category="truncated_output",
                severity="error",
                message="Bands output appears incomplete: no JOB DONE marker.",
                source=source_label,
            )
        )

    fermi_energy_ev = _parse_first_float(_FERMI_RE, lines)
    reference_energy_ev = _parse_first_float(_REFERENCE_RE, lines)

    k_point_count = _parse_int(_KPOINT_COUNT_RE, lines)
    band_count = _parse_int(_BANDS_COUNT_RE, lines)
    high_symmetry_labels = _parse_high_symmetry_labels(lines)
    k_point_path = _parse_k_point_path_from_stdout(lines)

    resolved_data_file = _resolve_data_file(data_file, source=source)
    if resolved_data_file is not None:
        parsed_data = _parse_bands_data_file(resolved_data_file)
        if parsed_data["issues"]:
            issues.extend(parsed_data["issues"])
        if band_count is None and parsed_data["band_count"] is not None:
            band_count = parsed_data["band_count"]
        if k_point_count is None and parsed_data["k_point_count"] is not None:
            k_point_count = parsed_data["k_point_count"]
    else:
        parsed_data = _empty_data_summary()

    data_file_label = str(resolved_data_file) if resolved_data_file is not None else (
        str(data_file) if data_file is not None else None
    )

    if data_file is not None and resolved_data_file is None:
        issues.append(
            QEOutputEvent(
                line_number=_last_content_line(lines),
                category="file_not_found",
                severity="error",
                message=f"Bands data file not found: {data_file}",
                source=source_label,
            )
        )

    band_data_present = parsed_data["band_data_present"]
    eigenvalue_row_count = parsed_data["eigenvalue_row_count"]
    energy_min_ev = parsed_data["energy_min_ev"]
    energy_max_ev = parsed_data["energy_max_ev"]
    energy_samples = parsed_data["energy_samples"]

    return BandsOutput(
        program=program,
        version=version,
        issues=issues,
        source=source_label,
        job_done=job_done,
        fermi_energy_ev=fermi_energy_ev,
        reference_energy_ev=reference_energy_ev,
        k_point_count=k_point_count,
        band_count=band_count,
        data_file=data_file_label,
        band_data_present=band_data_present,
        eigenvalue_row_count=eigenvalue_row_count,
        energy_min_ev=energy_min_ev,
        energy_max_ev=energy_max_ev,
        high_symmetry_labels=high_symmetry_labels,
        k_point_path=k_point_path,
        energy_samples=energy_samples,
    )


def _read_text(text_or_path: str | Path, *, source: str | Path | None) -> tuple[str, str]:
    if isinstance(text_or_path, Path):
        return (
            text_or_path.read_text(encoding="utf-8", errors="replace"),
            _source_label(source if source is not None else text_or_path),
        )
    candidate = Path(text_or_path)
    if "\n" not in text_or_path and candidate.is_file():
        return (
            candidate.read_text(encoding="utf-8", errors="replace"),
            _source_label(source if source is not None else candidate),
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


def _parse_program(lines: list[str], source: str) -> tuple[str | None, str | None]:
    for line in lines:
        match = _PROGRAM_RE.match(line.strip())
        if match:
            return match.group(1).upper(), match.group(2)
        if "Program" in line and "BANDS" in line.upper():
            return "BANDS", None
    if _looks_like_bands_output(lines):
        return "bands", None
    return None, None


def _parse_first_float(pattern: re.Pattern[str], lines: list[str]) -> float | None:
    for line in lines:
        match = pattern.search(line)
        if match:
            return _to_float(match.group(1))
    return None


def _parse_int(pattern: re.Pattern[str], lines: list[str]) -> int | None:
    for line in lines:
        match = pattern.search(line)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def _parse_high_symmetry_labels(lines: list[str]) -> list[str]:
    labels: list[str] = []
    for line in lines:
        if not _HS_LABEL_SECTION_RE.search(line):
            continue
        for token in _HS_LABEL_TOKEN_RE.findall(line):
            token_clean = token.strip()
            if token_clean:
                labels.append(token_clean)
    return labels


def _parse_k_point_path_from_stdout(lines: list[str]) -> list[float]:
    counts: list[float] = []
    for line in lines:
        if "k-point" in line.lower() and "path" in line.lower() and "=" in line:
            numbers = [float(value) for value in line.split() if _is_float(value)]
            if numbers:
                counts.extend(numbers)
    return counts[:3]


def _looks_like_bands_output(lines: list[str]) -> bool:
    for line in lines:
        normalized = line.lower()
        if normalized.startswith("&plot") or normalized.startswith("&plot"):
            return True
        if "&end" in normalized and "plot" in normalized:
            return True
    return any(_HEADER_RE.search(line) for line in lines)


def _is_float(value: str) -> bool:
    try:
        _to_float(value)
        return True
    except ValueError:
        return False


def _parse_bands_data_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _data_parse_result(
            band_count=None,
            k_point_count=None,
            eigenvalue_row_count=None,
            energy_min=None,
            energy_max=None,
            energy_samples=(),
            issues=[
                QEOutputEvent(
                    line_number=1,
                    category="file_not_found",
                    severity="error",
                    message=f"Bands data file not found: {path}",
                    source=path.name,
                )
            ],
        )

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    header_match = _HEADER_RE.search(text)
    header_band_count = int(header_match.group(1)) if header_match else None
    header_k_point_count = int(header_match.group(2)) if header_match else None

    energy_values: list[float] = []
    eigenvalue_row_count = 0
    parsed_k_points: list[tuple[float, float, float]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        header_match = _HEADER_RE.search(line)
        if header_match:
            i += 1
            continue

        k_match = _KPOINT_RE.match(line)
        if k_match:
            tokens = k_match.group(1).strip().split()
            if len(tokens) == 3 and all(_is_float(value) for value in tokens):
                try:
                    parsed_k_points.append(tuple(_to_float(value) for value in tokens))
                except ValueError:
                    pass
                i += 1
                values: list[float] = []
                while i < len(lines):
                    row_tokens = lines[i].strip().split()
                    if not row_tokens:
                        i += 1
                        continue
                    if len(row_tokens) == 3 and all(_is_float(value) for value in row_tokens):
                        # Next k-point or accidental coordinate line; stop value collection.
                        break
                    if all(_is_float(value) for value in row_tokens):
                        values.extend(_to_float(value) for value in row_tokens)
                        i += 1
                        continue
                    break
                if values:
                    eigenvalue_row_count += len(values)
                    energy_values.extend(values)
                continue
        i += 1

    k_point_count = len(parsed_k_points)
    band_count = header_band_count
    values_per_k = _infer_band_count_from_rows(energy_values, k_point_count)
    if band_count is None and values_per_k:
        band_count = values_per_k

    issues: list[QEOutputEvent] = []
    if header_band_count is not None and header_band_count <= 0:
        issues.append(
            QEOutputEvent(
                line_number=1,
                category="invalid_output",
                severity="warning",
                message="Bands data header reports non-positive number of bands.",
                source=path.name,
            )
        )
    if k_point_count == 0 and header_k_point_count and header_k_point_count > 0:
        issues.append(
            QEOutputEvent(
                line_number=1,
                category="warning",
                severity="warning",
                message="Bands data file declares k-point count but no coordinate section was parsed.",
                source=path.name,
            )
        )

    data_energies = tuple(energy_values)
    return _data_parse_result(
        band_count=band_count,
        k_point_count=k_point_count or header_k_point_count,
        eigenvalue_row_count=eigenvalue_row_count,
        energy_min=min(data_energies) if data_energies else None,
        energy_max=max(data_energies) if data_energies else None,
        energy_samples=data_energies,
        issues=issues,
    )


def _infer_band_count_from_rows(energy_values: list[float], k_point_count: int) -> int | None:
    if k_point_count <= 0 or not energy_values:
        return None
    if len(energy_values) % k_point_count != 0:
        return None
    quotient, remainder = divmod(len(energy_values), k_point_count)
    if remainder == 0:
        return quotient
    return None


def _data_parse_result(
    *,
    band_count: int | None,
    k_point_count: int | None,
    eigenvalue_row_count: int | None,
    energy_min: float | None,
    energy_max: float | None,
    energy_samples: tuple[float, ...],
    issues: list[QEOutputEvent],
) -> dict[str, Any]:
    return {
        "band_count": band_count,
        "k_point_count": k_point_count,
        "eigenvalue_row_count": eigenvalue_row_count,
        "energy_min_ev": energy_min,
        "energy_max_ev": energy_max,
        "energy_samples": energy_samples,
        "band_data_present": bool(energy_samples),
        "issues": issues,
    }


def _empty_data_summary() -> dict[str, Any]:
    return _data_parse_result(
        band_count=None,
        k_point_count=None,
        eigenvalue_row_count=None,
        energy_min=None,
        energy_max=None,
        energy_samples=(),
        issues=[],
    )


def _resolve_data_file(data_file: str | Path | None, *, source: str | Path | None = None) -> Path | None:
    if data_file is None:
        return None

    candidate = Path(data_file)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    if source is not None:
        base = Path(source)
        if base.parent.exists():
            merged = base.parent / candidate
            if merged.exists():
                return merged

    if candidate.exists():
        return candidate
    return None


def _to_float(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "E"))


def _last_content_line(lines: list[str]) -> int:
    if not lines:
        return 1
    return max(1, len(lines))


__all__ = ["BandsOutput", "parse_bands_output"]
