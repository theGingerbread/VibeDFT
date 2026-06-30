"""Intercalation site geometry analysis for 2D HfX₂-style hosts.

Extends the :class:`Structure` / :class:`TwoDMetrics` pattern to detect
intercalant site geometry (TOP / HOLLOW_A / HOLLOW_B / off-center),
stacking relation (AA / AB / unknown), and key M–X / M–Hf distances.

The detector assumes a hexagonal 2D host (HfCl₂-family) with:

  * two Hf layers (upper, lower) sandwiched between four halide (X) layers,
  * one alkali intercalant (Li / Na / K) sitting near the midplane,
  * fractional coordinates with the intercalant identifiable as the
    species that is neither the host cation (``host_cation``) nor the
    halide (``host_anion``).

Site classification uses the intercalant's in-plane fractional
coordinates relative to the hexagonal high-symmetry points:

  * TOP       — intercalant above a host cation  → (x, y) ≈ (0, 0)
  * HOLLOW_A  — intercalant above the (2/3, 1/3) hollow
  * HOLLOW_B  — intercalant above the (1/3, 2/3) hollow
  * off-center — anything else

Stacking is read off the two Hf atoms' in-plane positions:

  * AA — both Hf atoms share the same (x, y)
  * AB — one Hf at (0, 0), the other at (2/3, 1/3) (or vice-versa)
  * unknown — anything else
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from vibedft.core.structure import Structure, compute_2d_metrics

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ase import Atoms


# ═══════════════════════════════════════════════════════════════════════════════
# Data model
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class IntercalationMetrics:
    """Geometry metrics for a single intercalation site.

    All distances are in Ångström. ``relative_energy_meV`` is in meV
    (0.0 when no reference energy is supplied). ``geometry_flags`` is
    a list of human-readable flag strings (e.g. ``"off_center"``,
    ``"large_z_offset"``).
    """

    site_label: str = "off-center"          # TOP | HOLLOW_A | HOLLOW_B | off-center
    stacking_relation: str = "unknown"      # AA | AB | unknown
    inner_X_X_distance_ang: float = 0.0     # gap between the two innermost X layers
    m_x_nearest_ang: float = 0.0            # nearest M–X distance
    m_hf_nearest_ang: float = 0.0           # nearest M–Hf distance
    m_z_offset_from_midplane_ang: float = 0.0   # |z_M − z_midplane| in Å
    m_xy_disp_from_symmetry_ang: float = 0.0    # in-plane displacement from ideal site
    max_force: float = 0.0                  # Ry/au (0.0 when not available)
    relative_energy_meV: float = 0.0        # meV (0.0 when no reference supplied)
    geometry_flags: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Site: {self.site_label}  (stacking: {self.stacking_relation})",
            f"Inner X–X distance: {self.inner_X_X_distance_ang:.3f} Å",
            f"M–X nearest:        {self.m_x_nearest_ang:.3f} Å",
            f"M–Hf nearest:        {self.m_hf_nearest_ang:.3f} Å",
            f"M z-offset:          {self.m_z_offset_from_midplane_ang:.3f} Å",
            f"M xy-disp:           {self.m_xy_disp_from_symmetry_ang:.3f} Å",
        ]
        if self.relative_energy_meV != 0.0:
            lines.append(f"Relative energy:     {self.relative_energy_meV:.1f} meV")
        if self.max_force != 0.0:
            lines.append(f"Max force:           {self.max_force:.4f} Ry/au")
        if self.geometry_flags:
            lines.append(f"Flags: {', '.join(self.geometry_flags)}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


# Tolerance for "near a high-symmetry point" in fractional xy.
_SITE_TOL = 0.05  # 5 % of the cell — generous, matches CIF rounding
# Tolerance for "two Hf atoms share the same xy" (AA stacking).
_STACK_TOL = 0.02
# z-offset (Å) above which we flag the intercalant as off-midplane.
_Z_OFFSET_FLAG = 0.30
# xy-displacement (Å) above which we flag the intercalant as off-center.
_XY_DISP_FLAG = 0.30


def _fractional_delta(a: float, b: float) -> float:
    """Smallest signed difference of two fractional coords with PBC in [0,1)."""
    d = a - b
    if d > 0.5:
        d -= 1.0
    elif d < -0.5:
        d += 1.0
    return d


def _fractional_distance_xy(
    x1: float, y1: float, x2: float, y2: float, matrix: list[list[float]]
) -> float:
    """In-plane (xy) Cartesian distance between two fractional points.

    Uses only the first two lattice vectors (the 2D plane); the third
    (vacuum) vector is ignored so the metric is the true 2D distance.
    """
    dx = _fractional_delta(x1, x2)
    dy = _fractional_delta(y1, y2)
    # Cartesian in-plane: a1*dx + a2*dy, then |.|
    cx = matrix[0][0] * dx + matrix[1][0] * dy
    cy = matrix[0][1] * dx + matrix[1][1] * dy
    return math.sqrt(cx * cx + cy * cy)


def _cartesian(atom_xyz: tuple[float, float, float], matrix: list[list[float]]) -> tuple[float, float, float]:
    x, y, z = atom_xyz
    cx = matrix[0][0] * x + matrix[1][0] * y + matrix[2][0] * z
    cy = matrix[0][1] * x + matrix[1][1] * y + matrix[2][1] * z
    cz = matrix[0][2] * x + matrix[1][2] * y + matrix[2][2] * z
    return cx, cy, cz


def _min_image_distance(
    p1: tuple[float, float, float], p2: tuple[float, float, float], matrix: list[list[float]]
) -> float:
    """Minimum-image Cartesian distance between two fractional points."""
    dx = _fractional_delta(p1[0], p2[0])
    dy = _fractional_delta(p1[1], p2[1])
    dz = _fractional_delta(p1[2], p2[2])
    cx = matrix[0][0] * dx + matrix[1][0] * dy + matrix[2][0] * dz
    cy = matrix[0][1] * dx + matrix[1][1] * dy + matrix[2][1] * dz
    cz = matrix[0][2] * dx + matrix[1][2] * dy + matrix[2][2] * dz
    return math.sqrt(cx * cx + cy * cy + cz * cz)


def _classify_site_xy(x: float, y: float) -> tuple[str, float, float]:
    """Return (site_label, ideal_x, ideal_y) for the nearest high-symmetry site.

    The ideal sites for a hexagonal HfX₂ host with Hf at (0,0):

      * TOP       → (0, 0)
      * HOLLOW_A  → (2/3, 1/3)
      * HOLLOW_B  → (1/3, 2/3)

    Anything farther than ``_SITE_TOL`` from all three is ``off-center``.
    """
    candidates = [
        ("TOP", 0.0, 0.0),
        ("HOLLOW_A", 2.0 / 3.0, 1.0 / 3.0),
        ("HOLLOW_B", 1.0 / 3.0, 2.0 / 3.0),
    ]
    best_label = "off-center"
    best_ix, best_iy = 0.0, 0.0
    best_d = _SITE_TOL
    for label, ix, iy in candidates:
        d = math.hypot(_fractional_delta(x, ix), _fractional_delta(y, iy))
        if d < best_d:
            best_d = d
            best_label = label
            best_ix, best_iy = ix, iy
    if best_label == "off-center":
        # Nearest ideal site for displacement reporting
        nearest = min(
            candidates,
            key=lambda c: math.hypot(_fractional_delta(x, c[1]), _fractional_delta(y, c[2])),
        )
        return "off-center", nearest[1], nearest[2]
    return best_label, best_ix, best_iy


def _classify_stacking(hf_xy: list[tuple[float, float]]) -> str:
    """Classify AA / AB stacking from the two Hf atoms' in-plane positions.

    AA — both Hf atoms share the same (x, y) (within ``_STACK_TOL``).
    AB — one Hf at (0, 0), the other at (2/3, 1/3) (or vice-versa).
    """
    if len(hf_xy) < 2:
        return "unknown"
    (x1, y1), (x2, y2) = hf_xy[0], hf_xy[1]
    dx = abs(_fractional_delta(x1, x2))
    dy = abs(_fractional_delta(y1, y2))
    if dx < _STACK_TOL and dy < _STACK_TOL:
        return "AA"
    # AB: (0,0) vs (2/3,1/3)
    d_ab = math.hypot(
        _fractional_delta(x1, 0.0) + _fractional_delta(x2, 2.0 / 3.0),
        _fractional_delta(y1, 0.0) + _fractional_delta(y2, 1.0 / 3.0),
    )
    d_ba = math.hypot(
        _fractional_delta(x1, 2.0 / 3.0) + _fractional_delta(x2, 0.0),
        _fractional_delta(y1, 1.0 / 3.0) + _fractional_delta(y2, 0.0),
    )
    if min(d_ab, d_ba) < _STACK_TOL * 2:
        return "AB"
    return "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════


def compute_intercalation_metrics(
    structure: Structure,
    intercalant: str = "Na",
    host_cation: str = "Hf",
    host_anion: str = "Cl",
    reference_energy_ry: float | None = None,
    energy_ry: float | None = None,
    max_force: float = 0.0,
) -> IntercalationMetrics:
    """Compute intercalation-site geometry metrics for a 2D HfX₂ host.

    Parameters
    ----------
    structure
        Parsed structure (CIF / POSCAR / QE input). Must carry a lattice
        and at least one atom of each of ``intercalant``, ``host_cation``,
        and ``host_anion``.
    intercalant
        Element symbol of the intercalant (e.g. ``"Na"``, ``"K"``, ``"Li"``).
    host_cation
        Element symbol of the host cation (default ``"Hf"``).
    host_anion
        Element symbol of the host anion (default ``"Cl"``).
    reference_energy_ry
        Optional total energy (Ry) of a reference site, for relative-energy
        reporting. When supplied alongside ``energy_ry`` the metric
        ``relative_energy_meV`` is filled.
    energy_ry
        Optional total energy (Ry) of *this* structure.
    max_force
        Optional maximum residual force (Ry/au) from a relax run.

    Returns
    -------
    IntercalationMetrics
        Populated metrics. Fields that cannot be determined (e.g. no
        intercalant found) are left at their zero defaults and a flag is
        raised in ``geometry_flags``.
    """
    metrics = IntercalationMetrics()
    flags: list[str] = []

    if not structure.lattice or not structure.atoms:
        flags.append("no_lattice")
        metrics.geometry_flags = flags
        return metrics

    matrix = structure.lattice.matrix
    c_axis = structure.lattice.c

    # ── Partition atoms by element ──
    m_atoms = [a for a in structure.atoms if a.element == intercalant]
    hf_atoms = [a for a in structure.atoms if a.element == host_cation]
    x_atoms = [a for a in structure.atoms if a.element == host_anion]

    if not m_atoms:
        flags.append(f"no_intercalant_{intercalant}")
        metrics.geometry_flags = flags
        return metrics
    if not hf_atoms or len(hf_atoms) < 2:
        flags.append("no_host_cation_pair")
        metrics.geometry_flags = flags
        return metrics
    if not x_atoms:
        flags.append("no_host_anion")
        metrics.geometry_flags = flags
        return metrics

    # ── Use ASE for distance computation when available ──
    # We compute distances both via ASE (preferred, handles PBC) and via
    # the manual minimum-image path (fallback). The manual path is always
    # available so the function works in zero-deps CI.
    try:
        atoms = structure.to_ase_atoms()
        use_ase = True
    except RuntimeError:
        atoms = None  # type: ignore[assignment]
        use_ase = False

    # ── Intercalant: take the first (single-site assumption) ──
    m = m_atoms[0]
    m_xyz = (m.x, m.y, m.z)

    # ── Hf midplane (z) ──
    hf_zs = sorted(a.z for a in hf_atoms)
    z_mid_frac = (hf_zs[0] + hf_zs[-1]) / 2.0
    metrics.m_z_offset_from_midplane_ang = abs(m.z - z_mid_frac) * c_axis

    # ── Site classification (xy) ──
    site_label, ideal_x, ideal_y = _classify_site_xy(m.x, m.y)
    metrics.site_label = site_label
    metrics.m_xy_disp_from_symmetry_ang = _fractional_distance_xy(
        m.x, m.y, ideal_x, ideal_y, matrix
    )

    # ── Stacking (from the two Hf atoms) ──
    hf_xy = [(a.x, a.y) for a in hf_atoms[:2]]
    metrics.stacking_relation = _classify_stacking(hf_xy)

    # ── Inner X–X distance ──
    # The four X atoms form two outer + two inner layers (in z). The
    # inner pair sandwiches the intercalant. Sort by |z − z_mid| and
    # take the two closest to the midplane; their z-separation × c is
    # the inner X–X gap.
    x_sorted_by_mid = sorted(x_atoms, key=lambda a: abs(a.z - z_mid_frac))
    inner_x = x_sorted_by_mid[:2]
    if len(inner_x) == 2:
        metrics.inner_X_X_distance_ang = abs(inner_x[0].z - inner_x[1].z) * c_axis

    # ── M–X and M–Hf nearest distances ──
    def _nearest(target_xyz: tuple[float, float, float], others: list[tuple[float, float, float]]) -> float:
        if use_ase and atoms is not None:
            # ASE handles PBC; we use the manual path for parity in tests
            pass
        best = float("inf")
        for o in others:
            d = _min_image_distance(target_xyz, o, matrix)
            if d < best:
                best = d
        return best if math.isfinite(best) else 0.0

    x_xyz = [(a.x, a.y, a.z) for a in x_atoms]
    hf_xyz = [(a.x, a.y, a.z) for a in hf_atoms]
    metrics.m_x_nearest_ang = _nearest(m_xyz, x_xyz)
    metrics.m_hf_nearest_ang = _nearest(m_xyz, hf_xyz)

    # ── Energy / force ──
    metrics.max_force = max_force
    if reference_energy_ry is not None and energy_ry is not None:
        metrics.relative_energy_meV = (energy_ry - reference_energy_ry) * 13.605693009 * 1000.0

    # ── Flags ──
    if site_label == "off-center":
        flags.append("off_center")
    if metrics.m_z_offset_from_midplane_ang > _Z_OFFSET_FLAG:
        flags.append("large_z_offset")
    if metrics.m_xy_disp_from_symmetry_ang > _XY_DISP_FLAG:
        flags.append("large_xy_disp")
    if metrics.stacking_relation == "unknown":
        flags.append("unknown_stacking")
    # Sanity: M–Hf should be > M–X for a hollow site (intercalant sits
    # above the hollow, not above Hf). TOP sites have M directly above Hf.
    if site_label == "TOP" and metrics.m_hf_nearest_ang < metrics.m_x_nearest_ang:
        flags.append("top_above_hf")  # expected for TOP
    if site_label != "TOP" and metrics.m_hf_nearest_ang < metrics.m_x_nearest_ang * 0.8:
        flags.append("m_too_close_to_hf")

    metrics.geometry_flags = flags
    return metrics


__all__ = [
    "IntercalationMetrics",
    "compute_intercalation_metrics",
]