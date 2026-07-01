"""Parse Quantum ESPRESSO pp.x stdout and optional post-processing artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from vibedft.calculator.qe.common import QEOutputEvent, parse_qe_output_events


_FLOAT_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"


@dataclass(frozen=True)
class PpOutput:
    """Structured pp.x parse artifact."""

    program: str | None
    version: str | None
    source: str
    issues: list[QEOutputEvent]
    job_done: bool
    plot_num: int | None
    field_kind: str
    output_format: str | None
    output_files: list[str]
    existing_output_files: list[str]
    nonempty_output_files: list[str]
    data_file_count: int
    data_sample_count: int | None
    data_min: float | None
    data_max: float | None
    data_columns: list[str]
    artifact_extensions: list[str]
    stdout_output_hints: list[str]

    def to_schema(self) -> dict[str, object]:
        return {
            "program": self.program,
            "version": self.version,
            "source": self.source,
            "job_done": self.job_done,
            "plot_num": self.plot_num,
            "field_kind": self.field_kind,
            "output_format": self.output_format,
            "output_files": list(self.output_files),
            "existing_output_files": list(self.existing_output_files),
            "nonempty_output_files": list(self.nonempty_output_files),
            "data_file_count": self.data_file_count,
            "data_sample_count": self.data_sample_count,
            "data_min": self.data_min,
            "data_max": self.data_max,
            "data_columns": list(self.data_columns),
            "artifact_extensions": list(self.artifact_extensions),
            "stdout_output_hints": list(self.stdout_output_hints),
            "issues_count": len(self.issues),
        }


def parse_pp_output(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
    data_files: list[str | Path] | None = None,
) -> PpOutput:
    """Parse pp.x stdout text/path and optional generated data artifacts."""

    text, source_label, source_path = _load_text_and_source(text_or_path, source=source)
    lines = text.splitlines()

    scan = parse_qe_output_events(text, source=source_label)
    issues = list(scan.issues)

    program, version = _parse_program(lines)
    pp_markers_present = _appears_pp_output(lines)
    if program is None and pp_markers_present:
        program = "PP"
    elif program is None:
        issues.append(
            QEOutputEvent(
                line_number=1,
                category="invalid_output",
                severity="warning",
                message="Output does not look like pp.x stdout.",
                source=source_label,
            )
        )

    job_done = any("JOB DONE" in line for line in lines)
    plot_num = _parse_plot_num(lines)
    field_kind = _infer_field_kind(text, plot_num)
    stdout_output_hints = _parse_output_hints(lines)

    resolved_artifacts = _resolve_artifacts(
        stdout_output_hints=stdout_output_hints,
        data_files=data_files,
        source_path=source_path,
    )
    output_files = _unique(
        [str(item) for item in stdout_output_hints]
        + [str(item) for item in (data_files or [])]
    )

    existing_output_files: list[str] = []
    nonempty_output_files: list[str] = []
    artifact_extensions: set[str] = set()
    numeric_results: list[dict[str, object]] = []

    explicit_paths = [Path(item) for item in (data_files or [])]
    for explicit_path in explicit_paths:
        if not explicit_path.is_file():
            issues.append(
                QEOutputEvent(
                    line_number=1,
                    category="file_not_found",
                    severity="error",
                    message=f"pp.x data file not found: {explicit_path}",
                    source=source_label,
                )
            )

    for artifact in resolved_artifacts:
        artifact_text = artifact.as_posix()
        suffix = artifact.suffix.lower()
        if suffix:
            artifact_extensions.add(suffix)
        if artifact.is_file():
            existing_output_files.append(artifact_text)
            try:
                size = artifact.stat().st_size
            except OSError:
                size = 0
            if size > 0:
                nonempty_output_files.append(artifact_text)
                numeric_result = _parse_numeric_artifact(artifact)
                if numeric_result is not None:
                    numeric_results.append(numeric_result)
            else:
                issues.append(
                    QEOutputEvent(
                        line_number=1,
                        category="empty_artifact",
                        severity="warning",
                        message=f"pp.x artifact is empty: {artifact}",
                        source=source_label,
                    )
                )
        elif artifact_text in stdout_output_hints:
            issues.append(
                QEOutputEvent(
                    line_number=1,
                    category="artifact_missing",
                    severity="warning",
                    message=f"pp.x artifact hint could not be resolved: {artifact_text}",
                    source=source_label,
                )
            )

    if job_done and not resolved_artifacts:
        issues.append(
            QEOutputEvent(
                line_number=1,
                category="artifact_untracked",
                severity="warning",
                message="pp.x output reached JOB DONE but no output artifact was provided or detected.",
                source=source_label,
            )
        )

    if not job_done and (program == "PP" or pp_markers_present):
        issues.append(
            QEOutputEvent(
                line_number=_last_content_line(lines),
                category="truncated_output",
                severity="error",
                message="pp.x output did not reach JOB DONE.",
                source=source_label,
            )
        )

    data_sample_count, data_min, data_max, data_columns = _merge_numeric_results(numeric_results)
    output_format = _infer_output_format(output_files, artifact_extensions)

    return PpOutput(
        program=program,
        version=version,
        source=source_label,
        issues=issues,
        job_done=job_done,
        plot_num=plot_num,
        field_kind=field_kind,
        output_format=output_format,
        output_files=output_files,
        existing_output_files=_unique(existing_output_files),
        nonempty_output_files=_unique(nonempty_output_files),
        data_file_count=len(resolved_artifacts),
        data_sample_count=data_sample_count,
        data_min=data_min,
        data_max=data_max,
        data_columns=data_columns,
        artifact_extensions=sorted(artifact_extensions),
        stdout_output_hints=stdout_output_hints,
    )


def _load_text_and_source(
    text_or_path: str | Path,
    *,
    source: str | Path | None,
) -> tuple[str, str, Path | None]:
    if isinstance(text_or_path, Path):
        return (
            text_or_path.read_text(encoding="utf-8", errors="replace"),
            _source_label(source if source is not None else text_or_path),
            text_or_path,
        )

    if _looks_like_existing_file(text_or_path):
        path = Path(text_or_path)
        return (
            path.read_text(encoding="utf-8", errors="replace"),
            _source_label(source if source is not None else path),
            path,
        )

    return text_or_path, _source_label(source if source is not None else "text"), None


def _looks_like_existing_file(value: str) -> bool:
    if "\n" in value or "\r" in value:
        return False
    try:
        return Path(value).is_file()
    except OSError:
        return False


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
        match = re.search(r"Program\s+([A-Za-z0-9_.-]+)\s+v\.?([\S]+)", line_strip, re.IGNORECASE)
        if match:
            return match.group(1).upper().rstrip("."), match.group(2)
        if line_strip.upper().startswith("PROGRAM") and "PP" in line_strip.upper():
            return "PP", None
    return None, None


def _appears_pp_output(lines: list[str]) -> bool:
    for line in lines:
        lower = line.lower()
        if "pp.x" in lower or "program pp" in lower:
            return True
        if "plot_num" in lower or "fileout" in lower or "writing data to" in lower:
            return True
    return False


def _parse_plot_num(lines: list[str]) -> int | None:
    for line in lines:
        match = re.search(r"\bplot_num\b\s*=\s*([+-]?\d+)", line, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def _infer_field_kind(text: str, plot_num: int | None) -> str:
    lower = text.lower()
    if re.search(r"\bspin\b|\bmagneti[sz]ation\b", lower):
        return "spin_density"
    if re.search(r"\bpotential\b|\bv_bare\b|\bv_h\b|\bv_xc\b", lower):
        return "potential"
    if re.search(r"\bcharge\b|\brho\b|\bdensity\b", lower):
        return "charge_density"
    if plot_num in {0, 1}:
        return "generic_field"
    return "unknown_field"


def _parse_output_hints(lines: list[str]) -> list[str]:
    hints: list[str] = []
    patterns = (
        re.compile(r"\bWriting\s+data\s+to\s+['\"]?([^'\"\s,;]+)", re.IGNORECASE),
        re.compile(r"\bfileout\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE),
        re.compile(r"\bfileout\s*=\s*([^'\"]\S+)", re.IGNORECASE),
        re.compile(r"\boutput\s+file\s*(?:is|=|:)?\s*['\"]?([^'\"\s,;]+)", re.IGNORECASE),
    )
    for line in lines:
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                hints.append(match.group(1).strip())
                break
    return _unique(hints)


def _resolve_artifacts(
    *,
    stdout_output_hints: list[str],
    data_files: list[str | Path] | None,
    source_path: Path | None,
) -> list[Path]:
    artifacts: list[Path] = []
    explicit_paths = [Path(item) for item in (data_files or [])]
    artifacts.extend(explicit_paths)

    source_parent = source_path.parent if source_path is not None else None
    for hint in stdout_output_hints:
        hint_path = Path(hint)
        resolved = hint_path
        if not hint_path.is_file() and source_parent is not None:
            candidate = source_parent / hint_path
            if candidate.is_file():
                resolved = candidate
        if not resolved.is_file():
            for explicit_path in explicit_paths:
                if explicit_path.name == hint_path.name:
                    resolved = explicit_path
                    break
        artifacts.append(resolved)

    return _unique_paths(artifacts)


def _parse_numeric_artifact(path: Path) -> dict[str, object] | None:
    if path.suffix.lower() in {".cube", ".xsf", ".bxsf"}:
        return None

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    columns: list[str] = []
    values: list[float] = []
    row_count = 0
    inferred_width = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("!"):
            candidate_columns = stripped.lstrip("#!").strip().split()
            if candidate_columns and not all(_can_float(item) for item in candidate_columns):
                columns = candidate_columns
            continue

        parts = re.split(r"[\s,]+", stripped)
        numeric_values = [_to_float(part) for part in parts if part]
        numeric_values = [value for value in numeric_values if value is not None]
        if not numeric_values:
            continue
        row_count += 1
        inferred_width = max(inferred_width, len(numeric_values))
        values.extend(numeric_values)

    if row_count <= 0:
        return None

    if not columns and inferred_width > 0:
        columns = [f"col{index}" for index in range(1, inferred_width + 1)]

    return {
        "count": row_count,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "columns": columns,
    }


def _merge_numeric_results(
    numeric_results: list[dict[str, object]],
) -> tuple[int | None, float | None, float | None, list[str]]:
    if not numeric_results:
        return None, None, None, []

    sample_count = 0
    mins: list[float] = []
    maxes: list[float] = []
    columns: list[str] = []

    for result in numeric_results:
        count = result.get("count")
        if isinstance(count, int):
            sample_count += count
        min_value = result.get("min")
        max_value = result.get("max")
        if isinstance(min_value, float):
            mins.append(min_value)
        if isinstance(max_value, float):
            maxes.append(max_value)
        for column in result.get("columns", []):
            if isinstance(column, str) and column not in columns:
                columns.append(column)

    return (
        sample_count if sample_count > 0 else None,
        min(mins) if mins else None,
        max(maxes) if maxes else None,
        columns,
    )


def _infer_output_format(output_files: list[str], artifact_extensions: set[str]) -> str | None:
    if len(artifact_extensions) > 1:
        return "mixed"
    if len(artifact_extensions) == 1:
        ext = next(iter(artifact_extensions)).lstrip(".")
        if ext in {"dat", "txt", "out"}:
            return "text"
        return ext
    for output_file in output_files:
        suffix = Path(output_file).suffix.lower().lstrip(".")
        if suffix:
            return "text" if suffix in {"dat", "txt", "out"} else suffix
    return None


def _last_content_line(lines: list[str]) -> int:
    for index in range(len(lines), 0, -1):
        if lines[index - 1].strip():
            return index
    return 1


def _to_float(value: str) -> float | None:
    try:
        return float(value.replace("D", "E").replace("d", "E"))
    except ValueError:
        return None


def _can_float(value: str) -> bool:
    return _to_float(value) is not None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _unique_paths(values: list[Path]) -> list[Path]:
    unique: dict[str, Path] = {}
    for path in values:
        key = path.as_posix()
        if key not in unique:
            unique[key] = path
    return list(unique.values())


__all__ = ["PpOutput", "parse_pp_output"]
