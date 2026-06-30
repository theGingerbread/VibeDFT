"""Batch intent detection — strain scans, dual-grid EPC, calculation families."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BatchIntent:
    strain_scan: bool = False
    strain_type: str = ""              # "compressive" | "tensile" | "both"
    strain_values: list[str] = field(default_factory=list)
    dual_grid_epc: bool = False
    epc_grids: list[str] = field(default_factory=list)  # ["ph64", "ph96"]
    calculation_families: list[str] = field(default_factory=list)
    is_template_library: bool = False
    is_batch_campaign: bool = False
    summary: str = ""


def detect_batch_intent(case_dir: Path | str) -> BatchIntent:
    """Detect batch study design from directory structure and naming."""
    d = Path(case_dir)
    result = BatchIntent()

    # ── Strain scan detection ──
    compress_dir = d / "compress"
    tensile_dir = d / "tensile"
    strain_values: list[str] = []
    strain_types: list[str] = []

    if compress_dir.is_dir():
        vals = sorted([x.name for x in compress_dir.iterdir() if x.is_dir() and _is_float(x.name)])
        strain_values.extend(vals)
        if vals:
            strain_types.append("compressive")
            result.strain_scan = True

    if tensile_dir.is_dir():
        vals = sorted([x.name for x in tensile_dir.iterdir() if x.is_dir() and _is_float(x.name)])
        strain_values.extend(vals)
        if vals:
            strain_types.append("tensile")
            result.strain_scan = True

    result.strain_type = "+".join(strain_types) if strain_types else ""

    # Collect all numeric subdirectories as strain values
    all_numeric: set[str] = set()
    for child in d.iterdir():
        if child.is_dir() and _is_float(child.name):
            all_numeric.add(child.name)
    result.strain_values = sorted(all_numeric, key=float)

    # ── Dual-grid EPC detection ──
    epc_grids: set[str] = set()
    for sub in d.rglob("ph*"):
        if sub.is_dir() and re.match(r'^ph\d+$', sub.name):
            epc_grids.add(sub.name)
    result.dual_grid_epc = len(epc_grids) >= 2
    result.epc_grids = sorted(epc_grids)

    # ── Calculation families ──
    families: set[str] = set()
    top_dirs = [x.name for x in d.iterdir() if x.is_dir()]
    family_map = {
        "rx": "relaxation", "relax": "relaxation",
        "scf": "electronic_structure", "scf_dos": "electronic_structure",
        "bands": "band_structure",
        "ph": "phonon_epc", "ph64": "phonon_epc", "ph96": "phonon_epc",
        "compress": "strain_engineering", "tensile": "strain_engineering",
    }
    for td in top_dirs:
        for key, fam in family_map.items():
            if td == key or td.startswith(key):
                families.add(fam)

    # Also check deeper
    for sub in d.rglob("*"):
        if sub.is_dir():
            for key, fam in family_map.items():
                if sub.name == key:
                    families.add(fam)

    result.calculation_families = sorted(families)

    # ── Is this a template library? ──
    # Heuristic: many .in files, structured subdirectories, repetitive patterns
    in_count = len(list(d.rglob("*.in")))
    result.is_template_library = in_count > 20
    result.is_batch_campaign = result.strain_scan and in_count > 50

    # ── Summary ──
    parts: list[str] = []
    if result.strain_scan:
        parts.append(
            f"Strain-engineering scan detected: {result.strain_type} "
            f"({', '.join(result.strain_values[:8])})"
        )
    if result.dual_grid_epc:
        parts.append(f"Dual-grid EPC: {', '.join(result.epc_grids)}")
    if result.calculation_families:
        parts.append(f"Families: {', '.join(result.calculation_families)}")
    if result.is_template_library:
        parts.append("Appears to be a template library (many input files, structured layout).")

    result.summary = " ".join(parts) if parts else "Single-case or unstructured directory."

    return result


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False
