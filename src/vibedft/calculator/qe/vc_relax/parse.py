"""Parse Quantum ESPRESSO vc-relax output via the relax parser scaffold."""

from __future__ import annotations

from pathlib import Path

from vibedft.calculator.qe.relax.parse import parse_relax_output as parse_relax_output
from vibedft.calculator.qe.relax.parse import RelaxOutput


def parse_vc_relax_output(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
) -> RelaxOutput:
    """Parse QE vc-relax output with explicit variable-cell intent."""

    return parse_relax_output(text_or_path, source=source, variable_cell=True)


def parse_vc_relax_outputs(outputs: list[str | Path]) -> list[RelaxOutput]:
    """Parse one or more vc-relax output files."""

    return [parse_vc_relax_output(output) for output in outputs]


__all__ = [
    "RelaxOutput",
    "parse_vc_relax_output",
    "parse_vc_relax_outputs",
]
