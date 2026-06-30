"""AIMD stability analyzer — temperature drift, energy conservation, structure integrity."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibedft.properties.base import PropertyResult
from vibedft.research.models import (
    AnalysisResult,
    ArtifactType,
    EvidenceRef,
    PhysicsDescriptor,
    ReliabilityLevel,
    ResultStatus,
)


@dataclass
class MDAtom:
    """One atom in an XYZ trajectory frame."""

    element: str
    x: float
    y: float
    z: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "x": self.x,
            "y": self.y,
            "z": self.z,
        }


@dataclass
class MDTrajectory:
    """Parsed XYZ trajectory frames."""

    frames: list[list[MDAtom]] = field(default_factory=list)
    source_file: str = ""
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return bool(self.frames)

    @property
    def n_frames(self) -> int:
        return len(self.frames)

    @property
    def n_atoms(self) -> int:
        return len(self.frames[0]) if self.frames else 0

    def to_summary(self) -> dict[str, Any]:
        return {
            "n_frames": self.n_frames,
            "n_atoms": self.n_atoms,
            "parse_errors": list(self.parse_errors),
        }


def analyze_aimd(case_dir: Path) -> PropertyResult:
    """Analyze AIMD output for thermal stability.

    Expected files:
      - md.out (QE pw.x MD output)
      - *.pos (trajectory files)
      - *.cel (cell trajectory)
    """
    result = PropertyResult(property_name="aimd_stability")

    md_files = list(case_dir.rglob("md.out")) + list(case_dir.rglob("*md*.out"))
    if not md_files:
        result.status = "missing"
        result.insights.append("No MD output file found — run pw.x with calculation='md'.")
        return result

    for fp in md_files[:1]:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        temperatures: list[float] = []
        energies: list[float] = []
        times: list[float] = []

        import re
        for line in text.splitlines():
            # Temperature: "temperature   =   300.0 K"
            m_temp = re.search(r"temperature\s*=\s*([\d.]+)", line)
            if m_temp:
                temperatures.append(float(m_temp.group(1)))
            # Total energy: "!    total energy  =  -100.0 Ry"
            m_energy = re.search(r"!\s+total energy\s+=\s+([-\d.]+)\s+Ry", line)
            if m_energy:
                energies.append(float(m_energy.group(1)))

        if not temperatures:
            result.insights.append("No temperature traces found in MD output.")
            return result

        n_steps = len(temperatures)
        t_mean = sum(temperatures) / n_steps
        t_std = _std(temperatures)
        t_drift = temperatures[-1] - temperatures[0] if n_steps > 1 else 0.0

        e_drift = 0.0
        if energies:
            e_drift_per_step = (energies[-1] - energies[0]) / max(len(energies), 1)
            e_drift = abs(e_drift_per_step * len(energies))

        # Stability assessment
        is_stable = abs(t_drift) < 50 and t_std < 100
        is_melting = t_drift > 200
        is_energy_conserving = e_drift < 0.01 if energies else None

        result.status = "ok"
        result.data = {
            "n_steps": n_steps,
            "temperature_mean_K": round(t_mean, 1),
            "temperature_std_K": round(t_std, 1),
            "temperature_drift_K": round(t_drift, 1),
            "energy_drift_Ry": round(e_drift, 6) if energies else None,
            "is_stable": is_stable,
            "is_melting": is_melting,
            "is_energy_conserving": is_energy_conserving,
        }
        result.source_files.append(str(fp))

        if is_melting:
            result.insights.append(
                f"⚠ Possible melting: T drift = {t_drift:.0f} K over {n_steps} steps."
            )
        elif is_stable:
            result.insights.append(
                f"Thermally stable: T_mean = {t_mean:.0f} K, σ = {t_std:.0f} K "
                f"over {n_steps} steps."
            )
        else:
            result.insights.append(
                f"Moderate temperature fluctuations: T_drift = {t_drift:.0f} K, "
                f"σ = {t_std:.0f} K. Consider longer equilibration."
            )

        if is_energy_conserving is False:
            result.insights.append(
                f"Energy drift detected ({e_drift:.4f} Ry) — check timestep and SCF convergence."
            )

    return result


def _std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    return (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5


def parse_temperature_series(filepath: Path | str) -> list[float]:
    """Parse temperature values from QE ``md.out`` or ``T_K.dat`` files."""

    path = Path(filepath)
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    temperatures: list[float] = []
    for line in text.splitlines():
        md_match = re.search(r"temperature\s*=\s*([-+]?\d+(?:\.\d+)?)", line, re.IGNORECASE)
        if md_match:
            temperatures.append(float(md_match.group(1)))
            continue
        values = _line_float_values(line)
        if len(values) >= 2:
            temperatures.append(values[-1])
    return temperatures


def parse_energy_series(filepath: Path | str) -> list[float]:
    """Parse total-energy values from QE ``md.out`` or ``Etot_Ry.dat`` files."""

    path = Path(filepath)
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    energies: list[float] = []
    for line in text.splitlines():
        md_match = re.search(
            r"!\s*total energy\s*=\s*([-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?)\s+Ry",
            line,
            re.IGNORECASE,
        )
        if md_match:
            energies.append(float(md_match.group(1)))
            continue
        values = _line_float_values(line)
        if len(values) >= 2:
            energies.append(values[-1])
    return energies


def parse_xyz_trajectory(filepath: Path | str) -> MDTrajectory:
    """Parse a simple multi-frame XYZ trajectory."""

    path = Path(filepath)
    trajectory = MDTrajectory(source_file=str(path))
    if not path.is_file():
        trajectory.parse_errors.append(f"trajectory not found: {path}")
        return trajectory

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        try:
            n_atoms = int(line)
        except ValueError:
            trajectory.parse_errors.append(f"invalid XYZ atom-count line: {line}")
            break
        if i + 1 + n_atoms >= len(lines) + 1:
            trajectory.parse_errors.append("incomplete XYZ frame")
            break
        frame: list[MDAtom] = []
        for atom_line in lines[i + 2 : i + 2 + n_atoms]:
            parts = atom_line.split()
            if len(parts) < 4:
                trajectory.parse_errors.append(f"invalid XYZ atom row: {atom_line}")
                continue
            try:
                frame.append(
                    MDAtom(
                        element=parts[0],
                        x=float(parts[1]),
                        y=float(parts[2]),
                        z=float(parts[3]),
                    )
                )
            except ValueError:
                trajectory.parse_errors.append(f"invalid XYZ coordinate row: {atom_line}")
        if len(frame) == n_atoms:
            trajectory.frames.append(frame)
        i += n_atoms + 2
    return trajectory


def analyze_md_stability(case_dir: Path | str) -> AnalysisResult:
    """Build evidence-backed thermal stability descriptors from QE MD artifacts."""

    root = Path(case_dir)
    temperature_path = _first_existing([
        *root.rglob("T_K.dat"),
        *root.rglob("md.out"),
        *root.rglob("*md*.out"),
    ])
    energy_path = _first_existing([
        *root.rglob("Etot_Ry.dat"),
        *root.rglob("md.out"),
        *root.rglob("*md*.out"),
    ])
    stress_path = _first_existing(root.rglob("stress_Rybohr3.dat"))
    trajectory_path = _first_existing(root.rglob("traj.xyz"))
    cell_path = _first_existing(root.rglob("cell_vectors.dat"))

    temperatures = parse_temperature_series(temperature_path) if temperature_path else []
    energies = parse_energy_series(energy_path) if energy_path else []
    trajectory = parse_xyz_trajectory(trajectory_path) if trajectory_path else MDTrajectory()

    warnings: list[str] = []
    blockers: list[str] = []
    evidence: list[EvidenceRef] = []

    if temperature_path is None or not temperatures:
        blockers.append("temperature time series is required for MD thermal stability")
    else:
        evidence.append(
            EvidenceRef(
                artifact_path=str(temperature_path),
                artifact_type=ArtifactType.OUTPUT,
                parser_name="vibedft.properties.aimd_analyzer.parse_temperature_series",
                parsed_quantity="temperature_time_series",
                raw_value=_series_summary(temperatures),
                summary=f"Parsed {len(temperatures)} temperature samples.",
                reliability=ReliabilityLevel.MEDIUM,
            )
        )

    if energy_path is None or not energies:
        warnings.append("total energy time series is missing")
    else:
        evidence.append(
            EvidenceRef(
                artifact_path=str(energy_path),
                artifact_type=ArtifactType.OUTPUT,
                parser_name="vibedft.properties.aimd_analyzer.parse_energy_series",
                parsed_quantity="total_energy_time_series",
                raw_value=_series_summary(energies),
                summary=f"Parsed {len(energies)} total-energy samples.",
                reliability=ReliabilityLevel.MEDIUM,
            )
        )

    if trajectory_path is None or not trajectory.has_data:
        blockers.append("trajectory evidence is required for RMSD and bond stability")
    else:
        evidence.append(
            EvidenceRef(
                artifact_path=str(trajectory_path),
                artifact_type=ArtifactType.OUTPUT,
                parser_name="vibedft.properties.aimd_analyzer.parse_xyz_trajectory",
                parsed_quantity="xyz_trajectory",
                raw_value=trajectory.to_summary(),
                summary=f"Parsed {trajectory.n_frames} trajectory frames.",
                warnings=list(trajectory.parse_errors),
                reliability=ReliabilityLevel.MEDIUM,
            )
        )

    if stress_path is not None:
        evidence.append(
            EvidenceRef(
                artifact_path=str(stress_path),
                artifact_type=ArtifactType.OUTPUT,
                parser_name="vibedft.properties.aimd_analyzer.stress_series_presence",
                parsed_quantity="stress_time_series",
                summary="Stress time-series artifact is present.",
                reliability=ReliabilityLevel.LOW,
            )
        )
    if cell_path is not None:
        evidence.append(
            EvidenceRef(
                artifact_path=str(cell_path),
                artifact_type=ArtifactType.OUTPUT,
                parser_name="vibedft.properties.aimd_analyzer.cell_vectors_presence",
                parsed_quantity="cell_vectors",
                summary="Cell-vector time-series artifact is present.",
                reliability=ReliabilityLevel.LOW,
            )
        )

    temperature_average = round(sum(temperatures) / len(temperatures), 6) if temperatures else None
    temperature_fluctuation = round(_std(temperatures), 6) if temperatures else None
    temperature_drift = round(temperatures[-1] - temperatures[0], 6) if len(temperatures) >= 2 else None
    energy_drift = round(abs(energies[-1] - energies[0]), 6) if len(energies) >= 2 else None
    rmsd_values = _rmsd_series(trajectory)
    rmsd_max = round(max(rmsd_values), 6) if rmsd_values else None
    rmsd_mean = round(sum(rmsd_values) / len(rmsd_values), 6) if rmsd_values else None
    bond_stability = _bond_stability(trajectory)

    if temperature_drift is not None and abs(temperature_drift) > 200.0:
        blockers.append(f"temperature drift is too large for stable MD: {temperature_drift:.3f} K")
    if temperature_fluctuation is not None and temperature_fluctuation > 150.0:
        blockers.append(
            f"temperature fluctuation is too large for stable MD: {temperature_fluctuation:.3f} K"
        )
    if energy_drift is not None and energy_drift > 0.05:
        warnings.append(f"total energy drift is high: {energy_drift:.6f} Ry")
    if bond_stability["bond_break_warning"]:
        blockers.append("bond stability monitor detected a likely bond break")

    if any("required" in blocker for blocker in blockers):
        verdict = "insufficient_md_evidence"
        status = ResultStatus.INSUFFICIENT_EVIDENCE
    elif blockers:
        verdict = "thermally_unstable"
        status = ResultStatus.BLOCKED
    elif warnings:
        verdict = "thermally_stable"
        status = ResultStatus.WARNING
    else:
        verdict = "thermally_stable"
        status = ResultStatus.PASS

    descriptors = [
        PhysicsDescriptor(
            name="thermal_stability_verdict",
            value=verdict,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if evidence else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="temperature_average_K",
            value=temperature_average,
            unit="K",
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if temperatures else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="temperature_fluctuation_K",
            value=temperature_fluctuation,
            unit="K",
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if temperatures else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="energy_drift_Ry",
            value=energy_drift,
            unit="Ry",
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if energies else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="rmsd_max_angstrom",
            value=rmsd_max,
            unit="angstrom",
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if rmsd_values else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="rmsd_mean_angstrom",
            value=rmsd_mean,
            unit="angstrom",
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if rmsd_values else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="bond_stability",
            value=bond_stability,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if trajectory.has_data else ReliabilityLevel.LOW,
        ),
    ]

    return AnalysisResult(
        id="analysis.md_stability",
        parser_name="vibedft.properties.aimd_analyzer.analyze_md_stability",
        status=status,
        parsed_quantity="md_thermal_stability",
        evidence=evidence,
        descriptors=descriptors,
        raw_value={
            "thermal_stability_verdict": verdict,
            "temperature_average_K": temperature_average,
            "temperature_fluctuation_K": temperature_fluctuation,
            "temperature_drift_K": temperature_drift,
            "energy_drift_Ry": energy_drift,
            "rmsd_max_angstrom": rmsd_max,
            "rmsd_mean_angstrom": rmsd_mean,
            "bond_stability": bond_stability,
        },
        summary="Evidence-backed QE MD thermal stability analysis.",
        warnings=warnings,
        blockers=blockers,
        reliability=(
            ReliabilityLevel.MEDIUM
            if status in {ResultStatus.PASS, ResultStatus.WARNING}
            else ReliabilityLevel.LOW
        ),
        metadata={
            "forbidden_conclusions": [
                "Do not claim thermal stability without temperature and trajectory evidence."
            ] if status == ResultStatus.INSUFFICIENT_EVIDENCE else [],
        },
    )


def _line_float_values(line: str) -> list[float]:
    values: list[float] = []
    for item in line.replace(",", " ").split():
        try:
            values.append(float(item))
        except ValueError:
            continue
    return values


def _first_existing(paths) -> Path | None:
    for path in paths:
        p = Path(path)
        if p.is_file():
            return p
    return None


def _series_summary(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "first": values[0] if values else None,
        "last": values[-1] if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def _rmsd_series(trajectory: MDTrajectory) -> list[float]:
    if trajectory.n_frames < 2:
        return []
    reference = trajectory.frames[0]
    values: list[float] = []
    for frame in trajectory.frames[1:]:
        if len(frame) != len(reference):
            continue
        squared = 0.0
        for atom, ref in zip(frame, reference):
            squared += (atom.x - ref.x) ** 2 + (atom.y - ref.y) ** 2 + (atom.z - ref.z) ** 2
        values.append(math.sqrt(squared / len(reference)))
    return values


def _bond_stability(trajectory: MDTrajectory) -> dict[str, Any]:
    if trajectory.n_frames < 2 or trajectory.n_atoms < 2:
        return {
            "bond_break_warning": False,
            "max_bond_delta_angstrom": None,
            "max_relative_change": None,
        }

    initial = _pair_distances(trajectory.frames[0])
    final = _pair_distances(trajectory.frames[-1])
    max_delta = 0.0
    max_relative = 0.0
    for key, initial_distance in initial.items():
        final_distance = final.get(key)
        if final_distance is None or initial_distance <= 1.0e-12:
            continue
        delta = abs(final_distance - initial_distance)
        max_delta = max(max_delta, delta)
        max_relative = max(max_relative, delta / initial_distance)

    warning = max_delta > 1.0 or max_relative > 0.5
    return {
        "bond_break_warning": warning,
        "max_bond_delta_angstrom": round(max_delta, 6),
        "max_relative_change": round(max_relative, 6),
    }


def _pair_distances(frame: list[MDAtom]) -> dict[tuple[int, int], float]:
    distances: dict[tuple[int, int], float] = {}
    for i, left in enumerate(frame):
        for j in range(i + 1, len(frame)):
            right = frame[j]
            distances[(i, j)] = math.sqrt(
                (left.x - right.x) ** 2
                + (left.y - right.y) ** 2
                + (left.z - right.z) ** 2
            )
    return distances
