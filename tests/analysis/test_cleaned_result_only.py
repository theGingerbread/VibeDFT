"""Tests that analysis functions accept CleanedResult only."""

from __future__ import annotations

from pathlib import Path

import pytest

from vibedft.analysis import analyze_cleaned_result
from vibedft.analysis.routing import supported_analysis_domains


def test_analyze_cleaned_result_rejects_raw_text_path() -> None:
    with pytest.raises(TypeError, match="analysis requires CleanedResult input"):
        analyze_cleaned_result("scf.out")

    with pytest.raises(TypeError, match="analysis requires CleanedResult input"):
        analyze_cleaned_result(Path("scf.out"))

    with pytest.raises(TypeError, match="analysis requires CleanedResult input"):
        analyze_cleaned_result({"task": "dos"})


def test_supported_domains_rejects_non_cleaned_result() -> None:
    with pytest.raises(TypeError, match="analysis requires CleanedResult input"):
        supported_analysis_domains("raw")
