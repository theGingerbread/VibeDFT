"""Plot q-resolved λ_qv bubble chart overlaid on a phonon dispersion.

This is the **formal EPC figure** — not the α²F diagnostic plot.
Each bubble is a (q, ω_qν) point whose area is proportional to
the per-mode electron-phonon coupling strength λ_qν.

Usage as CLI::

    python -m vibedft.postprocess.lambda_qv_plot \\
        --phonon phonon.freq.gp --bubble lambda_qv.gp --out epc_bubble.png

Migrated from ``~/Documents/DFT/scripts/qe_plot_lambda_qv_bubble.py``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

_STYLE = {
    "branch_color": "#5a5a5a",
    "branch_lw": 0.72,
    "vline_color": "#a9a9a9",
    "bubble_color": "red",
    "ylabel_size": 20,
    "xtick_size": 20,
    "ytick_size": 13,
}


def _parse_figsize(text: str) -> tuple[float, float]:
    parts = [x.strip() for x in text.split(",") if x.strip()]
    if len(parts) != 2:
        raise ValueError("--figsize must be like '7.6,5.6'")
    return float(parts[0]), float(parts[1])


def _read_columns(path: Path, skip_comments: bool = True) -> np.ndarray:
    rows: list[list[float]] = []
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s:
            continue
        if skip_comments and s.startswith("#"):
            continue
        parts = s.split()
        try:
            rows.append([float(x) for x in parts])
        except ValueError:
            continue
    if not rows:
        raise RuntimeError(f"No data found in {path}")
    return np.array(rows, dtype=float)


def _infer_ticks(q: np.ndarray) -> list[float]:
    if len(q) < 3:
        return [float(q[0]), float(q[-1])]
    steps = np.diff(q)
    if len(steps) == 0:
        return [float(q[0]), float(q[-1])]
    boundaries = [0]
    ref = steps[0]
    tol = max(1e-6, abs(ref) * 0.2)
    for i in range(1, len(steps)):
        if abs(steps[i] - ref) > tol:
            boundaries.append(i)
            ref = steps[i]
            tol = max(1e-6, abs(ref) * 0.2)
    boundaries.append(len(q) - 1)
    ticks: list[float] = []
    for idx in boundaries:
        value = float(q[idx])
        if not ticks or abs(value - ticks[-1]) > 1e-6:
            ticks.append(value)
    return ticks


def _split_signed(q: np.ndarray, y: np.ndarray):
    """Split a branch into positive (solid) and negative (dashed) segments."""
    pos_x: list[float | None] = []
    pos_y: list[float | None] = []
    neg_x: list[float | None] = []
    neg_y: list[float | None] = []

    def _append(xs, ys, xv, yv):
        if xs and xs[-1] is not None and abs(xs[-1] - xv) < 1e-12 and abs(ys[-1] - yv) < 1e-12:
            return
        xs.append(float(xv))
        ys.append(float(yv))

    def _cut(xs, ys):
        if xs and xs[-1] is not None:
            xs.append(None)
            ys.append(None)

    for i in range(len(q) - 1):
        x0, y0 = float(q[i]), float(y[i])
        x1, y1 = float(q[i + 1]), float(y[i + 1])
        if y0 >= 0.0 and y1 >= 0.0:
            _append(pos_x, pos_y, x0, y0)
            _append(pos_x, pos_y, x1, y1)
        elif y0 <= 0.0 and y1 <= 0.0:
            _append(neg_x, neg_y, x0, y0)
            _append(neg_x, neg_y, x1, y1)
        else:
            x_cross = x0 + (-y0) * (x1 - x0) / (y1 - y0)
            if y0 > 0.0:
                _append(pos_x, pos_y, x0, y0)
                _append(pos_x, pos_y, x_cross, 0.0)
                _cut(pos_x, pos_y)
                _append(neg_x, neg_y, x_cross, 0.0)
                _append(neg_x, neg_y, x1, y1)
            else:
                _append(neg_x, neg_y, x0, y0)
                _append(neg_x, neg_y, x_cross, 0.0)
                _cut(neg_x, neg_y)
                _append(pos_x, pos_y, x_cross, 0.0)
                _append(pos_x, pos_y, x1, y1)
    return pos_x, pos_y, neg_x, neg_y


def plot_lambda_qv_bubble(
    phonon_path: Path | str,
    bubble_path: Path | str,
    output: Path | str,
    *,
    title: str = "",
    doping_label: str = "",
    ticks: str = "",
    tick_labels: str = "G,M,K,G",
    figsize: str = "7.3,5.6",
    dpi: int = 260,
    bubble_max: float = 82.0,
    bubble_min: float = 2.0,
    quantile: float = 0.995,
    bubble_power: float = 1.45,
    threshold_frac: float = 0.028,
) -> str:
    """Create a q-resolved λ_qν bubble chart.

    Parameters
    ----------
    phonon_path : Path
        QE ``*.freq.gp`` file (column 0 = q-distance, 1+ = ω in cm⁻¹).
    bubble_path : Path
        Three-column ``lambda_qv.gp`` file (q-dist, ω, λ_qν).
    output : Path
        Output PNG path.
    title : str
        Figure suptitle.
    doping_label : str
        Short label shown at top centre (alias for *title*).
    ticks : str
        Comma-separated tick positions (auto-detected if empty).
    tick_labels : str
        Comma-separated high-symmetry point labels.
    figsize : str
        ``"width,height"`` in inches.
    dpi : int
        Output resolution.
    bubble_max : float
        Maximum bubble area in pt².
    bubble_min : float
        Minimum visible bubble area in pt².
    quantile : float
        Robust quantile for bubble-size normalisation.
    bubble_power : float
        Exponent controlling mid-size bubble suppression.
    threshold_frac : float
        Suppress bubbles with |λ_qν| below ``threshold_frac * robust_max``.

    Returns
    -------
    str
        Output file path.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "STIXGeneral", "mathtext.fontset": "stix"})

    phonon = _read_columns(Path(phonon_path))
    bubble = _read_columns(Path(bubble_path))
    w, h = _parse_figsize(figsize)

    q = phonon[:, 0]
    tick_positions = (
        [float(x.strip()) for x in ticks.split(",") if x.strip()]
        if ticks
        else _infer_ticks(q)
    )
    labels = [x.strip() for x in tick_labels.split(",") if x.strip()]
    if len(labels) != len(tick_positions):
        labels = (labels + [""] * len(tick_positions))[: len(tick_positions)]
    labels = [r"$\Gamma$" if x in {"G", "Γ", "Gamma"} else x for x in labels]

    fig, ax = plt.subplots(figsize=(w, h), dpi=dpi)

    for j in range(1, phonon.shape[1]):
        pos_x, pos_y, neg_x, neg_y = _split_signed(q, phonon[:, j])
        ax.plot(pos_x, pos_y, color=_STYLE["branch_color"], lw=_STYLE["branch_lw"], zorder=1)
        ax.plot(neg_x, neg_y, color=_STYLE["branch_color"], lw=_STYLE["branch_lw"], zorder=1)

    for xpos in tick_positions[1:-1]:
        ax.axvline(xpos, color=_STYLE["vline_color"], lw=0.6, ls=(0, (3, 3)), zorder=0)

    x = bubble[:, 0]
    y = bubble[:, 1]
    val = np.abs(bubble[:, 2])
    robust_max = float(np.quantile(val, quantile))
    threshold = robust_max * threshold_frac
    mask = val >= threshold

    if robust_max <= 0.0:
        sizes = np.full_like(val, bubble_min)
    else:
        scaled = np.clip(val / robust_max, 0.0, 1.0)
        sizes = bubble_min + (bubble_max - bubble_min) * np.power(scaled, bubble_power)

    ax.scatter(
        x[mask], y[mask],
        s=sizes[mask],
        c=_STYLE["bubble_color"],
        alpha=0.95,
        edgecolors="none",
        zorder=3,
    )

    ax.set_xlim(float(q.min()), float(q.max()))
    ax.set_ylim(0.0, max(float(phonon[:, 1:].max()), float(y.max())) * 1.01)
    ax.set_ylabel(r"Frequency (cm$^{-1}$)", fontsize=_STYLE["ylabel_size"])
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(labels, fontsize=_STYLE["xtick_size"])
    ax.tick_params(axis="y", direction="in", length=6, width=1.0, labelsize=_STYLE["ytick_size"], pad=8)
    ax.tick_params(axis="x", direction="in", length=0, width=1.0, labelsize=_STYLE["xtick_size"], pad=8)
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)

    top_text = title or doping_label
    if top_text:
        fig.suptitle(top_text, y=0.985, fontsize=16)

    fig.subplots_adjust(left=0.14, right=0.98, bottom=0.12, top=0.93)
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    return str(out_path)
