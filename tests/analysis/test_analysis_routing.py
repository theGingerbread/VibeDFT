"""Tests for analysis domain routing from CleanedResult readiness."""

from __future__ import annotations

from dataclasses import asdict

from vibedft.analysis import analyze_cleaned_result
from vibedft.analysis.routing import blocked_analysis_domains, supported_analysis_domains
from ._helpers import make_cleaned_result


def test_supported_analysis_domains_filters_allowed_analysis_tasks() -> None:
    result = make_cleaned_result(
        task="dos",
        allowed=("analysis.dos", "analysis.pdos"),
        blocked=("phonon",),
    )
    assert "analysis.dos" in supported_analysis_domains(result)
    assert "analysis.pdos" in supported_analysis_domains(result)
    assert "phonon" not in supported_analysis_domains(result)


def test_blocked_analysis_domains_filters_blocked_analysis_tasks() -> None:
    result = make_cleaned_result(
        task="bands",
        allowed=("analysis.bands",),
        blocked=("analysis.bandgap", "phonon"),
    )
    assert "analysis.bandgap" in blocked_analysis_domains(result)
    assert "analysis.bands" not in blocked_analysis_domains(result)
    assert "phonon" not in blocked_analysis_domains(result)


def test_routing_ignores_non_analysis_tasks() -> None:
    result = make_cleaned_result(
        task="pp",
        allowed=("analysis.pp",),
        blocked=("phonon",),
        extra_downstream={"scf": False, "dos": False},
    )
    assert supported_analysis_domains(result) == ["analysis.pp"]
    assert blocked_analysis_domains(result) == []


def test_requesting_disallowed_domain_produces_blocking_finding() -> None:
    result = make_cleaned_result(
        task="pp",
        allowed=("analysis.pp",),
        blocked=("analysis.charge_density",),
    )
    report = analyze_cleaned_result(result, domain="analysis.bandgap")

    findings = [asdict(item) for item in report.findings]
    assert findings, "expected findings for disallowed requested domain"
    assert any(item["level"] in {"block", "warn"} for item in findings)
    assert any("analysis.bandgap" in item["evidence_refs"] for item in findings)
