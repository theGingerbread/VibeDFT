"""Merge all analysis results into a single unified evidence dict for decision-making."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def merge_all_evidence(
    case_dir: Path | str,
    review_result: Any = None,
    physics_report: Any = None,
    property_bundle: Any = None,
    convergence_report: Any = None,
) -> dict[str, Any]:
    """Merge ReviewResult, MaterialReport, PropertyBundle, and optional
    ConvergenceReport into a single flat evidence dict for the decision layer.
    """
    e: dict[str, Any] = {
        "case_dir": str(case_dir),
        "blockers": [],
        "warnings": [],
        "positives": [],
        "metrics": {},
    }

    # ── Review issues ──
    if review_result is not None:
        for iss in (review_result.all_issues or []):
            sev = _sev(iss)
            msg = getattr(iss, "message", "")
            cid = getattr(iss, "id", "")
            entry = {"id": cid, "message": msg[:120]}
            if sev == "error":
                e["blockers"].append(entry)
            elif sev == "warning":
                e["warnings"].append(entry)

    # ── Physics ──
    if physics_report is not None:
        try:
            pdict = physics_report.to_dict()
        except AttributeError:
            pdict = physics_report if isinstance(physics_report, dict) else {}
        scores = pdict.get("scores", {})
        e["metrics"].update({
            "stability_score": scores.get("stability", 0),
            "electronic_score": scores.get("electronic", 0),
            "superconductivity_score": scores.get("superconductivity", 0),
            "workflow_confidence": scores.get("workflow_confidence", 0),
            "recommendation": pdict.get("recommendation", ""),
        })
        kv = pdict.get("key_values", {})
        e["metrics"].update({
            "lambda_max": kv.get("lambda_max"),
            "tc_max_K": kv.get("tc_max_K"),
            "dos_at_ef": kv.get("dos_at_ef"),
            "n_imaginary_modes": kv.get("n_imaginary_modes", 0),
            "n_imaginary_non_gamma": kv.get("n_imaginary_non_gamma", 0),
        })
        for ins in pdict.get("insights", [])[:20]:
            level = ins.get("level", "neutral")
            msg = ins.get("message", "")
            if level == "positive":
                e["positives"].append(msg)
            elif level in ("negative", "warning"):
                e["warnings"].append({"id": ins.get("id", ""), "message": msg})

    # ── Properties ──
    if property_bundle is not None:
        try:
            pdict = property_bundle.to_dict()
        except AttributeError:
            pdict = {}
        for name, pr in (pdict.get("properties") or {}).items():
            if pr.get("status") == "ok":
                for ins in pr.get("insights", []):
                    e["positives"].append(f"[{name}] {ins}")
                e["metrics"].update({f"prop_{name}_{k}": v for k, v in (pr.get("data") or {}).items()})
            elif pr.get("status") == "missing":
                pass  # Missing properties are not blockers by default

    # ── Convergence ──
    if convergence_report is not None:
        e["metrics"]["convergence_confidence"] = getattr(convergence_report, "overall_confidence", "unknown")
        e["metrics"]["convergence_n_cases"] = len(getattr(convergence_report, "rows", []))
        if getattr(convergence_report, "unconverged_params", []):
            for p in convergence_report.unconverged_params:
                e["warnings"].append({"id": f"convergence.{p}", "message": f"Parameter '{p}' not converged"})

    # ── Workflow completeness ──
    if review_result is not None and review_result.best_match:
        wf = review_result.best_match
        e["metrics"]["workflow_completeness"] = wf.completeness
        missing = [s.label for s in wf.missing_steps]
        if missing:
            e["warnings"].append({"id": "workflow.incomplete", "message": f"Missing steps: {', '.join(missing[:5])}"})

    return e


def _sev(iss: Any) -> str:
    try:
        return iss.severity.value
    except AttributeError:
        return str(getattr(iss, "severity", "?"))
