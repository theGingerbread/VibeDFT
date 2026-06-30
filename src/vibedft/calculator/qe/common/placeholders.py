"""Shared placeholder utilities for QE task modules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QETaskStagePlaceholder:
    """Minimal contract marker for QE task-stage placeholders."""

    task: str
    stage: str
    summary: str


def make_stage_placeholder(task: str, stage: str) -> QETaskStagePlaceholder:
    return QETaskStagePlaceholder(
        task=task,
        stage=stage,
        summary=f"Placeholder for qe/{task}/{stage}.py",
    )
