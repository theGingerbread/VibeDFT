"""Spin logic consistency validator — nspin/noncolin/lspinorb rules."""

from __future__ import annotations

from vibedft.spin.soc_parser import SocConfig


def validate_spin_consistency(config: SocConfig) -> list[dict]:
    """Validate nspin/noncolin/lspinorb logic consistency.

    Returns a list of issue dicts with severity and message.
    """
    issues: list[dict] = []

    # noncolin requires nspin not set to 2 (noncolin uses its own spinor framework)
    if config.noncolin and config.nspin == 2:
        issues.append({
            "severity": "error",
            "id": "spin.noncolin_nspin_conflict",
            "message": "noncolin=.true. with nspin=2 is inconsistent. "
                       "Use noncolin without nspin for spinor calculations.",
        })

    # lspinorb requires noncolin
    if config.lspinorb and not config.noncolin:
        issues.append({
            "severity": "error",
            "id": "spin.lspinorb_without_noncolin",
            "message": "lspinorb=.true. requires noncolin=.true. Calculation will fail.",
        })

    # SOC with nspin=1 (unusual but not wrong — just note it)
    if config.has_soc and config.nspin == 1:
        issues.append({
            "severity": "info",
            "id": "spin.soc_with_nspin1",
            "message": "SOC enabled but nspin=1. This is valid for non-magnetic SOC calculations.",
        })

    # Heavy elements without SOC
    if config.needs_soc_check:
        issues.append({
            "severity": "warning",
            "id": "spin.heavy_elements_no_soc",
            "message": f"Heavy elements ({', '.join(config.heavy_elements[:3])}) "
                       f"without SOC — electronic properties may be unreliable.",
        })

    # starting_magnetization with nspin=1
    if config.has_magnetic_atoms and config.nspin == 1:
        issues.append({
            "severity": "warning",
            "id": "spin.magnetic_no_spinpol",
            "message": "Starting magnetization set but nspin=1. "
                       "Spin polarization will be ignored.",
        })

    return issues
