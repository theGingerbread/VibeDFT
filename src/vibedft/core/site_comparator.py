"""Multi-configuration intercalation site screening.

Scans a root directory for intercalation site subdirectories (e.g.
``rx_1``, ``rx_2``, … or ``HfI2_Li_1``, ``HfI2_Li_2``, …), extracts
the final vc-relax energy and geometry from each, ranks them by energy,
and emits a recommendation (``primary`` / ``backup`` / ``excluded`` /
``needs_verification``) per site.

Ranking rules (ΔE relative to the reference site, meV/cell):

    ΔE <  25  AND geometry OK        → "primary"
    ΔE 25–150                         → "backup"
    ΔE > 300                          → "excluded"
    relax not converged               → "needs_verification"
    M–X abnormally short              → force downgrade

The geometry metrics (``nearest_M_X_ang``, ``inner_X_X_ang``) are
computed from the relaxed structure.  When
:mod:`vibedft.core.intercalation` is available (built by P0.1), its
``compute_intercalation_metrics`` is used; otherwise a built-in
minimum-image fallback computes the same quantities directly from the
:class:`~vibedft.core.structure.Structure`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from vibedft.core.analysis import parse_qe_output
from vibedft.core.structure import (
    Structure,
    parse_structure_from_qe_input,
    parse_structure_from_qe_output,
)

# ── Optional intercalation metrics (P0.1) ──────────────────────────────
try:  # pragma: no cover - exercised once P0.1 lands
    from vibedft.core.intercalation import (  # type: ignore[import-not-found]
        IntercalationMetrics,
        compute_intercalation_metrics,
    )
    _HAS_INTERCALATION = True
except ImportError:
    IntercalationMetrics = None  # type: ignore[assignment, misc]
    compute_intercalation_metrics = None  # type: ignore[assignment, misc]
    _HAS_INTERCALATION = False


# ══════════════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════════════

RY_TO_MEV = 13_605.693009  # 1 Ry = 13.6057 eV = 13605.7 meV

# Recommendation thresholds (meV/cell)
PRIMARY_MAX_MEV = 25.0
BACKUP_MAX_MEV = 150.0
EXCLUDED_MIN_MEV = 300.0

# Geometry thresholds (Å)
MIN_MX_BOND_ANG = 2.0  # abnormally short M–X → downgrade
MIGRATION_THRESH_ANG = 1.0  # intercalant displacement > this → "migrated"

# Halogens and common host metals for geometry classification
_HALOGENS = {"F", "Cl", "Br", "I"}
_HOST_METALS = {
    "Hf", "Zr", "Ti", "V", "Nb", "Ta", "Mo", "W",
    "Cr", "Re", "Tc", "Ru", "Os", "Rh", "Ir", "Pd", "Pt",
    "Fe", "Co", "Ni", "Cu", "Zn", "Mn", "Sc", "Y",
}


# ══════════════════════════════════════════════════════════════════════════════
# Data models
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SiteComparisonRow:
    """One intercalation site in the ranked comparison table."""

    rank: int
    site_label: str
    final_energy_Ry: float
    delta_E_meV_per_cell: float
    relax_status: str  # "converged" | "not_converged" | "incomplete"
    max_force: float  # Ry/au (last "Total force" from QE output)
    nearest_M_X_ang: float
    inner_X_X_ang: float
    site_migrated: bool
    ph_gamma_status: str  # "unknown" | "stable" | "unstable" | "not_run"
    recommendation: str  # "primary" | "backup" | "excluded" | "needs_verification"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "site_label": self.site_label,
            "final_energy_Ry": self.final_energy_Ry,
            "delta_E_meV_per_cell": self.delta_E_meV_per_cell,
            "relax_status": self.relax_status,
            "max_force": self.max_force,
            "nearest_M_X_ang": self.nearest_M_X_ang,
            "inner_X_X_ang": self.inner_X_X_ang,
            "site_migrated": self.site_migrated,
            "ph_gamma_status": self.ph_gamma_status,
            "recommendation": self.recommendation,
        }


@dataclass
class SiteComparisonResult:
    """Full ranked comparison across all intercalation sites."""

    reference_site: str
    sites: list[SiteComparisonRow] = field(default_factory=list)
    summary_table: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_site": self.reference_site,
            "sites": [s.to_dict() for s in self.sites],
            "summary_table": self.summary_table,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Site discovery
# ══════════════════════════════════════════════════════════════════════════════

def discover_site_dirs(
    root: Path,
    intercalant: str = "Na",
) -> list[tuple[str, Path]]:
    """Find intercalation site subdirectories under *root*.

    Matches directory names that contain the intercalant symbol (case
    sensitive — chemical symbols are capitalised) OR the prefix ``rx``
    followed by an underscore and a number, e.g.::

        HfI2_Li_1   → matches intercalant="Li"
        rx_1        → matches any intercalant (generic "rx" prefix)
        Na_2        → matches intercalant="Na"

    Returns a sorted list of ``(site_label, directory_path)`` tuples.
    """
    r = Path(root).resolve()
    if not r.is_dir():
        return []

    sites: list[tuple[str, Path]] = []
    for child in sorted(r.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        if _is_site_dir(child.name, intercalant):
            sites.append((child.name, child))
    return sites


def _is_site_dir(name: str, intercalant: str) -> bool:
    """Return True if *name* looks like an intercalation site directory."""
    # Pattern: <prefix>_<intercalant>_<n>  (e.g. HfI2_Li_1, K-HfCl2_Na_2)
    parts = re.split(r"[-_]", name)
    if intercalant in parts and _ends_with_number(parts):
        return True
    # Generic pattern: rx_<n>  (e.g. rx_1, rx_2)
    if name.lower().startswith("rx") and _ends_with_number(parts):
        return True
    # Pattern: <intercalant>_<n>  (e.g. Na_1, Li_2)
    if parts and parts[0] == intercalant and _ends_with_number(parts):
        return True
    return False


def _ends_with_number(parts: list[str]) -> bool:
    if not parts:
        return False
    try:
        int(parts[-1])
        return True
    except ValueError:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Output file discovery
# ══════════════════════════════════════════════════════════════════════════════

def find_vc_relax_output(site_dir: Path) -> Path | None:
    """Locate the vc-relax / relax output file inside a site directory.

    Search order:
      1. Common explicit names (``relax.out``, ``vc-relax.out``, ``rx.out``)
      2. Any ``*.out`` file containing ``bfgs`` or ``Total force``
         (i.e. a relax/vc-relax output, not a plain SCF)
      3. Any ``*.out`` file as last resort
    """
    candidates_explicit = ["relax.out", "vc-relax.out", "rx.out", "vc_relax.out"]
    for name in candidates_explicit:
        p = site_dir / name
        if p.is_file():
            return p

    out_files = sorted(site_dir.rglob("*.out"))
    # Prefer files that look like relax output
    for f in out_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "bfgs" in text or "Total force" in text:
            return f
    # Last resort: any .out
    if out_files:
        return out_files[0]
    return None


def find_vc_relax_input(site_dir: Path) -> Path | None:
    """Locate the vc-relax / relax input file inside a site directory."""
    candidates_explicit = ["relax.in", "vc-relax.in", "rx.in", "vc_relax.in"]
    for name in candidates_explicit:
        p = site_dir / name
        if p.is_file():
            return p

    in_files = sorted(site_dir.rglob("*.in"))
    for f in in_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "calculation" in text and (
            "relax" in text or "vc-relax" in text
        ):
            return f
    if in_files:
        return in_files[0]
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Energy / force / relax-status extraction
# ══════════════════════════════════════════════════════════════════════════════

def extract_relax_info(out_path: Path) -> dict[str, Any]:
    """Extract energy, relax status, and max force from a QE relax output.

    Returns a dict with keys:
        ``energy_ry`` (float|None), ``relax_status`` (str),
        ``max_force`` (float), ``job_done`` (bool)
    """
    text = out_path.read_text(encoding="utf-8", errors="replace")

    # Final energy: last "!  total energy" line
    energies = re.findall(r"!\s+total energy\s+=\s+([-\d.]+)\s+Ry", text)
    energy_ry = float(energies[-1]) if energies else None

    # Relax convergence
    job_done = "JOB DONE" in text
    not_converged = "convergence not achieved" in text or "bfgs failed" in text
    if not_converged:
        relax_status = "not_converged"
    elif job_done and energy_ry is not None:
        relax_status = "converged"
    else:
        relax_status = "incomplete"

    # Max force: last "Total force =     X.XXXXXX" line
    forces = re.findall(r"Total force\s*=\s*([\d.]+)", text)
    max_force = float(forces[-1]) if forces else 0.0

    return {
        "energy_ry": energy_ry,
        "relax_status": relax_status,
        "max_force": max_force,
        "job_done": job_done,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Geometry metrics (fallback when vibedft.core.intercalation is absent)
# ══════════════════════════════════════════════════════════════════════════════

def _cartesian(struct: Structure, atom_idx: int) -> list[float]:
    """Return Cartesian coordinates (Å) of atom *atom_idx*."""
    a = struct.atoms[atom_idx]
    cm = struct.lattice.matrix if struct.lattice else [
        [1, 0, 0], [0, 1, 0], [0, 0, 1]
    ]
    return [
        a.x * cm[0][0] + a.y * cm[1][0] + a.z * cm[2][0],
        a.x * cm[0][1] + a.y * cm[1][1] + a.z * cm[2][1],
        a.x * cm[0][2] + a.y * cm[1][2] + a.z * cm[2][2],
    ]


def _min_image_distance(
    struct: Structure, i: int, j: int
) -> float:
    """Minimum-image distance (Å) between atoms *i* and *j*."""
    a = struct.atoms[i]
    b = struct.atoms[j]
    cm = struct.lattice.matrix if struct.lattice else [
        [1, 0, 0], [0, 1, 0], [0, 0, 1]
    ]
    # Fractional displacement
    df = [a.x - b.x, a.y - b.y, a.z - b.z]
    # Apply minimum image convention in fractional space
    for k in range(3):
        df[k] -= round(df[k])
    # Convert to Cartesian
    dx = df[0] * cm[0][0] + df[1] * cm[1][0] + df[2] * cm[2][0]
    dy = df[0] * cm[0][1] + df[1] * cm[1][1] + df[2] * cm[2][1]
    dz = df[0] * cm[0][2] + df[1] * cm[1][2] + df[2] * cm[2][2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _classify_atoms(
    struct: Structure, intercalant: str
) -> tuple[list[int], list[int], list[int]]:
    """Return (metal_indices, halogen_indices, intercalant_indices)."""
    metals: list[int] = []
    halogens: list[int] = []
    inter: list[int] = []
    for idx, atom in enumerate(struct.atoms):
        el = atom.element
        if el == intercalant:
            inter.append(idx)
        elif el in _HALOGENS:
            halogens.append(idx)
        elif el in _HOST_METALS:
            metals.append(idx)
        else:
            # Unknown element: treat as metal if not halogen/intercalant
            metals.append(idx)
    return metals, halogens, inter


def compute_geometry_metrics(
    struct: Structure, intercalant: str
) -> tuple[float, float]:
    """Compute (nearest_M_X_ang, inner_X_X_ang) from a Structure.

    * ``nearest_M_X_ang`` — shortest metal–halogen distance (Å).
    * ``inner_X_X_ang`` — shortest halogen–halogen distance (Å),
      excluding trivial self-distance.
    """
    if _HAS_INTERCALATION and compute_intercalation_metrics is not None:
        metrics = compute_intercalation_metrics(struct, intercalant=intercalant)
        return metrics.m_x_nearest_ang, metrics.inner_X_X_distance_ang

    # Fallback: direct minimum-image computation
    metals, halogens, _ = _classify_atoms(struct, intercalant)

    nearest_mx = float("inf")
    for mi in metals:
        for xi in halogens:
            d = _min_image_distance(struct, mi, xi)
            if d < nearest_mx:
                nearest_mx = d

    inner_xx = float("inf")
    for i, xi in enumerate(halogens):
        for xj in halogens[i + 1:]:
            d = _min_image_distance(struct, xi, xj)
            if d < inner_xx:
                inner_xx = d

    if nearest_mx == float("inf"):
        nearest_mx = 0.0
    if inner_xx == float("inf"):
        inner_xx = 0.0

    return nearest_mx, inner_xx


def detect_migration(
    initial: Structure | None,
    final: Structure | None,
    intercalant: str,
) -> bool:
    """Return True if the intercalant atom moved > MIGRATION_THRESH_ANG.

    Compares the intercalant position in *initial* vs *final* structure.
    Returns False if either structure is None or no intercalant found.
    """
    if initial is None or final is None:
        return False

    _, _, init_inter = _classify_atoms(initial, intercalant)
    _, _, final_inter = _classify_atoms(final, intercalant)
    if not init_inter or not final_inter:
        return False

    # Compare first intercalant atom (single-intercalant sites)
    i0 = init_inter[0]
    f0 = final_inter[0]
    d = _min_image_distance_between_structs(initial, final, i0, f0)
    return d > MIGRATION_THRESH_ANG


def _min_image_distance_between_structs(
    s1: Structure, s2: Structure, i: int, j: int
) -> float:
    """Minimum-image distance between atom *i* in s1 and atom *j* in s2.

    Uses s1's lattice for the minimum-image convention.
    """
    a = s1.atoms[i]
    b = s2.atoms[j]
    cm = s1.lattice.matrix if s1.lattice else [
        [1, 0, 0], [0, 1, 0], [0, 0, 1]
    ]
    df = [a.x - b.x, a.y - b.y, a.z - b.z]
    for k in range(3):
        df[k] -= round(df[k])
    dx = df[0] * cm[0][0] + df[1] * cm[1][0] + df[2] * cm[2][0]
    dy = df[0] * cm[0][1] + df[1] * cm[1][1] + df[2] * cm[2][1]
    dz = df[0] * cm[0][2] + df[1] * cm[1][2] + df[2] * cm[2][2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


# ══════════════════════════════════════════════════════════════════════════════
# Recommendation engine
# ══════════════════════════════════════════════════════════════════════════════

def _recommend(
    delta_e_mev: float,
    relax_status: str,
    nearest_mx: float,
) -> str:
    """Apply ranking rules to produce a recommendation string."""
    # Relax not converged → needs_verification (overrides energy)
    if relax_status == "not_converged":
        return "needs_verification"
    if relax_status == "incomplete":
        return "needs_verification"

    # M–X abnormally short → force downgrade to excluded
    if nearest_mx > 0 and nearest_mx < MIN_MX_BOND_ANG:
        return "excluded"

    # Energy-based ranking
    if delta_e_mev < PRIMARY_MAX_MEV:
        return "primary"
    elif delta_e_mev < BACKUP_MAX_MEV:
        return "backup"
    elif delta_e_mev > EXCLUDED_MIN_MEV:
        return "excluded"
    else:
        # 150–300 meV: still backup (borderline)
        return "backup"


# ══════════════════════════════════════════════════════════════════════════════
# Summary table formatting
# ══════════════════════════════════════════════════════════════════════════════

def _format_summary_table(rows: Sequence[SiteComparisonRow]) -> str:
    """Render a fixed-width text table from ranked rows."""
    header = (
        f"{'#':>2} {'Site':20s} {'E(Ry)':>14s} {'ΔE(meV)':>9s} "
        f"{'Status':14s} {'Fmax':>8s} {'M-X(Å)':>7s} "
        f"{'X-X(Å)':>7s} {'Mig':>4s} {'Reco':>18s}"
    )
    lines = [header, "-" * len(header)]
    for r in rows:
        mig = "Y" if r.site_migrated else "N"
        lines.append(
            f"{r.rank:>2} {r.site_label:20s} {r.final_energy_Ry:>14.6f} "
            f"{r.delta_E_meV_per_cell:>9.1f} {r.relax_status:14s} "
            f"{r.max_force:>8.4f} {r.nearest_M_X_ang:>7.3f} "
            f"{r.inner_X_X_ang:>7.3f} {mig:>4s} {r.recommendation:>18s}"
        )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════════════════════

def compare_intercalation_sites(
    root: Path,
    intercalant: str = "Na",
    reference: str | None = None,
) -> SiteComparisonResult:
    """Scan *root* for intercalation sites and rank them by energy.

    Parameters
    ----------
    root
        Directory containing intercalation site subdirectories
        (e.g. ``rx_1/``, ``HfI2_Li_2/``, …).
    intercalant
        Chemical symbol of the intercalant (``"Li"``, ``"Na"``, ``"K"``).
    reference
        Site label to use as the energy reference.  If ``None`` or not
        found, the lowest-energy converged site is used.

    Returns
    -------
    SiteComparisonResult
        Ranked table with per-site recommendations.
    """
    r = Path(root).resolve()
    site_dirs = discover_site_dirs(r, intercalant=intercalant)

    if not site_dirs:
        return SiteComparisonResult(
            reference_site=reference or "",
            sites=[],
            summary_table="No intercalation site directories found.",
        )

    # Collect raw data per site
    raw: list[dict[str, Any]] = []
    for label, sdir in site_dirs:
        out_path = find_vc_relax_output(sdir)
        in_path = find_vc_relax_input(sdir)

        if out_path is None:
            raw.append({
                "label": label,
                "energy_ry": None,
                "relax_status": "incomplete",
                "max_force": 0.0,
                "nearest_mx": 0.0,
                "inner_xx": 0.0,
                "migrated": False,
            })
            continue

        info = extract_relax_info(out_path)
        final_struct = parse_structure_from_qe_output(out_path)
        initial_struct = (
            parse_structure_from_qe_input(in_path) if in_path else None
        )

        nearest_mx, inner_xx = (0.0, 0.0)
        if final_struct is not None:
            nearest_mx, inner_xx = compute_geometry_metrics(
                final_struct, intercalant=intercalant
            )

        migrated = detect_migration(
            initial_struct, final_struct, intercalant=intercalant
        )

        raw.append({
            "label": label,
            "energy_ry": info["energy_ry"],
            "relax_status": info["relax_status"],
            "max_force": info["max_force"],
            "nearest_mx": nearest_mx,
            "inner_xx": inner_xx,
            "migrated": migrated,
        })

    # Determine reference energy
    ref_label = reference
    ref_energy: float | None = None
    if ref_label is not None:
        for entry in raw:
            if entry["label"] == ref_label and entry["energy_ry"] is not None:
                ref_energy = entry["energy_ry"]
                break

    if ref_energy is None:
        # Fall back to lowest-energy converged site
        converged = [
            e for e in raw
            if e["energy_ry"] is not None and e["relax_status"] == "converged"
        ]
        if converged:
            best = min(converged, key=lambda e: e["energy_ry"])
            ref_energy = best["energy_ry"]
            if ref_label is None:
                ref_label = best["label"]
        else:
            # No converged site: use lowest energy overall
            with_energy = [e for e in raw if e["energy_ry"] is not None]
            if with_energy:
                best = min(with_energy, key=lambda e: e["energy_ry"])
                ref_energy = best["energy_ry"]
                if ref_label is None:
                    ref_label = best["label"]

    # Build rows
    rows: list[SiteComparisonRow] = []
    for entry in raw:
        energy = entry["energy_ry"]
        if energy is not None and ref_energy is not None:
            delta_mev = (energy - ref_energy) * RY_TO_MEV * 1000.0
        else:
            delta_mev = float("inf")

        reco = _recommend(
            delta_mev,
            entry["relax_status"],
            entry["nearest_mx"],
        )
        rows.append(SiteComparisonRow(
            rank=0,  # assigned after sorting
            site_label=entry["label"],
            final_energy_Ry=energy if energy is not None else 0.0,
            delta_E_meV_per_cell=round(delta_mev, 1)
            if delta_mev != float("inf") else float("inf"),
            relax_status=entry["relax_status"],
            max_force=entry["max_force"],
            nearest_M_X_ang=round(entry["nearest_mx"], 3),
            inner_X_X_ang=round(entry["inner_xx"], 3),
            site_migrated=entry["migrated"],
            ph_gamma_status="unknown",
            recommendation=reco,
        ))

    # Sort by energy (ascending); incomplete sites go last
    rows.sort(key=lambda r: (
        r.relax_status == "incomplete",
        r.final_energy_Ry if r.relax_status != "incomplete" else float("inf"),
    ))

    # Assign ranks
    for i, row in enumerate(rows, 1):
        row.rank = i

    summary = _format_summary_table(rows)
    return SiteComparisonResult(
        reference_site=ref_label or "",
        sites=rows,
        summary_table=summary,
    )