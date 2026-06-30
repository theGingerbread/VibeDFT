"""Phonon analysis: freq.gp parsing, virtual-frequency QA, phDOS support.

Handles QE matdyn.x freq.gp output format (multi-column q-path phonon
dispersion) and related quality assurance.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vibedft.core.phonon_modes import PhononMode


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PhononDispersion:
    """Parsed phonon dispersion from QE matdyn.x freq.gp."""

    n_qpoints: int = 0
    n_branches: int = 0
    q_distances: list[float] = field(default_factory=list)    # cumulative q-path distance
    frequencies: list[list[float]] = field(default_factory=list)  # freq[ibranch][iq] in cm⁻¹
    min_frequency_cm1: float = 0.0
    max_frequency_cm1: float = 0.0
    imaginary_modes: list[dict[str, Any]] = field(default_factory=list)
    """Imaginary modes: [{'q_index': int, 'branch': int, 'freq_cm1': float}, ...]."""
    has_data: bool = False

    @property
    def n_imaginary(self) -> int:
        return len(self.imaginary_modes)

    @property
    def n_imaginary_non_gamma(self) -> int:
        """Imaginary modes at non-Γ q-points (physically dangerous)."""
        n = len(self.q_distances)
        gamma_indices = {0}
        if n > 1 and self.q_distances[-1] < 0.001:
            gamma_indices.add(n - 1)
        return sum(1 for m in self.imaginary_modes if m["q_index"] not in gamma_indices)

    def summary(self) -> str:
        lines = [
            f"Phonon Dispersion: {self.n_qpoints} q-points × {self.n_branches} branches",
            f"Frequency range: {self.min_frequency_cm1:.2f} — {self.max_frequency_cm1:.2f} cm⁻¹",
            f"Imaginary modes: {self.n_imaginary} total, {self.n_imaginary_non_gamma} non-Γ",
        ]
        if self.imaginary_modes:
            lines.append("Imaginary mode details:")
            for m in self.imaginary_modes[:10]:
                lines.append(
                    f"  q[{m['q_index']}] branch {m['branch']}: "
                    f"{m['freq_cm1']:.3f} cm⁻¹"
                )
            if len(self.imaginary_modes) > 10:
                lines.append(f"  ... and {len(self.imaginary_modes) - 10} more")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parser: freq.gp
# ---------------------------------------------------------------------------


def parse_freq_gp(filepath: Path | str) -> PhononDispersion:
    """Parse a QE matdyn.x freq.gp phonon dispersion file.

    Format::
        # header line (optional)
        q_dist_1  freq_1_1  freq_1_2  ...  freq_1_N
        q_dist_2  freq_2_1  freq_2_2  ...  freq_2_N
        ...

    First column: q-path distance (dimensionless or Å⁻¹)
    Remaining columns: phonon frequencies in cm⁻¹ (negative = imaginary)
    """
    path = Path(filepath)
    if not path.is_file():
        return PhononDispersion()

    text = path.read_text(encoding="utf-8", errors="replace")
    result = PhononDispersion()

    q_dists = []
    all_freqs = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("@"):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        try:
            q = float(parts[0])
            freqs = [float(v) for v in parts[1:]]
        except ValueError:
            continue

        q_dists.append(q)
        all_freqs.append(freqs)

    if not q_dists:
        return result

    result.q_distances = q_dists
    result.n_qpoints = len(q_dists)
    result.n_branches = len(all_freqs[0]) if all_freqs else 0

    # Transpose to per-branch arrays
    result.frequencies = [
        [all_freqs[iq][ib] for iq in range(result.n_qpoints)]
        for ib in range(result.n_branches)
    ]

    # Global stats
    all_vals = [v for freqs in all_freqs for v in freqs]
    result.min_frequency_cm1 = min(all_vals) if all_vals else 0.0
    result.max_frequency_cm1 = max(all_vals) if all_vals else 0.0

    # Detect imaginary modes
    for iq in range(result.n_qpoints):
        for ib in range(result.n_branches):
            f = result.frequencies[ib][iq]
            if f < 0:
                result.imaginary_modes.append({
                    "q_index": iq,
                    "branch": ib + 1,
                    "freq_cm1": f,
                    "abs_freq_cm1": abs(f),
                })

    result.has_data = True
    return result


# ---------------------------------------------------------------------------
# Virtual-frequency QA
# ---------------------------------------------------------------------------


@dataclass
class PhononQaResult:
    """QA result for phonon calculation."""

    status: str = "pass"  # pass | warn | fail
    checks: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Phonon QA: {self.status.upper()}"]
        for c in self.checks:
            icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}.get(c.get("status", "?"), "?")
            lines.append(f"  {icon} [{c.get('id', '?')}] {c.get('message', '')}")
        return "\n".join(lines)


def qa_phonon_frequencies(
    dispersion: PhononDispersion,
    *,
    gamma_imaginary_threshold_cm1: float = 5.0,
    gamma_indices: set[int] | None = None,
) -> PhononQaResult:
    """Run virtual-frequency QA on phonon dispersion data.

    Rules (from DFT STANDARDS.md §4.2):
    - Γ-point imaginary modes < 5 cm⁻¹ → warn (acceptable for 2D acoustic sum rule)
    - Non-Γ imaginary modes → fail (dynamically unstable)
    - No imaginary modes → pass
    """
    result = PhononQaResult()
    if gamma_indices is None:
        n = len(dispersion.q_distances)
        gamma_indices = {0}
        if n > 1 and dispersion.q_distances[-1] < 0.001:
            gamma_indices.add(n - 1)

    if dispersion.n_imaginary == 0:
        result.checks.append({
            "id": "phonon.freq.imaginary",
            "status": "pass",
            "message": "No imaginary modes detected",
        })
        return result

    gamma_imaginary = [m for m in dispersion.imaginary_modes if m["q_index"] in gamma_indices]
    non_gamma_imaginary = [m for m in dispersion.imaginary_modes if m["q_index"] not in gamma_indices]

    if non_gamma_imaginary:
        result.status = "fail"
        modes_str = ", ".join(
            f"q[{m['q_index']}] b{m['branch']}={m['freq_cm1']:.2f}"
            for m in non_gamma_imaginary[:5]
        )
        result.checks.append({
            "id": "phonon.freq.imaginary.non_gamma",
            "status": "fail",
            "message": f"{len(non_gamma_imaginary)} non-Γ imaginary modes → dynamically unstable",
            "detail": modes_str,
        })

    if gamma_imaginary:
        large_gamma = [m for m in gamma_imaginary if abs(m["freq_cm1"]) > gamma_imaginary_threshold_cm1]
        if large_gamma:
            result.status = "fail"
            result.checks.append({
                "id": "phonon.freq.imaginary.gamma_large",
                "status": "fail",
                "message": f"Large Γ-point imaginary modes (> {gamma_imaginary_threshold_cm1} cm⁻¹)",
                "detail": ", ".join(f"{m['freq_cm1']:.2f}" for m in large_gamma),
            })
        else:
            if result.status != "fail":
                result.status = "warn"
            result.checks.append({
                "id": "phonon.freq.imaginary.gamma_small",
                "status": "warn",
                "message": (
                    f"{len(gamma_imaginary)} small Γ-point imaginary modes "
                    f"(< {gamma_imaginary_threshold_cm1} cm⁻¹) — acceptable for 2D acoustic sum rule"
                ),
            })

    if not result.checks:
        result.checks.append({
            "id": "phonon.freq.imaginary",
            "status": "pass",
            "message": "All checks passed",
        })

    return result


# ---------------------------------------------------------------------------
# Parser: dynmat.x output  (per-q mode frequencies + IR activities)
# ---------------------------------------------------------------------------


@dataclass
class DynmatOutput:
    """Parsed mode frequencies and IR activities from a QE dynmat.x output.

    dynmat.x does not print a ``Program DYNMAT`` header in many QE builds;
    detection falls back to the ``diagonalizing the dynamical matrix``
    marker. Frequencies are stored as QE prints them — imaginary modes
    are negative in both cm⁻¹ and THz.
    """

    q_point: list[float] = field(default_factory=list)
    """3-component q-vector parsed from the ``q =`` line."""
    frequencies_cm1: list[float] = field(default_factory=list)
    frequencies_thz: list[float] = field(default_factory=list)
    ir_activities: list[float] = field(default_factory=list)
    """IR activities in (D/A)^2/amu units, ordered by mode index."""
    n_modes: int = 0
    has_imaginary: bool = False
    source_file: str = ""

    def summary(self) -> str:
        lines = [
            f"dynmat.x output : {self.source_file}",
            f"q-point         : {self.q_point}",
            f"n_modes         : {self.n_modes}",
            f"has_imaginary   : {self.has_imaginary}",
        ]
        if self.frequencies_cm1:
            lines.append(
                f"freq range      : {min(self.frequencies_cm1):.2f} — "
                f"{max(self.frequencies_cm1):.2f} cm⁻¹"
            )
        if self.ir_activities:
            lines.append(f"IR activities   : {len(self.ir_activities)} values")
        return "\n".join(lines)


def parse_dynmat_output(filepath: Path | str) -> DynmatOutput | None:
    """Parse a QE dynmat.x output file into per-q mode frequencies + IR.

    Parses the ``freq ( N) = ... [THz] = ... [cm-1]`` lines for the
    frequency spectrum and the ``# mode [cm-1] [THz] IR`` table for IR
    activities. ``has_imaginary`` is True if any cm⁻¹ frequency is
    negative.

    Returns ``None`` if the file is missing or is not a dynmat.x output
    (no ``diagonalizing the dynamical matrix`` marker and no
    ``freq (`` lines).
    """
    path = Path(filepath)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")

    if "diagonalizing the dynamical matrix" not in text and "freq (" not in text:
        return None

    result = DynmatOutput(source_file=str(path))

    m = re.search(r"q\s*=\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", text)
    if m:
        result.q_point = [float(m.group(1)), float(m.group(2)), float(m.group(3))]

    freq_re = re.compile(
        r"freq\s*\(\s*(\d+)\s*\)\s*=\s*([-\d.]+)\s*\[THz\]\s*=\s*([-\d.]+)\s*\[cm-1\]"
    )
    for fm in freq_re.finditer(text):
        result.frequencies_thz.append(float(fm.group(2)))
        result.frequencies_cm1.append(float(fm.group(3)))

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "# mode" in line and "IR" in line:
            for j in range(i + 1, len(lines)):
                dline = lines[j]
                if not dline.strip():
                    continue
                dm = re.match(
                    r"\s*(\d+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", dline
                )
                if dm:
                    result.ir_activities.append(float(dm.group(4)))
                else:
                    break
            break

    result.n_modes = len(result.frequencies_cm1)
    result.has_imaginary = any(f < 0 for f in result.frequencies_cm1)
    return result


# ---------------------------------------------------------------------------
# Parser: ph.x dyn eigenvectors  (per-q mode frequencies + complex eigenvectors)
# ---------------------------------------------------------------------------

# Atom eigenvector line in dyn files: 6 floats (re,im pairs for x,y,z)
# "      (    1) H   0.123456  0.000000  0.123456  0.000000  0.123456  0.000000"
_DYN_ATOM_RE = re.compile(
    r"\(\s*(\d+)\s*\)\s*(\w+)\s+"
    r"([-\d.]+)\s+([-\d.]+)\s+"   # ux_re, ux_im
    r"([-\d.]+)\s+([-\d.]+)\s+"   # uy_re, uy_im
    r"([-\d.]+)\s+([-\d.]+)"      # uz_re, uz_im
)


def parse_dyn_eigenvectors(filepath: Path | str) -> list[PhononMode]:
    """Parse eigenvectors from a QE ph.x dyn file.

    The dyn file format has a header with cell + atom positions, then a
    ``Diagonalizing the dynamical matrix`` section, then per-q-point::

         q =  0.0000  0.0000  0.0000

         freq (    1) =   -0.123456 [THz] =   -4.123456 [cm-1]
         (    1) H   0.123456  0.000000  0.123456  0.000000  0.123456  0.000000
         (    2) H  -0.123456  0.000000  -0.123456  0.000000  -0.123456  0.000000
         ...

    Each atom line carries 6 floats: ``(ux_re, ux_im, uy_re, uy_im, uz_re, uz_im)``.
    The displacement magnitude ``sqrt(re^2 + im^2)`` is used for each component
    so the resulting :class:`PhononMode` objects match the same dataclass format
    as :func:`vibedft.core.phonon_modes.parse_matdyn_modes`.

    Returns an empty list if the file is missing or contains no eigenvector
    blocks.
    """
    from vibedft.core.phonon_modes import (
        AtomDisplacement,
        _build_phonon_mode,
    )

    path = Path(filepath)
    if not path.is_file():
        return []

    text = path.read_text(encoding="utf-8", errors="replace")

    # Require the diagonalization marker or at least freq lines
    if "diagonalizing the dynamical matrix" not in text and "freq (" not in text:
        return []

    lines = text.splitlines()

    modes: list[PhononMode] = []
    q_index = 0
    q_point: list[float] = [0.0, 0.0, 0.0]
    current_freq_cm1: float | None = None
    current_branch: int = 0
    current_disps: list[AtomDisplacement] = []
    seen_any_q = False

    def _flush_mode() -> None:
        nonlocal current_freq_cm1, current_disps
        if current_freq_cm1 is not None and current_disps:
            modes.append(_build_phonon_mode(
                q_index=q_index,
                branch_index=current_branch,
                frequency_cm1=current_freq_cm1,
                disps=current_disps,
                q_point=q_point,
            ))
        current_freq_cm1 = None
        current_disps = []

    for line in lines:
        # q-point header (skip the q= lines that appear in the header before
        # diagonalization — only track q-points after we've seen at least one
        # freq line or the diagonalization marker)
        qm = _Q_RE_DYN.search(line)
        if qm and "freq" not in line:
            _flush_mode()
            if seen_any_q:
                q_index += 1
            q_point = [float(qm.group(1)), float(qm.group(2)), float(qm.group(3))]
            seen_any_q = True
            continue

        # frequency line
        fm = _FREQ_RE_DYN.search(line)
        if fm:
            _flush_mode()
            current_branch = int(fm.group(1))
            current_freq_cm1 = float(fm.group(3))
            seen_any_q = True
            continue

        # atom eigenvector line (6 floats)
        am = _DYN_ATOM_RE.search(line)
        if am and current_freq_cm1 is not None:
            element = am.group(2)
            ux_re = float(am.group(3))
            ux_im = float(am.group(4))
            uy_re = float(am.group(5))
            uy_im = float(am.group(6))
            uz_re = float(am.group(7))
            uz_im = float(am.group(8))
            # Use magnitude of complex components
            ux = math.sqrt(ux_re ** 2 + ux_im ** 2)
            uy = math.sqrt(uy_re ** 2 + uy_im ** 2)
            uz = math.sqrt(uz_re ** 2 + uz_im ** 2)
            current_disps.append(AtomDisplacement(
                element=element, x_disp=ux, y_disp=uy, z_disp=uz,
            ))
            continue

    _flush_mode()
    return modes


# Regex patterns for dyn eigenvector parsing (declared after use to keep
# them near the function, but at module level for reuse).
_Q_RE_DYN = re.compile(
    r"q\s*=\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)"
)
_FREQ_RE_DYN = re.compile(
    r"freq\s*\(\s*(\d+)\s*\)\s*=\s*"
    r"([-\d.]+)\s*\[THz\]\s*=\s*"
    r"([-\d.]+)\s*\[cm-1\]"
)
