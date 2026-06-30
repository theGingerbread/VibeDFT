"""Batch directory scanner — discovers case subdirectories with results."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CaseSnapshot:
    """Metadata and result paths for one batch case directory."""
    name: str                          # directory name
    path: str                          # full path
    has_scf_output: bool = False
    has_dos_output: bool = False
    has_bands_output: bool = False
    has_phonon_output: bool = False
    has_lambda_output: bool = False
    has_a2f_output: bool = False
    file_count: int = 0
    input_files: list[str] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)


def scan_batch_root(root: Path | str) -> list[CaseSnapshot]:
    """Scan a root directory for case subdirectories.

    A subdirectory is considered a "case" if it contains an output/ dir
    with at least one .out file, OR it directly contains .out files.
    """
    r = Path(root).resolve()
    if not r.is_dir():
        return []

    snapshots: list[CaseSnapshot] = []

    # Strategy: iterate over all subdirectories at depth 1
    for child in sorted(r.iterdir()):
        if not child.is_dir():
            continue
        # Skip hidden / non-case dirs
        if child.name.startswith("."):
            continue

        snap = _scan_case_dir(child)
        if snap.has_scf_output or snap.has_lambda_output or snap.has_phonon_output:
            snapshots.append(snap)

    # If no sub-cases found, treat root itself as a single case
    if not snapshots:
        snap = _scan_case_dir(r)
        if snap.has_scf_output or snap.has_lambda_output or snap.has_phonon_output:
            snapshots.append(snap)

    return snapshots


def _scan_case_dir(d: Path) -> CaseSnapshot:
    snap = CaseSnapshot(name=d.name, path=str(d))

    all_files = list(d.rglob("*"))
    snap.file_count = len([f for f in all_files if f.is_file()])

    for f in all_files:
        if not f.is_file():
            continue
        if f.suffix == ".in":
            snap.input_files.append(str(f))
        if f.suffix == ".out":
            snap.output_files.append(str(f))

        name_lower = f.name.lower()
        if "scf" in name_lower and f.suffix == ".out":
            snap.has_scf_output = True
        if f.suffix == ".dos" or "dos" in name_lower:
            snap.has_dos_output = True
        if "bands" in name_lower and f.suffix not in (".out",):
            snap.has_bands_output = True
        if ("freq" in name_lower and f.suffix == ".gp") or name_lower.endswith(".fc"):
            snap.has_phonon_output = True
        if "lambdax" in name_lower and f.suffix == ".out":
            snap.has_lambda_output = True
        if "alpha2f" in name_lower or "a2f" in name_lower:
            snap.has_a2f_output = True

    return snap
