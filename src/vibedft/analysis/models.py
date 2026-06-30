"""Analysis-layer placeholders."""

from __future__ import annotations

from dataclasses import dataclass

from vibedft._shared.contracts import CleanedResult


@dataclass
class AnalysisRequest:
    """Minimal analysis request operating on cleaned results only."""

    result: CleanedResult
    analysis_kind: str
