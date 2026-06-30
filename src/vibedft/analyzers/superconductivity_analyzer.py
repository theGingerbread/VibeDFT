"""Superconductivity physics analyzer: λ, Tc, α²F interpretation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibedft.analyzers.base import (
    Analyzer,
    _match_files,
    register_analyzer,
)
from vibedft.analyzers.physics_models import (
    EvidenceLink,
    InsightLevel,
    PhysicsInsight,
    SuperconductivityData,
)
from vibedft.core.tc import LambdaOutput, parse_lambdax_output


def _interp_at_degauss(
    degauss_values: list[float],
    y_values: list[float],
    target_degauss: float,
) -> float | None:
    """Nearest-neighbour interpolation of y at target degauss value."""
    if not degauss_values or len(degauss_values) != len(y_values):
        return None
    best_idx = 0
    best_dist = float("inf")
    for i, dg in enumerate(degauss_values):
        dist = abs(dg - target_degauss)
        if dist < best_dist:
            best_dist = dist
            best_idx = i
    return y_values[best_idx] if best_dist < float("inf") else None


def extract_superconductivity_data(case_dir: Path | str) -> SuperconductivityData | None:
    """Extract SC parameters from all lambda.x outputs in a case directory."""
    d = Path(case_dir)
    lambdax_files = sorted(d.rglob("lambdax.out"))
    if not lambdax_files:
        return None

    data = SuperconductivityData()
    all_lambda: list[float] = []
    all_tc: list[float] = []
    mustars: list[float] = []
    omega_logs: list[float] = []
    parsed_outputs: list[LambdaOutput] = []

    for lf in lambdax_files:
        try:
            lam = parse_lambdax_output(lf)
        except Exception:
            continue
        if not lam.has_data:
            continue
        data.source_files.append(str(lf))
        parsed_outputs.append(lam)
        all_lambda.extend(v for v in lam.lambda_values if v > 0)
        all_tc.extend(v for v in lam.tc_values if v > 0)
        omega_logs.extend(v for v in lam.omega_log_values if v > 0)
        mustars.append(lam.mustar)
        data.nan_rows += len(lam.nan_rows)
        data.lambda_values = lam.lambda_values

    if all_lambda:
        data.lambda_max = max(all_lambda)
    if all_tc:
        data.tc_max_K = max(all_tc)
    if omega_logs:
        data.omega_log_K = max(omega_logs)  # typical value
    if mustars:
        data.mustar = mustars[0]

    data.has_two_grids = len(parsed_outputs) >= 2

    # Compute Tc overlap if two grids available
    if data.has_two_grids and len(lambdax_files) >= 2:
        try:
            from vibedft.core.tc import compute_tc_overlap
            overlap = compute_tc_overlap(lambdax_files[0], lambdax_files[1])
            data.tc_overlap_passed = overlap.overlap_status == "pass"
            data.overlap_status = overlap.overlap_status
            data.tc_point_K = overlap.tc_point_k
            data.overlap_degauss_ry = overlap.degauss_ry
            data.overlap_start_degauss = overlap.overlap_start_degauss
            data.overlap_end_degauss = overlap.overlap_end_degauss

            # Compute lambda and omega_log at the overlap degauss point
            if overlap.tc_point_k is not None and overlap.degauss_ry is not None:
                lam_a = _interp_at_degauss(
                    parsed_outputs[0].degauss_values,
                    parsed_outputs[0].lambda_values,
                    overlap.degauss_ry,
                )
                lam_b = _interp_at_degauss(
                    parsed_outputs[1].degauss_values,
                    parsed_outputs[1].lambda_values,
                    overlap.degauss_ry,
                )
                if lam_a is not None and lam_b is not None:
                    data.lambda_at_point = (lam_a + lam_b) / 2.0
                elif lam_a is not None:
                    data.lambda_at_point = lam_a
                elif lam_b is not None:
                    data.lambda_at_point = lam_b

                wlog_a = _interp_at_degauss(
                    parsed_outputs[0].degauss_values,
                    parsed_outputs[0].omega_log_values,
                    overlap.degauss_ry,
                )
                wlog_b = _interp_at_degauss(
                    parsed_outputs[1].degauss_values,
                    parsed_outputs[1].omega_log_values,
                    overlap.degauss_ry,
                )
                if wlog_a is not None and wlog_b is not None:
                    data.omega_log_at_point = (wlog_a + wlog_b) / 2.0
                elif wlog_a is not None:
                    data.omega_log_at_point = wlog_a
                elif wlog_b is not None:
                    data.omega_log_at_point = wlog_b
        except Exception:
            data.tc_overlap_passed = False

    # Check for α²F data
    a2f_files = sorted(d.rglob("alpha2F.dat"))
    data.a2f_available = bool(a2f_files)

    # Dominant frequency range from α²F
    if a2f_files:
        dominant = _dominant_frequency_range(a2f_files[0], data.lambda_max)
        if dominant:
            data.dominant_freq_range, data.dominant_freq_fraction = dominant

    return data


def analyze_superconductivity(data: SuperconductivityData | None) -> tuple[list[PhysicsInsight], float]:
    """Produce physics insights and a score (0–10) from SC data."""
    if data is None:
        return [
            PhysicsInsight(
                id="sc.no_data", category="superconductivity",
                level=InsightLevel.NEUTRAL,
                message="No superconductivity data found — λ and Tc cannot be assessed.",
                detail="Run ph.x with electron_phonon='dvscf' followed by lambda.x.",
            )
        ], 0.0

    insights: list[PhysicsInsight] = []
    score = 5.0  # start neutral

    # ── λ strength ──
    lam = data.lambda_max
    if lam > 2.0:
        insights.append(PhysicsInsight(
            id="sc.strong_coupling", category="superconductivity",
            level=InsightLevel.POSITIVE,
            message=f"λ = {lam:.2f} — strong coupling superconductor.",
            detail="Electron-phonon coupling is strong. Tc may exceed the McMillan limit "
                   "and require Eliashberg-level treatment.",
            evidence=[EvidenceLink(key="lambda_max", value=lam, parser="parse_lambdax_output")],
        ))
        score += 2.0
    elif lam > 1.0:
        insights.append(PhysicsInsight(
            id="sc.moderate_coupling", category="superconductivity",
            level=InsightLevel.POSITIVE,
            message=f"λ = {lam:.2f} — moderate-to-strong coupling.",
            detail="Coupling is sufficient for observable Tc in most 2D materials.",
            evidence=[EvidenceLink(key="lambda_max", value=lam, parser="parse_lambdax_output")],
        ))
        score += 1.5
    elif lam > 0.5:
        insights.append(PhysicsInsight(
            id="sc.weak_coupling", category="superconductivity",
            level=InsightLevel.NEUTRAL,
            message=f"λ = {lam:.2f} — weak coupling.",
            detail="Tc will be low (< 1–2 K typically). Check if k/q-grid convergence "
                   "could increase λ.",
            evidence=[EvidenceLink(key="lambda_max", value=lam, parser="parse_lambdax_output")],
        ))
        score -= 1.0
    elif lam > 0:
        insights.append(PhysicsInsight(
            id="sc.very_weak", category="superconductivity",
            level=InsightLevel.NEGATIVE,
            message=f"λ = {lam:.2f} — very weak coupling, unlikely to superconduct.",
            detail="Tc is expected to be negligible. Consider doping, strain, or "
                   "a different material.",
            evidence=[EvidenceLink(key="lambda_max", value=lam, parser="parse_lambdax_output")],
        ))
        score -= 3.0

    # ── Tc ──
    # Prefer tc_point_K from two-grid overlap when available;
    # fall back to tc_max_K (single-grid) with a warning.
    tc_primary = (
        data.tc_point_K
        if data.tc_point_K is not None and data.tc_overlap_passed
        else data.tc_max_K
    )
    tc_uses_overlap = data.tc_point_K is not None and data.tc_overlap_passed

    if tc_primary > 10:
        label = f"Tc_point = {tc_primary:.1f} K" if tc_uses_overlap else f"Tc_max = {tc_primary:.1f} K"
        insights.append(PhysicsInsight(
            id="sc.tc_high", category="superconductivity",
            level=InsightLevel.POSITIVE,
            message=f"{label} — promising for applications.",
            evidence=[EvidenceLink(key="tc_point_K" if tc_uses_overlap else "tc_max_K",
                                  value=tc_primary, parser="compute_tc_overlap" if tc_uses_overlap else "parse_lambdax_output")],
        ))
        score += 1.5
    elif tc_primary > 1:
        label = f"Tc_point = {tc_primary:.1f} K" if tc_uses_overlap else f"Tc_max = {tc_primary:.1f} K"
        insights.append(PhysicsInsight(
            id="sc.tc_moderate", category="superconductivity",
            level=InsightLevel.NEUTRAL,
            message=f"{label}.",
            evidence=[EvidenceLink(key="tc_point_K" if tc_uses_overlap else "tc_max_K",
                                  value=tc_primary, parser="compute_tc_overlap" if tc_uses_overlap else "parse_lambdax_output")],
        ))
    elif tc_primary > 0:
        label = f"Tc_point = {tc_primary:.2f} K" if tc_uses_overlap else f"Tc_max = {tc_primary:.2f} K"
        insights.append(PhysicsInsight(
            id="sc.tc_low", category="superconductivity",
            level=InsightLevel.NEGATIVE,
            message=f"{label} — very low, may not be observable.",
            evidence=[EvidenceLink(key="tc_point_K" if tc_uses_overlap else "tc_max_K",
                                  value=tc_primary, parser="compute_tc_overlap" if tc_uses_overlap else "parse_lambdax_output")],
        ))
        score -= 1.0

    # ── Two-grid convergence ──
    if data.has_two_grids and data.tc_overlap_passed:
        insights.append(PhysicsInsight(
            id="sc.two_grids_pass", category="superconductivity",
            level=InsightLevel.POSITIVE,
            message="Two k-grids available AND Tc overlap passes — k-point converged.",
            detail="Tc is converged with respect to k-point sampling.",
        ))
        score += 1.5
    elif data.has_two_grids:
        insights.append(PhysicsInsight(
            id="sc.two_grids_fail", category="superconductivity",
            level=InsightLevel.NEGATIVE,
            message="Two k-grids available but Tc overlap FAILS — NOT k-point converged.",
            detail="Tc changes significantly between the two k-grids. "
                   "Increase k/q-point density. Single-grid Tc is NOT publishable.",
        ))
        score -= 3.0  # heavy penalty for failed convergence
    else:
        insights.append(PhysicsInsight(
            id="sc.single_grid", category="superconductivity",
            level=InsightLevel.WARNING,
            message="Only one k-grid found — Tc convergence cannot be confirmed.",
            detail="Run lambda.x on a second k-mesh density for reliable Tc. "
                   "Single-grid Tc is NOT publishable.",
        ))
        score -= 1.5

    # ── Dominant frequency range ──
    if data.dominant_freq_range and data.dominant_freq_fraction > 0.3:
        low, high = data.dominant_freq_range
        frac_pct = data.dominant_freq_fraction * 100
        insights.append(PhysicsInsight(
            id="sc.dominant_freq", category="superconductivity",
            level=InsightLevel.NEUTRAL,
            message=f"Tc primarily from {low:.0f}–{high:.0f} cm⁻¹ phonons ({frac_pct:.0f}% of λ).",
            detail="Low-frequency modes dominate EPC — typical for soft phonon-mediated SC "
                   "in 2D materials. Check these modes for imaginary frequencies.",
            evidence=[EvidenceLink(key="dominant_freq_range", value=f"{low}-{high}"),
                      EvidenceLink(key="dominant_freq_fraction", value=data.dominant_freq_fraction)],
        ))
        score += 0.5

    # ── NaN rows ──
    if data.nan_rows > 0:
        insights.append(PhysicsInsight(
            id="sc.nan_rows", category="superconductivity",
            level=InsightLevel.WARNING,
            message=f"{data.nan_rows} NaN rows in lambda.x output — Tc may be unreliable.",
            detail="Check elph.inp_lambda.* for missing low-frequency EPC matrix elements.",
        ))
        score -= 1.0

    # ── μ* ──
    if data.mustar < 0.05 or data.mustar > 0.25:
        insights.append(PhysicsInsight(
            id="sc.mustar_extreme", category="superconductivity",
            level=InsightLevel.WARNING,
            message=f"μ* = {data.mustar} is outside typical range (0.08–0.15).",
            detail="Reported Tc is sensitive to μ*. Use standard values for comparison.",
        ))

    # ── α²F available ──
    if not data.a2f_available:
        insights.append(PhysicsInsight(
            id="sc.no_a2f", category="superconductivity",
            level=InsightLevel.WARNING,
            message="α²F(ω) data not found — mode-resolved EPC analysis not possible.",
            detail="Ensure lambda.x completed and alpha2F.dat was pulled from the cluster.",
        ))
        score -= 0.5

    return insights, max(0.0, min(10.0, score))


@register_analyzer
class SuperconductivityAnalyzer(Analyzer):
    """Analyzer wrapping ``extract_superconductivity_data`` + ``analyze_superconductivity``."""

    id = "superconductivity"
    label = "Superconductivity (λ/Tc)"
    required_patterns = ["**/lambdax.out"]
    optional_patterns = ["**/alpha2F.dat"]

    def __init__(self) -> None:
        self.case_dir: Path | None = None
        self.matched_files: list[Path] = []
        self.score: float = 0.0
        self._data: SuperconductivityData | None = None

    def discover(self, files: list[Path]) -> list[Path]:
        return _match_files(files, self.required_patterns)

    def parse(self) -> dict:
        assert self.case_dir is not None
        self._data = extract_superconductivity_data(self.case_dir)
        if self._data is None:
            return {}
        result: dict[str, object] = {
            "lambda_max": self._data.lambda_max,
            "lambda_values": list(self._data.lambda_values),
            "omega_log_K": self._data.omega_log_K,
            "tc_max_K": self._data.tc_max_K,
            "mustar": self._data.mustar,
            "has_two_grids": self._data.has_two_grids,
            "tc_overlap_passed": self._data.tc_overlap_passed,
            "a2f_available": self._data.a2f_available,
            "nan_rows": self._data.nan_rows,
            "source_files": list(self._data.source_files),
        }
        if self._data.tc_point_K is not None:
            result["tc_point_K"] = self._data.tc_point_K
            result["overlap_status"] = self._data.overlap_status
            result["overlap_degauss_ry"] = self._data.overlap_degauss_ry
            result["lambda_at_point"] = self._data.lambda_at_point
            result["omega_log_at_point"] = self._data.omega_log_at_point
        return result

    def summarize(self) -> dict:
        if self._data is None:
            return {"status": "missing"}
        lam = self._data.lambda_max
        tc = self._data.tc_max_K

        has_overlap = (
            self._data.tc_point_K is not None
            and self._data.overlap_status == "pass"
        )

        if lam <= 0 and tc <= 0:
            status = "missing"
        elif self._data.has_two_grids and not self._data.tc_overlap_passed:
            status = "fail"
        elif self._data.nan_rows > 0 or not self._data.has_two_grids:
            status = "warn"
        else:
            status = "pass"

        result: dict[str, object] = {
            "status": status,
            "lambda_max": lam,
            "a2f_available": self._data.a2f_available,
        }

        if has_overlap:
            result["tc_point_K"] = self._data.tc_point_K
            result["tc_point_status"] = self._data.overlap_status
            result["lambda_at_point"] = self._data.lambda_at_point
            result["omega_log_at_point"] = self._data.omega_log_at_point
            if self._data.overlap_start_degauss is not None and self._data.overlap_end_degauss is not None:
                result["degauss_range"] = [
                    self._data.overlap_start_degauss,
                    self._data.overlap_end_degauss,
                ]
            if self._data.tc_max_K > 0:
                result["tc_max_K_diagnostic"] = self._data.tc_max_K
        else:
            if self._data.tc_max_K > 0:
                result["tc_max_K"] = self._data.tc_max_K
                result["tc_max_K_warning"] = (
                    "single-grid, not reportable"
                    if not self._data.has_two_grids
                    else "overlap failed, not reportable"
                )

        return result

    def insights(self) -> list[PhysicsInsight]:
        ins, score = analyze_superconductivity(self._data)
        self.score = score
        return ins

    def plots(self) -> list[dict]:
        return []

    def provenance(self) -> dict:
        return {
            "parser": "vibedft.core.tc.parse_lambdax_output",
            "source_files": list(self._data.source_files) if self._data else [],
        }


def _dominant_frequency_range(
    a2f_path: Path, lambda_total: float,
) -> tuple[tuple[float, float], float] | None:
    """Find the frequency range that contributes most to λ.

    λ(ω) = 2 ∫ α²F(ω')/ω' dω'.  We approximate by finding the contiguous
    frequency window that contributes the largest share of total α²F weight.
    """
    try:
        text = a2f_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    rows: list[tuple[float, float]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                rows.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    if len(rows) < 5:
        return None

    omegas = [r[0] for r in rows]
    a2f_vals = [r[1] for r in rows]

    # Integrate α²F to find λ(ω) accumulation
    # λ(ω) ≈ 2 ∫₀^ω α²F(ω')/ω' dω'
    lambda_integral: list[float] = []
    cum = 0.0
    for i, (om, a2f) in enumerate(zip(omegas, a2f_vals)):
        if i > 0 and om > 0:
            d_omega = om - omegas[i - 1]
            cum += 2.0 * a2f / om * d_omega
        lambda_integral.append(cum)

    total = lambda_integral[-1] if lambda_integral else 1.0
    if total < 1e-10:
        return None

    # Find the 25%–75% accumulation window (dominant range)
    target_lo = 0.15 * total
    target_hi = 0.85 * total
    lo_idx = next((i for i, v in enumerate(lambda_integral) if v >= target_lo), 0)
    hi_idx = next((i for i, v in enumerate(lambda_integral) if v >= target_hi), len(omegas) - 1)

    if hi_idx <= lo_idx:
        return None

    fraction = (lambda_integral[hi_idx] - lambda_integral[lo_idx]) / total
    return (omegas[lo_idx], omegas[hi_idx]), fraction
