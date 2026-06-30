"""Intercalation site analyzer: geometry, stacking, and distance assessment.

Two-layer pattern (mirrors ``stability_analyzer.py``):

  * module-level ``extract_intercalation_site_data(case_dir)`` — finds
    the structure file (CIF / POSCAR / QE input), parses it, and calls
    :func:`compute_intercalation_metrics`.
  * module-level ``analyze_intercalation_site(data)`` — turns the
    metrics into :class:`PhysicsInsight` objects + a 0–10 score.
  * ``IntercalationSiteAnalyzer(Analyzer)`` — ABC subclass registered
    via ``@register_analyzer`` so the orchestrator auto-discovers it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibedft.analyzers.base import (
    Analyzer,
    SectionResult,
    _match_files,
    register_analyzer,
    run_analyzer,
)
from vibedft.analyzers.physics_models import (
    EvidenceLink,
    InsightLevel,
    IntercalationSiteData,
    PhysicsInsight,
)
from vibedft.core.intercalation import IntercalationMetrics, compute_intercalation_metrics
from vibedft.core.structure import Structure, parse_structure


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level extract
# ═══════════════════════════════════════════════════════════════════════════════


# Order matters: CIF is the canonical intercalation-site format, then
# POSCAR, then QE relax inputs.
_STRUCTURE_GLOBS = ["**/*.cif", "**/POSCAR", "**/rx.in", "**/vc-relax.in"]


def _find_structure_file(case_dir: Path) -> tuple[Path, Structure] | None:
    """Find and parse the first usable structure file in ``case_dir``."""
    for glob in _STRUCTURE_GLOBS:
        for f in sorted(case_dir.rglob(glob.lstrip("**/"))):
            if not f.is_file():
                continue
            struct = parse_structure(f)
            if struct and struct.atoms and struct.lattice:
                return f, struct
    return None


def _detect_intercalant(structure: Structure, host_cation: str = "Hf", host_anion: str = "Cl") -> str:
    """Return the element that is neither the host cation nor the anion.

    Falls back to ``"Na"`` when no third species is found (the most
    common intercalant in the HfCl₂ family).
    """
    for elem in structure.elements:
        if elem != host_cation and elem != host_anion:
            return elem
    return "Na"


def extract_intercalation_site_data(case_dir: Path | str) -> IntercalationSiteData | None:
    """Extract intercalation-site geometry metrics from a case directory.

    Searches for CIF / POSCAR / QE-relax input files, parses the first
    usable structure, and computes :class:`IntercalationMetrics`.

    Returns ``None`` when no structure file is found.
    """
    d = Path(case_dir)
    if not d.is_dir():
        return None
    found = _find_structure_file(d)
    if found is None:
        return None
    src_file, structure = found
    intercalant = _detect_intercalant(structure)
    metrics = compute_intercalation_metrics(structure, intercalant=intercalant)
    return IntercalationSiteData(
        site_label=metrics.site_label,
        stacking_relation=metrics.stacking_relation,
        inner_X_X_distance_ang=metrics.inner_X_X_distance_ang,
        m_x_nearest_ang=metrics.m_x_nearest_ang,
        m_hf_nearest_ang=metrics.m_hf_nearest_ang,
        m_z_offset_from_midplane_ang=metrics.m_z_offset_from_midplane_ang,
        m_xy_disp_from_symmetry_ang=metrics.m_xy_disp_from_symmetry_ang,
        max_force=metrics.max_force,
        relative_energy_meV=metrics.relative_energy_meV,
        geometry_flags=list(metrics.geometry_flags),
        intercalant=intercalant,
        host_cation="Hf",
        host_anion="Cl",
        formula=structure.formula,
        source_files=[str(src_file)],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level analyze
# ═══════════════════════════════════════════════════════════════════════════════


def analyze_intercalation_site(
    data: IntercalationSiteData | None,
) -> tuple[list[PhysicsInsight], float]:
    """Produce physics insights and a score (0–10) from intercalation-site data.

    Scoring rubric (deterministic):

      * +2.0 for a clean high-symmetry site (TOP / HOLLOW_A / HOLLOW_B)
      * +1.0 for a recognised stacking (AA / AB)
      * −2.0 for off-center site
      * −1.5 for large z-offset from midplane
      * −1.0 for unknown stacking
      * −1.0 per geometry flag that indicates a problem
    """
    if data is None:
        return [
            PhysicsInsight(
                id="intercalation.no_data",
                category="material",
                level=InsightLevel.NEUTRAL,
                message="No intercalation structure found — site geometry cannot be assessed.",
                detail="Place a CIF / POSCAR / QE relax input in the case directory.",
            )
        ], 5.0

    insights: list[PhysicsInsight] = []
    score = 5.0  # neutral start

    # ── Site label ──
    site = data.site_label
    if site in ("TOP", "HOLLOW_A", "HOLLOW_B"):
        insights.append(PhysicsInsight(
            id=f"intercalation.site_{site.lower()}",
            category="material",
            level=InsightLevel.POSITIVE,
            message=f"Intercalant occupies the {site} high-symmetry site.",
            detail=f"{data.intercalant} at a recognised high-symmetry position "
                   f"(xy-disp = {data.m_xy_disp_from_symmetry_ang:.3f} Å from ideal).",
            evidence=[EvidenceLink(key="site_label", value=site)],
        ))
        score += 2.0
    else:
        insights.append(PhysicsInsight(
            id="intercalation.site_off_center",
            category="material",
            level=InsightLevel.WARNING,
            message=f"Intercalant is off-center (xy-disp = {data.m_xy_disp_from_symmetry_ang:.3f} Å).",
            detail="Off-center sites break the high-symmetry assumption and may "
                   "indicate an incomplete relaxation or a wrong starting geometry.",
            evidence=[EvidenceLink(key="site_label", value=site)],
        ))
        score -= 2.0

    # ── Stacking ──
    stacking = data.stacking_relation
    if stacking in ("AA", "AB"):
        insights.append(PhysicsInsight(
            id=f"intercalation.stacking_{stacking.lower()}",
            category="material",
            level=InsightLevel.POSITIVE,
            message=f"Host stacking: {stacking}.",
            detail=f"Hf layers are {stacking}-stacked; intercalant sits in the "
                   f"corresponding hollow / top site.",
            evidence=[EvidenceLink(key="stacking_relation", value=stacking)],
        ))
        score += 1.0
    else:
        insights.append(PhysicsInsight(
            id="intercalation.stacking_unknown",
            category="material",
            level=InsightLevel.WARNING,
            message="Host stacking could not be classified as AA or AB.",
            detail="The two Hf atoms' in-plane positions do not match either "
                   "the AA (same xy) or AB (2/3,1/3 offset) pattern.",
            evidence=[EvidenceLink(key="stacking_relation", value=stacking)],
        ))
        score -= 1.0

    # ── Distances ──
    insights.append(PhysicsInsight(
        id="intercalation.distances",
        category="material",
        level=InsightLevel.NEUTRAL,
        message=(
            f"M–X nearest = {data.m_x_nearest_ang:.3f} Å, "
            f"M–Hf nearest = {data.m_hf_nearest_ang:.3f} Å, "
            f"inner X–X = {data.inner_X_X_distance_ang:.3f} Å."
        ),
        evidence=[
            EvidenceLink(key="m_x_nearest_ang", value=data.m_x_nearest_ang),
            EvidenceLink(key="m_hf_nearest_ang", value=data.m_hf_nearest_ang),
            EvidenceLink(key="inner_X_X_distance_ang", value=data.inner_X_X_distance_ang),
        ],
    ))

    # ── z-offset ──
    if data.m_z_offset_from_midplane_ang > 0.30:
        insights.append(PhysicsInsight(
            id="intercalation.large_z_offset",
            category="material",
            level=InsightLevel.WARNING,
            message=f"Intercalant z-offset from midplane = {data.m_z_offset_from_midplane_ang:.3f} Å — "
                    "larger than expected for a symmetric site.",
            detail="A large z-offset suggests the intercalant is not centred "
                   "between the two Hf layers; check the relaxation convergence.",
            evidence=[EvidenceLink(key="m_z_offset_from_midplane_ang", value=data.m_z_offset_from_midplane_ang)],
        ))
        score -= 1.5

    # ── Relative energy ──
    if data.relative_energy_meV != 0.0:
        level = InsightLevel.POSITIVE if data.relative_energy_meV < 0.0 else InsightLevel.WARNING
        insights.append(PhysicsInsight(
            id="intercalation.relative_energy",
            category="material",
            level=level,
            message=f"Relative energy = {data.relative_energy_meV:+.1f} meV vs reference site.",
            evidence=[EvidenceLink(key="relative_energy_meV", value=data.relative_energy_meV)],
        ))
        if data.relative_energy_meV < 0.0:
            score += 1.0
        else:
            score -= 0.5

    # ── Geometry flags ──
    problem_flags = [f for f in data.geometry_flags if f not in ("top_above_hf",)]
    for flag in problem_flags:
        insights.append(PhysicsInsight(
            id=f"intercalation.flag_{flag}",
            category="material",
            level=InsightLevel.WARNING,
            message=f"Geometry flag: {flag}.",
        ))
        score -= 1.0

    return insights, max(0.0, min(10.0, score))


# ═══════════════════════════════════════════════════════════════════════════════
# Analyzer ABC subclass
# ═══════════════════════════════════════════════════════════════════════════════


@register_analyzer
class IntercalationSiteAnalyzer(Analyzer):
    """Analyzer wrapping ``extract_intercalation_site_data`` + ``analyze_intercalation_site``."""

    id = "intercalation_site"
    label = "Intercalation site analysis"
    required_patterns = ["**/*.cif", "**/POSCAR", "**/rx.in", "**/vc-relax.in"]
    optional_patterns: list[str] = []

    def __init__(self) -> None:
        self.case_dir: Path | None = None
        self.matched_files: list[Path] = []
        self.score: float = 0.0
        self._data: IntercalationSiteData | None = None

    def discover(self, files: list[Path]) -> list[Path]:
        return _match_files(files, self.required_patterns)

    def parse(self) -> dict[str, Any]:
        assert self.case_dir is not None
        self._data = extract_intercalation_site_data(self.case_dir)
        if self._data is None:
            return {}
        return {
            "site_label": self._data.site_label,
            "stacking_relation": self._data.stacking_relation,
            "inner_X_X_distance_ang": self._data.inner_X_X_distance_ang,
            "m_x_nearest_ang": self._data.m_x_nearest_ang,
            "m_hf_nearest_ang": self._data.m_hf_nearest_ang,
            "m_z_offset_from_midplane_ang": self._data.m_z_offset_from_midplane_ang,
            "m_xy_disp_from_symmetry_ang": self._data.m_xy_disp_from_symmetry_ang,
            "max_force": self._data.max_force,
            "relative_energy_meV": self._data.relative_energy_meV,
            "geometry_flags": list(self._data.geometry_flags),
            "intercalant": self._data.intercalant,
            "formula": self._data.formula,
            "source_files": list(self._data.source_files),
        }

    def summarize(self) -> dict[str, Any]:
        if self._data is None:
            return {"status": "missing"}
        site = self._data.site_label
        if site in ("TOP", "HOLLOW_A", "HOLLOW_B"):
            status = "pass"
        elif "off_center" in self._data.geometry_flags:
            status = "warn"
        else:
            status = "warn"
        return {
            "status": status,
            "site_label": site,
            "stacking_relation": self._data.stacking_relation,
        }

    def insights(self) -> list[PhysicsInsight]:
        ins, score = analyze_intercalation_site(self._data)
        self.score = score
        return ins

    def plots(self) -> list[dict[str, Any]]:
        return []

    def provenance(self) -> dict[str, Any]:
        return {
            "parser": "vibedft.core.intercalation.compute_intercalation_metrics",
            "source_files": list(self._data.source_files) if self._data else [],
        }


__all__ = [
    "IntercalationSiteAnalyzer",
    "extract_intercalation_site_data",
    "analyze_intercalation_site",
]