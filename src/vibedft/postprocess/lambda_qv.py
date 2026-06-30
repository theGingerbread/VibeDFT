"""Compute q-resolved EPC strength λ_qv from freq.gp + elph.gamma.* files.

Formula: λ_qv = γ_qv / (π × N(E_F) × ω_qv²)

This is the direct gamma_qv route. When elph.gamma.* files are unavailable,
use the alternative elph.inp_lambda route via ``elph_extract.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass
class LambdaQvResult:
    """Computed λ_qv per (q-point, mode)."""

    n_qpoints: int
    n_modes: int
    n_ef: float
    lambda_qv: list[list[float]] = field(default_factory=list)
    omega_cm1: list[list[float]] = field(default_factory=list)
    gamma_ghz: list[list[float]] = field(default_factory=list)
    total_lambda: float = 0.0

    @property
    def has_data(self) -> bool:
        return self.n_qpoints > 0 and len(self.lambda_qv) > 0


def parse_elph_gamma(filepath: Path | str, n_q: int | None = None) -> list[list[float]]:
    """Parse a QE ``elph.gamma.{row}`` file into gamma_qv[imode][iq].

    Each data row has format: ``qx qy qz gamma1 gamma2 ... gammaM``
    where M modes share the same q-point.  Multiple consecutive data rows
    with identical q-coordinates are grouped per q-point (the gamma values
    for all modes at one q-point may span multiple physical rows).

    Returns
    -------
    gamma_qv : list of lists
        ``gamma_qv[imode][iq]``, one inner list per mode.
    """
    path = Path(filepath)
    lines = [line.strip() for line in path.read_text().splitlines()
             if line.strip() and not line.strip().startswith("#")]

    # Determine n_q from header or companion freq.gp
    if n_q is None:
        n_q = _count_q_from_freq(path)
    if n_q is None or n_q <= 0:
        raise ValueError(f"Cannot determine n_qpoints from {filepath}")

    # Collect all per-mode gamma values
    data_rows: list[tuple[float, float, float, list[float]]] = []
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            qx, qy, qz = float(parts[0]), float(parts[1]), float(parts[2])
            gammas = [float(x) for x in parts[3:]]
        except ValueError:
            continue
        data_rows.append((qx, qy, qz, gammas))

    if not data_rows:
        raise ValueError(f"No parseable gamma data in {filepath}")

    # Determine n_modes: total gamma values / n_q
    total_values = sum(len(r[3]) for r in data_rows)
    if total_values % n_q != 0:
        raise ValueError(
            f"Gamma file has {total_values} gamma values total, "
            f"not divisible by {n_q} q-points"
        )
    n_modes = total_values // n_q

    gamma_qv: list[list[float]] = [[] for _ in range(n_modes)]

    # Collect by q-point: group rows that share the same q coordinate
    # (within tolerance), respecting sequential order
    current_qx, current_qy = None, None
    current_gammas: list[float] = []
    iq = 0

    def _flush():
        nonlocal iq
        if not current_gammas:
            return
        if len(current_gammas) != n_modes:
            raise ValueError(
                f"q-point {iq}: expected {n_modes} gamma values, "
                f"got {len(current_gammas)}"
            )
        for m in range(n_modes):
            gamma_qv[m].append(current_gammas[m])
        iq += 1

    for qx, qy, _qz, gammas in data_rows:
        if current_qx is None:
            current_qx, current_qy = qx, qy
            current_gammas = list(gammas)
        elif abs(qx - current_qx) < 1e-6 and abs(qy - current_qy) < 1e-6:
            current_gammas.extend(gammas)
        else:
            _flush()
            current_qx, current_qy = qx, qy
            current_gammas = list(gammas)
    _flush()

    if iq != n_q:
        raise ValueError(
            f"Expected {n_q} q-point groups in gamma file, found {iq}"
        )
    return gamma_qv


def compute_lambda_qv(
    freq_gp: Path | str,
    gamma_file: Path | str,
    n_ef: float,
) -> LambdaQvResult:
    """Compute q-resolved λ_qv from frequency and gamma files.

    Parameters
    ----------
    freq_gp :
        Path to a QE ``*.freq.gp`` file (first column = q-distance,
        remaining columns = ω_qv in cm⁻¹).
    gamma_file :
        Path to an ``elph.gamma.{row}`` file.
    n_ef :
        Density of states at the Fermi level N(E_F), in
        states/(spin·Ry·unit cell).

    Returns
    -------
    LambdaQvResult
    """
    freq_path = Path(freq_gp)
    gamma_path = Path(gamma_file)

    omega_cm1_raw = _read_numbers(freq_path)
    if not omega_cm1_raw:
        raise ValueError(f"No data found in {freq_gp}")

    n_q = len(omega_cm1_raw)
    n_modes = len(omega_cm1_raw[0]) - 1   # first column is q-distance

    omega_cm1: list[list[float]] = [[] for _ in range(n_modes)]
    for row in omega_cm1_raw:
        for m in range(n_modes):
            omega_cm1[m].append(abs(row[m + 1]))

    gamma_qv = parse_elph_gamma(gamma_path)

    if len(gamma_qv) != n_modes:
        raise ValueError(
            f"Mode count mismatch: freq.gp has {n_modes} branches, "
            f"gamma has {len(gamma_qv)}"
        )
    for m in range(n_modes):
        if len(gamma_qv[m]) != n_q:
            raise ValueError(
                f"q-point count mismatch for mode {m}: "
                f"freq.gp has {n_q}, gamma has {len(gamma_qv[m])}"
            )

    prefactor = 1.0 / (math.pi * n_ef)
    lambda_qv: list[list[float]] = [[] for _ in range(n_modes)]
    total = 0.0

    for m in range(n_modes):
        for iq in range(n_q):
            w = omega_cm1[m][iq]
            g = gamma_qv[m][iq]
            if w > 1.0e-3:   # acoustic-mode floor — softer modes produce unphysical λ
                val = prefactor * g / (w * w)
            else:
                val = 0.0
            lambda_qv[m].append(val)
            total += val

    return LambdaQvResult(
        n_qpoints=n_q,
        n_modes=n_modes,
        n_ef=n_ef,
        lambda_qv=lambda_qv,
        omega_cm1=omega_cm1,
        gamma_ghz=gamma_qv,
        total_lambda=total,
    )


def write_lambda_qv(result: LambdaQvResult, output: Path | str) -> None:
    """Write λ_qv in wide-matrix format (one row per q-point)."""
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        fh.write(f"# n_ef = {result.n_ef}\n")
        fh.write(f"# n_qpoints = {result.n_qpoints}, n_modes = {result.n_modes}\n")
        fh.write(f"# total_lambda = {result.total_lambda:.6f}\n")
        for iq in range(result.n_qpoints):
            row = [result.lambda_qv[m][iq] for m in range(result.n_modes)]
            fh.write(" ".join(f"{v:.12f}" for v in row) + "\n")


def write_lambda_qv_gp(
    result: LambdaQvResult,
    freq_gp: Path | str,
    output: Path | str,
) -> None:
    """Write λ_qv in three-column GP format (q-distance, ω_cm⁻¹, λ_qv).

    Output is organised by mode, with blank-line separators, suitable
    for the ``qe_plot_lambda_qv_bubble`` plotter.
    """
    freq_path = Path(freq_gp)
    q_dist = [row[0] for row in _read_numbers(freq_path)]

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        fh.write(f"# n_ef = {result.n_ef}\n")
        fh.write(f"# total_lambda = {result.total_lambda:.6f}\n")
        for m in range(result.n_modes):
            for iq in range(result.n_qpoints):
                fh.write(
                    f"{q_dist[iq]:.6f} "
                    f"{result.omega_cm1[m][iq]:.4f} "
                    f"{result.lambda_qv[m][iq]:.12f}\n"
                )
            fh.write("\n")


# ── internal helpers ──


def _read_numbers(path: Path) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        try:
            rows.append([float(x) for x in parts])
        except ValueError:
            continue
    return rows


def _count_q_from_freq(gamma_path: Path) -> int | None:
    """Try to locate a companion freq.gp to count q-points."""
    parent = gamma_path.parent
    candidates = list(parent.glob("*.freq.gp"))
    if not candidates:
        return None
    freq = _read_numbers(candidates[0])
    return len(freq) if freq else None
