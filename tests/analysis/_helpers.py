"""Test helpers for analysis contract unit tests."""

from __future__ import annotations

from typing import Any

from vibedft._shared.contracts import CleanedResult, Diagnostics, DownstreamReadiness, Readiness, ReviewResult


def make_cleaned_result(
    *,
    task: str,
    status: str = "pass",
    review_status: str = "PASS",
    allowed: tuple[str, ...] = ("analysis.dos",),
    blocked: tuple[str, ...] = (),
    observables: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    diagnostics_errors: list[str] | None = None,
    diagnostics_warnings: list[str] | None = None,
    next_actions: list[str] | None = None,
    extra_downstream: dict[str, bool] | None = None,
) -> CleanedResult:
    """Build a lightweight `CleanedResult` fixture for analysis-layer tests."""

    allowed = tuple(allowed)
    blocked = tuple(blocked)

    downstream: dict[str, DownstreamReadiness] = {}
    all_tasks = {task_name: True for task_name in allowed}
    all_tasks.update({task_name: False for task_name in blocked})
    if extra_downstream is not None:
        all_tasks.update(extra_downstream)

    for name, is_allowed in all_tasks.items():
        downstream[name] = DownstreamReadiness(
            task=name,
            allowed=is_allowed,
            reason="test routing",
        )

    review = ReviewResult(
        status=review_status,
        allowed_downstream=list(allowed),
        blocked_downstream=list(blocked),
        recommendations=list(next_actions or []),
    )
    return CleanedResult(
        calculator="qe",
        task=task,
        status=status,
        review=review,
        source_artifacts=[f"{task}.out"],
        observables=observables or {},
        outputs=outputs or {},
        diagnostics=Diagnostics(
            errors=list(diagnostics_errors or []),
            warnings=list(diagnostics_warnings or []),
        ),
        readiness=Readiness(downstream=downstream),
        next_actions=list(next_actions or []),
    )
