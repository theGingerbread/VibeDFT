"""Wannier quality checker — spread, disentanglement, band interpolation risk."""

from __future__ import annotations

from vibedft.epw.output_parser import EpwResult


def check_wannier_quality(epw: EpwResult | None) -> dict:
    """Assess Wannier function quality from EPW output.

    Returns a dict with:
      - status: "good" | "acceptable" | "unreliable"
      - issues: list of warning strings
    """
    if epw is None or not epw.has_data:
        return {"status": "no_data", "issues": []}

    issues: list[str] = []
    score = 0

    # Check spreads
    if epw.wannier_max_spread is not None:
        max_spr = epw.wannier_max_spread
        if max_spr > 10.0:
            issues.append(f"Large Wannier spread: max = {max_spr:.1f} Å² — may indicate poor localization")
        elif max_spr > 5.0:
            issues.append(f"Moderate Wannier spread: max = {max_spr:.1f} Å²")
            score += 1
        else:
            score += 2

    if epw.wannier_total_spread is not None and epw.wannier_num_bands:
        avg_spr = epw.wannier_total_spread / epw.wannier_num_bands
        if avg_spr > 5.0:
            issues.append(f"High average spread: {avg_spr:.1f} Å²")

    # Warnings from EPW output
    for w in epw.warnings:
        if "wannier" in w.lower() or "spread" in w.lower():
            issues.append(w)
            score -= 1

    # Determine status
    if score >= 3 and not issues:
        status = "good"
    elif score >= 1:
        status = "acceptable"
    else:
        status = "unreliable"

    return {"status": status, "score": score, "issues": issues}
