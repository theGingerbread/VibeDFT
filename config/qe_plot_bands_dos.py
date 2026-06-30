#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
qe_plot_bands_dos_v3.py  (EF-locked, strict validation, TDOS/PDOS multi-curves)

Design goals:
- Single energy reference (EF locked): E_plot = E - EF, controlled by --fermi + --*-ref
- Minimal input contract:
  * Bands: gnu blocks with two columns: k  E, separated by blank lines
  * DOS/PDOS: numeric tables (first column energy), optional header lines starting with '#'
- Reproducible layout: left bands, right DOS/PDOS (shared y)
- More rigorous correctness:
  * k-grid consistency check across all bands
  * explicit warnings/errors for likely misuse of --dos-ref/--pdos-ref
  * error if no DOS curves were actually plotted
- Unicode NFKC normalization by default (reduces missing glyph warnings for fullwidth punctuation)

Typical usage (Bands + TDOS):
python qe_plot_bands_dos_v3.py \
  --bands-gnu hfi2.bands.dat.gnu \
  --dos ../scf_dos/hfi2.dos \
  --fermi -5.2334 \
  --dos-ref abs \
  --emin -5 --emax 5 \
  --klabels "G,K,M,G" \
  --knodes "0,50,100,150" \
  --out HfCl2_hole0p25_bands_dos.png \
  --title-prefix "HfCl2(Hole0.25)"

Typical usage (Bands + TDOS + PDOS):
python qe_plot_bands_dos_v3.py \
  --bands-gnu hfi2.bands.dat.gnu \
  --dos ../scf_dos/hfi2.dos \
  --pdos "Hf_d.pdos,I_p.pdos" \
  --pdos-labels "Hf-d,I-p" \
  --pdos-cols "2,2" \
  --fermi -5.2334 \
  --dos-ref abs \
  --pdos-ref abs \
  --emin -5 --emax 5 \
  --klabels "G,K,M,G" \
  --knodes "0,50,100,150" \
  --out HfCl2_hole_0p25_bands_dos.png \
  --title-prefix "HfCl2(Hole0.25)"
"""

import argparse
import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import gridspec


# -------------------------
# Utilities
# -------------------------

def normalize_text(s: str) -> str:
    """Normalize Unicode to NFKC so fullwidth punctuation becomes ASCII.
    Helps avoid missing glyph warnings on clusters with partial fonts.
    """
    if not s:
        return s
    return unicodedata.normalize("NFKC", s)


def prettify_label(lbl: str, unicode_nfkc: bool = True) -> str:
    s = lbl.strip()
    if unicode_nfkc:
        s = normalize_text(s)
    low = s.lower()
    if low in ["g", "gamma", "γ", "Γ"]:
        return r"$\Gamma$"
    return s


def parse_int_list_csv(s: str) -> List[int]:
    """Parse comma-separated integers: "2,3,4" -> [2,3,4]."""
    out: List[int] = []
    if not s:
        return out
    for x in s.split(","):
        x = x.strip()
        if not x:
            continue
        out.append(int(x))
    return out


def parse_cols_expr(expr: str) -> List[int]:
    """Parse a column expression.
    Supports:
      "2" -> [2]
      "2+3+4" -> [2,3,4]
    Column indices are 1-based.
    """
    expr = expr.strip()
    if not expr:
        return []
    parts = [p.strip() for p in expr.split("+") if p.strip()]
    return [int(p) for p in parts]


def setup_ticks_in(ax) -> None:
    ax.tick_params(direction="in", which="both", top=True, right=True, length=5, width=1.0)


# -------------------------
# Bands (gnu blocks)
# -------------------------

def parse_bands_gnu(path: str, kgrid_atol: float = 1e-8) -> Tuple[np.ndarray, np.ndarray]:
    """
    gnu block format:
      k  E
      k  E
      ...
      <blank line>
      (next band)
    return:
      kdist (Nk,)
      energies (Nk, Nb)
    """
    bands_k: List[List[float]] = []
    bands_e: List[List[float]] = []

    k_cur: List[float] = []
    e_cur: List[float] = []

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s:
                if k_cur and e_cur:
                    bands_k.append(k_cur)
                    bands_e.append(e_cur)
                k_cur, e_cur = [], []
                continue

            parts = s.split()
            if len(parts) < 2:
                continue
            try:
                k_val = float(parts[0])
                e_val = float(parts[1])
            except Exception:
                continue
            k_cur.append(k_val)
            e_cur.append(e_val)

    if k_cur and e_cur:
        bands_k.append(k_cur)
        bands_e.append(e_cur)

    if not bands_k:
        raise RuntimeError(f"[ERROR] No band data parsed from: {path}")

    nk = len(bands_k[0])
    for k_list, e_list in zip(bands_k, bands_e):
        if len(k_list) != nk or len(e_list) != nk:
            raise RuntimeError("[ERROR] Inconsistent Nk among bands in gnu file.")

    kdist = np.array(bands_k[0], dtype=float)

    # stricter: ensure all bands share identical k-grid (avoid silent misalignment)
    for j, k_list in enumerate(bands_k[1:], start=1):
        k_other = np.array(k_list, dtype=float)
        if not np.allclose(k_other, kdist, rtol=0.0, atol=kgrid_atol):
            raise RuntimeError(f"[ERROR] Band {j} has a different k-grid than band 0")

    nb = len(bands_e)
    energies = np.zeros((nk, nb), dtype=float)
    for ib, e_list in enumerate(bands_e):
        energies[:, ib] = np.array(e_list, dtype=float)

    return kdist, energies


# -------------------------
# DOS / PDOS reading
# -------------------------

@dataclass
class DosTable:
    data: np.ndarray          # shape (N, M), col0=energy
    ef_header: Optional[float]  # parsed from header "# ... EFermi = x"
    source: str               # filename


_EFERMI_RE = re.compile(r"EFermi\s*=\s*([0-9Ee\+\-\.]+)")

def read_table_with_optional_efermi(path: str) -> DosTable:
    """
    Reads a numeric table where:
      - Comment/header lines start with '#'
      - Numeric lines contain float columns
    Returns DosTable(data, ef_header, source)
    """
    ef_header: Optional[float] = None
    rows: List[List[float]] = []

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("#"):
                m = _EFERMI_RE.search(s)
                if m:
                    try:
                        ef_header = float(m.group(1))
                    except Exception:
                        ef_header = None
                continue

            parts = s.split()
            try:
                row = [float(x) for x in parts]
            except Exception:
                continue
            rows.append(row)

    if not rows:
        raise RuntimeError(f"[ERROR] No valid numeric table parsed from: {path}")

    data = np.array(rows, dtype=float)
    if data.shape[1] < 2:
        raise RuntimeError(f"[ERROR] Table has <2 columns (need energy + DOS). File: {path}")

    return DosTable(data=data, ef_header=ef_header, source=path)


def validate_ref_vs_header(
    ref: str,
    ef_hdr: Optional[float],
    ef_cli: float,
    warn_thresh: float,
    strict: bool,
    tag: str,
    source: str
) -> None:
    """
    Diagnostics:
    - Always report header diff if ef_hdr exists.
    - If ref=='ef0' (no shift) but header EFermi exists, warn/error because typical QE tables are absolute.
    """
    if ef_hdr is not None:
        diff = abs(ef_hdr - ef_cli)
        if diff > warn_thresh:
            msg = (f"{tag} header EFermi={ef_hdr:.6f} differs from --fermi={ef_cli:.6f} by {diff:.6f} eV "
                   f"(source: {source})")
            if strict:
                raise RuntimeError("[ERROR] " + msg)
            print("[WARN] " + msg)
        else:
            print(f"[INFO] {tag} header EFermi={ef_hdr:.6f} diff={diff:.6f} eV (OK)")

        if ref == "ef0":
            msg = (f"{tag}-ref=ef0 disables shifting energies, but header reports EFermi={ef_hdr:.6f} eV. "
                   f"If this is a typical QE dos/projwfc table with absolute energies, you probably want "
                   f"{tag}-ref=abs. (source: {source})")
            if strict:
                raise RuntimeError("[ERROR] " + msg)
            print("[WARN] " + msg)


def apply_energy_reference(data: np.ndarray, ref: str, ef: float) -> np.ndarray:
    """
    Returns a copy of `data` where col0 (energy) is shifted if ref=='abs':
      E_plot = E - EF
    If ref=='ef0', col0 is unchanged.
    """
    out = data.copy()
    if ref == "abs":
        out[:, 0] = out[:, 0] - ef
    elif ref == "ef0":
        out[:, 0] = out[:, 0]
    else:
        raise ValueError("ref must be 'abs' or 'ef0'")
    return out


# -------------------------
# Plotting
# -------------------------

def detect_band_gap_window(e_bands: np.ndarray, fallback_emin: float, fallback_emax: float,
                           gap_max: float = 10.0,
                           margin: float = 0.5) -> Tuple[float, float]:
    """Detect band-gap region and return (emin, emax) showing relevant bands.

    Algorithm:
      1. Find VBM / CBM across all k-points.
      2. Determine a focus energy window:
         - Semiconductor (gap > 0.05 eV): (VBM-4, CBM+4) to capture valence+conduction bands.
         - Metal (gap <= 0.05 eV): (-5, 5) around EF.
      3. Keep only *bands* whose energy range overlaps the focus window
         (excludes flat semi-core / deep states).
      4. Set window = (floor(min_overlapping - margin), ceil(max_overlapping + margin)).
      5. Enforce minimum span of 2 eV.
    """
    nk, nb = e_bands.shape
    local_vbm = np.full(nk, -np.inf)
    local_cbm = np.full(nk, np.inf)

    for ik in range(nk):
        below = e_bands[ik, :][e_bands[ik, :] < 0.0]
        above = e_bands[ik, :][e_bands[ik, :] > 0.0]
        if len(below) > 0:
            local_vbm[ik] = np.max(below)
        if len(above) > 0:
            local_cbm[ik] = np.min(above)

    valid_vbm = local_vbm[np.isfinite(local_vbm) & (local_vbm > -1e6)]
    valid_cbm = local_cbm[np.isfinite(local_cbm) & (local_cbm < 1e6)]

    if len(valid_vbm) == 0 or len(valid_cbm) == 0:
        print("[INFO] auto-window: no clean band edges, using defaults")
        return fallback_emin, fallback_emax

    vbm = float(np.max(valid_vbm))
    cbm = float(np.min(valid_cbm))
    gap = cbm - vbm

    # Determine focus energy window
    gap_min = 0.05  # below this, treat as metal
    if gap > gap_min and gap <= gap_max:
        focus_lo = vbm - 4.0
        focus_hi = cbm + 4.0
        kind = f"semiconductor gap={gap:.4f}"
    else:
        focus_lo = -5.0
        focus_hi = 5.0
        kind = "metal"

    # Select bands overlapping the focus window, excluding deep semi-core states
    band_mins = np.min(e_bands, axis=0)
    band_maxs = np.max(e_bands, axis=0)
    core_cutoff = vbm - 3.0  # bands with entire range below this are semi-core

    visible_energies = []
    for ib in range(nb):
        if band_maxs[ib] < core_cutoff:
            continue  # deep semi-core, skip
        if band_maxs[ib] >= focus_lo and band_mins[ib] <= focus_hi:
            visible_energies.extend(e_bands[:, ib].tolist())

    if not visible_energies:
        print(f"[INFO] auto-window: {kind}, no bands in focus, using defaults")
        return fallback_emin, fallback_emax

    visible = np.array(visible_energies)
    emin_auto = float(np.floor(np.min(visible) - margin))
    emax_auto = float(np.ceil(np.max(visible) + margin))

    # Minimum span
    if emax_auto - emin_auto < 2.0:
        centre = (emin_auto + emax_auto) / 2.0
        emin_auto = float(np.floor(centre - 1.0))
        emax_auto = float(np.ceil(centre + 1.0))

    print(f"[INFO] auto-window: {kind} eV "
          f"-> window=({emin_auto:.0f},{emax_auto:.0f})")
    return emin_auto, emax_auto


def plot_bands_and_dos(
    kdist: np.ndarray,
    e_bands: np.ndarray,
    emin: float,
    emax: float,
    knodes: List[int],
    klabels: List[str],
    title_prefix: str,
    out_png: str,
    dos_curves: List[Tuple[np.ndarray, np.ndarray, str, dict]],  # (x,y,label,style)
    dos_xmax: Optional[float] = None,
    unicode_nfkc: bool = True,
) -> None:
    """
    dos_curves: list of (x, y, label, style_kwargs)
      y is energy (already shifted), x is DOS value
    If dos_curves is empty => band-only plot.
    """
    have_dos = len(dos_curves) > 0

    # layout: band wide, DOS narrow
    band_w, band_h = 8.0, 6.0
    dos_w = band_w * 0.25
    wspace = 0.08

    if have_dos:
        fig = plt.figure(figsize=(band_w + dos_w, band_h))
        gs = gridspec.GridSpec(1, 2, width_ratios=[4, 1], wspace=wspace)
        ax_b = fig.add_subplot(gs[0])
        ax_d = fig.add_subplot(gs[1], sharey=ax_b)
    else:
        fig, ax_b = plt.subplots(figsize=(band_w, band_h))
        ax_d = None

    # bands (red)
    nk, nb = e_bands.shape
    for ib in range(nb):
        y = e_bands[:, ib]
        if np.all(np.isnan(y)):
            continue
        ax_b.plot(kdist, y, color="red", lw=1.4)

    # title
    if unicode_nfkc:
        title_prefix = normalize_text(title_prefix)
    title_band = "Band Structure" if not title_prefix else f"{title_prefix} - Band Structure"
    ax_b.set_title(title_band)

    ax_b.set_ylabel("Energy (eV)")
    ax_b.set_ylim(emin, emax)

    # x-range: follow symmetry path range (knodes first->last), remove side whitespace
    x_min, x_max = kdist[0], kdist[-1]
    if knodes and len(knodes) >= 2:
        k0 = max(0, min(nk - 1, knodes[0]))
        k1 = max(0, min(nk - 1, knodes[-1]))
        x_min, x_max = kdist[k0], kdist[k1]
    ax_b.set_xlim(x_min, x_max)
    ax_b.margins(x=0.0)

    # EF=0 horizontal line
    ax_b.axhline(0.0, ls="--", lw=1.0, color="0.35")

    # symmetry ticks & vertical lines
    if knodes and klabels and len(knodes) == len(klabels):
        valid = [k for k in knodes if 0 <= k < nk]
        if valid:
            xt = [kdist[k] for k in valid]
            xl = [prettify_label(lb, unicode_nfkc=unicode_nfkc) for lb in klabels[:len(valid)]]
            ax_b.set_xticks(xt)
            ax_b.set_xticklabels(xl)
            for x in xt:
                ax_b.axvline(x, ls=":", lw=0.9, color="0.5")

    ax_b.grid(True, axis="both", alpha=0.3)
    setup_ticks_in(ax_b)

    # DOS panel
    if have_dos and ax_d is not None:
        for sp in ax_d.spines.values():
            sp.set_visible(True)

        ax_d.set_title("Density of States")
        ax_d.axhline(0.0, ls="--", lw=1.0, color="0.35")
        ax_d.grid(True, axis="both", alpha=0.3)

        plotted_any = False
        for x, y, label, style in dos_curves:
            if x is None or y is None or len(x) == 0 or len(y) == 0:
                continue
            ax_d.plot(x, y, label=label, **style)
            plotted_any = True

        if not plotted_any:
            raise RuntimeError("[ERROR] DOS panel requested but no curves were plotted.")

        if dos_xmax is None:
            visible_max = 0.0
            for x, y, _label, _style in dos_curves:
                mask = (y >= emin) & (y <= emax) & np.isfinite(x) & np.isfinite(y)
                if np.any(mask):
                    visible_max = max(visible_max, float(np.max(x[mask])))
            dos_xmax = visible_max * 1.05 if visible_max > 0.0 else None

        if dos_xmax is not None:
            ax_d.set_xlim(0.0, dos_xmax)
        else:
            ax_d.set_xlim(left=0.0)
        ax_d.set_xlabel("DOS (states/eV)")
        plt.setp(ax_d.get_yticklabels(), visible=False)
        setup_ticks_in(ax_d)
        ax_d.tick_params(axis="x", bottom=True, labelbottom=True)

        # show legend if multiple labels exist
        labels_present = [c[2] for c in dos_curves if c[2]]
        if len(labels_present) >= 2:
            ax_d.legend(loc="upper right", frameon=True, fontsize=9)

    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.12, top=0.90)
    fig.savefig(out_png, dpi=300)
    print(f"[INFO] Saved: {out_png}")


# -------------------------
# Main
# -------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot QE bands(gnu) with TDOS/PDOS (EF locked, strict validation) [V3]",
        allow_abbrev=False
    )

    parser.add_argument("--bands-gnu", required=True, help="bands gnu file (*.dat.gnu)")
    parser.add_argument("--bands-ref", choices=["abs", "ef0"], default="abs",
                        help="Bands energy reference: abs=shift by EF; ef0=already EF=0 (no shift)")

    parser.add_argument("--fermi", type=float, required=True, help="SCF EF (eV) used as the only zero")
    parser.add_argument("--emin", type=float, default=-4.0)
    parser.add_argument("--emax", type=float, default=4.0)
    parser.add_argument("--auto-window", action="store_true",
                        help="Auto-detect relevant band region. For semiconductors: shows "
                             "valence + conduction bands. For metals: shows bands within "
                             "±5 eV of EF, excluding deep semi-core states.")

    parser.add_argument("--klabels", type=str, default="", help='e.g. "G,K,M,G"')
    parser.add_argument("--knodes", type=str, default="", help='e.g. "0,50,100,150" (indices, not k-values)')

    # TDOS (single file, can plot multiple columns)
    parser.add_argument("--dos", default=None, help="TDOS file (numeric table; col0=E)")
    parser.add_argument("--dos-ref", choices=["abs", "ef0"], default="abs",
                        help="TDOS energy reference: abs=shift by EF; ef0=no shift")
    parser.add_argument("--dos-cols", type=str, default="2",
                        help="1-based TDOS columns to plot from --dos (excluding col1 energy). "
                             "Supports CSV, e.g. '2' or '2,3,4'.")
    parser.add_argument("--dos-labels", type=str, default="",
                        help="comma labels for dos-cols, e.g. 'TDOS,IntDOS,Other'")

    # PDOS (multiple files, each usually one curve)
    parser.add_argument("--pdos", type=str, default="",
                        help="comma-separated PDOS files (numeric tables; col0=E)")
    parser.add_argument("--pdos-ref", choices=["abs", "ef0"], default="abs",
                        help="PDOS energy reference: abs=shift by EF; ef0=no shift")
    parser.add_argument("--pdos-cols", type=str, default="2",
                        help="PDOS columns per file. Either a single expr applied to all files (e.g. '2' or '2+3+4'), "
                             "or CSV list with same length as --pdos files, e.g. '2,2,2' or '2+3,2,2'.")
    parser.add_argument("--pdos-labels", type=str, default="",
                        help="comma labels for PDOS files, same length as --pdos files")

    parser.add_argument("--title-prefix", type=str, default="")
    parser.add_argument("--out", type=str, default="HfI2/Bands_dos/Plot/bands_dos.png")
    parser.add_argument("--dos-xmax", type=float, default=None,
                        help="Fix DOS axis upper limit. Default: auto")

    parser.add_argument("--warn-dos-ef-diff", type=float, default=0.02,
                        help="warn/error if DOS header EFermi differs from --fermi beyond this (eV)")
    parser.add_argument("--strict", action="store_true",
                        help="Treat validation warnings as errors")
    parser.add_argument("--no-unicode-nfkc", action="store_true",
                        help="Disable NFKC unicode normalization for labels/titles")

    args = parser.parse_args()
    unicode_nfkc = (not args.no_unicode_nfkc)

    # ---- bands
    kdist, e_abs = parse_bands_gnu(args.bands_gnu)
    if args.bands_ref == "abs":
        e_bands = e_abs - args.fermi
    else:
        e_bands = e_abs

    # ---- auto energy window (gap detection)
    if args.auto_window:
        args.emin, args.emax = detect_band_gap_window(
            e_bands, args.emin, args.emax,
        )

    # ---- ticks
    klabels = [x.strip() for x in args.klabels.split(",")] if args.klabels else []
    if unicode_nfkc:
        klabels = [normalize_text(x) for x in klabels]
    knodes = parse_int_list_csv(args.knodes)

    # ---- DOS curves to plot (x vs y)
    dos_curves: List[Tuple[np.ndarray, np.ndarray, str, dict]] = []

    # TDOS file (possibly multiple columns)
    if args.dos:
        tdos = read_table_with_optional_efermi(args.dos)
        validate_ref_vs_header(
            ref=args.dos_ref,
            ef_hdr=tdos.ef_header,
            ef_cli=args.fermi,
            warn_thresh=args.warn_dos_ef_diff,
            strict=args.strict,
            tag="DOS",
            source=tdos.source
        )
        tdos_shifted = apply_energy_reference(tdos.data, args.dos_ref, args.fermi)
        e = tdos_shifted[:, 0]

        cols = parse_int_list_csv(args.dos_cols)
        labels = [x.strip() for x in args.dos_labels.split(",") if x.strip()] if args.dos_labels else []

        plotted_any = False
        for i, col in enumerate(cols):
            idx = col - 1
            if idx <= 0 or idx >= tdos_shifted.shape[1]:
                continue
            x = tdos_shifted[:, idx]
            label = labels[i] if (labels and i < len(labels)) else ("TDOS" if i == 0 else f"DOS{col}")
            if unicode_nfkc:
                label = normalize_text(label)
            style = {"lw": 1.3, "color": "black"} if i == 0 else {"lw": 1.2}
            dos_curves.append((x, e, label, style))
            plotted_any = True

        if not plotted_any:
            raise RuntimeError("[ERROR] No TDOS curves were plotted. Check --dos-cols and DOS file column count.")

    # PDOS files (each usually one curve; allow column expression like '2+3' to sum columns)
    pdos_files = [x.strip() for x in args.pdos.split(",") if x.strip()] if args.pdos else []
    if pdos_files:
        # labels per PDOS file
        pdos_labels = [x.strip() for x in args.pdos_labels.split(",") if x.strip()] if args.pdos_labels else []
        if unicode_nfkc:
            pdos_labels = [normalize_text(x) for x in pdos_labels]

        # columns specification
        # - if single token => apply to all files
        # - if multiple tokens separated by comma => must match file count
        pdos_cols_tokens = [x.strip() for x in args.pdos_cols.split(",") if x.strip()] if args.pdos_cols else ["2"]
        if len(pdos_cols_tokens) == 1:
            pdos_cols_tokens = pdos_cols_tokens * len(pdos_files)
        elif len(pdos_cols_tokens) != len(pdos_files):
            raise RuntimeError("[ERROR] --pdos-cols must be either a single expr or match the number of --pdos files.")

        for i, pf in enumerate(pdos_files):
            pd = read_table_with_optional_efermi(pf)
            validate_ref_vs_header(
                ref=args.pdos_ref,
                ef_hdr=pd.ef_header,
                ef_cli=args.fermi,
                warn_thresh=args.warn_dos_ef_diff,
                strict=args.strict,
                tag="PDOS",
                source=pd.source
            )
            pd_shifted = apply_energy_reference(pd.data, args.pdos_ref, args.fermi)
            e = pd_shifted[:, 0]

            cols_to_sum = parse_cols_expr(pdos_cols_tokens[i])
            if not cols_to_sum:
                cols_to_sum = [2]

            # sum selected DOS columns (1-based)
            x_sum = None
            for col in cols_to_sum:
                idx = col - 1
                if idx <= 0 or idx >= pd_shifted.shape[1]:
                    continue
                if x_sum is None:
                    x_sum = pd_shifted[:, idx].copy()
                else:
                    x_sum += pd_shifted[:, idx]

            if x_sum is None:
                raise RuntimeError(f"[ERROR] PDOS file plotted nothing (bad columns). File: {pf}")

            label = pdos_labels[i] if (pdos_labels and i < len(pdos_labels)) else f"PDOS{i+1}"
            # style: default line; let matplotlib cycle colors unless user wants fixed
            style = {"lw": 1.2}
            dos_curves.append((x_sum, e, label, style))

    # ---- title
    title_prefix = args.title_prefix
    if unicode_nfkc:
        title_prefix = normalize_text(title_prefix)

    # ---- plot
    plot_bands_and_dos(
        kdist=kdist,
        e_bands=e_bands,
        emin=args.emin,
        emax=args.emax,
        knodes=knodes,
        klabels=klabels,
        title_prefix=title_prefix,
        out_png=args.out,
        dos_curves=dos_curves,
        dos_xmax=args.dos_xmax,
        unicode_nfkc=unicode_nfkc,
    )


if __name__ == "__main__":
    main()
