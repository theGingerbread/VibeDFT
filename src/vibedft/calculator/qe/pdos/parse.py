"""Parse Quantum ESPRESSO projwfc.x output and optional PDOS data files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from vibedft.calculator.qe.common import QEOutputEvent, parse_qe_output_events

_FLOAT_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"

@dataclass(frozen=True)
class PdosOutput:
    """Structured PDOS parse artifact."""

    program: str | None
    version: str | None
    issues: list[QEOutputEvent]
    source: str

    job_done: bool
    projection_files: list[str]
    projection_file_count: int
    atom_projector_count: int
    orbital_channels: list[str]
    spin_channels: int | None
    fermi_energy_ev: float | None
    energy_grid_count: int | None
    energy_min_ev: float | None
    energy_max_ev: float | None
    pdos_total_present: bool

    def to_schema(self) -> dict[str, object]:
        return {
            "program": self.program,
            "version": self.version,
            "source": self.source,
            "job_done": self.job_done,
            "projection_files": list(self.projection_files),
            "projection_file_count": self.projection_file_count,
            "atom_projector_count": self.atom_projector_count,
            "orbital_channels": list(self.orbital_channels),
            "spin_channels": self.spin_channels,
            "fermi_energy_ev": self.fermi_energy_ev,
            "energy_grid_count": self.energy_grid_count,
            "energy_min_ev": self.energy_min_ev,
            "energy_max_ev": self.energy_max_ev,
            "pdos_total_present": self.pdos_total_present,
            "issues_count": len(self.issues),
        }


def parse_pdos_output(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
    pdos_files: list[str | Path] | None = None,
) -> PdosOutput:
    """Parse projwfc.x stdout text/path and optional PDOS data files."""

    scan = parse_qe_output_events(text_or_path, source=source)
    source_label = scan.source
    raw_text = _read_text(text_or_path)
    lines = raw_text.splitlines()

    issues = list(scan.issues)
    program, version = _parse_program(lines)
    if program is None:
        program = _infer_legacy_program(raw_text)
        if not program:
            issues.append(
                QEOutputEvent(
                    line_number=1,
                    category="invalid_output",
                    severity="warning",
                    message="Output does not look like projwfc.x/PDOS stdout.",
                    source=source_label,
                )
            )

    job_done = any("JOB DONE" in line for line in lines)

    fermi_energy_ev = _parse_fermi(lines)
    projection_files: list[str] = []
    orbital_channels: set[str] = set()
    atom_indices: set[int] = set()
    spin_channels = _parse_spin_channels(lines)

    if pdos_files:
        candidate_files = list(pdos_files)
    else:
        candidate_files = [path_str for path_str in _parse_projection_filenames(raw_text)]

    resolve_base: str | Path | None
    resolve_base = source if source is not None else (text_or_path if isinstance(text_or_path, Path) else None)

    for candidate in candidate_files:
        projection_files.append(str(candidate))

    projection_file_count = 0
    energy_grid_count: int | None = None
    energy_min_ev: float | None = None
    energy_max_ev: float | None = None
    pdos_total_present = False

    for projection_file in projection_files:
        resolved_file = _resolve_pdos_file(projection_file, base=resolve_base)
        file_issues, file_results = _parse_projection_file(resolved_file)
        issues.extend(file_issues)
        if file_results is None:
            continue

        projection_file_count += 1
        atom_indices.update(file_results["atoms"])
        orbital_channels.update(file_results["orbitals"])

        file_grid_count = file_results["count"]
        file_min = file_results["energy_min"]
        file_max = file_results["energy_max"]
        file_total_present = file_results["total_present"]
        file_has_fermi = file_results["has_fermi"]
        file_fermi = file_results["fermi"]

        if file_grid_count is not None and file_grid_count > 0:
            if energy_grid_count is None:
                energy_grid_count = file_grid_count
            else:
                energy_grid_count = max(energy_grid_count, file_grid_count)

        if file_min is not None:
            energy_min_ev = file_min if energy_min_ev is None else min(energy_min_ev, file_min)
        if file_max is not None:
            energy_max_ev = file_max if energy_max_ev is None else max(energy_max_ev, file_max)

        if file_total_present:
            pdos_total_present = True
        if file_has_fermi and fermi_energy_ev is None:
            fermi_energy_ev = file_fermi

    atom_projector_count = len(atom_indices)

    if not projection_files and not any("pdos" in line.lower() for line in lines):
        issues.append(
            QEOutputEvent(
                line_number=1,
                category="file_not_found",
                severity="error",
                message="No PDOS projection files were provided or detected.",
                source=source_label,
            )
        )

    if not job_done and projection_files:
        issues.append(
            QEOutputEvent(
                line_number=1,
                category="truncated_output",
                severity="error",
                message="PDOS output did not reach JOB DONE.",
                source=source_label,
            )
        )

    return PdosOutput(
        program=program,
        version=version,
        issues=issues,
        source=source_label,
        job_done=job_done,
        projection_files=projection_files,
        projection_file_count=projection_file_count,
        atom_projector_count=atom_projector_count,
        orbital_channels=sorted(orbital_channels),
        spin_channels=spin_channels,
        fermi_energy_ev=fermi_energy_ev,
        energy_grid_count=energy_grid_count,
        energy_min_ev=energy_min_ev,
        energy_max_ev=energy_max_ev,
        pdos_total_present=pdos_total_present,
    )


def _read_text(text_or_path: str | Path) -> str:
    if isinstance(text_or_path, Path):
        return text_or_path.read_text(encoding="utf-8", errors="replace")
    return text_or_path


def _parse_program(lines: list[str]) -> tuple[str | None, str | None]:
    for line in lines:
        line_strip = line.strip()
        if "Program" not in line_strip:
            continue
        m = re.search(r"Program\s+([A-Za-z0-9_.-]+)\s+v\.?([\S]+)", line_strip, re.IGNORECASE)
        if m:
            return m.group(1).upper(), m.group(2)
    return None, None


def _infer_legacy_program(raw_text: str) -> str | None:
    if "PROJWFC" in raw_text.upper():
        return "PROJWFC"
    if "projwfc" in raw_text.lower():
        return "PROJWFC"
    return None


def _parse_fermi(lines: list[str]) -> float | None:
    for line in lines:
        if "fermi" not in line.lower():
            continue
        m = re.search(
            rf"fermi(?:\s+energy)?(?:\s+(?:is|=|:)?\s*)({_FLOAT_RE})",
            line,
            re.IGNORECASE,
        )
        if m:
            return _to_float(m.group(1))
    return None


def _parse_spin_channels(lines: list[str]) -> int | None:
    for line in lines:
        lower = line.lower()
        if "spin" not in lower:
            continue
        if "lsda" in lower or "spin-polarized" in lower or "nspin" in lower:
            if any(token in lower for token in (" 2", " 2.0", "nspin  = 2", "nspin=2")):
                return 2
        if "lsda" in lower and ("polar" in lower or "spin" in lower):
            return 2
    if any("2" in line.lower() and "spin" in line.lower() for line in lines):
        return 2
    if any("up" in line.lower() and "down" in line.lower() for line in lines):
        return 2
    return 1 if any("spin" in line.lower() for line in lines) else None


def _parse_projection_filenames(raw_text: str) -> list[str]:
    projection_files: list[str] = []
    for line in raw_text.splitlines():
        if "pdos" not in line.lower():
            continue
        for match in re.findall(r"(\S+pdos[^\s,;]*)", line):
            projection_files.append(match.strip("'\""))
    return projection_files


def _resolve_pdos_file(
    path_text: str,
    *,
    base: str | Path | None,
) -> Path:
    candidate = Path(path_text)
    if candidate.is_file():
        return candidate
    if base is not None and base != "text":
        base_path = Path(base)
        if base_path.exists():
            candidate_with_base = base_path.parent / candidate
            if candidate_with_base.is_file():
                return candidate_with_base
    return candidate


def _parse_projection_file(path: Path) -> tuple[list[QEOutputEvent], dict[str, object] | None]:
    issues: list[QEOutputEvent] = []
    if not path.is_file():
        issues.append(
            QEOutputEvent(
                line_number=1,
                category="file_not_found",
                severity="error",
                message=f"PDOS file not found: {path}",
                source=path.as_posix(),
            )
        )
        return issues, None

    atom_ids: set[int] = set()
    orbitals: set[str] = set()
    energy_values: list[float] = []
    energies_present = False
    has_fermi = False
    fermi: float | None = None

    atom_match = re.search(r"pdos_atm#(\d+)", path.name, re.IGNORECASE)
    if atom_match:
        try:
            atom_ids.add(int(atom_match.group(1)))
        except ValueError:
            pass

    orbital_match = re.search(r"wfc#\d+\(([^)]+)\)", path.name, re.IGNORECASE)
    if orbital_match:
        orbitals.add(orbital_match.group(1))

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "EFermi" in stripped or "Fermi" in stripped:
            m = re.search(
                r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?|[+-]?\d+\.?)",
                stripped,
            )
            if m:
                fermi = _to_float(m.group(1))
                has_fermi = True
            continue

        parts = stripped.split()
        if len(parts) < 2:
            continue
        try:
            value = float(parts[0].replace("D", "E").replace("d", "E"))
        except ValueError:
            continue
        energy_values.append(value)
        energies_present = True

    energy_min = min(energy_values) if energy_values else None
    energy_max = max(energy_values) if energy_values else None
    energy_count = len(energy_values)

    return issues, {
        "atoms": atom_ids,
        "orbitals": orbitals,
        "count": energy_count,
        "energy_min": energy_min,
        "energy_max": energy_max,
        "total_present": energies_present,
        "has_fermi": has_fermi,
        "fermi": fermi,
    }


def _to_float(value: str) -> float | None:
    try:
        return float(value.replace("D", "E").replace("d", "E"))
    except ValueError:
        return None


__all__ = ["PdosOutput", "parse_pdos_output"]
