"""Structure analysis: parsing, symmetry, 2D metrics, and report integration.

Parses atomic structures from CIF, POSCAR, QE input, and QE output.
Computes symmetry, 2D-specific metrics, and builds a report section
with an embedded 3Dmol.js viewer.

Backend selection:
    - When `ase` and `spglib` are installed (see the `ase` extra in
      ``pyproject.toml``), structure IO uses `ase.io.read` and symmetry
      analysis uses `spglib.get_symmetry_dataset`. This is the default
      on Preston's Mac (Python 3.14 + ase 3.29 + spglib 2.7).
    - When `ase` is unavailable, the module falls back to a built-in
      single-pass regex parser so the rest of the pipeline still runs
      without scientific Python dependencies. The fallback path is
      exercised by the test suite on minimal CI environments.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ase import Atoms


# ═══════════════════════════════════════════════════════════════════════════════
# Backend probe (cached)
# ═══════════════════════════════════════════════════════════════════════════════

_ASE_AVAILABLE: bool | None = None


def _ase_available() -> bool:
    """Return True once we successfully import `ase` and `spglib`.

    Calls to `ase` modules must go through this probe so the fallback
    path stays intact. Result is cached so the import cost is paid once.
    """
    global _ASE_AVAILABLE
    if _ASE_AVAILABLE is not None:
        return _ASE_AVAILABLE
    try:
        import ase  # noqa: F401
        import spglib  # noqa: F401
        _ASE_AVAILABLE = True
    except Exception:
        _ASE_AVAILABLE = False
    return _ASE_AVAILABLE


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models (public API — frozen shape, consumed across vibedft.*)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Lattice:
    """3×3 cell matrix (rows = lattice vectors in Å)."""
    matrix: list[list[float]]  # [a1, a2, a3] each a list of 3 floats
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    alpha: float = 0.0  # degrees
    beta: float = 0.0
    gamma: float = 0.0

    def __post_init__(self):
        if self.matrix and len(self.matrix) >= 3:
            v = self.matrix
            self.a = math.sqrt(v[0][0]**2 + v[0][1]**2 + v[0][2]**2)
            self.b = math.sqrt(v[1][0]**2 + v[1][1]**2 + v[1][2]**2)
            self.c = math.sqrt(v[2][0]**2 + v[2][1]**2 + v[2][2]**2)
            self.alpha = _angle_between(v[1], v[2])
            self.beta  = _angle_between(v[0], v[2])
            self.gamma = _angle_between(v[0], v[1])

    @property
    def volume(self) -> float:
        a1, a2, a3 = self.matrix[0], self.matrix[1], self.matrix[2]
        return abs(
            a1[0]*(a2[1]*a3[2] - a2[2]*a3[1]) -
            a1[1]*(a2[0]*a3[2] - a2[2]*a3[0]) +
            a1[2]*(a2[0]*a3[1] - a2[1]*a3[0])
        )


@dataclass
class Atom:
    element: str
    x: float; y: float; z: float  # fractional coordinates
    label: str = ""


@dataclass
class Structure:
    """Atomic structure with lattice and positions.

    ``source`` is recorded so evidence-tracked analyzers can attribute
    the structure back to its origin file (QE input, CIF, POSCAR, …).
    """
    lattice: Lattice | None = None
    atoms: list[Atom] = field(default_factory=list)
    formula: str = ""
    source: str = ""  # e.g. "qe_input", "cif", "poscar", "qe_output"

    @property
    def n_atoms(self) -> int:
        return len(self.atoms)

    @property
    def elements(self) -> list[str]:
        seen = []
        for a in self.atoms:
            if a.element not in seen:
                seen.append(a.element)
        return seen

    @property
    def n_species(self) -> int:
        return len(self.elements)

    def to_xyz_string(self) -> str:
        """Export as XYZ format string (for 3Dmol.js)."""
        lines = [str(self.n_atoms), self.formula or "structure"]
        cm = self.lattice.matrix if self.lattice else [[1,0,0],[0,1,0],[0,0,1]]
        for a in self.atoms:
            # Convert fractional → Cartesian
            cx = a.x*cm[0][0] + a.y*cm[1][0] + a.z*cm[2][0]
            cy = a.x*cm[0][1] + a.y*cm[1][1] + a.z*cm[2][1]
            cz = a.x*cm[0][2] + a.y*cm[1][2] + a.z*cm[2][2]
            lines.append(f"{a.element:3s} {cx:10.6f} {cy:10.6f} {cz:10.6f}")
        return "\n".join(lines)

    def to_ase_atoms(self) -> "Atoms":
        """Convert to ``ase.Atoms`` (requires the ``ase`` extra)."""
        if not _ase_available():
            raise RuntimeError(
                "Conversion to ase.Atoms requires the 'ase' extra. "
                "Install with: pip install -e \".[ase]\""
            )
        from ase import Atoms
        cell = self.lattice.matrix if self.lattice else None
        positions = [(a.x, a.y, a.z) for a in self.atoms]
        symbols = [a.element for a in self.atoms]
        return Atoms(
            symbols=symbols,
            scaled_positions=positions,
            cell=cell,
            pbc=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ASE bridge (private)
# ═══════════════════════════════════════════════════════════════════════════════

def _ase_atoms_to_structure(atoms: "Atoms", source: str = "") -> Structure:
    """Build a :class:`Structure` from an ``ase.Atoms`` object.

    Coordinates are stored as fractional (scaled) positions so the
    existing 2D-metric and symmetry code paths continue to work
    unchanged.
    """
    from ase import Atoms  # noqa: F401  (assert import works)
    cell = atoms.get_cell().tolist()
    # Scaled positions are fractional; ASE returns Cartesian in
    # ``get_positions()``. Use ``get_scaled_positions()`` so the
    # dataclass invariant (fractional) is preserved.
    scaled = atoms.get_scaled_positions(wrap=False)
    symbols = atoms.get_chemical_symbols()
    atoms_list = [
        Atom(element=str(s), x=float(p[0]), y=float(p[1]), z=float(p[2]))
        for s, p in zip(symbols, scaled)
    ]
    # Build a stable formula: element order of first appearance with
    # counts. ASE has ``atoms.get_chemical_formula()`` but it sorts
    # alphabetically; we want the vibedft-canonical order (preserves
    # POSCAR ordering for diff-friendly provenance).
    counts: dict[str, int] = {}
    for s in symbols:
        counts[s] = counts.get(s, 0) + 1
    seen_order: list[str] = []
    for s in symbols:
        if s not in seen_order:
            seen_order.append(s)
    # For binary+ we follow Hill notation only when C/H present; for
    # HfX2-style materials the original file order is what users
    # expect. We keep the appearance order.
    formula = "".join(f"{s}{counts[s] if counts[s] > 1 else ''}" for s in seen_order)
    return Structure(
        lattice=Lattice(matrix=cell),
        atoms=atoms_list,
        formula=formula or atoms.get_chemical_formula(),
        source=source,
    )


def _read_with_ase(filepath: Path, source_tag: str) -> Structure | None:
    """Common ASE read path used by every ``parse_structure_from_*`` helper.

    ASE's ``read`` autodetects format; we route a few extensions to the
    explicit QE format when ambiguity is likely (e.g. for QE inputs
    that lack a distinctive suffix).
    """
    if not _ase_available():
        return None
    from ase.io import read
    try:
        suffix = filepath.suffix.lower()
        if suffix in (".in", ".inp", "") or filepath.name.lower().startswith("pw"):
            # QE input — use espresso-in. (QE output uses a different
            # format tag and is handled by the dedicated helper below.)
            atoms = read(str(filepath), format="espresso-in")
        else:
            # Let ASE sniff (cif, poscar/vasp, xyz, …)
            atoms = read(str(filepath))
    except Exception:
        return None
    if atoms is None or len(atoms) == 0:
        return None
    return _ase_atoms_to_structure(atoms, source=str(filepath) or source_tag)


def _read_qe_output_with_ase(filepath: Path) -> Structure | None:
    """Read a QE pw.x output file using ASE's espresso-out parser."""
    if not _ase_available():
        return None
    from ase.io import read
    try:
        # ``index=-1`` returns the *last* structure reported by QE
        # (i.e. the relaxed geometry for vc-relax runs).
        atoms = read(str(filepath), format="espresso-out", index=-1)
    except Exception:
        return None
    if atoms is None or len(atoms) == 0:
        return None
    return _ase_atoms_to_structure(atoms, source=str(filepath))


# ═══════════════════════════════════════════════════════════════════════════════
# Public parsers
# ═══════════════════════════════════════════════════════════════════════════════

def parse_structure_from_qe_input(filepath: Path | str) -> Structure | None:
    """Parse a QE pw.x input file for CELL_PARAMETERS and ATOMIC_POSITIONS.

    Prefers ASE's ``espresso-in`` reader (handles ibrav, alat scaling,
    crystal/alat/angstrom coordinate modes, and species cards). Falls
    back to the built-in regex parser when the ``ase`` extra is
    unavailable.
    """
    path = Path(filepath)
    if not path.is_file():
        return None
    ase_struct = _read_with_ase(path, source_tag="qe_input")
    if ase_struct is not None:
        ase_struct.source = "qe_input:" + str(path)
        return ase_struct
    text = path.read_text(encoding="utf-8", errors="replace")
    struct = _parse_qe_text(text, source="qe_input:" + str(path))
    if struct:
        struct.source = "qe_input:" + str(path)
    return struct


def parse_structure_from_qe_output(filepath: Path | str) -> Structure | None:
    """Extract the final structure from a QE pw.x output (relax/vc-relax).

    Prefers ASE's ``espresso-out`` reader (captures the relaxed frame
    directly), falling back to the regex-based last-block parser.
    """
    path = Path(filepath)
    if not path.is_file():
        return None
    ase_struct = _read_qe_output_with_ase(path)
    if ase_struct is not None:
        ase_struct.source = "qe_output:" + str(path)
        return ase_struct
    # Fallback regex path (legacy)
    text = path.read_text(encoding="utf-8", errors="replace")
    cell = _parse_cell_from_output(text)
    atoms = _parse_atoms_from_output(text)
    if cell and atoms:
        return Structure(
            lattice=Lattice(matrix=cell),
            atoms=atoms,
            source="qe_output:" + str(path),
        )
    return None


def parse_structure_from_poscar(filepath: Path | str) -> Structure | None:
    """Parse a VASP POSCAR/CONTCAR file.

    When ASE is present this also accepts CIF, XYZ, and any other
    format ASE can read (front-end shared with :func:`parse_structure_from_cif`).
    Falls back to the legacy line-based parser otherwise.
    """
    path = Path(filepath)
    if not path.is_file():
        return None
    if _ase_available():
        ase_struct = _read_with_ase(path, source_tag="poscar")
        if ase_struct is not None:
            ase_struct.source = "poscar:" + str(path)
            return ase_struct
    # Legacy fallback
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 7:
        return None
    scale = float(lines[1].strip())
    cell = []
    for i in range(2, 5):
        parts = lines[i].split()
        if len(parts) >= 3:
            cell.append([float(x) * scale for x in parts[:3]])
    elements = lines[5].split()
    counts = [int(x) for x in lines[6].split()]
    atoms = []
    line_idx = 7
    coord_type = "Direct"
    for i in range(7, min(len(lines), 10)):
        if lines[i].strip().lower() in ("direct", "cartesian", "cart"):
            coord_type = lines[i].strip()
            line_idx = i + 1
            break
    lattice = Lattice(matrix=cell)
    for elem, count in zip(elements, counts):
        for _ in range(count):
            if line_idx >= len(lines):
                break
            parts = lines[line_idx].split()
            if len(parts) >= 3:
                if coord_type.lower().startswith("cart"):
                    inv = _invert_3x3(cell)
                    cx = float(parts[0]); cy = float(parts[1]); cz = float(parts[2])
                    fx = cx*inv[0][0] + cy*inv[1][0] + cz*inv[2][0]
                    fy = cx*inv[0][1] + cy*inv[1][1] + cz*inv[2][1]
                    fz = cx*inv[0][2] + cy*inv[1][2] + cz*inv[2][2]
                    atoms.append(Atom(element=elem, x=fx, y=fy, z=fz))
                else:
                    atoms.append(Atom(element=elem, x=float(parts[0]), y=float(parts[1]), z=float(parts[2])))
            line_idx += 1
    formula = "".join(f"{e}{c}" for e, c in zip(elements, counts))
    return Structure(
        lattice=lattice, atoms=atoms, formula=formula,
        source="poscar:" + str(path),
    )


def parse_structure_from_cif(filepath: Path | str) -> Structure | None:
    """Parse a CIF file. Requires the ``ase`` extra.

    CIF support was the primary motivation for the ASE integration:
    the legacy regex parser could not handle CIF's ``_cell_*`` and
    ``_atom_site_*`` loops. With ASE, reading CIF (and many other
    formats) is a one-liner.
    """
    path = Path(filepath)
    if not path.is_file():
        return None
    if not _ase_available():
        raise RuntimeError(
            "CIF parsing requires the 'ase' extra. "
            "Install with: pip install -e \".[ase]\""
        )
    ase_struct = _read_with_ase(path, source_tag="cif")
    if ase_struct is not None:
        ase_struct.source = "cif:" + str(path)
    return ase_struct


def parse_structure(filepath: Path | str) -> Structure | None:
    """Dispatch parser based on file extension.

    Convenience entry point used by the CLI's ``analyze structure``
    subcommand. Routes:
        - ``.cif`` → :func:`parse_structure_from_cif`
        - ``.in/.inp`` (or filename starts with ``pw``) →
          :func:`parse_structure_from_qe_input`
        - other → :func:`parse_structure_from_poscar` (POSCAR/CONTCAR)
    """
    path = Path(filepath)
    if not path.is_file():
        return None
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix == ".cif":
        try:
            return parse_structure_from_cif(path)
        except RuntimeError:
            # CIF needs ASE; if missing, drop to POSCAR-style parse
            # which will fail gracefully (returns None) and the CLI
            # surfaces a clear error.
            return None
    if suffix in (".in", ".inp") or name.startswith("pw"):
        struct = parse_structure_from_qe_input(path)
        if struct is not None:
            return struct
    # Default: try POSCAR, then QE input (back-compat with existing
    # callers), then QE output.
    return (
        parse_structure_from_poscar(path)
        or parse_structure_from_qe_input(path)
        or parse_structure_from_qe_output(path)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 2D Metrics (format-agnostic — works on the Structure dataclass)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TwoDMetrics:
    """2D-specific structural metrics."""
    vacuum_thickness_ang: float = 0.0
    layer_thickness_ang: float = 0.0
    interlayer_distance_ang: float = 0.0
    interlayer_gaps_ang: list[float] = field(default_factory=list)
    slab_has_vacuum: bool = False
    vacuum_sufficient: bool | None = None  # None = can't determine
    n_layers: int = 1
    buckling_ang: float = 0.0

    def summary(self) -> str:
        lines = [
            f"Vacuum thickness: {self.vacuum_thickness_ang:.2f} Å",
            f"Layer thickness:  {self.layer_thickness_ang:.2f} Å",
            f"Number of layers: {self.n_layers}",
        ]
        if self.vacuum_sufficient is not None:
            lines.append(f"Vacuum sufficient: {'Yes' if self.vacuum_sufficient else 'No'}")
        if self.buckling_ang > 0.01:
            lines.append(f"Buckling height: {self.buckling_ang:.3f} Å")
        return "\n".join(lines)


def compute_2d_metrics(structure: Structure) -> TwoDMetrics:
    """Compute 2D material metrics: vacuum, layer distance, buckling."""
    result = TwoDMetrics()
    if not structure.lattice or not structure.atoms:
        return result

    c = structure.lattice.c
    sorted_atoms = sorted(structure.atoms, key=lambda a: a.z)
    z_min = sorted_atoms[0].z
    z_max = sorted_atoms[-1].z
    layer_span = (z_max - z_min) * c  # in Å

    result.layer_thickness_ang = layer_span
    result.vacuum_thickness_ang = c - layer_span
    result.slab_has_vacuum = result.vacuum_thickness_ang > 3.0
    result.vacuum_sufficient = result.vacuum_thickness_ang > 10.0  # typical ≥15Å for 2D

    z_gaps = []
    for i in range(1, len(sorted_atoms)):
        gap = (sorted_atoms[i].z - sorted_atoms[i-1].z) * c
        z_gaps.append(gap)
    if z_gaps:
        mean_gap = sum(z_gaps) / len(z_gaps)
        large_gap_threshold = mean_gap * 3.0
        for g in z_gaps:
            if g > large_gap_threshold and g > 2.0:
                result.n_layers += 1
                result.interlayer_gaps_ang.append(g)
    if result.interlayer_gaps_ang:
        result.interlayer_distance_ang = sum(result.interlayer_gaps_ang) / len(result.interlayer_gaps_ang)

    elem_z = {}
    for a in structure.atoms:
        elem_z.setdefault(a.element, []).append(a.z * c)
    for elem, zs in elem_z.items():
        if len(zs) > 1:
            buckle = max(zs) - min(zs)
            if buckle > result.buckling_ang:
                result.buckling_ang = buckle

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Symmetry (spglib, via ASE when available)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_symmetry(structure: Structure) -> dict[str, Any]:
    """Compute symmetry information using spglib if available.

    Returns a dict with ``space_group_number``, ``space_group_symbol``,
    ``n_operations``, and ``available`` (False when spglib missing).
    The optional ``wyckoff_positions`` key is added when spglib
    exposes Wyckoff labels. All values are JSON-serializable so the
    result can flow directly into evidence packs and review reports.
    """
    result: dict[str, Any] = {
        "space_group_number": None,
        "space_group_symbol": None,
        "n_operations": None,
        "available": False,
    }
    if not _ase_available():
        return result
    import spglib
    cell = structure.lattice.matrix if structure.lattice else [[1,0,0],[0,1,0],[0,0,1]]
    positions = [[a.x, a.y, a.z] for a in structure.atoms]
    numbers = [_atomic_number(a.element) for a in structure.atoms]
    try:
        spg_data = spglib.get_symmetry_dataset(
            (cell, positions, numbers), symprec=0.01
        )
    except Exception:
        # spglib >= 2.0 may raise on ill-formatted input; older
        # versions returned None. Treat both as "unavailable".
        spg_data = None
    if spg_data:
        # spglib 2.x: use attribute interface; 1.x: dict interface
        num = getattr(spg_data, "number", None) or spg_data.get("number")
        intl = getattr(spg_data, "international", None) or spg_data.get("international")
        rotations = getattr(spg_data, "rotations", None)
        if rotations is None and isinstance(spg_data, dict):
            rotations = spg_data.get("rotations", [])
        result["space_group_number"] = num
        result["space_group_symbol"] = intl
        result["n_operations"] = len(rotations) if rotations is not None else 0
        result["available"] = True
        wyckoffs = getattr(spg_data, "wyckoffs", None)
        if wyckoffs is None and isinstance(spg_data, dict):
            wyckoffs = spg_data.get("wyckoffs", [])
        if wyckoffs:
            result["wyckoff_positions"] = list(set(wyckoffs))
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers (legacy fallback path — preserved for zero-deps mode)
# ═══════════════════════════════════════════════════════════════════════════════

def _angle_between(v1: list[float], v2: list[float]) -> float:
    dot = v1[0]*v2[0] + v1[1]*v2[1] + v1[2]*v2[2]
    m1 = math.sqrt(v1[0]**2 + v1[1]**2 + v1[2]**2)
    m2 = math.sqrt(v2[0]**2 + v2[1]**2 + v2[2]**2)
    if m1 < 1e-12 or m2 < 1e-12:
        return 90.0
    cos = max(-1.0, min(1.0, dot/(m1*m2)))
    return math.degrees(math.acos(cos))


_ATOMIC_NUMBERS = {
    "H":1,"He":2,"Li":3,"Be":4,"B":5,"C":6,"N":7,"O":8,"F":9,"Ne":10,
    "Na":11,"Mg":12,"Al":13,"Si":14,"P":15,"S":16,"Cl":17,"Ar":18,
    "K":19,"Ca":20,"Sc":21,"Ti":22,"V":23,"Cr":24,"Mn":25,"Fe":26,"Co":27,"Ni":28,
    "Cu":29,"Zn":30,"Ga":31,"Ge":32,"As":33,"Se":34,"Br":35,"Kr":36,
    "Rb":37,"Sr":38,"Y":39,"Zr":40,"Nb":41,"Mo":42,"Tc":43,"Ru":44,"Rh":45,"Pd":46,
    "Ag":47,"Cd":48,"In":49,"Sn":50,"Sb":51,"Te":52,"I":53,"Xe":54,
    "Cs":55,"Ba":56,"La":57,"Ce":58,"Pr":59,"Nd":60,
    "Hf":72,"Ta":73,"W":74,"Re":75,"Os":76,"Ir":77,"Pt":78,"Au":79,"Hg":80,
    "Pb":82,"Bi":83,
}


def _atomic_number(element: str) -> int:
    return _ATOMIC_NUMBERS.get(element, 0)


def _invert_3x3(m: list[list[float]]) -> list[list[float]]:
    det = (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1]) -
           m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0]) +
           m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))
    if abs(det) < 1e-20:
        return [[1,0,0],[0,1,0],[0,0,1]]
    inv_det = 1.0/det
    return [
        [(m[1][1]*m[2][2]-m[1][2]*m[2][1])*inv_det,
         (m[0][2]*m[2][1]-m[0][1]*m[2][2])*inv_det,
         (m[0][1]*m[1][2]-m[0][2]*m[1][1])*inv_det],
        [(m[1][2]*m[2][0]-m[1][0]*m[2][2])*inv_det,
         (m[0][0]*m[2][2]-m[0][2]*m[2][0])*inv_det,
         (m[0][2]*m[1][0]-m[0][0]*m[1][2])*inv_det],
        [(m[1][0]*m[2][1]-m[1][1]*m[2][0])*inv_det,
         (m[0][1]*m[2][0]-m[0][0]*m[2][1])*inv_det,
         (m[0][0]*m[1][1]-m[0][1]*m[1][0])*inv_det],
    ]


def _parse_qe_text(text: str, source: str = "") -> Structure | None:
    """Parse CELL_PARAMETERS and ATOMIC_POSITIONS from QE input/output text.

    Used as the fallback when ASE is unavailable. ASE's
    ``espresso-in`` reader is preferred because it understands
    ``ibrav`` and ``alat`` scaling, which this regex path does not.
    """
    cell = None
    atoms = []

    m_cell = re.search(
        r"CELL_PARAMETERS[^\n]*\n((?:\s*[-.\d]+\s+[-.\d]+\s+[-.\d]+\s*\n){3})",
        text
    )
    if not m_cell:
        m_cell = re.search(
            r"CELL_PARAMETERS[^\n]*\n((?:\s*[-.\d]+\s+[-.\d]+\s+[-.\d]+(?:\s*\n|$)){3})",
            text
        )
    if m_cell:
        lines = m_cell.group(1).strip().splitlines()
        cell = []
        for line in lines[:3]:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    cell.append([float(x) for x in parts[:3]])
                except ValueError:
                    break
        if len(cell) < 3:
            cell = None

    m_atoms = re.search(
        r"ATOMIC_POSITIONS[^\n]*\n((?:\s*\w[\w.]*(?:\s+[-.\d]+){3}\s*\n?)*)",
        text
    )
    if m_atoms:
        for line in m_atoms.group(1).strip().splitlines():
            parts = line.split()
            if len(parts) >= 4:
                try:
                    atoms.append(Atom(
                        element=parts[0],
                        x=float(parts[1]), y=float(parts[2]), z=float(parts[3]),
                    ))
                except ValueError:
                    continue

    if cell or atoms:
        return Structure(
            lattice=Lattice(matrix=cell) if cell else None,
            atoms=atoms, source=source,
        )
    return None


def _parse_cell_from_output(text: str) -> list[list[float]] | None:
    """Find the last CELL_PARAMETERS block in QE output (fallback path)."""
    blocks = list(re.finditer(
        r"CELL_PARAMETERS.*?\n((?:\s*[-.\d]+\s+[-.\d]+\s+[-.\d]+\s*\n){3})",
        text
    ))
    if not blocks:
        return None
    last = blocks[-1].group(1)
    cell = []
    for line in last.strip().splitlines():
        parts = line.split()
        try:
            cell.append([float(x) for x in parts[:3]])
        except ValueError:
            return None
    return cell if len(cell) == 3 else None


def _parse_atoms_from_output(text: str) -> list[Atom] | None:
    """Find the last ATOMIC_POSITIONS block in QE output (fallback path)."""
    m = re.search(
        r"ATOMIC_POSITIONS\s*\(crystal\)\s*\n(.*?)(?:\n\s*\n|\n[ A-Z])",
        text, re.DOTALL
    )
    if not m:
        return None
    atoms = []
    for line in m.group(1).strip().splitlines():
        parts = line.split()
        if len(parts) >= 4:
            try:
                atoms.append(Atom(element=parts[0], x=float(parts[1]), y=float(parts[2]), z=float(parts[3])))
            except ValueError:
                continue
    return atoms if atoms else None