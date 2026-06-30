"""Next-step agent — evidence-based calculation planning."""

from __future__ import annotations

import json
from typing import Any

from vibedft.agent.safety import redact_private
from vibedft.agent.evidence_pack import build_evidence_pack
from vibedft.agent.prompt_templates import NEXT_STEP_TEMPLATE, SYSTEM_PROMPT


def recommend_next_steps(
    review_result: Any,
    physics_report: Any = None,
    *,
    llm_call: Any = None,
) -> dict[str, Any]:
    """Recommend next calculation steps.

    Returns:
        {"steps": [str], "mode": "llm"|"fallback"}
    """
    evidence = build_evidence_pack(review_result, physics_report)

    if llm_call is None:
        return _fallback_steps(evidence)

    prompt = NEXT_STEP_TEMPLATE.format(
        evidence_json=json.dumps(evidence, indent=2, ensure_ascii=False, default=str),
    )
    try:
        response = llm_call(prompt, system_prompt=SYSTEM_PROMPT)
    except Exception:
        return _fallback_steps(evidence)

    # Parse steps from response
    steps = [l.strip().lstrip("- ").lstrip("0123456789. ") for l in response.split("\n")
             if l.strip() and not l.startswith("#") and len(l.strip()) > 10]
    steps = steps[:5]

    return {
        "steps": [redact_private(s) for s in steps],
        "mode": "llm",
        "raw": redact_private(response),
    }


def _fallback_steps(evidence: dict[str, Any]) -> dict[str, Any]:
    """Deterministic next-step recommendations."""
    steps: list[str] = []

    n_err = evidence.get("summary", {}).get("n_errors", 0)
    wf = evidence.get("workflow", {}).get("best_match")
    p = evidence.get("physics", {})

    if n_err > 0:
        critical_ids = [i["evidence_id"] for i in evidence.get("issues", [])
                       if i.get("severity") == "error"][:3]
        steps.append(f"Fix {n_err} error(s) before proceeding. See: {', '.join(critical_ids)} [review.summary]")

    if wf and wf.get("completeness", 1.0) < 0.8:
        missing = wf.get("missing_steps", [])
        steps.append(f"Complete missing workflow stages: {', '.join(missing[:4])} [review.workflow]")

    rec = p.get("recommendation", "")
    if rec == "convergence_test":
        steps.append("Run convergence tests: increase k-grid and q-grid density until Tc overlap passes [physics.report]")
    elif rec == "needs_review":
        steps.append("Address critical issues before running any new calculations [physics.report]")

    if not steps:
        steps.append("Workflow is complete and no critical issues found. Consider archiving and running convergence report [review.summary]")

    if len(steps) < 3:
        steps.append("After completing the above, run: vibedft report generate --case-dir . --output report.html [review.summary]")
        steps.append("Archive results with: vibedft archive apply --case-dir . --target-root <DFT_RESULTS_DIR> [review.summary]")

    return {"steps": steps[:5], "mode": "fallback"}
