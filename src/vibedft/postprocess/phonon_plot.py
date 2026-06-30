"""Phonon dispersion plot generator."""

from __future__ import annotations

from pathlib import Path

from vibedft.core.phonon import parse_freq_gp, qa_phonon_frequencies
from vibedft.postprocess.artifacts import Artifact


def generate_phonon_plot(
    case_dir: Path | str,
) -> Artifact | None:
    """Generate a phonon dispersion plot from freq.gp files.

    Returns None if no freq.gp data is found.
    """
    d = Path(case_dir)
    freq_files = sorted(d.rglob("*.freq.gp"))
    if not freq_files:
        return None

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # If multiple grids found, plot side by side
    n_grids = len(freq_files)
    n_cols = min(n_grids, 2)
    n_rows = (n_grids + 1) // 2

    fig, axes = plt.subplots(n_rows, n_cols, figsize=(6 * n_cols, 4 * n_rows), squeeze=False)
    src_files: list[str] = []
    all_qa_status: list[str] = []

    for idx, fp in enumerate(freq_files[:4]):  # max 4 grids
        ax = axes[idx // n_cols][idx % n_cols]
        try:
            disp = parse_freq_gp(fp)
            qa = qa_phonon_frequencies(disp)
        except Exception:
            continue

        if not disp.has_data:
            continue

        for ib in range(disp.n_branches):
            freqs = disp.frequencies[ib]
            color = "#f85149" if any(v < 0 for v in freqs) else "#e6edf3"
            ax.plot(disp.q_distances, freqs, color=color, linewidth=0.7)

        ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.5)
        grid_label = _grid_label(fp)
        ax.set_title(f"{grid_label} — {qa.status.upper()}")
        ax.set_xlabel("q-path")
        ax.set_ylabel("Frequency (cm⁻¹)")

        src_files.append(str(fp.relative_to(d)) if fp.is_relative_to(d) else str(fp))
        all_qa_status.append(f"{grid_label}:{qa.status}")

    # Hide unused subplots
    for idx in range(n_grids, n_rows * n_cols):
        axes[idx // n_cols][idx % n_cols].set_visible(False)

    fig.suptitle("Phonon Dispersion", fontsize=13)
    fig.tight_layout()

    return Artifact.figure(
        id="phonon_dispersion", title="Phonon Dispersion",
        fig=fig,
        source_files=src_files,
        provenance={"parser": "parse_freq_gp", "qa": "; ".join(all_qa_status)},
        caption=f"Phonon dispersion for {n_grids} q-grid(s). "
                f"Red = imaginary modes, gray = stable.",
    )


def _grid_label(path: Path) -> str:
    """Extract grid label from path: .../ph64/file → 'ph64'."""
    for part in reversed(path.parts):
        if part in ("ph64", "ph96", "ph48", "sc_ph48", "sc_ph64"):
            return part
    return path.parent.name
