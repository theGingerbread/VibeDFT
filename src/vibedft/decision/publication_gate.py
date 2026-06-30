"""Publication gate — deterministic decision: BLOCKED / NEEDS_CONVERGENCE / PROMISING / READY_FOR_FIGURES."""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibedft.decision.evidence_merge import merge_all_evidence


class GateLevel(str, enum.Enum):
    BLOCKED = "BLOCKED"
    NEEDS_CONVERGENCE = "NEEDS_CONVERGENCE"
    PROMISING = "PROMISING"
    READY_FOR_FIGURES = "READY_FOR_FIGURES"


@dataclass
class DecisionResult:
    """Unified research decision for a 2D material calculation."""
    case_dir: str = ""
    gate: GateLevel = GateLevel.BLOCKED
    primary_blocker: str = ""
    secondary_blockers: list[str] = field(default_factory=list)
    positives: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_dir": self.case_dir,
            "gate": self.gate.value,
            "primary_blocker": self.primary_blocker,
            "secondary_blockers": self.secondary_blockers,
            "positives": self.positives[:10],
            "scores": self.scores,
            "next_actions": self.next_actions,
            "summary": self.summary,
        }


def decide(
    case_dir: Path | str,
    review_result: Any = None,
    physics_report: Any = None,
    property_bundle: Any = None,
    convergence_report: Any = None,
) -> DecisionResult:
    """Run the full decision pipeline and return a DecisionResult."""
    evidence = merge_all_evidence(
        case_dir, review_result, physics_report,
        property_bundle, convergence_report,
    )
    return _evaluate(evidence)


def _evaluate(evidence: dict[str, Any]) -> DecisionResult:
    from vibedft.decision.recommendation import build_recommendations  # lazy import to break cycle
    result = DecisionResult(case_dir=evidence.get("case_dir", ""))
    metrics = evidence.get("metrics", {})

    # ── BLOCKED checks ──
    blocks: list[str] = []

    # Critical input bugs (la2F, prefix mismatch, etc.)
    for b in evidence.get("blockers", []):
        cid = b.get("id", "")
        msg = b.get("message", "")
        if any(kw in cid.lower() for kw in ("la2f", "forbidden", "crash")):
            blocks.append(f"CRITICAL input bug: {msg}")
        elif "prefix" in cid.lower() and "mismatch" in cid.lower():
            blocks.append(f"Prefix mismatch: {msg}")
        elif "missing" in cid.lower():
            blocks.append(f"Missing required parameter: {msg}")

    # Structural instability (non-Γ imaginary modes)
    n_imag_non_gamma = metrics.get("n_imaginary_non_gamma", 0) or 0
    if n_imag_non_gamma > 0:
        blocks.append(f"Dynamic instability: {n_imag_non_gamma} non-Γ imaginary phonon modes")

    # AIMD melting
    if metrics.get("prop_aimd_stability_is_melting"):
        blocks.append("AIMD indicates possible melting — structure not thermally stable")

    # Workflow missing critical steps
    wf_completeness = metrics.get("workflow_completeness", 1.0) or 1.0
    if wf_completeness < 0.3:
        blocks.append(f"Workflow only {wf_completeness:.0%} complete — critical stages missing")

    # Energy not conserving in MD
    if metrics.get("prop_aimd_stability_is_energy_conserving") is False:
        blocks.append("AIMD energy not conserved — check timestep and SCF convergence")

    if blocks:
        result.gate = GateLevel.BLOCKED
        result.primary_blocker = blocks[0]
        result.secondary_blockers = blocks[1:4]
        result.scores = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
        result.next_actions = build_recommendations(evidence, GateLevel.BLOCKED)
        result.summary = f"BLOCKED — {len(blocks)} critical issue(s). Fix {blocks[0][:80]} first."
        return result

    # ── NEEDS_CONVERGENCE checks ──
    needs_conv: list[str] = []

    # Tc overlap failure (strongest signal)
    sc_score = metrics.get("superconductivity_score", 10) or 10
    if sc_score < 5.0:
        needs_conv.append("Tc convergence not established — overlap between k-grids failed or insufficient")

    # Convergence confidence
    conv_conf = evidence.get("convergence_confidence", "unknown")
    if conv_conf in ("low", "medium"):
        needs_conv.append(f"Convergence confidence is {conv_conf} — increase k/q-grid density")

    # Work function vacuum not flat
    if metrics.get("prop_work_function_vacuum_flat") is False:
        needs_conv.append("Work function vacuum potential not flat — dipole correction may be needed")

    # Sparse k-mesh from review warnings
    for w in evidence.get("warnings", []):
        wid = w.get("id", "") if isinstance(w, dict) else ""
        if "kpoints" in wid.lower() or "sparse" in wid.lower():
            needs_conv.append(f"Convergence warning: {w.get('message', str(w))}")

    if needs_conv:
        result.gate = GateLevel.NEEDS_CONVERGENCE
        result.primary_blocker = needs_conv[0]
        result.secondary_blockers = needs_conv[1:4]
        result.positives = [str(p) for p in evidence.get("positives", [])[:5]]
        result.scores = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
        result.next_actions = build_recommendations(evidence, GateLevel.NEEDS_CONVERGENCE)
        result.summary = f"NEEDS_CONVERGENCE — {len(needs_conv)} aspect(s) need further testing."
        return result

    # ── PROMISING vs READY_FOR_FIGURES ──
    # Check for complete figure set
    has_bands = metrics.get("electronic_score", 0) > 5
    has_phonon = metrics.get("stability_score", 0) > 5
    has_epc = metrics.get("superconductivity_score", 0) > 7
    has_wf = "prop_work_function_work_function_ev" in metrics
    has_bader = "prop_bader_charge_n_atoms" in metrics
    has_elf = "prop_elf_elf_max" in metrics
    has_aimd = "prop_aimd_stability_n_steps" in metrics

    figure_count = sum([has_bands, has_phonon, has_epc, has_wf, has_bader, has_elf, has_aimd])

    if figure_count >= 5 and metrics.get("workflow_completeness", 0) > 0.8:
        result.gate = GateLevel.READY_FOR_FIGURES
        result.summary = f"READY_FOR_FIGURES — {figure_count}/7 figure sets available, workflow complete."
    else:
        result.gate = GateLevel.PROMISING
        result.summary = f"PROMISING — {figure_count}/7 figure sets ready. Continue building evidence."

    result.positives = [str(p) for p in evidence.get("positives", [])[:10]]
    result.scores = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
    result.next_actions = build_recommendations(evidence, result.gate)
    return result
