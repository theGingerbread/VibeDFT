"""Physics analysis orchestrator: runs all analyzers → MaterialReport."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibedft.analyzers.physics_models import (
    InsightLevel,
    MaterialReport,
    PhysicsInsight,
)
from vibedft.analyzers.superconductivity_analyzer import (
    extract_superconductivity_data,
    analyze_superconductivity,
)
from vibedft.analyzers.stability_analyzer import (
    extract_phonon_stability_data,
    analyze_phonon_stability,
)
from vibedft.analyzers.electronic_structure_analyzer import (
    extract_electronic_data,
    analyze_electronic_structure,
)
from vibedft.analyzers.material_analyzer import analyze_material
from vibedft.analyzers.workflow_health_analyzer import analyze_workflow_health
from vibedft.analyzers.gates import evaluate_gates, Decision


def run_physics_analysis(
    case_dir: Path | str,
    review_result: Any | None = None,
) -> MaterialReport:
    """Run all five physics analyzers and produce a MaterialReport.

    This is the main entry point for the Physics Insight Layer.
    """
    d = Path(case_dir).resolve()
    report = MaterialReport(case_dir=str(d))

    all_insights: list[PhysicsInsight] = []

    # ── 1. Material ──
    mat_insights, mat_score = analyze_material(d)
    report.stability_score = mat_score  # material score feeds into stability
    all_insights.extend(mat_insights)

    # ── 2. Electronic Structure ──
    elec_data = extract_electronic_data(d)
    elec_insights, elec_score = analyze_electronic_structure(elec_data)
    report.electronic_score = elec_score
    all_insights.extend(elec_insights)

    # ── 3. Phonon Stability ──
    ph_data = extract_phonon_stability_data(d)
    ph_insights, ph_score = analyze_phonon_stability(ph_data)
    report.stability_score = max(report.stability_score, ph_score)  # take the max
    all_insights.extend(ph_insights)

    # ── 4. Superconductivity ──
    sc_data = extract_superconductivity_data(d)
    sc_insights, sc_score = analyze_superconductivity(sc_data)
    report.superconductivity_score = sc_score
    all_insights.extend(sc_insights)

    # ── 5. Workflow Health ──
    wh_insights, wh_score = analyze_workflow_health(review_result, case_dir=str(d))
    report.workflow_confidence = wh_score
    all_insights.extend(wh_insights)

    report.insights = all_insights

    # ── Key values ──
    if sc_data:
        report.key_values.update({
            "lambda_max": sc_data.lambda_max,
            "tc_max_K": sc_data.tc_max_K,
            "omega_log_K": sc_data.omega_log_K,
            "mustar": sc_data.mustar,
            "has_two_grids": sc_data.has_two_grids,
        })
    if elec_data:
        report.key_values.update({
            "dos_at_ef": elec_data.dos_at_ef,
            "fermi_energy_ev": elec_data.fermi_energy_ev,
            "band_gap_ev": elec_data.band_gap_ev,
            "gap_type": elec_data.gap_type,
            "dominant_orbital": elec_data.dominant_orbital_near_ef,
        })
    if ph_data:
        report.key_values.update({
            "n_imaginary_modes": ph_data.n_imaginary_total,
            "n_imaginary_non_gamma": ph_data.n_imaginary_non_gamma,
            "min_freq_cm1": ph_data.min_freq_cm1,
            "max_freq_cm1": ph_data.max_freq_cm1,
        })

    # ── Cross-reference with review errors ──
    # CRITICAL errors (la2F, crashes waiting to happen) and Tc overlap FAIL
    # must override optimistic physics scores.
    n_critical = 0
    n_errors = 0
    tc_overlap_failed = False
    if review_result is not None:
        from vibedft.models.inspection import Severity
        for iss in review_result.all_issues:
            if iss.severity == Severity.ERROR:
                n_errors += 1
                # Check for critical-blocking errors
                if any(kw in iss.id.lower() for kw in ("la2f", "forbidden", "crash", "missing", "not_converged")):
                    n_critical += 1
            if "tc" in iss.id.lower() and "overlap" in iss.message.lower():
                tc_overlap_failed = True

    # ── Apply caps based on real issues ──
    if n_critical >= 2:
        # Multiple critical errors: severe downgrade
        report.stability_score = min(report.stability_score, 4.0)
        report.workflow_confidence = min(report.workflow_confidence, 3.0)
        report.electronic_score = min(report.electronic_score, 4.0)
    elif n_critical >= 1:
        report.workflow_confidence = min(report.workflow_confidence, 5.0)

    if tc_overlap_failed:
        report.superconductivity_score = min(report.superconductivity_score, 4.0)
        report.workflow_confidence = min(report.workflow_confidence, 4.0)

    if n_errors >= 10:
        report.workflow_confidence = min(report.workflow_confidence, 4.0)

    # ── Overall verdict (with caps applied) ──
    avg_score = (report.stability_score + report.electronic_score +
                 report.superconductivity_score + report.workflow_confidence) / 4.0

    if n_critical >= 2:
        report.overall_verdict = (
            f"BLOCKED — {n_critical} critical errors must be fixed before publication. "
            f"Example: la2F in q2r.x will crash the calculation."
        )
        report.recommendation = "needs_review"
    elif tc_overlap_failed and avg_score < 5.0:
        report.overall_verdict = (
            "Tc convergence FAILED between k-grids AND critical errors present. "
            "Fix errors first, then increase k/q-grid density and re-converge."
        )
        report.recommendation = "needs_review"
    elif tc_overlap_failed:
        report.overall_verdict = (
            "Physics results are promising but Tc convergence FAILED between k-grids. "
            "Increase k-point sampling until Tc overlap is achieved."
        )
        report.recommendation = "convergence_test"
    elif avg_score >= 8.0:
        report.overall_verdict = "High-quality calculation — results are publishable with appropriate caveats."
        report.recommendation = "continue"
    elif avg_score >= 6.0:
        report.overall_verdict = "Adequate calculation — some aspects need convergence testing or further analysis."
        report.recommendation = "convergence_test"
    elif avg_score >= 4.0:
        report.overall_verdict = "Concerning — multiple issues reduce confidence. Address warnings before publication."
        report.recommendation = "needs_review"
    else:
        report.overall_verdict = "Calculation quality is low — results are not reliable. Significant rework needed."
        report.recommendation = "abandon"

    # ── Append coupling summary ──
    if sc_data and sc_data.lambda_max > 0:
        coupling = "strong" if sc_data.lambda_max > 1.5 else ("moderate" if sc_data.lambda_max > 0.8 else "weak")
        report.overall_verdict += (
            f" {coupling}-coupling superconductor with λ={sc_data.lambda_max:.2f}."
        )

    # ── Named-gate decision (primary, gate-based) ──
    has_la2f = any(
        "la2f" in iss.id.lower()
        for iss in (review_result.all_issues if review_result else [])
    )
    relax_converged = (
        ph_data is not None and ph_data.n_imaginary_total >= 0
    )
    gate_decision: Decision = evaluate_gates(
        n_critical_errors=n_critical,
        n_errors=n_errors,
        has_la2f_violation=has_la2f,
        relax_converged=relax_converged if ph_data else None,
        has_scf=elec_data is not None,
        has_dos=elec_data is not None and elec_data.dos_at_ef > 0,
        has_bands=elec_data is not None and elec_data.band_gap_ev is not None,
        is_metallic=True if (elec_data and elec_data.band_gap_ev is not None and elec_data.band_gap_ev < 0.01) else None,
        has_ph_gamma=ph_data is not None,
        has_imaginary_gamma_non_acoustic=(
            ph_data is not None
            and ph_data.n_imaginary_gamma > 0
            and any(m["abs_freq_cm1"] > 5.0 for m in (ph_data.imaginary_at_gamma or []))
        ),
        has_ph_fullq=ph_data is not None and ph_data.n_qpoints > 1,
        has_imaginary_non_gamma=ph_data is not None and ph_data.n_imaginary_non_gamma > 0,
        has_epc_complete=sc_data is not None and sc_data.lambda_max > 0,
        has_lambda=sc_data is not None and sc_data.lambda_max > 0,
        has_tc_overlap_pass=sc_data.tc_overlap_passed if sc_data else None,
        has_tc_point=sc_data is not None and getattr(sc_data, 'tc_point_K', None) is not None,
        tc_nan_or_infinity=(
            sc_data is not None
            and sc_data.tc_max_K is not None
            and (sc_data.tc_max_K != sc_data.tc_max_K or sc_data.tc_max_K > 1e6)
        ),
    )
    report.key_values["gate_decision"] = gate_decision.verdict
    report.key_values["gate_blocked_by"] = gate_decision.blocked_by
    report.key_values["gates"] = [
        {"name": g.gate_name, "status": g.status.value, "reason": g.reason}
        for g in gate_decision.gates
    ]

    return report
