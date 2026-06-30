"""Convergence report artifacts: tables and trend plots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibedft.convergence.analyzer import ConvergenceReport, ConvergenceRow
from vibedft.postprocess.artifacts import Artifact


def build_convergence_table(report: ConvergenceReport) -> Artifact | None:
    """Build a convergence summary table artifact."""
    if not report.rows:
        return None

    headers = ["Case", "k-grid", "q-grid", "ecut (Ry)", "degauss",
               "λ_max", "Tc (K)", "ωlog (K)", "DOS@EF", "min_freq", "Imag", "Confidence"]
    rows: list[list[str]] = []

    for r in report.rows:
        rows.append([
            r.case_name,
            r.k_grid,
            r.q_grid,
            f"{r.ecutwfc:.0f}" if r.ecutwfc else "—",
            f"{r.degauss:.4f}" if r.degauss else "—",
            f"{r.lambda_max:.4f}" if r.lambda_max is not None else "—",
            f"{r.tc_max_K:.2f}" if r.tc_max_K is not None else "—",
            f"{r.omega_log_K:.1f}" if r.omega_log_K is not None else "—",
            f"{r.dos_at_ef:.3f}" if r.dos_at_ef is not None else "—",
            f"{r.min_phonon_freq_cm1:.1f}" if r.min_phonon_freq_cm1 is not None else "—",
            str(r.n_imaginary_modes) if r.n_imaginary_modes is not None else "—",
            r.confidence.upper(),
        ])

    return Artifact.table(
        id="convergence_table", title="Convergence Summary",
        headers=headers, rows=rows,
        caption=f"Parameter convergence across {len(report.rows)} cases. "
                f"Varying: {', '.join(report.varying_params) if report.varying_params else 'none'}.",
    )


def build_convergence_trend_plot(report: ConvergenceReport) -> Artifact | None:
    """Build a trend plot: λ and Tc vs k-grid density."""
    valid_rows = [r for r in report.rows if r.lambda_max is not None]
    if len(valid_rows) < 2:
        return None

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Sort by k-grid density
    sorted_rows = sorted(valid_rows, key=lambda r: _grid_density(r.k_grid))

    densities = [_grid_density(r.k_grid) for r in sorted_rows]
    lambdas = [r.lambda_max for r in sorted_rows]
    tcs = [r.tc_max_K for r in sorted_rows]

    fig, ax1 = plt.subplots(figsize=(8, 4.5))

    color1 = "#58a6ff"
    ax1.set_xlabel("k-grid density (nk1 × nk2)")
    ax1.set_ylabel("λ", color=color1)
    ax1.plot(densities, lambdas, "o-", color=color1, linewidth=1.5, markersize=6, label="λ")
    ax1.tick_params(axis="y", labelcolor=color1)

    # Label points with k-grid
    for i, r in enumerate(sorted_rows):
        ax1.annotate(r.k_grid, (densities[i], lambdas[i] if lambdas[i] else 0),
                     textcoords="offset points", xytext=(0, 10), fontsize=7, color=color1, ha="center")

    ax2 = ax1.twinx()
    color2 = "#f85149"
    ax2.set_ylabel("Tc (K)", color=color2)
    tc_valid = [(d, t) for d, t in zip(densities, tcs) if t is not None and t > 0]
    if tc_valid:
        d_vals, t_vals = zip(*tc_valid)
        ax2.plot(d_vals, t_vals, "s--", color=color2, linewidth=1.5, markersize=6, label="Tc")
    ax2.tick_params(axis="y", labelcolor=color2)

    fig.suptitle("Convergence: λ and Tc vs k-grid density")
    fig.tight_layout()

    return Artifact.figure(
        id="convergence_trend", title="Convergence Trend: λ & Tc vs k-grid",
        fig=fig,
        caption="λ (left axis, blue) and Tc (right axis, red) as functions of k-mesh density.",
    )


def build_convergence_status_table(report: ConvergenceReport) -> Artifact | None:
    """Build a table showing which parameters have converged."""
    rows: list[list[str]] = []
    for param in ["lambda", "tc", "omega_log", "dos_at_ef", "phonon_min"]:
        status = "✅ Converged" if param in report.converged_params else (
            "❌ Not converged" if param in report.unconverged_params else "— No data"
        )
        label = {"lambda": "λ (EPC constant)", "tc": "Tc (K)",
                 "omega_log": "ωlog (K)", "dos_at_ef": "DOS@EF",
                 "phonon_min": "Phonon stability"}.get(param, param)
        rows.append([label, status])

    return Artifact.table(
        id="convergence_status", title="Convergence Status",
        headers=["Metric", "Status"],
        rows=rows,
        caption=f"Overall confidence: {report.overall_confidence.upper()}. "
                f"{'✅ All metrics converged.' if not report.unconverged_params else '⚠ Some metrics not converged.'}"
    )


def _grid_density(grid_str: str) -> int:
    parts = grid_str.replace("×", "x").split("x")
    if len(parts) >= 2:
        try:
            return int(parts[0]) * int(parts[1])
        except ValueError:
            pass
    return 0
