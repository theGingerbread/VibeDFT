"""Plotting utilities for VibeDFT post-processing.

Requires matplotlib (optional dependency — CLI will show a clear error
if it is missing).
"""

from __future__ import annotations

from pathlib import Path

from vibedft.core.analysis import parse_bands_output, parse_dos_output, compute_k_distances


def plot_bands_dos(
    *,
    bands_file: Path | str,
    dos_file: Path | str,
    output: Path | str = "bands_dos.png",
    title: str = "Bands + DOS",
    e_fermi_ev: float | None = None,
    e_range: tuple[float, float] | None = None,
) -> Path:
    """Render a combined bands+DOS figure and save to *output*.

    Parameters
    ----------
    bands_file: path to ``HfBr2.bands`` data file
    dos_file: path to ``HfBr2.dos`` data file
    output: output image path
    title: figure title
    e_fermi_ev: override Fermi energy; if None, detected from DOS file header
    e_range: energy range (eV) for the y-axis; if None, auto-detected
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib is required for plotting. Install with: pip install matplotlib"
        ) from exc

    bands = parse_bands_output(bands_file)
    dos = parse_dos_output(dos_file)

    if e_fermi_ev is None:
        e_fermi_ev = dos.e_fermi_ev or 0.0

    k_dists = compute_k_distances(bands.k_points)

    # High-symmetry positions for HfBr2  Γ-M-K-Γ  path
    # The path is:
    #   Γ (0,0,0) → M (0.5,0,0) → K (1/3,1/3,0) → Γ (0,0,0)
    # We compute cumulative distances to find the tick positions.
    gamma_idx = 0
    m_idx: int | None = None
    k_idx: int | None = None
    gamma2_idx = len(k_dists) - 1

    target_m = (0.5, 0.0, 0.0)
    target_k = (1.0 / 3.0, 1.0 / 3.0, 0.0)
    for i, kp in enumerate(bands.k_points):
        if (
            m_idx is None
            and abs(kp[0] - target_m[0]) < 1e-4
            and abs(kp[1] - target_m[1]) < 1e-4
        ):
            m_idx = i
        if (
            k_idx is None
            and abs(kp[0] - target_k[0]) < 1e-4
            and abs(kp[1] - target_k[1]) < 1e-4
        ):
            k_idx = i

    if m_idx is None:
        m_idx = len(k_dists) // 3
    if k_idx is None:
        k_idx = 2 * len(k_dists) // 3

    tick_positions = [
        k_dists[gamma_idx],
        k_dists[m_idx],
        k_dists[k_idx],
        k_dists[gamma2_idx],
    ]
    tick_labels = ["Γ", "M", "K", "Γ"]

    # --- Layout ---
    fig = plt.figure(figsize=(10, 8))
    gs = fig.add_gridspec(1, 2, width_ratios=[3, 1], wspace=0.05)

    # Left panel: bands
    ax_bands = fig.add_subplot(gs[0])
    for ib in range(bands.nbnd):
        energies = [e - e_fermi_ev for e in bands.bands[ib]]
        ax_bands.plot(k_dists, energies, "b-", linewidth=0.8)

    ax_bands.axhline(y=0, color="gray", linestyle="--", linewidth=0.6)

    if e_range:
        ax_bands.set_ylim(e_range[0] - e_fermi_ev, e_range[1] - e_fermi_ev)

    ax_bands.set_xticks(tick_positions)
    ax_bands.set_xticklabels(tick_labels)
    ax_bands.set_xlim(k_dists[0], k_dists[-1])
    for pos in tick_positions[1:-1]:
        ax_bands.axvline(x=pos, color="gray", linestyle=":", linewidth=0.5)
    ax_bands.set_ylabel("E − E_F (eV)")
    ax_bands.set_title(title)

    # Right panel: DOS
    ax_dos = fig.add_subplot(gs[1], sharey=ax_bands)
    energies_dos = [d["energy_ev"] - e_fermi_ev for d in dos.dos_data]
    dos_vals = [d["dos"] for d in dos.dos_data]
    ax_dos.plot(dos_vals, energies_dos, "r-", linewidth=0.8)
    ax_dos.axhline(y=0, color="gray", linestyle="--", linewidth=0.6)
    ax_dos.fill_betweenx(
        energies_dos, 0, dos_vals, alpha=0.15, color="red"
    )
    ax_dos.set_xlabel("DOS (states/eV)")
    ax_dos.tick_params(labelleft=False)

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
