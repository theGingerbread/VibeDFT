"""EPW input file parser — epw.in and related namelists."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EpwInput:
    """Parsed EPW input parameters."""
    source_file: str = ""
    prefix: str = ""
    outdir: str = "./"
    elph: bool = False
    epbwrite: bool = False
    epbread: bool = False
    kmaps: bool = False
    etf_mem: int = 0
    nk1: int = 0
    nk2: int = 0
    nk3: int = 0
    nq1: int = 0
    nq2: int = 0
    nq3: int = 0
    degaussw: float = 0.0
    fsthick: float = 0.0
    eptemp: float = 300.0
    muc: float = 0.1
    nsmear: int = 1
    delta_smear: float = 0.04
    wannierize: bool = False
    num_wann: int = 0
    dis_win_min: float = 0.0
    dis_win_max: float = 0.0
    dis_froz_min: float = 0.0
    dis_froz_max: float = 0.0
    proj: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    raw_text: str = ""


def parse_epw_input(filepath: Path | str) -> EpwInput | None:
    """Parse an EPW input file (epw.in)."""
    path = Path(filepath)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    inp = EpwInput(source_file=str(path), raw_text=text)

    # Parse &inputepw namelist and &wannier block
    from vibedft.parsers.qe_input_parser import _parse_qe_text
    parsed = _parse_qe_text(text)

    # Collect params from all namelists
    for nl_name, nl_block in parsed.namelists.items():
        params = nl_block.params
        for key, val in params.items():
            _set_if_match(inp, key, val)

    # Cards: WANNIER_PROJ lines
    for card_name, card in parsed.cards.items():
        if card_name.upper().startswith("WANNIER"):
            for row in card.rows:
                inp.proj.extend(row)

    inp.parse_errors = parsed.parse_errors
    return inp


def _set_if_match(inp: EpwInput, key: str, val: Any) -> None:
    """Set EPW input attribute if the key matches."""
    field_map = {
        "prefix": "prefix", "outdir": "outdir",
        "elph": "elph", "epbwrite": "epbwrite", "epbread": "epbread",
        "kmaps": "kmaps", "etf_mem": "etf_mem",
        "nk1": "nk1", "nk2": "nk2", "nk3": "nk3",
        "nq1": "nq1", "nq2": "nq2", "nq3": "nq3",
        "degaussw": "degaussw", "fsthick": "fsthick",
        "eptemp": "eptemp", "muc": "muc",
        "nsmear": "nsmear", "delta_smear": "delta_smear",
        "wannierize": "wannierize", "num_wann": "num_wann",
        "dis_win_min": "dis_win_min", "dis_win_max": "dis_win_max",
        "dis_froz_min": "dis_froz_min", "dis_froz_max": "dis_froz_max",
    }
    if key.lower() in field_map:
        try:
            setattr(inp, field_map[key.lower()], _convert(val))
        except (ValueError, TypeError):
            pass


def _convert(val: Any) -> Any:
    if isinstance(val, str):
        try:
            return int(val)
        except ValueError:
            try:
                return float(val)
            except ValueError:
                if val.lower() in (".true.", "true"):
                    return True
                if val.lower() in (".false.", "false"):
                    return False
                return val
    return val
