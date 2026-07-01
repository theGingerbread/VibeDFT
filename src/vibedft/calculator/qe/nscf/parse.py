"""Parse Quantum ESPRESSO NSCF output using SCF parser compatibility mode."""

from __future__ import annotations

from pathlib import Path

from vibedft.calculator.qe.scf.parse import ScfOutput, parse_scf_output as _parse_scf_output


def parse_nscf_output(text_or_path: str | Path, *, source: str | Path | None = None) -> ScfOutput:
    """Parse NSCF stdout text or a path.

    Current NSCF parser behavior reuses the SCF parser because both share the same
    core structured log surface for QE scalar outputs in this stage.
    """

    return _parse_scf_output(text_or_path, source=source)


NscfOutput = ScfOutput

__all__ = ["NscfOutput", "parse_nscf_output"]
