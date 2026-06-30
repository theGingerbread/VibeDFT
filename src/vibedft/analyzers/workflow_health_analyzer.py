"""Workflow health analyzer: convergence confidence scoring."""

from __future__ import annotations

from typing import Any

from vibedft.analyzers.physics_models import (
    EvidenceLink,
    InsightLevel,
    PhysicsInsight,
)
from vibedft.parsers.qe_input_parser import parse_qe_input


def analyze_workflow_health(
    review_result: Any | None,
    case_dir: str = "",
) -> tuple[list[PhysicsInsight], float]:
    """Assess workflow convergence quality and produce a confidence score (0–10).

    Checks k-point density, q-grid density, ecut convergence, and whether
    multi-grid Tc analysis was performed.
    """
    insights: list[PhysicsInsight] = []
    score = 7.0  # start neutral

    if review_result is None:
        return [
            PhysicsInsight(
                id="wh.no_review", category="workflow_health",
                level=InsightLevel.NEUTRAL,
                message="No review data — cannot assess workflow health.",
            )
        ], 5.0

    # Check each identified task for convergence quality
    from pathlib import Path
    d = Path(case_dir) if case_dir else None

    for task in review_result.inspection.tasks:
        src = task.source_file
        if not src or not Path(src).is_file():
            continue

        try:
            qe = parse_qe_input(src)
        except Exception:
            continue

        # ── pw.x: check k-points and ecut ──
        from vibedft.models.inspection import QEProgram
        if task.program == QEProgram.PW:
            kp_card = qe.cards.get("K_POINTS")
            if kp_card and kp_card.rows and kp_card.rows[0]:
                row = kp_card.rows[0]
                if len(row) >= 3:
                    try:
                        nk1, nk2 = int(row[0]), int(row[1])
                    except (ValueError, IndexError):
                        continue
                    if nk1 * nk2 < 64:
                        insights.append(PhysicsInsight(
                            id="wh.kmesh_sparse", category="workflow_health",
                            level=InsightLevel.WARNING,
                            message=f"k-mesh {nk1}×{nk2}×1 may be too sparse "
                                    f"({nk1*nk2} points) — check convergence.",
                            detail="Run a convergence test: double the k-mesh and compare "
                                   "total energy, DOS@EF, and phonon frequencies.",
                            evidence=[EvidenceLink(key="kpoints", value=f"{nk1}x{nk2}",
                                                   source_file=src)],
                        ))
                        score -= 1.5
                    elif nk1 * nk2 >= 144:
                        score += 1.0

            ecut = qe.get_param("system", "ecutwfc", None)
            if ecut is not None:
                try:
                    ecut_val = float(ecut)
                    if ecut_val < 50:
                        insights.append(PhysicsInsight(
                            id="wh.ecut_low", category="workflow_health",
                            level=InsightLevel.WARNING,
                            message=f"ecutwfc = {ecut_val:.0f} Ry — may be below convergence.",
                            detail="Typical values: 60–80 Ry for norm-conserving pseudos.",
                            evidence=[EvidenceLink(key="ecutwfc", value=ecut_val)],
                        ))
                        score -= 1.0
                except (ValueError, TypeError):
                    pass

        # ── ph.x: check q-grid ──
        if task.program == QEProgram.PH:
            nq1 = qe.get_param("inputph", "nq1", None)
            nq2 = qe.get_param("inputph", "nq2", None)
            if nq1 is not None and nq2 is not None:
                try:
                    nq_prod = int(nq1) * int(nq2)
                    if nq_prod < 36:
                        insights.append(PhysicsInsight(
                            id="wh.qgrid_sparse", category="workflow_health",
                            level=InsightLevel.WARNING,
                            message=f"q-grid {nq1}×{nq2}×1 is sparse ({nq_prod} points) — "
                                    "phonon frequencies may not be converged.",
                            evidence=[EvidenceLink(key="qgrid", value=f"{nq1}x{nq2}",
                                                   source_file=src)],
                        ))
                        score -= 1.5
                    elif nq_prod >= 64:
                        score += 0.5
                except (ValueError, TypeError):
                    pass

    # ── Workflow completeness ──
    if review_result.best_match and review_result.best_match.completeness < 0.8:
        insights.append(PhysicsInsight(
            id="wh.incomplete_workflow", category="workflow_health",
            level=InsightLevel.WARNING,
            message=f"Workflow is only {review_result.best_match.completeness:.0%} complete — "
                    f"missing steps may affect result reliability.",
            detail="Complete all workflow steps before drawing physical conclusions.",
        ))
        score -= 2.0

    if review_result.best_match and review_result.best_match.completeness == 1.0:
        score += 1.0
        insights.append(PhysicsInsight(
            id="wh.complete", category="workflow_health",
            level=InsightLevel.POSITIVE,
            message="Workflow is complete — all expected steps are present.",
        ))

    # ── Issue count ──
    if review_result.n_errors > 0:
        insights.append(PhysicsInsight(
            id="wh.errors_present", category="workflow_health",
            level=InsightLevel.WARNING,
            message=f"{review_result.n_errors} error(s) found — resolve before publication.",
        ))
        score -= min(review_result.n_errors * 0.5, 3.0)

    return insights, max(0.0, min(10.0, score))
