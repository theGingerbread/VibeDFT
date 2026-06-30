"""Unified data models for the VibeDFT inspection pipeline.

These dataclasses provide a stable JSON-serialisable contract between
parsers, classifiers, validators, and the CLI / future web API.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════════
# Program / Task enums
# ═══════════════════════════════════════════════════════════════════════════════


class QEProgram(str, enum.Enum):
    """Quantum ESPRESSO program identified from namelist or output signature."""
    PW = "pw.x"
    PH = "ph.x"
    Q2R = "q2r.x"
    MATDYN = "matdyn.x"
    LAMBDA = "lambda.x"
    DOS = "dos.x"
    BANDS = "bands.x"
    PROJWFC = "projwfc.x"
    FS = "fs.x"
    PP = "pp.x"            # pp.x post-processing (charge/potential plotter)
    DYNMAT = "dynmat.x"    # dynmat.x dynamical matrix diagonalization
    AVERAGE = "average.x"  # average.x planar/spherical average of charge/potential
    UNKNOWN = "unknown"


class TaskType(str, enum.Enum):
    """Calculation purpose classified from namelist content."""
    SCF = "scf"                       # pw.x self-consistent field
    NSCF = "nscf"                     # pw.x non-self-consistent
    RELAX = "relax"                   # pw.x ionic relaxation
    VC_RELAX = "vc-relax"             # pw.x variable-cell relaxation
    BANDS = "bands"                   # pw.x band-structure (NSCF on k-path)
    AIMD = "aimd"                     # pw.x ab-initio molecular dynamics (calculation='md')
    PH_STABILITY = "ph_stability"     # ph.x phonon stability (no EPC)
    PH_EPC = "ph_epc"                 # ph.x with electron-phonon coupling
    Q2R = "q2r"                       # q2r.x Fourier transform
    MATDYN_DISP = "matdyn_disp"       # matdyn.x phonon dispersion
    MATDYN_DOS = "matdyn_dos"         # matdyn.x phonon DOS
    LAMBDA_TC = "lambda_tc"           # lambda.x Tc post-processing
    PP_RHO = "pp_rho"                 # pp.x charge/potential extraction
    DYNMAT = "dynmat"                 # dynmat.x dynamical matrix post-proc
    PLANAR_AVERAGE = "planar_average"  # average.x planar average of charge/potential
    UNKNOWN = "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# Parsed input model
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class NamelistBlock:
    """One Fortran namelist (e.g. &CONTROL … /)."""
    name: str                                        # e.g. "CONTROL", "SYSTEM"
    params: dict[str, Any] = field(default_factory=dict)
    raw_lines: list[str] = field(default_factory=list)


@dataclass
class CardBlock:
    """One QE card block (e.g. ATOMIC_SPECIES, K_POINTS …)."""
    name: str                                        # e.g. "ATOMIC_SPECIES"
    option: str = ""                                 # e.g. "crystal", "automatic", "angstrom"
    rows: list[list[str]] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)


@dataclass
class QEInput:
    """Complete parsed Quantum ESPRESSO input file.

    Covers pw.x, ph.x, q2r.x, matdyn.x, and lambda.x inputs.
    For lambda.x (free-format, no namelists), the *raw_text* field
    holds the full content for specialised parsing.
    """
    source_path: str = ""
    program: QEProgram = QEProgram.UNKNOWN
    namelists: dict[str, NamelistBlock] = field(default_factory=dict)
    cards: dict[str, CardBlock] = field(default_factory=dict)
    raw_text: str = ""
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_namelists(self) -> bool:
        return len(self.namelists) > 0

    @property
    def has_cards(self) -> bool:
        return len(self.cards) > 0

    def get_param(self, namelist: str, key: str, default: Any = None) -> Any:
        """Convenience: retrieve a parameter from a namelist."""
        nl = self.namelists.get(namelist.lower())
        if nl is None:
            return default
        return nl.params.get(key, default)


# ═══════════════════════════════════════════════════════════════════════════════
# Issue / Evidence
# ═══════════════════════════════════════════════════════════════════════════════


class Severity(str, enum.Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class SanityIssue:
    """A single sanity-check finding."""
    id: str
    severity: Severity
    message: str
    source_file: str = ""
    source_line: int | None = None
    detail: str = ""


@dataclass
class EvidenceRef:
    """Pointer to a source file + parser that produced a value."""
    file: str
    parser: str = ""
    key: str = ""       # e.g. "namelist:CONTROL:calculation"
    value: Any = None


# ═══════════════════════════════════════════════════════════════════════════════
# Task record
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class TaskRecord:
    """One identified calculation task from a file or file pair."""
    program: QEProgram = QEProgram.UNKNOWN
    task_type: TaskType = TaskType.UNKNOWN
    source_file: str = ""
    paired_files: list[str] = field(default_factory=list)
    key_params: dict[str, Any] = field(default_factory=dict)
    confidence: str = "low"   # low | medium | high


# ═══════════════════════════════════════════════════════════════════════════════
# File record
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class FileRecord:
    """Metadata and parse result for one user-supplied file."""
    path: str
    type: str = "unknown"          # "input" | "output" | "data" | "unknown"
    parse_status: str = "pending"  # "ok" | "partial" | "failed"
    program: QEProgram = QEProgram.UNKNOWN
    summary: str = ""
    parse_errors: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Top-level inspection result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class InspectionResult:
    """Complete inspection result for one or more QE files.

    This is the stable JSON contract for ``vibedft inspect``.
    """
    files: list[FileRecord] = field(default_factory=list)
    tasks: list[TaskRecord] = field(default_factory=list)
    issues: list[SanityIssue] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (JSON-safe)."""
        import dataclasses

        def _convert(obj: Any) -> Any:
            if dataclasses.is_dataclass(obj):
                return {k: _convert(v) for k, v in dataclasses.asdict(obj).items()}
            if isinstance(obj, enum.Enum):
                return obj.value
            if isinstance(obj, (list, tuple)):
                return [_convert(v) for v in obj]
            return obj

        return _convert(self)  # type: ignore[no-any-return]

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)
