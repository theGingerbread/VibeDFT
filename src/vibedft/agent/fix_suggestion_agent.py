"""Fix suggestion agent — precise, evidence-bound fix recommendations."""

from __future__ import annotations

import json
from typing import Any

from vibedft.agent.safety import redact_private
from vibedft.agent.prompt_templates import FIX_SUGGESTION_TEMPLATE, SYSTEM_PROMPT


def suggest_fixes(
    review_result: Any,
    *,
    llm_call: Any = None,
) -> dict[str, Any]:
    """Generate fix suggestions for issues in a case review.

    Returns:
        {"suggestions": [{"issue_id": str, "fix": str, "severity": str}], "mode": "llm"|"fallback"}
    """
    # Extract issues only — the fix agent doesn't need physics data
    issues = []
    for i, iss in enumerate(review_result.all_issues or []):
        issues.append({
            "issue_id": f"issue.{i}",
            "check_id": getattr(iss, "id", ""),
            "severity": _sev(iss),
            "message": redact_private(getattr(iss, "message", "")),
        })

    if not issues:
        return {"suggestions": [], "mode": "fallback"}

    if llm_call is None:
        return _fallback_fixes(issues)

    issues_json = json.dumps(issues, indent=2, ensure_ascii=False)
    prompt = FIX_SUGGESTION_TEMPLATE.format(issues_json=issues_json)

    try:
        response = llm_call(prompt, system_prompt=SYSTEM_PROMPT)
    except Exception:
        return _fallback_fixes(issues)

    return {
        "suggestions": _parse_fix_response(response, issues),
        "mode": "llm",
        "raw": redact_private(response),
    }


def _fallback_fixes(issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic fix suggestions based on known issue patterns."""
    suggestions: list[dict[str, Any]] = []
    for iss in issues:
        cid = iss.get("check_id", "")
        fix = None
        if "la2f" in cid.lower():
            fix = "Remove la2F=.true. from this input file. la2F belongs only in EPC-related matdyn.x, never in q2r.x."
        elif "prefix" in cid.lower() and "mismatch" in cid.lower():
            fix = "Ensure the prefix in this input matches the SCF prefix exactly."
        elif "missing" in cid.lower():
            fix = "Add the required parameter or file indicated in the issue message."
        elif "not_converged" in cid.lower() or "not converged" in iss.get("message", "").lower():
            fix = "Check SCF parameters: increase ecutwfc/ecutrho or adjust mixing_beta."
        elif "tc" in cid.lower() or "overlap" in cid.lower():
            fix = "Increase k-point sampling density and re-run lambda.x on both grids until Tc curves overlap within 1%."

        if fix and iss["severity"] in ("error", "warning"):
            suggestions.append({
                "issue_id": iss["issue_id"],
                "check_id": cid,
                "severity": iss["severity"],
                "fix": fix,
            })

    return {"suggestions": suggestions[:10], "mode": "fallback"}


def _parse_fix_response(response: str, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Try to extract structured fix suggestions from LLM response."""
    import re
    suggestions: list[dict[str, Any]] = []
    refs = re.findall(r"\[(issue\.\d+)\]", response)
    lines = response.split("\n")
    for ref in refs:
        matching = [i for i in issues if i["issue_id"] == ref]
        if matching:
            for line in lines:
                if ref in line:
                    suggestions.append({
                        "issue_id": ref,
                        "check_id": matching[0].get("check_id", ""),
                        "severity": matching[0].get("severity", ""),
                        "fix": line.strip().lstrip("- ").lstrip("0123456789. "),
                    })
                    break
    return suggestions[:10]


def _sev(iss: Any) -> str:
    try:
        return iss.severity.value
    except AttributeError:
        return str(getattr(iss, "severity", "?"))
