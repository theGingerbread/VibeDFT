"""Phonon stability physics analyzer: mode-by-mode imaginary frequency analysis."""

from __future__ import annotations

from pathlib import Path

from vibedft.analyzers.base import (
    Analyzer,
    _match_files,
    register_analyzer,
)
from vibedft.analyzers.physics_models import (
    EvidenceLink,
    InsightLevel,
    PhysicsInsight,
    PhononStabilityData,
)
from vibedft.core.phonon import parse_freq_gp


def extract_phonon_stability_data(case_dir: Path | str) -> PhononStabilityData | None:
    """Extract phonon stability metrics from freq.gp files."""
    d = Path(case_dir)
    freq_files = sorted(d.rglob("*.freq.gp"))
    if not freq_files:
        return None

    # Use the first (or only) grid
    fp = freq_files[0]
    try:
        disp = parse_freq_gp(fp)
    except Exception:
        return None
    if not disp.has_data:
        return None

    data = PhononStabilityData(
        n_qpoints=disp.n_qpoints,
        n_branches=disp.n_branches,
        min_freq_cm1=disp.min_frequency_cm1,
        max_freq_cm1=disp.max_frequency_cm1,
        n_imaginary_total=disp.n_imaginary,
        n_imaginary_non_gamma=disp.n_imaginary_non_gamma,
        source_files=[str(fp)],
    )

    # Classify imaginary modes by q-point location
    n_all = disp.n_qpoints
    gamma_indices = {0}
    if n_all > 1 and disp.q_distances[-1] < 0.001:
        gamma_indices.add(n_all - 1)

    # Approximate M and K points as fractions of the q-path
    # For Γ-M-K-Γ path: M ≈ 1/3, K ≈ 2/3
    m_region = set(range(n_all // 3 - 2, n_all // 3 + 3))
    k_region = set(range(2 * n_all // 3 - 2, 2 * n_all // 3 + 3))

    for m in disp.imaginary_modes:
        qi = m["q_index"]
        entry = {"q_index": qi, "branch": m["branch"], "freq_cm1": m["freq_cm1"]}
        if qi in gamma_indices:
            data.imaginary_at_gamma.append(entry)
        elif qi in m_region:
            data.imaginary_at_M.append(entry)
        elif qi in k_region:
            data.imaginary_at_K.append(entry)
        else:
            data.imaginary_elsewhere.append(entry)

    data.n_imaginary_gamma = len(data.imaginary_at_gamma)
    if disp.imaginary_modes:
        data.largest_imaginary_cm1 = min(m["freq_cm1"] for m in disp.imaginary_modes)

    return data


def analyze_phonon_stability(data: PhononStabilityData | None) -> tuple[list[PhysicsInsight], float]:
    """Produce physics insights and a score (0–10) from phonon stability data."""
    if data is None:
        return [
            PhysicsInsight(
                id="ph.no_data", category="stability",
                level=InsightLevel.NEUTRAL,
                message="No phonon data found — dynamic stability cannot be assessed.",
                detail="Run ph.x with ldisp=.true. and matdyn.x to generate freq.gp.",
            )
        ], 5.0  # neutral — can't judge

    insights: list[PhysicsInsight] = []
    score = 7.0  # start optimistic

    # ── No imaginary modes ──
    if data.n_imaginary_total == 0:
        insights.append(PhysicsInsight(
            id="ph.stable", category="stability",
            level=InsightLevel.POSITIVE,
            message="No imaginary phonon modes — dynamically stable.",
            detail="All phonon branches have positive frequencies across the Brillouin zone.",
        ))
        score += 2.0

    # ── Γ-point only imaginary ──
    elif data.n_imaginary_non_gamma == 0 and data.n_imaginary_gamma > 0:
        worst = min(m["freq_cm1"] for m in data.imaginary_at_gamma)
        if abs(worst) < 5:
            insights.append(PhysicsInsight(
                id="ph.gamma_za_error", category="stability",
                level=InsightLevel.NEUTRAL,
                message=f"Small Γ-point imaginary mode ({worst:.2f} cm⁻¹) — "
                        "likely ZA acoustic sum rule numerical error, not physical instability.",
                detail="2D materials commonly show small Γ-point imaginary modes (< 5 cm⁻¹) "
                       "due to incomplete acoustic sum rule enforcement. This is acceptable.",
                evidence=[EvidenceLink(key="gamma_imaginary", value=worst)],
            ))
            score += 1.0
        else:
            insights.append(PhysicsInsight(
                id="ph.gamma_large_imaginary", category="stability",
                level=InsightLevel.WARNING,
                message=f"Large Γ-point imaginary mode ({worst:.2f} cm⁻¹) — "
                        "unusual for acoustic sum rule error. Check structure.",
                evidence=[EvidenceLink(key="gamma_imaginary", value=worst)],
            ))
            score -= 1.5

    # ── Non-Γ imaginary modes — potential CDW or instability ──
    if data.n_imaginary_non_gamma > 0:
        worst_non_gamma = min(
            (m["freq_cm1"] for m in (data.imaginary_at_M + data.imaginary_at_K + data.imaginary_elsewhere)),
            default=-1,
        )

        # Localization analysis
        if data.imaginary_at_M:
            m_worst = min(m["freq_cm1"] for m in data.imaginary_at_M)
            insights.append(PhysicsInsight(
                id="ph.imaginary_at_M", category="stability",
                level=InsightLevel.WARNING,
                message=f"Imaginary modes at M-point ({m_worst:.2f} cm⁻¹) — "
                        "possible CDW instability or zone-boundary softening.",
                detail="M-point instabilities in 2D hexagonal lattices often indicate "
                       "a Peierls-type distortion. Check the associated eigenvector "
                       "for displacement pattern.",
                evidence=[EvidenceLink(key="imaginary_at_M", value=m_worst)],
            ))
            score -= 2.0

        if data.imaginary_at_K:
            k_worst = min(m["freq_cm1"] for m in data.imaginary_at_K)
            insights.append(PhysicsInsight(
                id="ph.imaginary_at_K", category="stability",
                level=InsightLevel.WARNING,
                message=f"Imaginary modes at K-point ({k_worst:.2f} cm⁻¹) — "
                        "possible √3×√3 reconstruction.",
                evidence=[EvidenceLink(key="imaginary_at_K", value=k_worst)],
            ))
            score -= 2.0

        if data.imaginary_elsewhere:
            other_worst = min(m["freq_cm1"] for m in data.imaginary_elsewhere)
            insights.append(PhysicsInsight(
                id="ph.imaginary_broad", category="stability",
                level=InsightLevel.NEGATIVE,
                message=f"Broad imaginary modes at generic q-points ({other_worst:.2f} cm⁻¹) — "
                        "material is dynamically unstable.",
                detail="Widespread imaginary frequencies indicate the structure is not "
                       "a local energy minimum. Relaxation or supercell may be needed.",
                evidence=[EvidenceLink(key="imaginary_elsewhere", value=other_worst)],
            ))
            score -= 3.5

    # ── Frequency range ──
    if data.max_freq_cm1 > 0:
        insights.append(PhysicsInsight(
            id="ph.freq_range", category="stability",
            level=InsightLevel.NEUTRAL,
            message=f"Phonon frequencies: {data.min_freq_cm1:.1f} – {data.max_freq_cm1:.1f} cm⁻¹ "
                    f"({data.n_qpoints} q-pts × {data.n_branches} branches).",
        ))

    return insights, max(0.0, min(10.0, score))


@register_analyzer
class PhononStabilityAnalyzer(Analyzer):
    """Analyzer wrapping ``extract_phonon_stability_data`` + ``analyze_phonon_stability``."""

    id = "phonon_stability"
    label = "Phonon dynamic stability"
    required_patterns = ["**/*.freq.gp"]
    optional_patterns: list[str] = []

    def __init__(self) -> None:
        self.case_dir: Path | None = None
        self.matched_files: list[Path] = []
        self.score: float = 0.0
        self._data: PhononStabilityData | None = None

    def discover(self, files: list[Path]) -> list[Path]:
        return _match_files(files, self.required_patterns)

    def parse(self) -> dict:
        assert self.case_dir is not None
        self._data = extract_phonon_stability_data(self.case_dir)
        if self._data is None:
            return {}
        return {
            "n_qpoints": self._data.n_qpoints,
            "n_branches": self._data.n_branches,
            "min_freq_cm1": self._data.min_freq_cm1,
            "max_freq_cm1": self._data.max_freq_cm1,
            "n_imaginary_total": self._data.n_imaginary_total,
            "n_imaginary_gamma": self._data.n_imaginary_gamma,
            "n_imaginary_non_gamma": self._data.n_imaginary_non_gamma,
            "largest_imaginary_cm1": self._data.largest_imaginary_cm1,
            "source_files": list(self._data.source_files),
        }

    def summarize(self) -> dict:
        if self._data is None:
            return {"status": "missing"}
        if self._data.n_imaginary_total == 0:
            status = "pass"
        elif self._data.n_imaginary_non_gamma == 0:
            status = "warn"
        else:
            status = "fail"
        return {
            "status": status,
            "n_imaginary_total": self._data.n_imaginary_total,
            "n_imaginary_non_gamma": self._data.n_imaginary_non_gamma,
        }

    def insights(self) -> list[PhysicsInsight]:
        ins, score = analyze_phonon_stability(self._data)
        self.score = score
        return ins

    def plots(self) -> list[dict]:
        return []

    def provenance(self) -> dict:
        return {
            "parser": "vibedft.core.phonon.parse_freq_gp",
            "source_files": list(self._data.source_files) if self._data else [],
        }
