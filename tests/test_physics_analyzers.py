"""Tests for physics analyzers (Sprint 4)."""

import json
from pathlib import Path

from vibedft.analyzers.superconductivity_analyzer import (
    extract_superconductivity_data,
    analyze_superconductivity,
    SuperconductivityData,
)
from vibedft.analyzers.stability_analyzer import (
    analyze_phonon_stability,
    PhononStabilityData,
)
from vibedft.analyzers.electronic_structure_analyzer import (
    analyze_electronic_structure,
    ElectronicData,
)
from vibedft.analyzers.orchestrator import run_physics_analysis
from vibedft.analyzers.physics_models import InsightLevel


def test_sc_analyzer_strong_coupling():
    """Strong coupling (λ > 2.0) should produce positive insight."""
    data = SuperconductivityData(
        lambda_max=2.5, tc_max_K=15.0, omega_log_K=100.0,
        mustar=0.1, has_two_grids=True, tc_overlap_passed=True, a2f_available=True,
    )
    insights, score = analyze_superconductivity(data)
    assert score > 7.0
    messages = [i.id for i in insights]
    assert "sc.strong_coupling" in messages
    assert "sc.tc_high" in messages


def test_sc_analyzer_very_weak():
    """Very weak coupling (λ < 0.5) should produce negative insight."""
    data = SuperconductivityData(
        lambda_max=0.2, tc_max_K=0.1, mustar=0.1,
        has_two_grids=False, a2f_available=False,
    )
    insights, score = analyze_superconductivity(data)
    assert score < 5.0
    messages = [i.id for i in insights]
    assert "sc.very_weak" in messages
    assert "sc.single_grid" in messages


def test_sc_analyzer_no_data():
    """No data should produce neutral insight with score 0."""
    insights, score = analyze_superconductivity(None)
    assert score == 0.0
    assert insights[0].id == "sc.no_data"


def test_phonon_analyzer_stable():
    """No imaginary modes → positive."""
    data = PhononStabilityData(
        n_qpoints=100, n_branches=9,
        min_freq_cm1=10.0, max_freq_cm1=400.0,
        n_imaginary_total=0,
    )
    insights, score = analyze_phonon_stability(data)
    assert score > 7.0
    assert any("stable" in i.id for i in insights)


def test_phonon_analyzer_m_point_imaginary():
    """M-point imaginary modes → CDW warning."""
    data = PhononStabilityData(
        n_qpoints=100, n_branches=9,
        min_freq_cm1=-5.0, max_freq_cm1=400.0,
        n_imaginary_total=3, n_imaginary_non_gamma=3,
        imaginary_at_M=[{"q_index": 33, "branch": 1, "freq_cm1": -5.0}],
    )
    insights, score = analyze_phonon_stability(data)
    assert score < 6.0
    assert any("imaginary_at_M" in i.id for i in insights)


def test_electronic_analyzer_metallic():
    """High DOS@EF → positive for SC."""
    data = ElectronicData(
        dos_at_ef=5.0, fermi_energy_ev=-1.0, is_metallic=True,
        dominant_orbital_near_ef="Hf-d", dominant_orbital_fraction=0.6,
    )
    insights, score = analyze_electronic_structure(data)
    assert score > 7.0
    assert any("metallic" in i.id for i in insights)


def test_orchestrator_on_real_case():
    """Orchestrator should run on the real test case without crashing."""
    import os
    project_root = Path(__file__).resolve().parents[1]
    case_dir = project_root / "cases" / "HfBr2-test-run"
    if not case_dir.is_dir():
        return  # skip if test case doesn't exist

    report = run_physics_analysis(str(case_dir), review_result=None)
    assert report.case_dir
    assert len(report.insights) >= 1
    assert 0.0 <= report.stability_score <= 10.0
    assert 0.0 <= report.electronic_score <= 10.0
    assert report.overall_verdict  # non-empty

    # Should be serialisable
    d = report.to_dict()
    assert "scores" in d
    assert "insights" in d
    assert "recommendation" in d
