"""Evidence-backed absolute band alignment and Type-III classification."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibedft.properties.charge import parse_planar_profile
from vibedft.research.models import (
    AnalysisResult,
    ArtifactType,
    EvidenceRef,
    PhysicsDescriptor,
    ReliabilityLevel,
    ResultStatus,
)
from vibedft.spin.soc_parser import analyze_soc_config


@dataclass
class BandEdgeSummary:
    """Minimal absolute band-edge summary for one strained layer reference."""

    label: str = ""
    vbm_ev: float | None = None
    cbm_ev: float | None = None
    lattice_a_angstrom: float | None = None
    source_file: str = ""
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return self.vbm_ev is not None and self.cbm_ev is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "vbm_ev": self.vbm_ev,
            "cbm_ev": self.cbm_ev,
            "lattice_a_angstrom": self.lattice_a_angstrom,
            "source_file": self.source_file,
            "parse_errors": list(self.parse_errors),
        }


def parse_band_edge_summary(filepath: Path | str) -> BandEdgeSummary:
    """Parse a small key-value summary containing absolute VBM/CBM values."""

    path = Path(filepath)
    result = BandEdgeSummary(source_file=str(path))
    if not path.is_file():
        result.parse_errors.append(f"band-edge summary not found: {path}")
        return result

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        values[key.strip().lower()] = value.strip()

    result.label = values.get("label", path.stem)
    result.vbm_ev = _optional_float(values.get("vbm_ev"))
    result.cbm_ev = _optional_float(values.get("cbm_ev"))
    result.lattice_a_angstrom = _optional_float(values.get("lattice_a_angstrom"))
    if result.vbm_ev is None:
        result.parse_errors.append("band-edge summary is missing vbm_ev")
    if result.cbm_ev is None:
        result.parse_errors.append("band-edge summary is missing cbm_ev")
    return result


def analyze_band_alignment(
    *,
    reference_band_edge_paths: dict[str, Path | str],
    planar_profile_path: Path | str | None = None,
    heterostructure_input_path: Path | str | None = None,
    layer_projected_bands_path: Path | str | None = None,
    relaxed_structure_path: Path | str | None = None,
    bands_output_path: Path | str | None = None,
) -> AnalysisResult:
    """Build a conservative evidence-backed Type-I/II/III alignment analysis."""

    warnings: list[str] = []
    blockers: list[str] = []
    evidence: list[EvidenceRef] = []

    references: dict[str, BandEdgeSummary] = {}
    for label, edge_path in reference_band_edge_paths.items():
        edge = parse_band_edge_summary(edge_path)
        if not edge.label:
            edge.label = label
        references[label] = edge
        blockers.extend(edge.parse_errors)
        evidence.append(_edge_evidence_ref(edge_path, edge, label))

    if len([edge for edge in references.values() if edge.has_data]) < 2:
        blockers.append("same-lattice isolated references for at least two layers are required")
    blockers.extend(_same_lattice_blockers(references))

    planar_summary = None
    if planar_profile_path is None:
        blockers.append("valid planar or macroscopic potential is required for absolute alignment")
    else:
        planar = parse_planar_profile(planar_profile_path)
        planar_summary = _planar_summary(planar)
        warnings.extend(planar.warnings + planar.parse_errors)
        blockers.extend(planar.blockers)
        if planar.malformed or not planar.has_data:
            blockers.append("invalid planar potential blocks absolute band alignment")
        evidence.append(
            EvidenceRef(
                artifact_path=str(planar_profile_path),
                artifact_type=ArtifactType.OUTPUT,
                parser_name="vibedft.properties.charge.parse_planar_profile",
                parsed_quantity="vacuum_level_alignment",
                raw_value=planar_summary,
                summary=(
                    f"Planar profile points={planar.n_points}, "
                    f"vacuum={planar.vacuum_level_ev}, malformed={planar.malformed}"
                ),
                warnings=planar.warnings + planar.parse_errors,
                blockers=planar.blockers,
                reliability=(
                    ReliabilityLevel.MEDIUM
                    if planar.has_data and not planar.malformed
                    else ReliabilityLevel.LOW
                ),
            )
        )

    if heterostructure_input_path is None:
        blockers.append("SOC policy evidence is required for heavy-element band alignment")
    else:
        soc = analyze_soc_config(Path(heterostructure_input_path).parent)
        warnings.extend(soc.warnings)
        evidence.append(
            EvidenceRef(
                artifact_path=str(heterostructure_input_path),
                artifact_type=ArtifactType.INPUT,
                parser_name="vibedft.spin.soc_parser.analyze_soc_config",
                parsed_quantity="soc_policy",
                raw_value={
                    "has_soc": soc.has_soc,
                    "heavy_elements": soc.heavy_elements,
                    "needs_soc_check": soc.needs_soc_check,
                },
                summary=f"SOC enabled={soc.has_soc}, heavy_elements={soc.heavy_elements}",
                warnings=list(soc.warnings),
                reliability=ReliabilityLevel.MEDIUM,
            )
        )

    if not _existing_file(layer_projected_bands_path):
        blockers.append("layer-projected bands are required for a Type-III verdict")
    else:
        evidence.append(
            EvidenceRef(
                artifact_path=str(layer_projected_bands_path),
                artifact_type=ArtifactType.BANDS,
                parser_name="vibedft.properties.band_alignment.layer_projected_bands_presence",
                parsed_quantity="layer_projected_bands",
                summary="Layer-projected band evidence is present.",
                reliability=ReliabilityLevel.MEDIUM,
            )
        )

    if not _existing_file(relaxed_structure_path):
        blockers.append("relaxed heterostructure evidence is required for a Type-III verdict")
    else:
        evidence.append(
            EvidenceRef(
                artifact_path=str(relaxed_structure_path),
                artifact_type=ArtifactType.OUTPUT,
                parser_name="vibedft.properties.band_alignment.relaxed_structure_presence",
                parsed_quantity="relaxed_heterostructure_evidence",
                summary="Relaxed heterostructure evidence is present.",
                reliability=ReliabilityLevel.MEDIUM,
            )
        )

    if bands_output_path is not None:
        bands_warnings, bands_blockers = _bands_output_convergence_findings(bands_output_path)
        warnings.extend(bands_warnings)
        blockers.extend(bands_blockers)
        evidence.append(
            EvidenceRef(
                artifact_path=str(bands_output_path),
                artifact_type=ArtifactType.BANDS,
                parser_name="vibedft.properties.band_alignment.scan_bands_output_convergence",
                parsed_quantity="bands_convergence_warnings",
                raw_value={"warnings": bands_warnings, "blockers": bands_blockers},
                warnings=bands_warnings,
                blockers=bands_blockers,
                reliability=ReliabilityLevel.MEDIUM if not bands_blockers else ReliabilityLevel.LOW,
            )
        )

    classification, offsets = _classify_alignment(references)
    descriptors = [
        PhysicsDescriptor(
            name="absolute_band_edges",
            value={label: edge.to_dict() for label, edge in references.items()},
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if references and not blockers else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="band_offsets",
            value=offsets,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if offsets and not blockers else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="band_alignment_classification",
            value=classification,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=(
                ReliabilityLevel.MEDIUM
                if classification != "insufficient_evidence" and not blockers
                else ReliabilityLevel.LOW
            ),
        ),
    ]
    if planar_summary is not None:
        descriptors.append(
            PhysicsDescriptor(
                name="vacuum_alignment",
                value=planar_summary,
                evidence=evidence,
                warnings=warnings,
                blockers=blockers,
                reliability=ReliabilityLevel.MEDIUM if not blockers else ReliabilityLevel.LOW,
            )
        )

    if blockers:
        status = ResultStatus.BLOCKED
    elif warnings:
        status = ResultStatus.WARNING
    else:
        status = ResultStatus.PASS

    return AnalysisResult(
        id="analysis.band_alignment",
        parser_name="vibedft.properties.band_alignment.analyze_band_alignment",
        status=status,
        parsed_quantity="absolute_band_alignment",
        evidence=evidence,
        descriptors=descriptors,
        raw_value={
            "classification": classification,
            "band_offsets": offsets,
            "planar_profile": planar_summary,
        },
        summary="Evidence-backed absolute band alignment and Type-III gate.",
        warnings=warnings,
        blockers=blockers,
        reliability=(
            ReliabilityLevel.MEDIUM
            if status in {ResultStatus.PASS, ResultStatus.WARNING}
            else ReliabilityLevel.LOW
        ),
        metadata={
            "forbidden_conclusions": _forbidden_conclusions(blockers),
        },
    )


def _edge_evidence_ref(path: Path | str, edge: BandEdgeSummary, label: str) -> EvidenceRef:
    return EvidenceRef(
        artifact_path=str(path),
        artifact_type=ArtifactType.BANDS,
        parser_name="vibedft.properties.band_alignment.parse_band_edge_summary",
        parsed_quantity=f"absolute_band_edges.{label}",
        raw_value=edge.to_dict(),
        summary=f"{label}: VBM={edge.vbm_ev} eV, CBM={edge.cbm_ev} eV",
        blockers=list(edge.parse_errors),
        reliability=ReliabilityLevel.MEDIUM if edge.has_data else ReliabilityLevel.LOW,
    )


def _same_lattice_blockers(references: dict[str, BandEdgeSummary]) -> list[str]:
    lattice_values = [
        edge.lattice_a_angstrom
        for edge in references.values()
        if edge.has_data and edge.lattice_a_angstrom is not None
    ]
    if len(lattice_values) < 2:
        return ["same-lattice isolated references must report lattice_a_angstrom"]
    if max(lattice_values) - min(lattice_values) > 0.02:
        return ["same-lattice isolated references differ by more than 0.02 Angstrom"]
    return []


def _classify_alignment(references: dict[str, BandEdgeSummary]) -> tuple[str, dict[str, Any]]:
    edges = [edge for edge in references.values() if edge.has_data]
    if len(edges) < 2:
        return "insufficient_evidence", {}

    largest_overlap = max(
        (
            (left.vbm_ev or 0.0) - (right.cbm_ev or 0.0)
            for left in edges
            for right in edges
            if left is not right
        ),
        default=0.0,
    )
    offsets = {"broken_gap_ev": round(max(largest_overlap, 0.0), 6)}
    if largest_overlap > 0.0:
        return "type_iii_broken_gap", offsets

    first, second = edges[0], edges[1]
    first_contains_second = (
        first.vbm_ev is not None
        and first.cbm_ev is not None
        and second.vbm_ev is not None
        and second.cbm_ev is not None
        and first.vbm_ev <= second.vbm_ev
        and first.cbm_ev >= second.cbm_ev
    )
    second_contains_first = (
        first.vbm_ev is not None
        and first.cbm_ev is not None
        and second.vbm_ev is not None
        and second.cbm_ev is not None
        and second.vbm_ev <= first.vbm_ev
        and second.cbm_ev >= first.cbm_ev
    )
    if first_contains_second or second_contains_first:
        return "type_i_straddling", offsets
    return "type_ii_staggered", offsets


def _bands_output_convergence_findings(pathlike: Path | str) -> tuple[list[str], list[str]]:
    path = Path(pathlike)
    if not path.is_file():
        return [], [f"bands output not found: {path}"]
    text = path.read_text(encoding="utf-8", errors="replace")
    normalized = " ".join(text.lower().split())
    if "eigenvalues not converged" in normalized or (
        "c_bands" in normalized and "not converged" in normalized
    ):
        return [], ["bands.out reports eigenvalue nonconvergence"]
    return [], []


def _planar_summary(profile) -> dict[str, Any]:
    return {
        "n_points": profile.n_points,
        "vacuum_level_ev": profile.vacuum_level_ev,
        "top_vacuum_level_ev": profile.top_vacuum_level_ev,
        "bottom_vacuum_level_ev": profile.bottom_vacuum_level_ev,
        "vacuum_plateau_fluctuation_ev": profile.vacuum_plateau_fluctuation_ev,
        "dipole_moment_estimate": profile.dipole_moment_estimate,
        "malformed": profile.malformed,
    }


def _forbidden_conclusions(blockers: list[str]) -> list[str]:
    if not blockers:
        return []
    return [
        (
            "Do not write 'Type-III confirmed' without valid planar alignment, "
            "same-lattice references, layer-projected bands, relaxed "
            "heterostructure evidence, and SOC policy."
        ),
        "Do not use invalid or malformed planar potential output for absolute band alignment.",
    ]


def _existing_file(pathlike: Path | str | None) -> bool:
    return pathlike is not None and Path(pathlike).is_file()


def _optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
