"""Material identifier — infer formula, elements, lattice from input files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MaterialIdentity:
    formula_from_species: str = ""     # from ATOMIC_SPECIES
    formula_from_positions: str = ""   # from ATOMIC_POSITIONS counts
    elements: list[str] = field(default_factory=list)
    n_atoms: int = 0
    stoichiometry: dict[str, int] = field(default_factory=dict)
    lattice_vectors: list[list[float]] = field(default_factory=list)
    c_axis_ang: float = 0.0
    likely_2d: bool = False
    likely_space_group: str = ""
    label_formula: str = ""            # from directory/file naming
    formula_conflict: bool = False
    conflict_detail: str = ""
    evidence: list[str] = field(default_factory=list)


def identify_material(case_dir: Path | str) -> MaterialIdentity:
    """Infer material identity from all .in files in a case directory."""
    d = Path(case_dir)
    result = MaterialIdentity()

    # Gather ATOMIC_SPECIES and ATOMIC_POSITIONS from the FIRST valid pw.x input.
    # Using all files would aggregate atom counts across strain copies.
    from vibedft.parsers.qe_input_parser import parse_qe_input
    all_elements: list[str] = []
    position_counts: dict[str, int] = {}
    cell_found = False

    for in_file in sorted(d.rglob("*.in")):
        try:
            qe = parse_qe_input(in_file)
        except Exception:
            continue
        # Only sample from pw.x inputs (skip ph.x, q2r, matdyn, lambda)
        if qe.program.value not in ("pw.x",):
            continue

        species_card = qe.cards.get("ATOMIC_SPECIES")
        pos_card = qe.cards.get("ATOMIC_POSITIONS")
        cell_card = qe.cards.get("CELL_PARAMETERS")

        if species_card and species_card.rows and not all_elements:
            for row in species_card.rows:
                if row and row[0] not in all_elements:
                    all_elements.append(row[0])

        if pos_card and pos_card.rows and not position_counts:
            for row in pos_card.rows:
                if row:
                    elem = row[0]
                    # Skip option keywords like "crystal", "angstrom", "bohr" etc.
                    if elem.lower() in ("crystal", "angstrom", "bohr", "alat"):
                        continue
                    position_counts[elem] = position_counts.get(elem, 0) + 1

        if cell_card and cell_card.rows and not cell_found:
            for row in cell_card.rows[:3]:
                try:
                    result.lattice_vectors.append([float(x) for x in row[:3]])
                except ValueError:
                    pass
            cell_found = True

        # Stop once we have everything
        if all_elements and position_counts and cell_found:
            break

    result.elements = all_elements
    result.n_atoms = sum(position_counts.values())
    result.stoichiometry = dict(position_counts)

    # Formula from species list
    if all_elements:
        result.formula_from_species = "".join(all_elements)

    # Formula from position counts
    if position_counts:
        parts = []
        for elem in all_elements:
            c = position_counts.get(elem, 0)
            parts.append(f"{elem}{c}" if c > 1 else elem)
        result.formula_from_positions = "".join(parts)

    # c-axis for 2D detection
    if len(result.lattice_vectors) >= 3:
        c_vec = result.lattice_vectors[2]
        result.c_axis_ang = (c_vec[0]**2 + c_vec[1]**2 + c_vec[2]**2) ** 0.5
        result.likely_2d = result.c_axis_ang > 15

    # Detect formula conflict from directory naming
    result.label_formula = _guess_label_formula(d)
    if result.label_formula and result.formula_from_positions:
        if result.label_formula.upper() != result.formula_from_positions.upper():
            result.formula_conflict = True
            result.conflict_detail = (
                f"Label suggests '{result.label_formula}', but "
                f"ATOMIC_POSITIONS count gives '{result.formula_from_positions}'."
            )

    # Evidence
    if result.formula_from_positions:
        result.evidence.append(f"Formula from ATOMIC_POSITIONS: {result.formula_from_positions}")
    if result.likely_2d:
        result.evidence.append(f"Likely 2D material: c-axis = {result.c_axis_ang:.1f} Å")

    return result


def _guess_label_formula(d: Path) -> str:
    """Guess formula from directory name patterns."""
    import re
    # Check directory name for common patterns like HfBr2, AsS, etc.
    for part in d.parts:
        m = re.search(r'(?:^|/)([A-Z][a-z]?\d?[A-Z][a-z]?\d?)(?:/|$)', str(d))
        if m:
            return m.group(1)
    return d.name
