"""DOS / PDOS plot generator."""

from __future__ import annotations

from pathlib import Path

from vibedft.core.analysis import parse_dos_output, parse_pdos_bundle
from vibedft.postprocess.artifacts import Artifact


def generate_dos_plot(
    case_dir: Path | str,
    *,
    e_fermi_ev: float = 0.0,
    energy_window: tuple[float, float] | None = None,
) -> Artifact | None:
    """Generate a DOS + PDOS plot from a case directory.

    Returns None if no DOS data is found.
    """
    d = Path(case_dir)
    out = d / "output"

    # Find .dos file
    dos_files = sorted(out.rglob("*.dos"))
    dos_file = dos_files[0] if dos_files else None
    if dos_file is None:
        return None

    try:
        dos = parse_dos_output(dos_file)
    except Exception:
        return None

    if not dos.dos_data:
        return None

    # Try PDOS
    pdos_results = None
    try:
        pdos_results = parse_pdos_bundle(out)
    except Exception:
        pass

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 5))

    # TDOS
    energies = [d["energy_ev"] for d in dos.dos_data]
    dos_vals = [d["dos"] for d in dos.dos_data]
    aligned_e = [e - e_fermi_ev for e in energies]
    ax.plot(dos_vals, aligned_e, "r-", linewidth=1.2, label="TDOS")
    ax.fill_betweenx(aligned_e, 0, dos_vals, alpha=0.1, color="red")

    # PDOS (if available — pick top few by max value)
    if pdos_results:
        pdos_sorted = sorted(pdos_results, key=lambda p: max(d["dos"] for d in p.data) if p.data else 0, reverse=True)
        colors = ["#58a6ff", "#3fb950", "#d2991d", "#bc8cff", "#ff7b72"]
        for i, p in enumerate(pdos_sorted[:8]):
            if not p.data:
                continue
            p_energies = [d["energy_ev"] - e_fermi_ev for d in p.data]
            p_dos = [d["dos"] for d in p.data]
            ax.plot(p_dos, p_energies, color=colors[i % len(colors)], linewidth=0.6, alpha=0.7, label=_shorten_label(p.label))

    # EF line
    ax.axhline(y=0, color="gold", linestyle="--", linewidth=1.0, alpha=0.8)

    if energy_window:
        ax.set_ylim(*energy_window)
    elif dos.e_min is not None and dos.e_max is not None:
        margin = (dos.e_max - dos.e_min) * 0.05
        ax.set_ylim(dos.e_min - e_fermi_ev - margin, dos.e_max - e_fermi_ev + margin)

    ax.set_xlabel("DOS (states/eV)")
    ax.set_ylabel("E − EF (eV)")
    ax.set_title(f"DOS / PDOS — EF = {e_fermi_ev:.4f} eV")

    if len(ax.get_legend_handles_labels()[0]) > 1:
        ax.legend(fontsize=7, loc="upper right")

    fig.tight_layout()

    src_files = [str(dos_file.relative_to(d)) if dos_file.is_relative_to(d) else str(dos_file)]

    return Artifact.figure(
        id="dos_pdos", title="DOS / PDOS",
        fig=fig,
        source_files=src_files,
        provenance={"parser": "parse_dos_output", "e_fermi_ev": str(e_fermi_ev)},
        caption=f"Total DOS + atom/orbital-projected PDOS.",
    )


def _shorten_label(label: str) -> str:
    """Shorten PDOS file-name labels for legend readability."""
    # e.g. HfBr2.pdos.pdos_atm#1(Hf)_wfc#4(d) → Hf-d
    import re
    m_atm = re.search(r"\((\w+)\)", label)
    m_wfc = re.search(r"\((\w)\)", label)
    if m_atm and m_wfc:
        return f"{m_atm.group(1)}-{m_wfc.group(1)}"
    return label[:20]
