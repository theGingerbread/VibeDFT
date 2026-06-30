"""Semantics orchestrator — runs all semantic analyzers and produces a CaseSemanticSummary."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibedft.semantics.material_identifier import identify_material, MaterialIdentity
from vibedft.semantics.batch_intent import detect_batch_intent, BatchIntent
from vibedft.semantics.ph_chunking import analyze_ph_chunking, PhChunkingPlan
from vibedft.semantics.parameter_intelligence import analyze_parameters, ParameterIntelligenceReport, ParameterInsight
from vibedft.semantics.workflow_narrative import generate_narrative


@dataclass
class CaseSemanticSummary:
    case_dir: str = ""
    material: MaterialIdentity | None = None
    batch_intent: BatchIntent | None = None
    ph_chunking: PhChunkingPlan | None = None
    parameter_intel: list[ParameterInsight] = field(default_factory=list)
    narrative: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        m = self.material
        b = self.batch_intent
        p = self.ph_chunking
        return {
            "case_dir": self.case_dir,
            "material": {
                "formula": m.formula_from_positions if m else "",
                "elements": m.elements if m else [],
                "n_atoms": m.n_atoms if m else 0,
                "stoichiometry": m.stoichiometry if m else {},
                "likely_2d": m.likely_2d if m else False,
                "c_axis_ang": m.c_axis_ang if m else 0.0,
                "formula_conflict": m.formula_conflict if m else False,
                "conflict_detail": m.conflict_detail if m else "",
            } if m else None,
            "batch_intent": {
                "strain_scan": b.strain_scan if b else False,
                "strain_type": b.strain_type if b else "",
                "strain_values": b.strain_values if b else [],
                "dual_grid_epc": b.dual_grid_epc if b else False,
                "epc_grids": b.epc_grids if b else [],
                "calculation_families": b.calculation_families if b else [],
                "summary": b.summary if b else "",
            } if b else None,
            "ph_chunking": {
                "is_chunked": p.is_chunked if p else False,
                "chunk_count": p.chunk_count if p else 0,
                "total_q_points": p.total_q_points if p else 0,
                "coverage": p.coverage if p else "unknown",
                "missing_q": p.missing_q if p else [],
                "summary": p.summary if p else "",
            } if p else None,
            "parameter_insights": [
                {"parameter": i.parameter, "value": str(i.value),
                 "context": i.context, "severity": i.severity,
                 "message": i.message, "file": i.file}
                for i in self.parameter_intel
            ],
            "narrative": self.narrative,
            "warnings": self.warnings,
        }


def analyze_semantics(case_dir: Path | str) -> CaseSemanticSummary:
    """Run all semantic analyzers on a case directory."""
    d = Path(case_dir).resolve()
    result = CaseSemanticSummary(case_dir=str(d))

    result.material = identify_material(d)
    result.batch_intent = detect_batch_intent(d)
    result.ph_chunking = analyze_ph_chunking(d)

    param_report = analyze_parameters(d)
    result.parameter_intel = param_report.insights

    result.narrative = generate_narrative(
        result.material, result.batch_intent,
        result.ph_chunking, param_report,
    )

    # Collect warnings
    if result.material and result.material.formula_conflict:
        result.warnings.append(result.material.conflict_detail)
    if result.ph_chunking:
        result.warnings.extend(result.ph_chunking.warnings)
    for pi in result.parameter_intel:
        if pi.severity == "warning":
            result.warnings.append(pi.message)

    return result
