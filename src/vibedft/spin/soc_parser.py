"""SOC configuration parser — detect noncolin, lspinorb, nspin from inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SocConfig:
    """Spin-orbit coupling and magnetism configuration detected from inputs."""
    source_file: str = ""
    nspin: int = 1                 # 1, 2, or 4
    noncolin: bool = False
    lspinorb: bool = False
    starting_magnetization: list[float] = field(default_factory=list)
    total_magnetization: float = 0.0
    has_soc: bool = False          # noncolin + lspinorb
    has_spin_polarization: bool = False  # nspin=2
    has_magnetic_atoms: bool = False
    heavy_elements: list[str] = field(default_factory=list)
    needs_soc_check: bool = False  # heavy elements but no SOC
    warnings: list[str] = field(default_factory=list)


_HEAVY_ELEMENTS = {
    "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi",
    "I", "Te", "Sb", "Sn", "In", "Cd", "Ag", "Pd", "Rh", "Ru", "Tc", "Mo", "Nb", "Zr", "Y",
    "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu",
    "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
}


def analyze_soc_config(case_dir: Path | str) -> SocConfig:
    """Detect SOC and magnetism configuration from all input files in a case."""
    d = Path(case_dir)
    config = SocConfig()

    for in_file in d.rglob("*.in"):
        try:
            text = in_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Parse with QE input parser to get structured params
        try:
            from vibedft.parsers.qe_input_parser import parse_qe_input
            qe = parse_qe_input(in_file)
        except Exception:
            continue

        # nspin
        nspin = qe.get_param("system", "nspin", None)
        if nspin is not None:
            try:
                config.nspin = int(nspin)
            except (ValueError, TypeError):
                pass

        # noncolin
        nc = qe.get_param("system", "noncolin", None)
        if nc is True:
            config.noncolin = True

        # lspinorb
        so = qe.get_param("system", "lspinorb", None)
        if so is True:
            config.lspinorb = True

        # starting_magnetization
        sm = qe.get_param("system", "starting_magnetization", None)
        if sm is not None:
            if isinstance(sm, list):
                config.starting_magnetization = [float(v) for v in sm if _is_num(v)]
            elif _is_num(sm):
                config.starting_magnetization = [float(sm)]

        # total_magnetization
        tm = qe.get_param("system", "tot_magnetization", None)
        if tm is not None:
            try:
                config.total_magnetization = float(tm)
            except (ValueError, TypeError):
                pass

        config.source_file = str(in_file)

        # Detect heavy elements from ATOMIC_SPECIES
        species_card = qe.cards.get("ATOMIC_SPECIES")
        if species_card:
            for row in species_card.rows:
                if row and row[0] in _HEAVY_ELEMENTS:
                    if row[0] not in config.heavy_elements:
                        config.heavy_elements.append(row[0])

    # Derived flags
    config.has_soc = config.noncolin and config.lspinorb
    config.has_spin_polarization = config.nspin == 2
    config.has_magnetic_atoms = len(config.starting_magnetization) > 0
    config.needs_soc_check = bool(config.heavy_elements) and not config.has_soc

    if config.needs_soc_check:
        config.warnings.append(
            f"Heavy elements detected ({', '.join(config.heavy_elements[:5])}) "
            "but SOC is not enabled. Band structure and DOS@EF may be unreliable."
        )
    if config.lspinorb and not config.noncolin:
        config.warnings.append(
            "lspinorb=.true. requires noncolin=.true. — calculation may fail."
        )
    if config.nspin == 4:
        config.warnings.append(
            "nspin=4 (spinor) is unusual. Verify this is intentional."
        )

    return config


def _is_num(v) -> bool:
    try:
        float(v)
        return True
    except (ValueError, TypeError):
        return False
