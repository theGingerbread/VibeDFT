"""Convergence judgment: compare metrics across cases and assess stability."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vibedft.convergence.scanner import CaseSnapshot


@dataclass
class ConvergenceRow:
    """One row in the convergence table — a single case."""
    case_name: str
    case_path: str
    # Parameters
    k_grid: str = ""
    q_grid: str = ""
    ecutwfc: float = 0.0
    degauss: float = 0.0
    el_ph_sigma: float = 0.0
    mustar: float = 0.1
    # Metrics
    lambda_max: float | None = None
    tc_max_K: float | None = None
    omega_log_K: float | None = None
    dos_at_ef: float | None = None
    min_phonon_freq_cm1: float | None = None
    n_imaginary_modes: int | None = None
    scf_converged: bool | None = None
    # Confidence
    confidence: str = "unknown"   # low | medium | high


@dataclass
class ConvergenceReport:
    """Full convergence analysis result."""
    root_dir: str = ""
    rows: list[ConvergenceRow] = field(default_factory=list)
    varying_params: list[str] = field(default_factory=list)  # e.g. ["k_grid", "q_grid"]
    converged_params: list[str] = field(default_factory=list)
    unconverged_params: list[str] = field(default_factory=list)
    overall_confidence: str = "unknown"
    warnings: list[str] = field(default_factory=list)


def analyze_convergence(
    snapshots: list[CaseSnapshot],
    all_params: list[dict[str, Any]],
    all_metrics: list[dict[str, Any]],
) -> ConvergenceReport:
    """Analyze convergence across a batch of cases.

    Compares λ, Tc, ωlog, DOS@EF, and phonon stability across cases
    sorted by k-grid density (primary) or a user-specified parameter.
    """
    report = ConvergenceReport()

    if not snapshots:
        report.warnings.append("No cases to analyze.")
        return report

    # ── Build rows ──
    for snap, params, metrics in zip(snapshots, all_params, all_metrics):
        row = ConvergenceRow(
            case_name=snap.name,
            case_path=snap.path,
            k_grid=_fmt_grid(params, "k"),
            q_grid=_fmt_grid(params, "q"),
            ecutwfc=float(params.get("ecutwfc", 0) or 0),
            degauss=float(params.get("degauss", 0) or 0),
            el_ph_sigma=float(params.get("el_ph_sigma", 0) or 0),
            mustar=float(params.get("mustar", 0.1) or 0.1),
            lambda_max=metrics.get("lambda_max"),
            tc_max_K=metrics.get("tc_max_K"),
            omega_log_K=metrics.get("omega_log_K"),
            dos_at_ef=metrics.get("dos_at_ef"),
            min_phonon_freq_cm1=metrics.get("min_phonon_freq_cm1"),
            n_imaginary_modes=metrics.get("n_imaginary_modes"),
            scf_converged=metrics.get("scf_converged"),
        )
        report.rows.append(row)

    # ── Sort by k-grid density (primary), then q-grid ──
    report.rows.sort(key=lambda r: (_grid_density(r.k_grid), _grid_density(r.q_grid)))

    # ── Detect varying params ──
    if len(set(r.k_grid for r in report.rows)) > 1:
        report.varying_params.append("k_grid")
    if len(set(r.q_grid for r in report.rows)) > 1:
        report.varying_params.append("q_grid")
    if len(set(r.ecutwfc for r in report.rows)) > 1:
        report.varying_params.append("ecutwfc")
    if len(set(r.degauss for r in report.rows)) > 1:
        report.varying_params.append("degauss")
    if len(set(r.el_ph_sigma for r in report.rows)) > 1:
        report.varying_params.append("el_ph_sigma")
    report.root_dir = snapshots[0].path if snapshots else ""

    if not report.varying_params:
        report.warnings.append("No varying parameters detected — is this a convergence scan?")

    # ── Convergence checks on consecutive rows ──
    checks: dict[str, bool] = {"lambda": True, "tc": True, "omega_log": True,
                                 "dos_at_ef": True, "phonon_min": True}

    for i in range(1, len(report.rows)):
        prev, curr = report.rows[i - 1], report.rows[i]

        # λ convergence: Δλ < 0.05 between consecutive
        if prev.lambda_max is not None and curr.lambda_max is not None:
            if abs(curr.lambda_max - prev.lambda_max) >= 0.05:
                checks["lambda"] = False

        # Tc convergence: ΔTc < 0.5 K
        if prev.tc_max_K is not None and curr.tc_max_K is not None:
            if abs(curr.tc_max_K - prev.tc_max_K) >= 0.5:
                checks["tc"] = False

        # ωlog: < 5%
        if prev.omega_log_K is not None and curr.omega_log_K is not None and prev.omega_log_K > 0:
            if abs(curr.omega_log_K - prev.omega_log_K) / prev.omega_log_K >= 0.05:
                checks["omega_log"] = False

        # DOS@EF: < 10%
        if prev.dos_at_ef is not None and curr.dos_at_ef is not None and prev.dos_at_ef > 0.01:
            if abs(curr.dos_at_ef - prev.dos_at_ef) / prev.dos_at_ef >= 0.10:
                checks["dos_at_ef"] = False

        # Phonon min: stable (no new imaginary modes)
        if prev.n_imaginary_modes is not None and curr.n_imaginary_modes is not None:
            if curr.n_imaginary_modes > prev.n_imaginary_modes:
                checks["phonon_min"] = False

    # ── Classify ──
    for key, converged in checks.items():
        if converged:
            report.converged_params.append(key)
        else:
            report.unconverged_params.append(key)

    # ── Assign per-row confidence ──
    for i, row in enumerate(report.rows):
        if i == 0:
            row.confidence = "low"  # first data point — no comparison baseline
            continue

        prev = report.rows[i - 1]
        stable_count = 0
        total = 0
        if row.lambda_max is not None and prev.lambda_max is not None:
            total += 1
            if abs(row.lambda_max - prev.lambda_max) < 0.05:
                stable_count += 1
        if row.tc_max_K is not None and prev.tc_max_K is not None:
            total += 1
            if abs(row.tc_max_K - prev.tc_max_K) < 0.5:
                stable_count += 1

        if total >= 2 and stable_count == total:
            row.confidence = "high"
        elif total >= 1 and stable_count >= 1:
            row.confidence = "medium"
        else:
            row.confidence = "low"

    # ── Overall confidence ──
    if len(report.unconverged_params) == 0 and len(report.converged_params) >= 3:
        report.overall_confidence = "high"
    elif len(report.unconverged_params) <= 1:
        report.overall_confidence = "medium"
    else:
        report.overall_confidence = "low"

    return report


def _fmt_grid(params: dict[str, Any], prefix: str) -> str:
    if prefix == "k":
        return f"{params.get('k_nk1',0)}×{params.get('k_nk2',0)}×{params.get('k_nk3',0)}"
    return f"{params.get('q_nq1',0)}×{params.get('q_nq2',0)}×{params.get('q_nq3',0)}"


def _grid_density(grid_str: str) -> int:
    """Parse 'N1×N2×N3' → N1*N2 as a rough density metric."""
    parts = grid_str.replace("×", "x").split("x")
    if len(parts) >= 2:
        try:
            return int(parts[0]) * int(parts[1])
        except ValueError:
            pass
    return 0
