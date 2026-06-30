"""Magnetism analyzer — extract magnetization from SCF output."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MagnetismResult:
    """Magnetic properties extracted from QE output."""
    source_file: str = ""
    has_data: bool = False
    total_magnetization: float | None = None
    absolute_magnetization: float | None = None
    per_atom_moments: list[dict] = field(default_factory=list)
    fm_energy_ry: float | None = None
    is_magnetic: bool = False
    summary: str = ""


def extract_magnetism(case_dir: Path | str) -> MagnetismResult:
    """Extract magnetic properties from SCF output files."""
    d = Path(case_dir)
    result = MagnetismResult()

    scf_files = list(d.rglob("scf.out"))
    if not scf_files:
        return result

    for fp in scf_files[:1]:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        result.source_file = str(fp)

        # Total magnetization
        m_total = re.search(r"total magnetization\s*=\s*([-\d.]+)\s*Bohr", text, re.IGNORECASE)
        if not m_total:
            m_total = re.search(r"absolute magnetization\s*=\s*([-\d.]+)\s*Bohr", text, re.IGNORECASE)
        if m_total:
            result.total_magnetization = float(m_total.group(1))

        m_abs = re.search(r"absolute magnetization\s*=\s*([-\d.]+)\s*Bohr", text, re.IGNORECASE)
        if m_abs:
            result.absolute_magnetization = float(m_abs.group(1))

        # Per-atom moments (Mulliken or Löwdin)
        # Format: "atom  1  Hf  mag =  0.123"
        for m_atom in re.finditer(r"atom\s+\d+\s+\w+\s+mag\s*=\s*([-\d.]+)", text, re.IGNORECASE):
            result.per_atom_moments.append({"moment": float(m_atom.group(1))})

        result.has_data = True

    if result.total_magnetization is not None:
        result.is_magnetic = abs(result.total_magnetization) > 0.1
        if result.is_magnetic:
            result.summary = f"Magnetic: μ_total = {result.total_magnetization:.3f} μB"
        else:
            result.summary = "Non-magnetic (μ ≈ 0)"

    return result
