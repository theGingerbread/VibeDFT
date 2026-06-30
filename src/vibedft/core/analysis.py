"""Parse and extract key results from Quantum ESPRESSO output files.

Supports pw.x SCF/NSCF output, dos.x output, bands.x output,
and data-file parsing (HfBr2.dos, HfBr2.bands, HfBr2.bands.gnu).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# PW.X SCF output
# ---------------------------------------------------------------------------

@dataclass
class QeOutput:
    """Structured results parsed from a QE pw.x output file."""

    program: str = ""
    version: str = ""
    total_energy_ry: float | None = None
    total_energy_ev: float | None = None
    fermi_energy_ev: float | None = None
    scf_converged: bool = False
    scf_iterations: int = 0
    scf_accuracy_ry: float | None = None
    wall_time_sec: float | None = None
    cpu_time_sec: float | None = None
    convergence_history: list[dict[str, Any]] = field(default_factory=list)
    forces: list[dict[str, Any]] = field(default_factory=list)
    stress: list[float] = field(default_factory=list)
    raw_errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Program        : {self.program} v{self.version}",
            f"Total Energy   : {self.total_energy_ry:.6f} Ry ({self.total_energy_ev:.4f} eV)"
            if self.total_energy_ry
            else "Total Energy   : N/A",
            f"Fermi Energy   : {self.fermi_energy_ev:.4f} eV"
            if self.fermi_energy_ev
            else "Fermi Energy   : N/A",
            f"SCF Converged  : {self.scf_converged} ({self.scf_iterations} iterations)",
            f"SCF Accuracy   : {self.scf_accuracy_ry:.2e} Ry"
            if self.scf_accuracy_ry
            else "SCF Accuracy   : N/A",
            f"Wall Time      : {self.wall_time_sec:.1f} s"
            if self.wall_time_sec
            else "Wall Time      : N/A",
            f"CPU Time       : {self.cpu_time_sec:.1f} s"
            if self.cpu_time_sec
            else "CPU Time       : N/A",
        ]
        if self.forces:
            lines.append("Forces (Ry/au):")
            for f in self.forces:
                lines.append(
                    f"  {f['atom']}: {f['fx']:10.6f} {f['fy']:10.6f} {f['fz']:10.6f}"
                )
        if self.stress:
            lines.append(f"Stress (kbar): {self.stress}")
        if self.raw_errors:
            lines.append("Errors/Warnings:")
            for e in self.raw_errors:
                lines.append(f"  {e}")
        return "\n".join(lines)


def parse_qe_output(filepath: Path | str) -> QeOutput:
    """Parse a Quantum ESPRESSO pw.x output file into structured results."""
    path = Path(filepath)
    text = path.read_text(encoding="utf-8", errors="replace")
    result = QeOutput()

    # Program version
    m = re.search(r"Program\s+(PW\S*)\s+v\.(\S+)", text)
    if m:
        result.program = m.group(1)
        result.version = m.group(2)

    # SCF convergence
    result.scf_converged = "convergence has been achieved" in text
    # Count iterations from convergence history (most reliable)
    iter_count = re.findall(r"iteration #\s*(\d+)", text)
    if iter_count:
        result.scf_iterations = int(iter_count[-1])
    else:
        m = re.search(r"number of scf cycles\s*=\s*(\d+)", text)
        if m:
            result.scf_iterations = int(m.group(1))
    m = re.search(r"estimated scf accuracy\s*<\s*([\d.E+-]+)\s*Ry", text)
    if m:
        result.scf_accuracy_ry = float(m.group(1))

    # Total energy - last occurrence before final
    energies = re.findall(r"!\s+total energy\s+=\s+([-\d.]+)\s+Ry", text)
    if energies:
        result.total_energy_ry = float(energies[-1])
        result.total_energy_ev = result.total_energy_ry * 13.605703976

    # Fermi energy
    m = re.search(r"the Fermi energy is\s+([-\d.]+)\s+ev", text)
    if m:
        result.fermi_energy_ev = float(m.group(1))

    # Timing
    m = re.search(r"PWSCF\s+:\s+([\d.]+)s CPU\s+([\d.]+)s WALL", text)
    if m:
        result.cpu_time_sec = float(m.group(1))
        result.wall_time_sec = float(m.group(2))

    # SCF convergence history
    for m in re.finditer(
        r"iteration #\s*(\d+).*?"
        r"total energy\s+=\s+([-\d.]+)\s+Ry.*?"
        r"estimated scf accuracy\s*<\s*([\d.E+-]+)\s+Ry",
        text,
        re.DOTALL,
    ):
        result.convergence_history.append(
            {
                "iteration": int(m.group(1)),
                "energy_ry": float(m.group(2)),
                "accuracy_ry": float(m.group(3)),
            }
        )

    # Forces (for relax calculations)
    force_section = False
    for line in text.splitlines():
        if "Forces acting on atoms" in line:
            force_section = True
            continue
        if force_section and "atom" in line and "=" in line:
            force_section = False
        if force_section:
            m = re.match(
                r"\s*(\d+)\s+(\S+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", line
            )
            if m:
                result.forces.append(
                    {
                        "atom": int(m.group(1)),
                        "type": m.group(2),
                        "fx": float(m.group(3)),
                        "fy": float(m.group(4)),
                        "fz": float(m.group(5)),
                    }
                )
            elif line.strip() == "":
                force_section = False

    # Stress
    m = re.search(r"total\s+stress\s+\(Ry/bohr\*\*3\)\s+\(kbar\).*?\n(.*?)\n", text, re.DOTALL)
    if not m:
        m = re.search(r"total   stress.*?\n(.*?)\n", text, re.DOTALL)
    if m:
        # Require at least one digit to avoid capturing lone "." from "JOB DONE."
        vals = re.findall(r"[-\d]+(?:\.\d+)?", m.group(1))
        result.stress = [float(v) for v in vals]

    # Warnings/Errors
    for m in re.finditer(r"(?:WARNING|ERROR|Error)[:\s]+(.+)", text):
        result.raw_errors.append(m.group(1).strip())

    return result


# ---------------------------------------------------------------------------
# PW.X MD output  (calculation='md' — ab-initio molecular dynamics)
# ---------------------------------------------------------------------------

@dataclass
class MdOutput:
    """Structured results parsed from a QE pw.x MD (calculation='md') output file."""

    program: str = ""
    version: str = ""
    n_steps: int = 0
    temperatures: list[float] = field(default_factory=list)
    """Per-step temperatures in K."""
    energies: list[float] = field(default_factory=list)
    """Per-step total energies in Ry (the ``!  total energy`` line per step)."""
    job_done: bool = False
    wall_time_sec: float | None = None
    cpu_time_sec: float | None = None
    raw_errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Program        : {self.program} v{self.version}",
            f"MD Steps       : {self.n_steps}",
            f"Temperatures   : {len(self.temperatures)} values"
            + (f" (last={self.temperatures[-1]:.2f} K)" if self.temperatures else ""),
            f"Energies       : {len(self.energies)} values"
            + (f" (last={self.energies[-1]:.6f} Ry)" if self.energies else ""),
            f"JOB DONE       : {self.job_done}",
            f"Wall Time      : {self.wall_time_sec:.1f} s"
            if self.wall_time_sec
            else "Wall Time      : N/A",
        ]
        return "\n".join(lines)


def parse_md_output(filepath: Path | str) -> MdOutput:
    """Parse a Quantum ESPRESSO pw.x MD (calculation='md') output file.

    Extracts the MD-step count, per-step temperatures (K) and total
    energies (Ry), and the JOB DONE flag. Scans for the QE MD output
    markers ``Averaged quantities`` / ``temperature`` / ``Ekin`` /
    ``Epot`` / ``Total energy`` and the per-step ``!  total energy``
    line that pw.x prints for each MD step.
    """
    path = Path(filepath)
    text = path.read_text(encoding="utf-8", errors="replace")
    result = MdOutput()

    m = re.search(r"Program\s+(PW\S*)\s+v\.(\S+)", text)
    if m:
        result.program = m.group(1)
        result.version = m.group(2)

    result.job_done = "JOB DONE" in text

    # Per-step total energies (Ry) — the "!  total energy" line that pw.x
    # prints once per MD step.
    energy_lines = re.findall(r"!\s+total energy\s+=\s+([-\d.]+)\s+Ry", text)
    for val in energy_lines:
        try:
            result.energies.append(float(val))
        except ValueError:
            pass

    # MD step count: prefer the number of "Averaged quantities" blocks
    # (printed by thermostat-based MD), fall back to the number of
    # "!  total energy" lines, then to the nstep echo from the input.
    averaged_count = len(re.findall(r"Averaged quantities", text))
    if averaged_count > 0:
        result.n_steps = averaged_count
    elif result.energies:
        result.n_steps = len(result.energies)
    else:
        m = re.search(r"nstep\s*=\s*(\d+)", text, re.IGNORECASE)
        if m:
            result.n_steps = int(m.group(1))

    # Per-step temperatures (K) — anchor to line start to avoid matching
    # "Starting temperature" preamble lines.
    for m in re.finditer(r"^\s*temperature\s*=\s*([\d.]+)\s*K", text, re.MULTILINE):
        result.temperatures.append(float(m.group(1)))

    # Timing
    m = re.search(r"PWSCF\s+:\s+([\d.]+)s CPU\s+([\d.]+)s WALL", text)
    if m:
        result.cpu_time_sec = float(m.group(1))
        result.wall_time_sec = float(m.group(2))

    # Warnings/Errors
    for m in re.finditer(r"(?:WARNING|ERROR|Error)[:\s]+(.+)", text):
        result.raw_errors.append(m.group(1).strip())

    return result


# ---------------------------------------------------------------------------
# DOS output  (dos.x  stdout → HfBr2.dos data file)
# ---------------------------------------------------------------------------

@dataclass
class DosOutput:
    """Structured results from dos.x output and HfBr2.dos data file."""

    program: str = ""
    version: str = ""
    e_fermi_ev: float | None = None
    cpu_time_sec: float | None = None
    wall_time_sec: float | None = None
    dos_data: list[dict[str, float]] = field(default_factory=list)
    """Each row: {energy_ev, dos, int_dos}."""
    n_points: int = 0
    e_min: float | None = None
    e_max: float | None = None

    def summary(self) -> str:
        lines = [
            f"Program        : {self.program} v{self.version}",
            f"Fermi Energy   : {self.e_fermi_ev:.4f} eV"
            if self.e_fermi_ev
            else "Fermi Energy   : N/A",
            f"Data points    : {self.n_points}",
            f"Energy range   : {self.e_min:.4f} to {self.e_max:.4f} eV"
            if self.e_min is not None
            else "Energy range   : N/A",
            f"Wall Time      : {self.wall_time_sec:.1f} s"
            if self.wall_time_sec
            else "Wall Time      : N/A",
        ]
        return "\n".join(lines)


def parse_dos_output(
    datafile: Path | str,
    dos_output: Path | str | None = None,
) -> DosOutput:
    """Parse DOS data file (HfBr2.dos) and optionally the dos.x stdout.

    DOS data format::

        #  E (eV)   dos(E)     Int dos(E) EFermi =   -0.463 eV
         -10.000  0.5273E-84  0.5273E-86
          -9.990  0.5273E-84  0.1055E-85
          ...
    """
    data_path = Path(datafile)
    result = DosOutput()

    if dos_output and Path(dos_output).is_file():
        out_text = Path(dos_output).read_text(encoding="utf-8", errors="replace")
        m = re.search(r"Program\s+(DOS)\s+v\.(\S+)", out_text)
        if m:
            result.program = m.group(1)
            result.version = m.group(2)
        m = re.search(r"DOS\s+:\s+([\d.]+)s CPU\s+([\d.]+)s WALL", out_text)
        if m:
            result.cpu_time_sec = float(m.group(1))
            result.wall_time_sec = float(m.group(2))

    text = data_path.read_text(encoding="utf-8", errors="replace")
    header_m = re.search(r"EFermi\s*=\s*([-\d.]+)\s*eV", text)
    if header_m:
        result.e_fermi_ev = float(header_m.group(1))

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            e = float(parts[0])
            dos = float(parts[1])
            int_dos = float(parts[2])
        except ValueError:
            continue
        result.dos_data.append({"energy_ev": e, "dos": dos, "int_dos": int_dos})

    result.n_points = len(result.dos_data)
    if result.dos_data:
        result.e_min = result.dos_data[0]["energy_ev"]
        result.e_max = result.dos_data[-1]["energy_ev"]

    return result


# ---------------------------------------------------------------------------
# PDOS output  (projwfc.x → HfBr2.pdos_atm#N(Atom)_wfc#M(orbital))
# ---------------------------------------------------------------------------

@dataclass
class PdosOutput:
    """Projected DOS from projwfc.x."""

    label: str = ""
    """e.g. 'Hf-d', 'Br-p'."""
    fermi_ev: float | None = None
    data: list[dict[str, float]] = field(default_factory=list)
    """Each row: {energy_ev, dos, int_dos}."""
    n_points: int = 0


def parse_pdos_file(filepath: Path | str) -> PdosOutput:
    """Parse a single projwfc.x pdos file (one atom+orbital).

    Format::

        #  E (eV)   dos(E)     Int dos(E)
         -10.000  0.5273E-84  0.5273E-86
         ...
    """
    path = Path(filepath)
    text = path.read_text(encoding="utf-8", errors="replace")
    # Use the full stem containing atom/orbital info
    result = PdosOutput(label=path.name)

    # Fermi energy from header
    m = re.search(r"Fermi\s*=\s*([-\d.]+)\s*eV", text)
    if m:
        result.fermi_ev = float(m.group(1))

    result.data = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("@"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        e = float(parts[0])
        dos = float(parts[1])
        int_dos = float(parts[2]) if len(parts) > 2 else 0.0
        result.data.append({"energy_ev": e, "dos": dos, "int_dos": int_dos})

    result.n_points = len(result.data)
    return result


def discover_pdos_files(pdos_prefix_dir: Path) -> list[Path]:
    """Discover all ``*pdos_atm*`` files in a directory."""
    return sorted(pdos_prefix_dir.glob("*pdos_atm*"))


def parse_pdos_bundle(
    pdos_prefix_dir: Path | str,
    *,
    atom_label: str | None = None,
    orbital: str | None = None,
) -> list[PdosOutput]:
    """Parse multiple projwfc.x PDOS files matching criteria.

    *atom_label* filters by atom type (e.g. 'Hf', 'Br').
    *orbital* filters by orbital type (e.g. 's', 'p', 'd').
    """
    d = Path(pdos_prefix_dir)
    results: list[PdosOutput] = []
    for f in discover_pdos_files(d):
        name = f.stem  # e.g. HfBr2.pdos_atm#1(Hf)_wfc#1(s)
        if atom_label and f"({atom_label})" not in name:
            continue
        if orbital and f"({orbital})" not in name:
            continue
        results.append(parse_pdos_file(f))
    return results


# Bands output  (bands.x stdout → HfBr2.bands data file)
# ---------------------------------------------------------------------------

@dataclass
class BandsOutput:
    """Structured results from bands.x output and HfBr2.bands data file."""

    program: str = ""
    version: str = ""
    nbnd: int = 0
    nks: int = 0
    k_points: list[list[float]] = field(default_factory=list)
    """Each k-point: [kx, ky, kz]."""
    bands: list[list[float]] = field(default_factory=list)
    """bands[ibnd][ik] = energy in eV."""
    cpu_time_sec: float | None = None
    wall_time_sec: float | None = None
    high_symmetry_labels: list[dict[str, Any]] = field(default_factory=list)

    @property
    def n_bands(self) -> int:
        return self.nbnd

    @property
    def n_kpoints(self) -> int:
        return self.nks

    def summary(self) -> str:
        lines = [
            f"Program        : {self.program} v{self.version}",
            f"Bands          : {self.nbnd} bands, {self.nks} k-points",
            f"Wall Time      : {self.wall_time_sec:.1f} s"
            if self.wall_time_sec
            else "Wall Time      : N/A",
        ]
        return "\n".join(lines)


def parse_bands_output(
    datafile: Path | str,
    bands_output: Path | str | None = None,
    high_symmetry_path: list[dict[str, Any]] | None = None,
) -> BandsOutput:
    """Parse bands data file (HfBr2.bands) and optionally bands.x stdout.

    Bands data format::

        &plot nbnd= 17, nks= 50 /
                   0.000000  0.000000  0.000000
         -64.113  -32.937  -32.567  ...  (17 values for 17 bands)
                   0.031250  0.018042  0.000000
         -64.113  -32.936  -32.569  ...
         ...

    *high_symmetry_path* is an optional list of::

        {"label": "Γ", "k": [0, 0, 0], "distance": 0.0}
    """
    data_path = Path(datafile)
    result = BandsOutput()

    if bands_output and Path(bands_output).is_file():
        out_text = Path(bands_output).read_text(encoding="utf-8", errors="replace")
        m = re.search(r"Program\s+(BANDS)\s+v\.(\S+)", out_text)
        if m:
            result.program = m.group(1)
            result.version = m.group(2)
        m = re.search(r"BANDS\s+:\s+([\d.]+)s CPU\s+([\d.]+)s WALL", out_text)
        if m:
            result.cpu_time_sec = float(m.group(1))
            result.wall_time_sec = float(m.group(2))

    text = data_path.read_text(encoding="utf-8", errors="replace")

    # Parse header line: &plot nbnd= 17, nks= 50 /
    header_m = re.search(r"&plot\s+nbnd\s*=\s*(\d+)\s*,\s*nks\s*=\s*(\d+)", text)
    if header_m:
        result.nbnd = int(header_m.group(1))
        result.nks = int(header_m.group(2))

    # Parse k-point coordinates and bands.
    # K-point lines have ≥10 leading spaces then 3 floats.
    # Band-data lines have 1-3 leading spaces then a sign/digit.
    k_point_re = re.compile(
        r"^\s{8,}([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$"
    )
    band_line_re = re.compile(r"^\s{1,3}([-0-9].*)")

    # First pass: collect raw rows of (k_point, band_values) per k-point.
    rows: list[tuple[list[float], list[float]]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        km = k_point_re.match(lines[i])
        if km:
            kx, ky, kz = float(km.group(1)), float(km.group(2)), float(km.group(3))
            i += 1
            vals: list[float] = []
            while i < len(lines):
                bm = band_line_re.match(lines[i])
                if bm:
                    vals.extend(float(v) for v in bm.group(1).split())
                    i += 1
                else:
                    break
            rows.append(([kx, ky, kz], vals))
            continue
        i += 1

    result.k_points = [r[0] for r in rows]

    # Transpose band values into per-band arrays.
    if rows and result.nbnd > 0:
        result.bands = [[] for _ in range(result.nbnd)]
        for _kpt, vals in rows:
            for ib in range(result.nbnd):
                if ib < len(vals):
                    result.bands[ib].append(vals[ib])
                else:
                    result.bands[ib].append(0.0)
    result.nks = len(result.k_points)

    # Attach high-symmetry labels for plotting
    if high_symmetry_path:
        result.high_symmetry_labels = high_symmetry_path

    return result


# ---------------------------------------------------------------------------
# Utility: k-path distance for plotting x-axis
# ---------------------------------------------------------------------------

def _k_distance(k: list[float], prev: list[float] | None) -> float:
    """Cartesian distance between two k-points."""
    if prev is None:
        return 0.0
    dx = k[0] - prev[0]
    dy = k[1] - prev[1]
    dz = k[2] - prev[2]
    return (dx * dx + dy * dy + dz * dz) ** 0.5


def compute_k_distances(k_points: list[list[float]]) -> list[float]:
    """Compute cumulative k-path distances from origin for plotting x-axis.

    Note: `vibedft.core.kpath.compute_k_distances` is the canonical implementation.
    This copy exists for backward compatibility with existing import paths.
    """
    dists: list[float] = []
    cum = 0.0
    prev: list[float] | None = None
    for k in k_points:
        d = _k_distance(k, prev)
        cum += d
        dists.append(cum)
        prev = k
    return dists


# ---------------------------------------------------------------------------
# dos.x stdout  (Program DOS → .out metadata: ngauss, degauss, Emin/Emax/ΔE)
# ---------------------------------------------------------------------------

@dataclass
class DosxOutput:
    """Metadata parsed from a dos.x stdout (.out) file.

    The actual DOS spectrum is written to a separate ``.dos`` data file;
    this dataclass captures the broadening/range metadata that dos.x
    prints to stdout.
    """

    ngauss: int = 0
    degauss: float = 0.0
    emin: float = 0.0
    emax: float = 0.0
    delta_e: float = 0.0
    job_done: bool = False
    source_file: str = ""

    def summary(self) -> str:
        lines = [
            f"dos.x stdout    : {self.source_file}",
            f"ngauss/degauss  : {self.ngauss} / {self.degauss:.6f}",
            f"Emin/Emax/ΔE    : {self.emin:.4f} / {self.emax:.4f} / {self.delta_e:.4f} eV",
            f"JOB DONE        : {self.job_done}",
        ]
        return "\n".join(lines)


def parse_dosx_output(filepath: Path | str) -> DosxOutput | None:
    """Parse a dos.x stdout (.out) file into broadening/range metadata.

    Returns ``None`` if the file is missing or is not a dos.x output
    (no ``Program DOS`` header and no ``ngauss,degauss=`` marker).
    """
    path = Path(filepath)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")

    if "Program DOS" not in text and "ngauss,degauss=" not in text:
        return None

    result = DosxOutput(source_file=str(path))

    m = re.search(r"ngauss,degauss=\s+(\d+)\s+([-\d.]+)", text)
    if m:
        result.ngauss = int(m.group(1))
        result.degauss = float(m.group(2))

    for line in text.splitlines():
        if "Emin" in line and "Emax" in line:
            em = re.search(r":\s*([-+\d.]+)\s+([-+\d.]+)\s+([-+\d.]+)", line)
            if em:
                result.emin = float(em.group(1))
                result.emax = float(em.group(2))
                result.delta_e = float(em.group(3))
            break

    result.job_done = "JOB DONE" in text
    return result


# ---------------------------------------------------------------------------
# projwfc.x stdout  (Program PROJWFC → Lowdin charges + Spilling Parameter)
# ---------------------------------------------------------------------------

@dataclass
class ProjwfcOutput:
    """Structured results parsed from a projwfc.x stdout (.out) file.

    The PDOS spectra are written to separate ``pdos_atm#N_wfc#M.dat``
    files; this dataclass captures the Lowdin charges and the spilling
    parameter that projwfc.x prints to stdout.
    """

    lowdin_charges: list[dict[str, Any]] = field(default_factory=list)
    """Each entry: {'atom': int, 'total_charge': float, 's': float, ...}."""
    spilling_parameter: float = 0.0
    job_done: bool = False
    source_file: str = ""

    def summary(self) -> str:
        lines = [
            f"projwfc.x stdout : {self.source_file}",
            f"Lowdin atoms     : {len(self.lowdin_charges)}",
            f"Spilling Parameter: {self.spilling_parameter:.6f}",
            f"JOB DONE         : {self.job_done}",
        ]
        return "\n".join(lines)


def parse_projwfc_output(filepath: Path | str) -> ProjwfcOutput | None:
    """Parse a projwfc.x stdout (.out) file into Lowdin charges + spilling.

    Returns ``None`` if the file is missing or is not a projwfc.x output
    (no ``Program PROJWFC`` header, no ``Lowdin Charges:`` block, and no
    ``Spilling Parameter`` marker).
    """
    path = Path(filepath)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")

    is_projwfc = (
        "Program PROJWFC" in text
        or "Lowdin Charges:" in text
        or "Spilling Parameter" in text
    )
    if not is_projwfc:
        return None

    result = ProjwfcOutput(source_file=str(path))

    atom_re = re.compile(r"\s*Atom\s*#\s*(\d+):\s+total charge\s*=\s*([-\d.]+)")
    orb_re = re.compile(r"([a-zA-Z][\w-]*)\s*=\s*([-\d.eE+]+)")
    for line in text.splitlines():
        m = atom_re.match(line)
        if not m:
            continue
        entry: dict[str, Any] = {
            "atom": int(m.group(1)),
            "total_charge": float(m.group(2)),
        }
        rest = line[m.end():]
        for om in orb_re.finditer(rest):
            entry[om.group(1)] = float(om.group(2))
        result.lowdin_charges.append(entry)

    m = re.search(r"Spilling Parameter:\s+([-\d.]+)", text)
    if m:
        result.spilling_parameter = float(m.group(1))

    result.job_done = "JOB DONE" in text
    return result


# ---------------------------------------------------------------------------
# bands.x stdout  (Program BANDS → minimal .out: JOB DONE + optional nbnd/nks)
# ---------------------------------------------------------------------------

@dataclass
class BandsxOutput:
    """Minimal metadata parsed from a bands.x stdout (.out) file.

    The band data is written to a separate ``.bands.dat.gnu`` file; the
    bands.x stdout itself usually contains only ``JOB DONE`` and timing.
    """

    job_done: bool = False
    n_bands: int | None = None
    n_kpoints: int | None = None
    source_file: str = ""

    def summary(self) -> str:
        lines = [
            f"bands.x stdout  : {self.source_file}",
            f"n_bands         : {self.n_bands}",
            f"n_kpoints       : {self.n_kpoints}",
            f"JOB DONE        : {self.job_done}",
        ]
        return "\n".join(lines)


def parse_bandsx_output(filepath: Path | str) -> BandsxOutput | None:
    """Parse a bands.x stdout (.out) file into minimal metadata.

    Returns ``None`` if the file is missing or is not a bands.x output
    (no ``Program BANDS`` header).
    """
    path = Path(filepath)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")

    if "Program BANDS" not in text:
        return None

    result = BandsxOutput(source_file=str(path))

    m = re.search(r"nbnd\s*=\s*(\d+)", text)
    if m:
        result.n_bands = int(m.group(1))

    m = re.search(r"nks\s*=\s*(\d+)", text)
    if m:
        result.n_kpoints = int(m.group(1))
    if result.n_kpoints is None:
        m = re.search(r"number of k[\s_-]*points\s*=\s*(\d+)", text, re.IGNORECASE)
        if m:
            result.n_kpoints = int(m.group(1))

    result.job_done = "JOB DONE" in text
    return result


# ---------------------------------------------------------------------------
# pp.x stdout  (Program POST-PROC → .out metadata only; data goes to .cube/.dat)
# ---------------------------------------------------------------------------

@dataclass
class PpOutput:
    """Metadata parsed from a pp.x stdout (.out) file.

    pp.x writes the actual 2D/3D data to a separate ``filplot`` file
    (e.g. a Gaussian ``.cube`` or pwscf-format ``.dat``); the ``.out``
    stdout itself contains the input echo, optional integrated charge,
    and the ``JOB DONE`` marker. ``is_elf`` is True when ``plot_num == 9``
    (Electron Localization Function).
    """

    plot_num: int | None = None
    filplot: str = ""
    output_format: int | None = None
    iflag: int | None = None
    fileout: str = ""
    job_done: bool = False
    integrated_charge: float | None = None
    is_elf: bool = False
    source_file: str = ""

    def summary(self) -> str:
        lines = [
            f"pp.x stdout     : {self.source_file}",
            f"plot_num        : {self.plot_num}",
            f"filplot         : {self.filplot}",
            f"output_format   : {self.output_format}",
            f"iflag           : {self.iflag}",
            f"fileout         : {self.fileout}",
            f"is_elf          : {self.is_elf}",
            f"integrated_charge: {self.integrated_charge}",
            f"JOB DONE        : {self.job_done}",
        ]
        return "\n".join(lines)


def parse_pp_output(filepath: Path | str) -> PpOutput | None:
    """Parse a QE pp.x stdout (.out) file into plot metadata.

    Returns ``None`` if the file is missing or is not a pp.x output
    (no ``POST-PROC`` header and no pp.x content markers like
    ``plot_num``, ``filplot`` or ``iflag``).
    """
    path = Path(filepath)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")

    is_pp = (
        "POST-PROC" in text
        or "plot_num" in text
        or "filplot" in text
        or "iflag" in text
    )
    if not is_pp:
        return None

    result = PpOutput(source_file=str(path))

    m = re.search(r"plot_num\s*=\s*(\d+)", text)
    if m:
        result.plot_num = int(m.group(1))

    m = re.search(r"filplot\s*=\s*'?(\S+?)'?\s*$", text, re.MULTILINE)
    if m:
        result.filplot = m.group(1).strip().strip("'\"")

    m = re.search(r"output_format\s*=\s*(\d+)", text)
    if m:
        result.output_format = int(m.group(1))

    m = re.search(r"iflag\s*=\s*(\d+)", text)
    if m:
        result.iflag = int(m.group(1))

    m = re.search(r"fileout\s*=\s*'?(\S+?)'?\s*$", text, re.MULTILINE)
    if m:
        result.fileout = m.group(1).strip().strip("'\"")

    m = re.search(r"[Ii]ntegrated charge\s*=?\s*([-\d.]+)", text)
    if m:
        try:
            result.integrated_charge = float(m.group(1))
        except ValueError:
            pass

    result.is_elf = result.plot_num == 9
    result.job_done = "JOB DONE" in text
    return result


# ---------------------------------------------------------------------------
# average.x stdout  (Program AVERAGE → planar-average z vs value table)
# ---------------------------------------------------------------------------

@dataclass
class AverageOutput:
    """Planar-average table parsed from a QE average.x stdout (.out) file."""

    n_points: int = 0
    z_values: list[float] = field(default_factory=list)
    averages: list[float] = field(default_factory=list)
    job_done: bool = False
    source_file: str = ""

    def summary(self) -> str:
        lines = [
            f"average.x stdout: {self.source_file}",
            f"n_points        : {self.n_points}",
            f"z range         : {self.z_values[0]:.4f} — {self.z_values[-1]:.4f}"
            if self.z_values
            else "z range         : N/A",
            f"avg range       : {self.averages[0]:.6f} — {self.averages[-1]:.6f}"
            if self.averages
            else "avg range       : N/A",
            f"JOB DONE        : {self.job_done}",
        ]
        return "\n".join(lines)


def parse_average_output(filepath: Path | str) -> AverageOutput | None:
    """Parse a QE average.x stdout (.out) file into a planar-average table.

    The data table is two-or-more columns of floats (z-coordinate and one
    or more averaged quantities), often preceded by a ``#`` header line
    such as ``#  zcoord     average``. Only the first averaged column
    beyond z is stored.

    Returns ``None`` if the file is missing or is not an average.x output
    (no ``Program AVERAGE`` header and no numeric data table).
    """
    path = Path(filepath)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")

    if "Program AVERAGE" not in text:
        return None

    result = AverageOutput(source_file=str(path))

    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if in_table and result.z_values:
                break
            continue
        if stripped.startswith("#"):
            in_table = True
            continue
        parts = stripped.split()
        nums: list[float] = []
        ok = True
        for p in parts:
            try:
                nums.append(float(p))
            except ValueError:
                ok = False
                break
        if not ok or len(nums) < 2:
            if in_table and result.z_values:
                break
            continue
        result.z_values.append(nums[0])
        result.averages.append(nums[1])
        in_table = True

    result.n_points = len(result.z_values)
    result.job_done = "JOB DONE" in text
    return result


# ---------------------------------------------------------------------------
# pw.x spin-polarized output  (nspin=2 → total/absolute magnetization)
# ---------------------------------------------------------------------------

@dataclass
class MagnetismOutput:
    """Magnetization results parsed from a spin-polarized pw.x output."""

    total_magnetization: float = 0.0
    """Last reported ``total magnetization`` in Bohr mag/cell."""
    absolute_magnetization: float = 0.0
    """Last reported ``absolute magnetization`` in Bohr mag/cell."""
    total_energy_ry: float = 0.0
    """Last ``!  total energy`` in Ry (0.0 if absent)."""
    nspin: int = 1
    """nspin from the input echo (defaults to 1 if not found)."""
    job_done: bool = False
    source_file: str = ""

    def summary(self) -> str:
        lines = [
            f"magnetism pw.x  : {self.source_file}",
            f"nspin           : {self.nspin}",
            f"total mag       : {self.total_magnetization:.6f} Bohr mag/cell",
            f"absolute mag    : {self.absolute_magnetization:.6f} Bohr mag/cell",
            f"total energy    : {self.total_energy_ry:.6f} Ry",
            f"JOB DONE        : {self.job_done}",
        ]
        return "\n".join(lines)


def parse_magnetism_output(filepath: Path | str) -> MagnetismOutput | None:
    """Parse a spin-polarized QE pw.x output for magnetization quantities.

    Takes the *last* occurrence of ``total magnetization`` and
    ``absolute magnetization`` (pw.x prints them once per SCF iteration)
    and the last ``!  total energy`` line.

    Returns ``None`` if the file is missing or no magnetization lines
    are present (i.e. the output is not from a spin-polarized calculation).
    """
    path = Path(filepath)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")

    total_mags = re.findall(
        r"total magnetization\s*=\s*([-\d.]+)\s*Bohr mag/cell", text
    )
    abs_mags = re.findall(
        r"absolute magnetization\s*=\s*([-\d.]+)\s*Bohr mag/cell", text
    )
    if not total_mags and not abs_mags:
        return None

    result = MagnetismOutput(source_file=str(path))

    if total_mags:
        result.total_magnetization = float(total_mags[-1])
    if abs_mags:
        result.absolute_magnetization = float(abs_mags[-1])

    energies = re.findall(r"!\s+total energy\s+=\s+([-\d.]+)\s+Ry", text)
    if energies:
        result.total_energy_ry = float(energies[-1])

    m = re.search(r"nspin\s*=\s*(\d+)", text)
    if m:
        result.nspin = int(m.group(1))

    result.job_done = "JOB DONE" in text
    return result
