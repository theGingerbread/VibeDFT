"""HfCl2 evidence pack stubs — structured provenance for each workflow stage.

These provide the **schema contracts** for evidence collected at each
stage of the HfCl2 workflow.  Actual population happens during or
after calculation pullback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════════
# Base evidence types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ProvenanceRecord:
    """Provenance tracking for evidence."""
    input_files: list[str] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)
    commit: str | None = None
    job_ids: list[str] = field(default_factory=list)
    remote_host: str | None = None


@dataclass
class BaseEvidence:
    """Base for all HfCl2 evidence stubs."""
    case: str = ""
    stage: str = ""
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)


# ═══════════════════════════════════════════════════════════════════════════════
# P2: K fatband evidence
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class FatbandInputEvidence(BaseEvidence):
    """Evidence from P2 fatband input setup."""
    stage: str = "P2_fatband"
    inputs: dict[str, Any] = field(default_factory=lambda: {
        "prefix": "",
        "outdir": "",
        "filpdos": "",
        "kresolveddos": None,
        "Emin_ev": None,
        "Emax_ev": None,
        "DeltaE_ev": None,
    })
    status: str = "pending"  # pending | submitted | running | completed | failed


@dataclass
class FatbandOutputEvidence(BaseEvidence):
    """Evidence from P2 fatband output parsing."""
    stage: str = "P2_fatband"
    outputs: dict[str, Any] = field(default_factory=lambda: {
        "hf_d_at_ef_pct": None,
        "hf_dz2_at_ef_pct": None,
        "hf_dxy_dx2y2_at_ef_pct": None,
        "hf_dxz_dyz_at_ef_pct": None,
        "k_4s_at_ef_pct": None,
        "k_4p_at_ef_pct": None,
        "cl_3p_at_ef_pct": None,
        "max_weight_band_idx": None,
        "has_band_crossing": None,
    })
    status: str = "pending"


# ═══════════════════════════════════════════════════════════════════════════════
# P3: Smearing sensitivity evidence
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SmearingInputEvidence(BaseEvidence):
    """Evidence from P3 smearing sensitivity input setup."""
    stage: str = "P3_smearing"
    inputs: dict[str, Any] = field(default_factory=lambda: {
        "degauss_ry": [],
        "kmesh": [],
        "pseudo_family": "",
        "ecutwfc_ry": None,
        "ecutrho_ry": None,
        "nscf_prefix": "",
        "occupations": "",
        "smearing": "",
        "nbnd": None,
    })
    status: str = "pending"


@dataclass
class SmearingOutputEvidence(BaseEvidence):
    """Evidence from P3 smearing sensitivity DOS output."""
    stage: str = "P3_smearing"
    outputs: dict[str, Any] = field(default_factory=lambda: {
        "variants": [],  # [{degauss, dos_at_ef, dos_pm_0p1_ev, peak_position_ev}]
        "dos_max_variation_pct": None,
        "peak_shift_ev": None,
        "verdict": "",  # robust | smearing-sensitive | invalid
    })
    status: str = "pending"


# ═══════════════════════════════════════════════════════════════════════════════
# B1: Pristine rrkjus reference evidence
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class PristineInputEvidence(BaseEvidence):
    """Evidence from B1 pristine reference setup."""
    stage: str = "B1_pristine_rrkjus"
    inputs: dict[str, Any] = field(default_factory=lambda: {
        "pseudo_family": "",
        "ecutwfc_ry": None,
        "ecutrho_ry": None,
        "c_ang": None,
        "assume_isolated": "",
        "cell_dofree": "",
        "elements": [],
        "calculation": "",
    })
    status: str = "pending"


@dataclass
class PristineOutputEvidence(BaseEvidence):
    """Evidence from B1 pristine calculation output."""
    stage: str = "B1_pristine_rrkjus"
    outputs: dict[str, Any] = field(default_factory=lambda: {
        "final_energy_ry": None,
        "final_a_ang": None,
        "final_c_ang": None,
        "scf_converged": None,
        "relax_converged": None,
    })
    status: str = "pending"
