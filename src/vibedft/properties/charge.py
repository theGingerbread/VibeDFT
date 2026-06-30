"""Evidence-backed charge, Bader, cube, and planar-profile analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BaderAtom:
    """One row from a Henkelman Bader ``ACF.dat`` table."""

    index: int
    x: float
    y: float
    z: float
    charge: float
    min_distance: float
    atomic_volume: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "charge": self.charge,
            "min_distance": self.min_distance,
            "atomic_volume": self.atomic_volume,
        }


@dataclass
class BaderData:
    """Parsed ``ACF.dat`` with conservation metadata."""

    atoms: list[BaderAtom] = field(default_factory=list)
    vacuum_charge: float | None = None
    number_of_electrons: float | None = None
    source_file: str = ""
    warnings: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return bool(self.atoms)

    @property
    def n_atoms(self) -> int:
        return len(self.atoms)

    @property
    def total_bader_charge(self) -> float:
        return sum(atom.charge for atom in self.atoms)

    @property
    def charge_conservation_delta_e(self) -> float | None:
        if self.number_of_electrons is None:
            return None
        return self.total_bader_charge - self.number_of_electrons

    def atom_charge_sum(self, atom_indices: list[int]) -> float:
        index_set = set(atom_indices)
        return sum(atom.charge for atom in self.atoms if atom.index in index_set)


@dataclass
class CubeMetadata:
    """Gaussian cube header metadata without loading volumetric data."""

    n_atoms: int | None = None
    origin: tuple[float, float, float] | None = None
    grid: tuple[int, int, int] | None = None
    axes: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]] | None = None
    source_file: str = ""
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return self.n_atoms is not None and self.grid is not None


@dataclass
class PlanarProfile:
    """Numeric or diagnostic planar-average profile."""

    z_values: list[float] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    vacuum_level_ev: float | None = None
    vacuum_plateau_fluctuation_ev: float | None = None
    top_vacuum_level_ev: float | None = None
    bottom_vacuum_level_ev: float | None = None
    dipole_moment_estimate: float | None = None
    malformed: bool = False
    source_file: str = ""
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return bool(self.z_values)

    @property
    def n_points(self) -> int:
        return len(self.z_values)


def parse_acf_dat(filepath: Path | str) -> BaderData:
    """Parse Henkelman Bader ``ACF.dat`` table rows and totals."""

    path = Path(filepath)
    result = BaderData(source_file=str(path))
    if not path.is_file():
        result.parse_errors.append(f"ACF.dat not found: {path}")
        return result

    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        ls = line.strip()
        if not ls:
            continue

        m_vac = re.search(r"VACUUM\s+CHARGE\s*:\s*([+\-\d.Ee]+)", ls, re.IGNORECASE)
        if m_vac:
            result.vacuum_charge = _safe_float(m_vac.group(1))
            continue

        m_e = re.search(r"NUMBER\s+OF\s+ELECTRONS\s*:\s*([+\-\d.Ee]+)", ls, re.IGNORECASE)
        if m_e:
            result.number_of_electrons = _safe_float(m_e.group(1))
            continue

        parts = ls.split()
        if len(parts) < 7:
            continue
        try:
            atom = BaderAtom(
                index=int(parts[0]),
                x=float(parts[1]),
                y=float(parts[2]),
                z=float(parts[3]),
                charge=float(parts[4]),
                min_distance=float(parts[5]),
                atomic_volume=float(parts[6]),
            )
        except ValueError:
            continue
        result.atoms.append(atom)

    if not result.atoms:
        result.parse_errors.append(f"ACF.dat has no parseable atom rows: {path}")
    if result.has_data and result.number_of_electrons is None:
        result.warnings.append("ACF.dat does not report NUMBER OF ELECTRONS")
    return result


def parse_cube_metadata(filepath: Path | str) -> CubeMetadata:
    """Parse Gaussian cube header metadata without reading volumetric values."""

    path = Path(filepath)
    result = CubeMetadata(source_file=str(path))
    if not path.is_file():
        result.parse_errors.append(f"cube file not found: {path}")
        return result

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 6:
        result.parse_errors.append(f"cube header is incomplete: {path}")
        return result

    try:
        atom_line = lines[2].split()
        result.n_atoms = abs(int(atom_line[0]))
        result.origin = (float(atom_line[1]), float(atom_line[2]), float(atom_line[3]))
        grid_values: list[int] = []
        axes: list[tuple[float, float, float]] = []
        for line in lines[3:6]:
            parts = line.split()
            grid_values.append(abs(int(parts[0])))
            axes.append((float(parts[1]), float(parts[2]), float(parts[3])))
        result.grid = (grid_values[0], grid_values[1], grid_values[2])
        result.axes = (axes[0], axes[1], axes[2])
    except (IndexError, ValueError) as exc:
        result.parse_errors.append(f"cube header parse failed: {exc}")
    return result


def parse_planar_profile(filepath: Path | str) -> PlanarProfile:
    """Parse two-column planar profile data or a diagnostic malformed log."""

    path = Path(filepath)
    result = PlanarProfile(source_file=str(path))
    if not path.is_file():
        result.parse_errors.append(f"planar profile not found: {path}")
        return result

    text = path.read_text(encoding="utf-8", errors="replace")
    _collect_planar_text_warnings(text, result)

    for line in text.splitlines():
        ls = line.strip()
        if not ls or ls.startswith("#") or ls.startswith("!"):
            continue
        parts = ls.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            z = float(parts[0])
            value = float(parts[1])
        except ValueError:
            continue
        result.z_values.append(z)
        result.values.append(value)

    if result.n_points >= 4:
        _summarize_planar_numeric_profile(result)
    elif result.malformed:
        result.blockers.append("malformed planar average cannot support absolute alignment")
    else:
        result.parse_errors.append(f"planar profile has too few numeric rows: {path}")
    return result


def analyze_charge_evidence(
    *,
    hetero_acf_path: Path | str,
    reference_acf_paths: dict[str, Path | str] | None = None,
    layer_atom_indices: dict[str, list[int]] | None = None,
    planar_profile_path: Path | str | None = None,
    cube_path: Path | str | None = None,
):
    """Build an evidence-backed charge-transfer analysis result."""

    from vibedft.research.models import (
        AnalysisResult,
        ArtifactType,
        EvidenceRef,
        PhysicsDescriptor,
        ReliabilityLevel,
        ResultStatus,
    )

    reference_acf_paths = reference_acf_paths or {}
    layer_atom_indices = layer_atom_indices or {}
    warnings: list[str] = []
    blockers: list[str] = []
    evidence: list[EvidenceRef] = []

    hetero = parse_acf_dat(hetero_acf_path)
    blockers.extend(hetero.parse_errors)
    warnings.extend(hetero.warnings)
    evidence.append(_bader_evidence_ref(hetero_acf_path, hetero, "heterostructure_bader_charge"))

    references: dict[str, BaderData] = {}
    for label, ref_path in reference_acf_paths.items():
        ref = parse_acf_dat(ref_path)
        references[label] = ref
        warnings.extend(ref.warnings)
        if ref.parse_errors:
            blockers.append(f"reference {label} is incomplete or missing: {'; '.join(ref.parse_errors)}")
        evidence.append(_bader_evidence_ref(ref_path, ref, f"reference_bader_charge.{label}"))

    layer_transfer = _layer_charge_transfer(hetero, references, layer_atom_indices)
    if reference_acf_paths and not layer_transfer:
        blockers.append("reference layer charge transfer cannot be computed from the supplied atom map")

    conservation = {
        "heterostructure_delta_e": hetero.charge_conservation_delta_e,
        "heterostructure_total_bader_charge": hetero.total_bader_charge if hetero.has_data else None,
        "heterostructure_number_of_electrons": hetero.number_of_electrons,
    }
    if (
        hetero.charge_conservation_delta_e is not None
        and abs(hetero.charge_conservation_delta_e) > 1e-3
    ):
        warnings.append(
            "Bader electron count differs from NUMBER OF ELECTRONS by "
            f"{hetero.charge_conservation_delta_e:.4f} e"
        )

    planar: PlanarProfile | None = None
    if planar_profile_path is not None:
        planar = parse_planar_profile(planar_profile_path)
        warnings.extend(planar.warnings + planar.parse_errors)
        blockers.extend(planar.blockers)
        evidence.append(
            EvidenceRef(
                artifact_path=str(planar_profile_path),
                artifact_type=ArtifactType.OUTPUT,
                parser_name="vibedft.properties.charge.parse_planar_profile",
                parsed_quantity="planar_profile",
                raw_value=_planar_summary(planar),
                summary=f"Planar profile points={planar.n_points}, malformed={planar.malformed}",
                warnings=planar.warnings + planar.parse_errors,
                blockers=planar.blockers,
                reliability=ReliabilityLevel.MEDIUM if planar.has_data else ReliabilityLevel.LOW,
            )
        )

    cube: CubeMetadata | None = None
    if cube_path is not None:
        cube = parse_cube_metadata(cube_path)
        warnings.extend(cube.parse_errors)
        evidence.append(
            EvidenceRef(
                artifact_path=str(cube_path),
                artifact_type=ArtifactType.CUBE,
                parser_name="vibedft.properties.charge.parse_cube_metadata",
                parsed_quantity="cube_metadata",
                raw_value={
                    "n_atoms": cube.n_atoms,
                    "origin": cube.origin,
                    "grid": cube.grid,
                },
                summary=f"Cube grid={cube.grid}, atoms={cube.n_atoms}",
                warnings=list(cube.parse_errors),
                reliability=ReliabilityLevel.MEDIUM if cube.has_data else ReliabilityLevel.LOW,
            )
        )

    classification = _charge_transfer_classification(layer_transfer)
    descriptors = [
        PhysicsDescriptor(
            name="bader_charge_table",
            value=[atom.to_dict() for atom in hetero.atoms],
            evidence=evidence,
            blockers=blockers,
            warnings=warnings,
            reliability=ReliabilityLevel.MEDIUM if hetero.has_data else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="charge_conservation",
            value=conservation,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if hetero.has_data else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="layer_charge_transfer",
            value=layer_transfer,
            evidence=evidence,
            warnings=["Bader evidence alone cannot confirm Type-III alignment."],
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if layer_transfer else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="charge_transfer_classification",
            value=classification,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.LOW,
        ),
    ]
    if planar is not None:
        descriptors.append(
            PhysicsDescriptor(
                name="planar_profile_summary",
                value=_planar_summary(planar),
                evidence=evidence,
                warnings=planar.warnings + planar.parse_errors,
                blockers=planar.blockers,
                reliability=ReliabilityLevel.MEDIUM if planar.has_data else ReliabilityLevel.LOW,
            )
        )
    if cube is not None:
        descriptors.append(
            PhysicsDescriptor(
                name="cube_metadata",
                value={"n_atoms": cube.n_atoms, "origin": cube.origin, "grid": cube.grid},
                evidence=evidence,
                warnings=cube.parse_errors,
                reliability=ReliabilityLevel.MEDIUM if cube.has_data else ReliabilityLevel.LOW,
            )
        )

    if not hetero.has_data:
        status = ResultStatus.INSUFFICIENT_EVIDENCE
    elif blockers:
        status = ResultStatus.BLOCKED
    elif warnings:
        status = ResultStatus.WARNING
    else:
        status = ResultStatus.PASS

    return AnalysisResult(
        id="analysis.charge_bader_planar",
        parser_name="vibedft.properties.charge.analyze_charge_evidence",
        status=status,
        parsed_quantity="charge_transfer_and_planar_profile",
        evidence=evidence,
        descriptors=descriptors,
        raw_value={
            "charge_conservation": conservation,
            "layer_charge_transfer": layer_transfer,
            "planar_profile": _planar_summary(planar) if planar else None,
        },
        summary="Evidence-backed Bader charge and planar-potential analysis.",
        warnings=warnings,
        blockers=blockers,
        reliability=ReliabilityLevel.MEDIUM if hetero.has_data and not blockers else ReliabilityLevel.LOW,
        metadata={
            "forbidden_conclusions": [
                "Do not confirm Type-III or absolute band alignment from Bader evidence alone.",
                "Do not use malformed planar-average output for vacuum alignment.",
            ] if blockers else [
                "Bader charge transfer is provisional without valid band alignment evidence."
            ],
        },
    )


def _bader_evidence_ref(path: Path | str, data: BaderData, parsed_quantity: str):
    from vibedft.research.models import ArtifactType, EvidenceRef, ReliabilityLevel

    return EvidenceRef(
        artifact_path=str(path),
        artifact_type=ArtifactType.OUTPUT,
        parser_name="vibedft.properties.charge.parse_acf_dat",
        parsed_quantity=parsed_quantity,
        raw_value={
            "n_atoms": data.n_atoms,
            "total_bader_charge": data.total_bader_charge if data.has_data else None,
            "number_of_electrons": data.number_of_electrons,
            "charge_conservation_delta_e": data.charge_conservation_delta_e,
        },
        summary=f"ACF atoms={data.n_atoms}, electrons={data.number_of_electrons}",
        warnings=list(data.warnings),
        blockers=list(data.parse_errors),
        reliability=ReliabilityLevel.MEDIUM if data.has_data else ReliabilityLevel.LOW,
    )


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _collect_planar_text_warnings(text: str, result: PlanarProfile) -> None:
    lower = text.lower()
    normalized = " ".join(lower.split())
    if "fixed 600-line" in normalized or "600-line blocks" in normalized:
        result.malformed = True
        result.warnings.append("planar average used fixed 600-line blocks instead of grid metadata")
    if "old save" in normalized or "old_scf_save" in normalized:
        result.malformed = True
        result.warnings.append("planar average references old save provenance")
    if "vacuum plateau fluctuation" in normalized:
        result.malformed = True
        result.warnings.append("planar average reports vacuum plateau fluctuation")
    if "deltav" in normalized or "delta v" in normalized:
        result.warnings.append("reported deltaV requires validated planar provenance before reuse")


def _summarize_planar_numeric_profile(result: PlanarProfile) -> None:
    n = result.n_points
    edge_n = max(2, n // 5)
    bottom = result.values[:edge_n]
    top = result.values[-edge_n:]
    result.bottom_vacuum_level_ev = sum(bottom) / len(bottom)
    result.top_vacuum_level_ev = sum(top) / len(top)
    result.vacuum_level_ev = (result.bottom_vacuum_level_ev + result.top_vacuum_level_ev) / 2.0
    result.vacuum_plateau_fluctuation_ev = max(max(bottom) - min(bottom), max(top) - min(top))

    z_min = min(result.z_values)
    z_max = max(result.z_values)
    span = z_max - z_min
    if span > 0:
        mean_value = sum(result.values) / len(result.values)
        weighted = sum((z - z_min) * (value - mean_value) for z, value in zip(result.z_values, result.values))
        result.dipole_moment_estimate = weighted / span

    if result.vacuum_plateau_fluctuation_ev is not None and result.vacuum_plateau_fluctuation_ev > 0.5:
        result.warnings.append(
            "planar vacuum plateau is not flat: "
            f"fluctuation={result.vacuum_plateau_fluctuation_ev:.3f} eV"
        )


def _layer_charge_transfer(
    hetero: BaderData,
    references: dict[str, BaderData],
    layer_atom_indices: dict[str, list[int]],
) -> dict[str, dict[str, float]]:
    if not hetero.has_data or not references or not layer_atom_indices:
        return {}

    result: dict[str, dict[str, float]] = {}
    for label, atom_indices in layer_atom_indices.items():
        ref = references.get(label)
        if ref is None or not ref.has_data:
            continue
        hetero_charge = hetero.atom_charge_sum(atom_indices)
        reference_charge = ref.total_bader_charge
        result[label] = {
            "heterostructure_charge": round(hetero_charge, 6),
            "reference_charge": round(reference_charge, 6),
            "delta_e": round(hetero_charge - reference_charge, 6),
        }
    return result


def _charge_transfer_classification(layer_transfer: dict[str, dict[str, float]]) -> str:
    if not layer_transfer:
        return "insufficient_evidence"
    max_delta = max(abs(item["delta_e"]) for item in layer_transfer.values())
    if max_delta >= 1.0:
        return "ionic"
    return "mixed_or_covalent"


def _planar_summary(profile: PlanarProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        "n_points": profile.n_points,
        "vacuum_level_ev": profile.vacuum_level_ev,
        "top_vacuum_level_ev": profile.top_vacuum_level_ev,
        "bottom_vacuum_level_ev": profile.bottom_vacuum_level_ev,
        "vacuum_plateau_fluctuation_ev": profile.vacuum_plateau_fluctuation_ev,
        "dipole_moment_estimate": profile.dipole_moment_estimate,
        "malformed": profile.malformed,
    }
