"""Tests for the Unified Analyzer protocol (ROADMAP §3.1)."""

import json
from pathlib import Path

import pytest

from vibedft.analyzers.base import (
    Analyzer,
    SectionResult,
    get_all_analyzers,
    register_analyzer,
    run_analyzer,
)
from vibedft.analyzers.physics_models import PhysicsInsight
from vibedft.analyzers.stability_analyzer import (
    PhononStabilityAnalyzer,
    analyze_phonon_stability,
    extract_phonon_stability_data,
)
from vibedft.analyzers.superconductivity_analyzer import (
    SuperconductivityAnalyzer,
    analyze_superconductivity,
    extract_superconductivity_data,
)


# ── Fixture content (mirrors tests/test_tc.py & tests/test_phonon.py) ──

SAMPLE_LAMBDAX = """\
     lambda.x output
     mu* = 0.10

     lambda  omega_log  T_c
     degauss       lambda      omega_log        T_c
       0.0020      1.4500       115.000        12.500  N(Ef)=  2.350
       0.0040      1.4200       114.500        12.100  N(Ef)=  2.350
       0.0060      1.3800       114.000        11.600  N(Ef)=  2.350
       0.0080      1.3400       113.500        11.200  N(Ef)=  2.350
       0.0100      1.3000       113.000        10.800  N(Ef)=  2.350
"""

SAMPLE_FREQ_GP = """\
   0.0000   0.0000  12.3456  25.6789  45.1234
   0.1000  -0.5000  12.4000  25.7000  45.2000
   0.2000   0.0000  12.5000  25.8000  45.3000
   0.3000   1.2000  12.6000  25.9000  45.4000
"""


# ── ABC ──


def test_analyzer_is_abstract():
    """Analyzer cannot be instantiated directly."""
    with pytest.raises(TypeError):
        Analyzer()


def test_analyzer_subclass_requires_all_methods():
    """A subclass missing abstract methods fails to instantiate."""

    class Incomplete(Analyzer):
        id = "incomplete"
        label = "Incomplete"
        required_patterns: list[str] = []
        optional_patterns: list[str] = []

    with pytest.raises(TypeError):
        Incomplete()


# ── SuperconductivityAnalyzer ──


def test_superconductivity_analyzer_class_attrs():
    assert SuperconductivityAnalyzer.id == "superconductivity"
    assert SuperconductivityAnalyzer.label == "Superconductivity (λ/Tc)"
    assert SuperconductivityAnalyzer.required_patterns == ["**/lambdax.out"]
    assert SuperconductivityAnalyzer.optional_patterns == ["**/alpha2F.dat"]


def test_superconductivity_analyzer_discover(tmp_path: Path):
    (tmp_path / "ph64").mkdir()
    (tmp_path / "ph64" / "lambdax.out").write_text(SAMPLE_LAMBDAX)
    (tmp_path / "README.md").write_text("noise")

    az = SuperconductivityAnalyzer()
    files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    matched = az.discover(files)
    assert len(matched) == 1
    assert matched[0].name == "lambdax.out"


def test_superconductivity_analyzer_run(tmp_path: Path):
    (tmp_path / "ph64").mkdir()
    (tmp_path / "ph64" / "lambdax.out").write_text(SAMPLE_LAMBDAX)

    az = SuperconductivityAnalyzer()
    result = run_analyzer(az, tmp_path)

    assert isinstance(result, SectionResult)
    assert result.section_id == "superconductivity"
    assert result.status in {"pass", "warn", "fail", "missing"}
    assert result.data.get("lambda_max", 0) > 1.0
    assert result.data.get("tc_max_K", 0) > 5.0
    assert isinstance(result.insights, list)
    assert len(result.insights) >= 1
    assert all(isinstance(i, PhysicsInsight) for i in result.insights)
    assert result.plots == []
    assert result.provenance["parser"] == "vibedft.core.tc.parse_lambdax_output"
    assert result.provenance["source_files"]
    assert 0.0 <= az.score <= 10.0


def test_superconductivity_analyzer_missing(tmp_path: Path):
    az = SuperconductivityAnalyzer()
    result = run_analyzer(az, tmp_path)
    assert result.status == "missing"
    assert result.data == {}
    assert result.insights  # produces a no_data insight


# ── PhononStabilityAnalyzer ──


def test_phonon_stability_analyzer_class_attrs():
    assert PhononStabilityAnalyzer.id == "phonon_stability"
    assert PhononStabilityAnalyzer.required_patterns == ["**/*.freq.gp"]
    assert PhononStabilityAnalyzer.optional_patterns == []


def test_phonon_stability_analyzer_discover(tmp_path: Path):
    (tmp_path / "ph").mkdir()
    (tmp_path / "ph" / "test.freq.gp").write_text(SAMPLE_FREQ_GP)
    (tmp_path / "notes.txt").write_text("noise")

    az = PhononStabilityAnalyzer()
    files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    matched = az.discover(files)
    assert len(matched) == 1
    assert matched[0].name == "test.freq.gp"


def test_phonon_stability_analyzer_run(tmp_path: Path):
    (tmp_path / "ph").mkdir()
    (tmp_path / "ph" / "test.freq.gp").write_text(SAMPLE_FREQ_GP)

    az = PhononStabilityAnalyzer()
    result = run_analyzer(az, tmp_path)

    assert isinstance(result, SectionResult)
    assert result.section_id == "phonon_stability"
    assert result.status in {"pass", "warn", "fail"}
    assert result.data.get("n_qpoints") == 4
    assert result.data.get("n_branches") == 4
    assert isinstance(result.insights, list)
    assert len(result.insights) >= 1
    assert result.plots == []
    assert result.provenance["parser"] == "vibedft.core.phonon.parse_freq_gp"
    assert result.provenance["source_files"]
    assert 0.0 <= az.score <= 10.0


# ── run_analyzer / SectionResult ──


def test_run_analyzer_returns_section_result(tmp_path: Path):
    (tmp_path / "ph64").mkdir()
    (tmp_path / "ph64" / "lambdax.out").write_text(SAMPLE_LAMBDAX)
    az = SuperconductivityAnalyzer()
    result = run_analyzer(az, tmp_path)
    assert isinstance(result, SectionResult)
    for f in ("section_id", "status", "data", "insights", "plots", "provenance"):
        assert hasattr(result, f)


def test_section_result_to_dict_is_json_serializable(tmp_path: Path):
    (tmp_path / "ph64").mkdir()
    (tmp_path / "ph64" / "lambdax.out").write_text(SAMPLE_LAMBDAX)
    az = SuperconductivityAnalyzer()
    result = run_analyzer(az, tmp_path)
    d = result.to_dict()
    assert set(d.keys()) == {"section_id", "status", "data", "insights", "plots", "provenance"}
    s = json.dumps(d)
    assert json.loads(s)["section_id"] == "superconductivity"


# ── Registry ──


def test_registry_contains_concrete_analyzers():
    kinds = {c.id for c in get_all_analyzers()}
    assert "superconductivity" in kinds
    assert "phonon_stability" in kinds


def test_register_analyzer_decorator():
    before = set(get_all_analyzers())

    @register_analyzer
    class TempAnalyzer(Analyzer):
        id = "temp_test_only"
        label = "Temp"
        required_patterns: list[str] = []
        optional_patterns: list[str] = []

        def discover(self, files):
            return []

        def parse(self):
            return {}

        def summarize(self):
            return {"status": "missing"}

        def insights(self):
            return []

        def plots(self):
            return []

        def provenance(self):
            return {}

    try:
        after = set(get_all_analyzers())
        assert TempAnalyzer in get_all_analyzers()
        assert len(after) == len(before) + 1
    finally:
        from vibedft.analyzers import base as base_mod
        if TempAnalyzer in base_mod._ANALYZER_REGISTRY:
            base_mod._ANALYZER_REGISTRY.remove(TempAnalyzer)


def test_register_analyzer_rejects_non_subclass():
    with pytest.raises(TypeError):
        register_analyzer(int)


# ── Existing module functions still callable ──


def test_existing_sc_module_functions_callable():
    assert callable(extract_superconductivity_data)
    assert callable(analyze_superconductivity)
    ins, score = analyze_superconductivity(None)
    assert score == 0.0
    assert ins[0].id == "sc.no_data"


def test_existing_phonon_module_functions_callable():
    assert callable(extract_phonon_stability_data)
    assert callable(analyze_phonon_stability)
    ins, score = analyze_phonon_stability(None)
    assert score == 5.0
    assert ins[0].id == "ph.no_data"