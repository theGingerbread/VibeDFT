"""Evidence Pack builder — compresses deterministic findings into a safe, structured
JSON object that the LLM Agent can consume without accessing raw files.

Every value has an evidence_id for traceability.
"""

from __future__ import annotations

from typing import Any

from vibedft.agent.safety import redact_private


def build_evidence_pack(
    review_result: Any | None = None,
    physics_report: Any | None = None,
    artifacts: list[Any] | None = None,
) -> dict[str, Any]:
    """Build a compact, redacted evidence pack for LLM consumption.

    Includes only the information needed for explanation, fix suggestions,
    and next-step recommendations — no raw file content.
    """
    pack: dict[str, Any] = {
        "summary": {},
        "issues": [],
        "physics": {},
        "workflow": {},
        "key_values": {},
        "artifacts": [],
    }

    # ── Review summary ──
    if review_result is not None:
        pack["summary"] = {
            "evidence_id": "review.summary",
            "files_scanned": review_result.files_scanned,
            "files_inspected": review_result.files_inspected,
            "n_errors": review_result.n_errors,
            "n_warnings": review_result.n_warnings,
            "summary": redact_private(review_result.summary),
            "next_step": redact_private(review_result.next_step),
        }
        pack["workflow"] = {
            "evidence_id": "review.workflow",
            "best_match": _safe_workflow(review_result),
            "matches": [_safe_workflow_match(m) for m in (review_result.workflow_matches or [])[:3]],
        }
        # Issues with evidence IDs
        for i, iss in enumerate(review_result.all_issues or []):
            pack["issues"].append({
                "evidence_id": f"issue.{i}",
                "check_id": getattr(iss, "id", ""),
                "severity": _sev(iss),
                "message": redact_private(getattr(iss, "message", "")),
                "detail": redact_private(getattr(iss, "detail", "")),
                "source": _safe_path(getattr(iss, "source_file", "")),
            })

    # ── Physics ──
    if physics_report is not None:
        try:
            pdict = physics_report.to_dict()
        except AttributeError:
            pdict = physics_report if isinstance(physics_report, dict) else {}
        pack["physics"] = {
            "evidence_id": "physics.report",
            "scores": pdict.get("scores", {}),
            "verdict": redact_private(pdict.get("overall_verdict", "")),
            "recommendation": pdict.get("recommendation", ""),
            "key_insights": [
                {"evidence_id": f"physics.insight.{j}", "message": i.get("message", ""),
                 "level": i.get("level", ""), "category": i.get("category", "")}
                for j, i in enumerate((pdict.get("insights") or [])[:15])
            ],
        }
        pack["key_values"] = pdict.get("key_values", {})

    # ── Artifacts ──
    if artifacts:
        for a in artifacts:
            try:
                ad = a.to_dict()
            except AttributeError:
                ad = a if isinstance(a, dict) else {}
            pack["artifacts"].append({
                "evidence_id": f"artifact.{ad.get('id', '?')}",
                "kind": ad.get("kind", ""),
                "title": ad.get("title", ""),
                "source_files": [_safe_path(s) for s in ad.get("source_files", [])[:5]],
            })

    return pack


def _safe_workflow(review: Any) -> dict[str, Any] | None:
    if not review or not review.best_match:
        return None
    bm = review.best_match
    return {
        "workflow_id": bm.workflow.workflow_id,
        "label": bm.workflow.label,
        "completeness": bm.completeness,
        "missing_steps": [s.label for s in bm.missing_steps],
    }


def _safe_workflow_match(m: Any) -> dict[str, Any]:
    return {
        "workflow_id": m.workflow.workflow_id,
        "label": m.workflow.label,
        "completeness": m.completeness,
        "missing_steps": [s.label for s in m.missing_steps],
    }


def _sev(iss: Any) -> str:
    try:
        return iss.severity.value
    except AttributeError:
        return str(getattr(iss, "severity", "?"))


def _safe_path(p: str) -> str:
    """Keep only the filename, strip full paths."""
    if not p:
        return ""
    return redact_private(p).split("/")[-1]
