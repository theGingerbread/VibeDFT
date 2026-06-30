"""Convergence matrix generator — creates parameter sweep directories."""

from __future__ import annotations

from pathlib import Path

from vibedft.generators.manifest import WorkflowPlan, StageSpec, StageKind


def generate_convergence_readme(plan: WorkflowPlan) -> str:
    """Generate a README for the convergence analysis directory."""
    lines = [
        "# Convergence Analysis",
        "",
        "## Tc Overlap",
        "",
        "After EPC calculations complete on both k-grids:",
        "",
        "```bash",
        "vibedft analyze tc \\",
        "  08_epc_ph64/lambdax.out \\",
        "  09_epc_ph96/lambdax.out \\",
        "  --label-a ph64 --label-b ph96",
        "```",
        "",
        "## Full Convergence Report",
        "",
        "```bash",
        "vibedft convergence --root . --html convergence.html",
        "```",
        "",
        "## Review Entire Run",
        "",
        "```bash",
        "vibedft review --case-dir .",
        "vibedft report generate --case-dir . --output report.html",
        "```",
        "",
        "## Convergence Criteria",
        "",
        "- Δλ < 0.05 between successive k-grids",
        "- ΔTc < 0.5 K or < 5%",
        "- Δωlog < 5%",
        "- No new imaginary phonon modes",
        "- DOS@EF stable (< 10% change)",
    ]
    return "\n".join(lines) + "\n"
