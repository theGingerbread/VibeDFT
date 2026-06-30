"""Prioritized next-action recommendations based on decision gate level."""

from __future__ import annotations

from typing import Any

from vibedft.decision.publication_gate import GateLevel


def build_recommendations(evidence: dict[str, Any], gate: GateLevel) -> list[str]:
    """Build a ranked list of next actions based on the gate level and evidence."""
    actions: list[str] = []
    metrics = evidence.get("metrics", {})

    if gate == GateLevel.BLOCKED:
        actions.extend(_critical_fixes(evidence))
        actions.append("Re-run vibedft review after fixing critical errors to confirm clearance.")

    elif gate == GateLevel.NEEDS_CONVERGENCE:
        actions.extend(_convergence_actions(evidence, metrics))
        actions.append("Re-run vibedft convergence --root . to verify improved convergence.")

    elif gate == GateLevel.PROMISING:
        actions.extend(_build_evidence_actions(evidence, metrics))
        actions.append("Run vibedft report generate to produce an updated HTML report.")

    elif gate == GateLevel.READY_FOR_FIGURES:
        actions.append("Generate publication-quality figures: vibedft report generate --case-dir . --output final_report.html")
        actions.append("Run vibedft decide to confirm READY_FOR_FIGURES status.")
        actions.append("Archive results: vibedft archive apply --case-dir . --target-root <DFT_RESULTS_DIR>")

    return actions[:5]


def _critical_fixes(evidence: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for b in evidence.get("blockers", []):
        cid = b.get("id", "")
        if "la2f" in cid.lower():
            actions.insert(0, "Fix la2F bug: remove la2F=.true. from q2r.in and matdyn.in inputs")
        elif "prefix" in cid.lower():
            actions.append("Fix prefix mismatch: ensure ph.x prefix matches the SCF prefix exactly")
        elif "missing" in cid.lower():
            actions.append(f"Add missing parameter: {b.get('message', '')[:80]}")
    if not actions:
        actions.append("Review and fix all CRITICAL issues listed in the blockers before proceeding.")
    return actions


def _convergence_actions(evidence: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if metrics.get("superconductivity_score", 10) < 5:
        actions.append("Increase k-grid density (e.g. 96×96×1 and 128×128×1) and re-run EPC + lambda.x")
    if evidence.get("convergence_confidence", "high") in ("low", "medium"):
        actions.append("Run a systematic k-grid convergence sweep: try 24/36/48/64/96 k-point grids")
    if metrics.get("prop_work_function_vacuum_flat") is False:
        actions.append("Add dipole correction to SCF and re-run pp.x for work function")
    return actions if actions else ["Run convergence tests on unconverged parameters."]


def _build_evidence_actions(evidence: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if "prop_work_function_work_function_ev" not in metrics:
        actions.append("Compute work function: run pp.x with plot_num=11 and vibedft property analyze")
    if "prop_bader_charge_n_atoms" not in metrics:
        actions.append("Run Bader charge analysis on the charge density and vibedft property analyze")
    if "prop_elf_elf_max" not in metrics:
        actions.append("Compute ELF: run pp.x with plot_num=8 and vibedft property analyze")
    if "prop_aimd_stability_n_steps" not in metrics:
        actions.append("Run short AIMD (5 ps, 300 K) to verify thermal stability")
    return actions[:4] if actions else ["All property analyses complete. Consider targeted follow-up calculations."]
