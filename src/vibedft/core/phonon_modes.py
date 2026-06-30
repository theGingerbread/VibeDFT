"""Phonon mode analysis: eigenvector parsing from matdyn.modes and dyn files.

Provides dataclasses for atom displacements and phonon modes, parsers for
QE matdyn.x ``matdyn.modes`` and ph.x ``dyn`` eigenvector output, and
heuristic mode-type classification (acoustic / optical / shear / breathing /
slip / stretch).

The classification heuristics use only the information available in the
modes/eigenvector files (element labels, displacement components, frequency,
q-index).  Layer-based heuristics (shear, breathing) split atoms into
first-half / second-half by index as a proxy for top/bottom layers in
layered 2D materials where atoms are listed layer-by-layer.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

# Elements commonly used as intercalants in 2D-material superconductivity studies.
INTERCALANT_ELEMENTS: frozenset[str] = frozenset({
    "Li", "Na", "K", "Rb", "Cs", "Ca", "Mg", "Al", "Sr", "Ba",
})

# Polarization thresholds
_IN_PLANE_THRESHOLD = 0.7
_OUT_OF_PLANE_THRESHOLD = 0.3

# Acoustic mode frequency threshold (cm⁻¹)
_ACOUSTIC_FREQ_THRESHOLD = 5.0

# Stretch mode minimum frequency (cm⁻¹)
_STRETCH_FREQ_THRESHOLD = 200.0

# Gamma tolerance for q-vector components
_GAMMA_TOL = 1e-4


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class AtomDisplacement:
    """Displacement of one atom in a phonon eigenvector.

    Displacement components are the real parts of the eigenvector entries
    (matdyn.modes) or the magnitude ``sqrt(re^2 + im^2)`` of complex
    entries (dyn files).
    """

    element: str
    x_disp: float
    y_disp: float
    z_disp: float

    @property
    def magnitude(self) -> float:
        """Euclidean norm of the displacement vector."""
        return math.sqrt(self.x_disp ** 2 + self.y_disp ** 2 + self.z_disp ** 2)

    @property
    def in_plane_magnitude(self) -> float:
        return math.sqrt(self.x_disp ** 2 + self.y_disp ** 2)

    @property
    def out_of_plane_magnitude(self) -> float:
        return abs(self.z_disp)


@dataclass
class PhononMode:
    """A single phonon mode at a given q-point.

    Attributes:
        q_index: zero-based q-point index within the file.
        branch_index: one-based mode index (matches QE ``freq ( N)`` numbering).
        frequency_cm1: frequency in cm⁻¹ (negative = imaginary).
        is_imaginary: True if frequency < 0.
        displacements: per-atom displacement vectors.
        atom_participation: ``{element: fraction}`` of total |u|^2.
        in_plane_fraction: ``(ux^2+uy^2) / (ux^2+uy^2+uz^2)`` averaged over atoms.
        out_of_plane_fraction: ``1 - in_plane_fraction``.
        polarization: ``"in-plane"``, ``"out-of-plane"``, or ``"mixed"``.
        mode_type: heuristic classification (see module docstring).
    """

    q_index: int = 0
    branch_index: int = 0
    frequency_cm1: float = 0.0
    is_imaginary: bool = False
    displacements: list[AtomDisplacement] = field(default_factory=list)
    atom_participation: dict[str, float] = field(default_factory=dict)
    in_plane_fraction: float = 0.0
    out_of_plane_fraction: float = 0.0
    polarization: str = "mixed"
    mode_type: str = "unknown"
    q_point: list[float] = field(default_factory=list)
    """3-component q-vector if available from the file."""

    def summary(self) -> str:
        lines = [
            f"Mode q={self.q_index} branch={self.branch_index}: "
            f"{self.frequency_cm1:.2f} cm⁻¹ ({self.mode_type}, {self.polarization})",
        ]
        if self.atom_participation:
            parts = ", ".join(
                f"{el}={frac:.2f}" for el, frac in
                sorted(self.atom_participation.items(), key=lambda kv: -kv[1])
            )
            lines.append(f"  Participation: {parts}")
        lines.append(
            f"  In-plane: {self.in_plane_fraction:.2f}, "
            f"Out-of-plane: {self.out_of_plane_fraction:.2f}"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def _compute_atom_participation(
    disps: Sequence[AtomDisplacement],
) -> dict[str, float]:
    """Compute per-element participation fractions ``|u_i|^2 / sum |u|^2``."""
    sq_mags: list[float] = [d.magnitude ** 2 for d in disps]
    total = sum(sq_mags)
    if total < 1e-20:
        # All-zero displacements (e.g. acoustic mode at Gamma) — uniform.
        if not disps:
            return {}
        per_atom = 1.0 / len(disps)
        result: dict[str, float] = {}
        for d in disps:
            result[d.element] = result.get(d.element, 0.0) + per_atom
        return result

    result: dict[str, float] = {}
    for d, sq in zip(disps, sq_mags):
        result[d.element] = result.get(d.element, 0.0) + sq / total
    return result


def _compute_in_plane_fraction(
    disps: Sequence[AtomDisplacement],
) -> float:
    """Compute ``(sum ux^2+uy^2) / (sum ux^2+uy^2+uz^2)``."""
    in_plane_sq = sum(d.x_disp ** 2 + d.y_disp ** 2 for d in disps)
    total_sq = in_plane_sq + sum(d.z_disp ** 2 for d in disps)
    if total_sq < 1e-20:
        return 0.5  # indeterminate — call it mixed
    return in_plane_sq / total_sq


def _classify_polarization(in_plane_frac: float) -> str:
    """Classify polarization by in-plane fraction threshold."""
    if in_plane_frac > _IN_PLANE_THRESHOLD:
        return "in-plane"
    if in_plane_frac < _OUT_OF_PLANE_THRESHOLD:
        return "out-of-plane"
    return "mixed"


def _is_gamma(q_point: Sequence[float]) -> bool:
    """True if q-vector is at Gamma (all components near zero)."""
    return all(abs(c) < _GAMMA_TOL for c in q_point)


def _classify_mode_type(
    frequency_cm1: float,
    is_imaginary: bool,
    in_plane_frac: float,
    out_of_plane_frac: float,
    disps: Sequence[AtomDisplacement],
    atom_participation: dict[str, float],
    q_point: Sequence[float],
) -> str:
    """Heuristic mode-type classification.

    Order of checks (first match wins):
    1. acoustic  — |freq| < 5 cm⁻¹ at Gamma
    2. slip      — intercalant element dominates participation AND in-plane
    3. shear     — in-plane-dominated AND top/bottom halves have opposite
                   in-plane displacement directions
    4. breathing — out-of-plane-dominated AND top/bottom halves have opposite
                   z displacement signs
    5. stretch   — high freq (>200 cm⁻¹) AND out-of-plane AND same z sign
                   within each half
    6. optical   — any non-acoustic mode with non-trivial frequency
    7. unknown   — fallback
    """
    n_atoms = len(disps)
    at_gamma = _is_gamma(q_point)

    # 1. Acoustic: low frequency at Gamma
    if at_gamma and abs(frequency_cm1) < _ACOUSTIC_FREQ_THRESHOLD:
        return "acoustic"

    # 2. Slip: intercalant-dominated in-plane
    intercalant_participation = sum(
        frac for el, frac in atom_participation.items()
        if el in INTERCALANT_ELEMENTS
    )
    if intercalant_participation > 0.5 and in_plane_frac > _IN_PLANE_THRESHOLD:
        return "slip"

    # For layer-based heuristics, split atoms into first/second half
    if n_atoms >= 2:
        mid = n_atoms // 2
        first_half = disps[:mid]
        second_half = disps[mid:]

        # 3. Shear: in-plane, opposite in-plane directions between halves
        if in_plane_frac > _IN_PLANE_THRESHOLD and len(first_half) > 0 and len(second_half) > 0:
            first_in_plane = [
                (d.x_disp, d.y_disp) for d in first_half
                if d.in_plane_magnitude > 1e-10
            ]
            second_in_plane = [
                (d.x_disp, d.y_disp) for d in second_half
                if d.in_plane_magnitude > 1e-10
            ]
            if first_in_plane and second_in_plane:
                # Average in-plane direction for each half
                fx = sum(v[0] for v in first_in_plane) / len(first_in_plane)
                fy = sum(v[1] for v in first_in_plane) / len(first_in_plane)
                sx = sum(v[0] for v in second_in_plane) / len(second_in_plane)
                sy = sum(v[1] for v in second_in_plane) / len(second_in_plane)
                dot = fx * sx + fy * sy
                if dot < 0:  # opposite directions
                    return "shear"

        # 4. Breathing: out-of-plane, opposite z signs between halves
        if out_of_plane_frac > _IN_PLANE_THRESHOLD and len(first_half) > 0 and len(second_half) > 0:
            first_z = [d.z_disp for d in first_half if abs(d.z_disp) > 1e-10]
            second_z = [d.z_disp for d in second_half if abs(d.z_disp) > 1e-10]
            if first_z and second_z:
                first_sign = sum(1 for z in first_z if z > 0) - sum(1 for z in first_z if z < 0)
                second_sign = sum(1 for z in second_z if z > 0) - sum(1 for z in second_z if z < 0)
                if first_sign * second_sign < 0:  # opposite dominant signs
                    return "breathing"

        # 5. Stretch: high freq, out-of-plane, same z sign within halves
        if (
            frequency_cm1 > _STRETCH_FREQ_THRESHOLD
            and out_of_plane_frac > _IN_PLANE_THRESHOLD
        ):
            return "stretch"

    # 6. Optical: non-acoustic mode with meaningful frequency
    if abs(frequency_cm1) >= _ACOUSTIC_FREQ_THRESHOLD:
        return "optical"

    return "unknown"


def _build_phonon_mode(
    q_index: int,
    branch_index: int,
    frequency_cm1: float,
    disps: list[AtomDisplacement],
    q_point: list[float],
) -> PhononMode:
    """Assemble a PhononMode with all derived fields populated."""
    is_imag = frequency_cm1 < 0
    participation = _compute_atom_participation(disps)
    in_plane_frac = _compute_in_plane_fraction(disps)
    out_of_plane_frac = 1.0 - in_plane_frac
    polarization = _classify_polarization(in_plane_frac)
    mode_type = _classify_mode_type(
        frequency_cm1=frequency_cm1,
        is_imaginary=is_imag,
        in_plane_frac=in_plane_frac,
        out_of_plane_frac=out_of_plane_frac,
        disps=disps,
        atom_participation=participation,
        q_point=q_point,
    )
    return PhononMode(
        q_index=q_index,
        branch_index=branch_index,
        frequency_cm1=frequency_cm1,
        is_imaginary=is_imag,
        displacements=disps,
        atom_participation=participation,
        in_plane_fraction=in_plane_frac,
        out_of_plane_fraction=out_of_plane_frac,
        polarization=polarization,
        mode_type=mode_type,
        q_point=list(q_point),
    )


# ---------------------------------------------------------------------------
# Parser: matdyn.modes
# ---------------------------------------------------------------------------

# Matches: "     freq (    1) =   -0.123456 [THz] =   -4.123456 [cm-1]"
_FREQ_RE = re.compile(
    r"freq\s*\(\s*(\d+)\s*\)\s*=\s*"
    r"([-\d.]+)\s*\[THz\]\s*=\s*"
    r"([-\d.]+)\s*\[cm-1\]"
)

# Matches: "     q =  0.0000  0.0000  0.0000"
_Q_RE = re.compile(
    r"q\s*=\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)"
)

# Matches atom displacement line: "      (    1) H   0.123456  0.123456  0.123456"
# Element may be 1-3 chars; we capture everything after the ")" and split.
_ATOM_RE = re.compile(
    r"\(\s*(\d+)\s*\)\s*(\w+)\s+"
    r"([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)"
)


def parse_matdyn_modes(filepath: Path | str) -> list[PhononMode]:
    """Parse a QE matdyn.x ``matdyn.modes`` file into a list of PhononMode.

    The matdyn.modes format::

         q =  0.0000  0.0000  0.0000

         freq (    1) =   -0.123456 [THz] =   -4.123456 [cm-1]
         (    1) H   0.123456  0.123456  0.123456
         (    2) H  -0.123456  -0.123456  -0.123456
         ...
         freq (    2) =    1.234567 [THz] =    4.123457 [cm-1]
         ...

         q =  0.1000  0.0000  0.0000
         ...

    Returns an empty list if the file is missing or contains no mode blocks.
    """
    path = Path(filepath)
    if not path.is_file():
        return []

    text = path.read_text(encoding="utf-8", errors="replace")
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
        # Check for q-point header
        qm = _Q_RE.search(line)
        if qm and "freq" not in line:
            _flush_mode()
            if seen_any_q:
                q_index += 1
            q_point = [float(qm.group(1)), float(qm.group(2)), float(qm.group(3))]
            seen_any_q = True
            continue

        # Check for frequency line
        fm = _FREQ_RE.search(line)
        if fm:
            _flush_mode()
            current_branch = int(fm.group(1))
            current_freq_cm1 = float(fm.group(3))
            continue

        # Check for atom displacement line
        am = _ATOM_RE.search(line)
        if am and current_freq_cm1 is not None:
            element = am.group(2)
            ux = float(am.group(3))
            uy = float(am.group(4))
            uz = float(am.group(5))
            current_disps.append(AtomDisplacement(
                element=element, x_disp=ux, y_disp=uy, z_disp=uz,
            ))
            continue

    # Flush last mode
    _flush_mode()

    return modes


__all__ = [
    "AtomDisplacement",
    "PhononMode",
    "INTERCALANT_ELEMENTS",
    "parse_matdyn_modes",
]