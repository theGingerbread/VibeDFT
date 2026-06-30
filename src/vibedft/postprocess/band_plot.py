"""Band structure plot generator."""

from __future__ import annotations

from pathlib import Path

from vibedft.core.analysis import parse_bands_output, compute_k_distances
from vibedft.core.kpath import detect_high_symmetry
from vibedft.postprocess.artifacts import Artifact


def generate_band_plot(
    case_dir: Path | str,
    *,
    e_fermi_ev: float = 0.0,
    energy_window: tuple[float, float] | None = None,
) -> Artifact | None:
    """Generate a band structure plot from a case directory.

    Returns None if no bands data is found.
    """
    d = Path(case_dir)
    out = d / "output"

    # Find bands file — prefer .gnu format, then any bands data file
    bands_files = sorted(out.rglob("*bands*"))
    main_bands = [f for f in bands_files if "GA" not in f.name.upper() and "pdos" not in f.name.lower()]
    best = main_bands[0] if main_bands else (bands_files[0] if bands_files else None)

    if best is None:
        return None

    try:
        parsed = parse_bands_output(best)
        k_dists = compute_k_distances(parsed.k_points)
        hs = detect_high_symmetry(parsed.k_points, k_dists)
    except Exception:
        return None

    if not parsed.bands:
        return None

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))

    for ib, energies in enumerate(parsed.bands):
        aligned = [e - e_fermi_ev for e in energies]
        ax.plot(k_dists, aligned, "b-", linewidth=0.7)

    # EF line
    ax.axhline(y=0, color="gold", linestyle="--", linewidth=1.0, alpha=0.8)

    # High-symmetry labels
    if hs:
        for h in hs:
            ax.axvline(x=h["distance"], color="gray", linestyle=":", linewidth=0.5)
        tick_pos = [h["distance"] for h in hs]
        tick_lab = [h["label"] for h in hs]
        ax.set_xticks(tick_pos)
        ax.set_xticklabels(tick_lab)
        ax.set_xlim(k_dists[0], k_dists[-1])

    if energy_window:
        ax.set_ylim(*energy_window)

    ax.set_ylabel("E − EF (eV)")
    ax.set_title(f"Band Structure — {parsed.nbnd} bands, {parsed.nks} k-points")
    fig.tight_layout()

    src_files = [str(best.relative_to(d)) if best.is_relative_to(d) else str(best)]

    return Artifact.figure(
        id="band_structure", title="Band Structure",
        fig=fig,
        source_files=src_files,
        provenance={"parser": "parse_bands_output", "e_fermi_ev": str(e_fermi_ev)},
        caption=f"{parsed.nbnd} bands along Γ-M-K-Γ high-symmetry path.",
    )
