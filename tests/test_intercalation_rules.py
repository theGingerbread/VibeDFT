"""Tests for intercalation validation rules."""
import tempfile
from pathlib import Path
from vibedft.validators.intercalation_rules import (
    _is_high_symmetry_column,
    _distance,
    _nearest_anion_distance,
    _count_intercalation_sites,
    _has_non_gamma_imaginary,
    SanityIssue,
    Severity,
)


class TestHighSymmetryDetection:
    def test_top_site_is_high_symmetry(self):
        assert _is_high_symmetry_column(0.0, 0.0) is True

    def test_hollow_site_is_not_high_symmetry(self):
        assert _is_high_symmetry_column(2/3, 1/3) is False

    def test_off_center_is_not_high_symmetry(self):
        assert _is_high_symmetry_column(0.5, 0.5) is False


class TestDistanceFunctions:
    def test_zero_distance(self):
        assert _distance((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)) == 0.0

    def test_one_axial(self):
        assert abs(_distance((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)) - 1.0) < 1e-10


class TestNearestAnionDistance:
    def test_nearest_hf_to_cl(self):
        positions = [
            ("Hf", 0.0, 0.0, 0.5),
            ("Cl", 0.1, 0.0, 0.5),
        ]
        cell = [[3.3, 0, 0], [-1.65, 2.86, 0], [0, 0, 30]]
        intercalant = ("Hf", 0.0, 0.0, 0.5)
        result = _nearest_anion_distance(intercalant, positions, cell)
        assert result is not None
        elem, dist = result
        assert elem == "Cl"
        assert dist > 0.0


class TestSiteCounting:
    def test_no_case_dir(self):
        with tempfile.TemporaryDirectory() as td:
            assert _count_intercalation_sites(Path(td)) == 0


class TestNonGammaImaginary:
    def test_no_freq_file(self):
        p = Path("/tmp/nonexistent_phonon.freq.gp")
        assert _has_non_gamma_imaginary(p) is False


class TestSanityIssue:
    def test_issue_fields(self):
        issue = SanityIssue(
            id="test.rule",
            severity=Severity.ERROR,
            message="test message",
            detail="detail",
        )
        assert issue.id == "test.rule"
        assert issue.severity == Severity.ERROR
