"""Analysis routing helpers for CleanedResult-only contracts."""

from __future__ import annotations

from vibedft._shared.contracts import CleanedResult


def supported_analysis_domains(result: CleanedResult) -> list[str]:
    """Return allowed analysis.* downstream domains from result readiness."""

    cleaned = _ensure_cleaned_result(result)
    downstream = cleaned.readiness.downstream
    return [
        task
        for task, readiness in downstream.items()
        if isinstance(task, str)
        and task.startswith("analysis.")
        and isinstance(readiness, object)
        and getattr(readiness, "allowed", False)
    ]


def blocked_analysis_domains(result: CleanedResult) -> list[str]:
    """Return blocked analysis.* downstream domains from result readiness."""

    cleaned = _ensure_cleaned_result(result)
    downstream = cleaned.readiness.downstream
    return [
        task
        for task, readiness in downstream.items()
        if isinstance(task, str)
        and task.startswith("analysis.")
        and not getattr(readiness, "allowed", False)
    ]


def _ensure_cleaned_result(result: object) -> CleanedResult:
    """Return `result` as CleanedResult, otherwise raise contract guard error."""

    if not isinstance(result, CleanedResult):
        raise TypeError("analysis requires CleanedResult input")
    return result


__all__ = [
    "supported_analysis_domains",
    "blocked_analysis_domains",
    "_ensure_cleaned_result",
]
