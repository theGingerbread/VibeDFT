"""α²F(ω) + λ(ω) + Tc overlap plot generator."""

from __future__ import annotations

from pathlib import Path

from vibedft.core.tc import parse_lambdax_output
from vibedft.postprocess.artifacts import Artifact


def generate_epc_plot(
    case_dir: Path | str,
) -> Artifact | None:
    """Generate α²F(ω) and λ(ω) plots from lambda.x output.

    Returns None if no lambda.x data is found.
    """
    d = Path(case_dir)
    lambdax_files = sorted(d.rglob("lambdax.out"))

    if not lambdax_files:
        return None

    # Also find alpha2F.dat
    a2f_files = sorted(d.rglob("alpha2F.dat"))
    lambda_dat_files = sorted(d.rglob("lambda.dat"))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    has_a2f = bool(a2f_files)
    has_lambdax = bool(lambdax_files)

    # Determine layout: α²F (if present) + Tc (if present)
    if has_a2f and has_lambdax:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    elif has_a2f:
        fig, ax1 = plt.subplots(figsize=(6, 4.5))
        ax2 = None
    elif has_lambdax:
        fig, ax2 = plt.subplots(figsize=(6, 4.5))
        ax1 = None
    else:
        return None

    src_files: list[str] = []

    # ── α²F(ω) panel ──
    if has_a2f and ax1 is not None:
        for af in a2f_files[:4]:
            label = _grid_label(af)
            data = _parse_a2f_simple(af)
            if data:
                omegas = [r["omega_cm1"] for r in data]
                a2f_vals = [r["a2f"] for r in data]
                ax1.plot(omegas, a2f_vals, linewidth=1.0, label=label)
                src_files.append(str(af.relative_to(d)) if af.is_relative_to(d) else str(af))

        ax1.set_xlabel("ω (cm⁻¹)")
        ax1.set_ylabel("α²F(ω)")
        ax1.set_title("Eliashberg Spectral Function")
        if len(ax1.get_legend_handles_labels()[0]) > 1:
            ax1.legend(fontsize=7)

    # ── Tc(degauss) panel ──
    if has_lambdax and ax2 is not None:
        for lf in lambdax_files[:4]:
            label = _grid_label(lf)
            try:
                lam = parse_lambdax_output(lf)
            except Exception:
                continue
            if lam.has_data:
                valid = [(dg, tc) for dg, tc in zip(lam.degauss_values, lam.tc_values)
                         if tc > 0]
                if valid:
                    dgs, tcs = zip(*valid)
                    ax2.plot(dgs, tcs, "o-", markersize=4, linewidth=1.0, label=label)
                    src_files.append(str(lf.relative_to(d)) if lf.is_relative_to(d) else str(lf))

        ax2.set_xlabel("degauss (Ry)")
        ax2.set_ylabel("Tc (K)")
        ax2.set_title(f"Tc vs Degauss (μ*={lam.mustar})" if has_lambdax else "Tc vs Degauss")
        if len(ax2.get_legend_handles_labels()[0]) > 1:
            ax2.legend(fontsize=7)

    fig.tight_layout()

    return Artifact.figure(
        id="epc_tc", title="EPC: α²F(ω) + Tc",
        fig=fig,
        source_files=src_files,
        provenance={"parser": "parse_lambdax_output"},
        caption="Eliashberg spectral function α²F(ω) and Tc vs. degauss (McMillan-Allen-Dynes).",
    )


def generate_tc_table(
    case_dir: Path | str,
) -> Artifact | None:
    """Extract Tc, λ, ωlog from lambda.x outputs as a table artifact."""
    d = Path(case_dir)
    lambdax_files = sorted(d.rglob("lambdax.out"))
    if not lambdax_files:
        return None

    rows: list[list[str]] = []
    src_files: list[str] = []
    for lf in lambdax_files:
        try:
            lam = parse_lambdax_output(lf)
        except Exception:
            continue
        if not lam.has_data:
            continue
        grid = _grid_label(lf)
        lam_max = max((v for v in lam.lambda_values if v > 0), default=0)
        tc_max = max((v for v in lam.tc_values if v > 0), default=0)
        nan_count = len(lam.nan_rows)
        rows.append([grid, f"{lam_max:.4f}",
                     f"{tc_max:.2f}" if tc_max > 0 else "N/A",
                     str(nan_count), f"{lam.mustar:.2f}"])
        src_files.append(str(lf.relative_to(d)) if lf.is_relative_to(d) else str(lf))

    if not rows:
        return None

    return Artifact.table(
        id="tc_table", title="Superconducting Parameters",
        headers=["Grid", "λ_max", "Tc_max (K)", "NaN rows", "μ*"],
        rows=rows,
        source_files=src_files,
        provenance={"parser": "parse_lambdax_output"},
        caption="Key superconducting parameters extracted from lambda.x output.",
    )


def _parse_a2f_simple(filepath: Path) -> list[dict[str, float]] | None:
    """Minimal parser for QE alpha2F.dat (two-column: omega, a2f)."""
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            rows.append({"omega_cm1": float(parts[0]), "a2f": float(parts[1])})
        except ValueError:
            continue
    return rows[:500] if rows else None


def _grid_label(path: Path) -> str:
    for part in reversed(path.parts):
        if part in ("ph64", "ph96", "ph48", "sc_ph48", "sc_ph64"):
            return part
    return path.parent.name
