"""MaterialReport and typed physics insight data models.

Every insight carries evidence links back to source files and parsers,
so the HTML report and future LLM layer can trace every claim.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════════
# Insight level
# ═══════════════════════════════════════════════════════════════════════════════


class InsightLevel(str, enum.Enum):
    POSITIVE = "positive"    # good news (e.g. "strong coupling", "stable")
    NEGATIVE = "negative"    # bad news (e.g. "CDW instability suspected")
    NEUTRAL = "neutral"      # factual observation
    WARNING = "warning"      # concerning but not fatal


# ═══════════════════════════════════════════════════════════════════════════════
# Evidence link
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class EvidenceLink:
    """Traceable link from an insight back to source data."""
    source_file: str = ""
    parser: str = ""
    key: str = ""          # e.g. "dos_at_ef", "lambda_max"
    value: Any = None


# ═══════════════════════════════════════════════════════════════════════════════
# Physics insight
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class PhysicsInsight:
    """One physics-level finding with evidence."""
    id: str
    category: str          # "superconductivity", "stability", "electronic", "material", "workflow_health"
    level: InsightLevel = InsightLevel.NEUTRAL
    message: str = ""
    detail: str = ""       # longer explanation for the report
    evidence: list[EvidenceLink] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Material report (top-level container)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class MaterialReport:
    """Physics-level assessment of a 2D material calculation.

    Scores are 0.0–10.0 where higher is better.
    """
    material: str = ""
    case_dir: str = ""

    # ── Scores ──
    stability_score: float = 0.0
    electronic_score: float = 0.0
    superconductivity_score: float = 0.0
    workflow_confidence: float = 0.0

    # ── Overall verdict ──
    overall_verdict: str = ""       # one-line summary
    recommendation: str = ""        # "continue", "convergence_test", "abandon", "needs_review"

    # ── Findings ──
    insights: list[PhysicsInsight] = field(default_factory=list)

    # ── Key values (for quick reference) ──
    key_values: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "material": self.material,
            "case_dir": self.case_dir,
            "scores": {
                "stability": self.stability_score,
                "electronic": self.electronic_score,
                "superconductivity": self.superconductivity_score,
                "workflow_confidence": self.workflow_confidence,
            },
            "overall_verdict": self.overall_verdict,
            "recommendation": self.recommendation,
            "key_values": self.key_values,
            "insights": [
                {
                    "id": i.id, "category": i.category,
                    "level": i.level.value, "message": i.message,
                    "detail": i.detail,
                    "evidence": [
                        {"source_file": e.source_file, "parser": e.parser,
                         "key": e.key, "value": str(e.value)}
                        for e in i.evidence
                    ],
                }
                for i in self.insights
            ],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Domain-specific data classes (used internally by analyzers)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SuperconductivityData:
    """Extracted SC parameters from lambda.x outputs."""
    lambda_max: float = 0.0
    lambda_values: list[float] = field(default_factory=list)
    omega_log_K: float = 0.0
    tc_max_K: float = 0.0
    tc_point_K: float | None = None   # from two-grid overlap
    mustar: float = 0.1
    has_two_grids: bool = False
    tc_overlap_passed: bool = False
    overlap_status: str = "unknown"     # "pass", "fail", "single_grid", "no_data", "warn_nan"
    overlap_degauss_ry: float | None = None   # degauss at overlap mid-point
    overlap_start_degauss: float | None = None
    overlap_end_degauss: float | None = None
    lambda_at_point: float | None = None   # lambda at overlap degauss point
    omega_log_at_point: float | None = None  # omega_log at overlap degauss point
    a2f_available: bool = False
    dominant_freq_range: tuple[float, float] | None = None  # (low_cm1, high_cm1)
    dominant_freq_fraction: float = 0.0  # fraction of total λ from dominant range
    nan_rows: int = 0
    source_files: list[str] = field(default_factory=list)


@dataclass
class PhononStabilityData:
    """Extracted phonon stability metrics."""
    n_qpoints: int = 0
    n_branches: int = 0
    min_freq_cm1: float = 0.0
    max_freq_cm1: float = 0.0
    n_imaginary_total: int = 0
    n_imaginary_gamma: int = 0
    n_imaginary_non_gamma: int = 0
    largest_imaginary_cm1: float = 0.0
    # Per-q-point imaginary mode details
    imaginary_at_gamma: list[dict[str, Any]] = field(default_factory=list)
    imaginary_at_M: list[dict[str, Any]] = field(default_factory=list)
    imaginary_at_K: list[dict[str, Any]] = field(default_factory=list)
    imaginary_elsewhere: list[dict[str, Any]] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)


@dataclass
class ElectronicData:
    """Extracted electronic structure metrics."""
    dos_at_ef: float = 0.0
    fermi_energy_ev: float = 0.0
    band_gap_ev: float | None = None
    gap_type: str = "unknown"      # direct, indirect, metallic
    is_metallic: bool = False
    van_hove_near_ef: list[dict[str, Any]] = field(default_factory=list)
    dominant_orbital_near_ef: str = ""
    dominant_orbital_fraction: float = 0.0
    source_files: list[str] = field(default_factory=list)


@dataclass
class IntercalationSiteData:
    """Extracted intercalation-site geometry metrics.

    Wraps :class:`vibedft.core.intercalation.IntercalationMetrics` plus
    provenance so the analyzer protocol can serialise it.
    """
    site_label: str = "off-center"
    stacking_relation: str = "unknown"
    inner_X_X_distance_ang: float = 0.0
    m_x_nearest_ang: float = 0.0
    m_hf_nearest_ang: float = 0.0
    m_z_offset_from_midplane_ang: float = 0.0
    m_xy_disp_from_symmetry_ang: float = 0.0
    max_force: float = 0.0
    relative_energy_meV: float = 0.0
    geometry_flags: list[str] = field(default_factory=list)
    intercalant: str = ""
    host_cation: str = "Hf"
    host_anion: str = "Cl"
    formula: str = ""
    source_files: list[str] = field(default_factory=list)
