"""vc-relax output monitoring using the relax monitor primitives."""

from __future__ import annotations

from pathlib import Path

from .parse import parse_vc_relax_output
from vibedft.calculator.qe.relax.monitor import RelaxMonitorSnapshot, monitor_relax_output


def monitor_vc_relax_output(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
) -> RelaxMonitorSnapshot:
    """Monitor VC-relax output stream."""

    # Explicit parse pass keeps the state machine coupled to vc-relax geometry.
    parse_vc_relax_output(text_or_path, source=source)
    return monitor_relax_output(text_or_path, source=source)


__all__ = ["RelaxMonitorSnapshot", "monitor_vc_relax_output"]
