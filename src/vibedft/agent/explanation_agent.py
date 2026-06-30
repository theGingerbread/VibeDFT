"""Explanation agent — explains review findings with evidence citations."""

from __future__ import annotations

import json
from typing import Any

from vibedft.agent.safety import build_system_prompt, redact_private
from vibedft.agent.evidence_pack import build_evidence_pack
from vibedft.agent.prompt_templates import EXPLAIN_REVIEW_TEMPLATE, SYSTEM_PROMPT


def explain_review(
    review_result: Any,
    physics_report: Any = None,
    artifacts: list[Any] | None = None,
    *,
    llm_call: Any = None,
) -> dict[str, Any]:
    """Generate a natural-language explanation of a case review.

    Args:
        review_result: ReviewResult from vibedft.core.review
        physics_report: MaterialReport from vibedft.analyzers.orchestrator
        artifacts: list of Artifact from postprocess
        llm_call: optional callable(prompt, system_prompt) -> str.
                  If None, returns a structured fallback.

    Returns:
        {"explanation": str, "evidence_ids": [str], "mode": "llm"|"fallback"}
    """
    evidence = build_evidence_pack(review_result, physics_report, artifacts)

    if llm_call is None:
        return _fallback_explain(evidence)

    prompt = EXPLAIN_REVIEW_TEMPLATE.format(
        evidence_json=json.dumps(evidence, indent=2, ensure_ascii=False, default=str),
    )
    try:
        response = llm_call(prompt, system_prompt=SYSTEM_PROMPT)
    except Exception:
        return _fallback_explain(evidence)

    return {
        "explanation": redact_private(response),
        "evidence_ids": _extract_evidence_ids(response),
        "mode": "llm",
    }


def _fallback_explain(evidence: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fallback when no LLM is available."""
    parts: list[str] = []

    s = evidence.get("summary", {})
    n_err = s.get("n_errors", 0)
    n_warn = s.get("n_warnings", 0)

    if n_err > 0:
        parts.append(f"⚠ This case has {n_err} error(s) and {n_warn} warning(s).")
    elif n_warn > 0:
        parts.append(f"This case has {n_warn} warning(s). No critical errors.")
    else:
        parts.append("✅ No issues found in this case.")

    wf = evidence.get("workflow", {}).get("best_match")
    if wf:
        parts.append(f"Best workflow match: {wf['label']} ({wf['completeness']:.0%} complete).")
        if wf.get("missing_steps"):
            parts.append(f"Missing steps: {', '.join(wf['missing_steps'])}.")

    p = evidence.get("physics", {})
    if p.get("verdict"):
        parts.append(f"Physics verdict: {p['verdict']}")

    kv = evidence.get("key_values", {})
    if kv:
        vals = []
        if kv.get("lambda_max"):
            vals.append(f"λ={kv['lambda_max']:.2f}")
        if kv.get("tc_max_K"):
            vals.append(f"Tc={kv['tc_max_K']:.1f} K")
        if vals:
            parts.append("Key values: " + ", ".join(vals) + ". [physics.report]")

    critical_issues = [i for i in evidence.get("issues", []) if i.get("severity") == "error"]
    if critical_issues:
        parts.append(f"Top critical issue: [{critical_issues[0]['evidence_id']}] {critical_issues[0]['message']}")

    return {
        "explanation": " ".join(parts),
        "evidence_ids": [i["evidence_id"] for i in critical_issues[:5]],
        "mode": "fallback",
    }


def _extract_evidence_ids(text: str) -> list[str]:
    """Extract [evidence_id] references from LLM output."""
    import re
    return re.findall(r"\[([^\]]+)\]", text)
