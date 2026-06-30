"""Tests for intercalation site comparison."""
import tempfile
from pathlib import Path
from vibedft.core.site_comparator import (
    SiteComparisonRow,
    SiteComparisonResult,
    _is_site_dir,
    discover_site_dirs,
    find_vc_relax_output,
)


class TestIsSiteDir:
    def test_rx_pattern(self):
        assert _is_site_dir("rx_2", "Li") is True

    def test_lowercase_li(self):
        assert _is_site_dir("Li_3", "Li") is True

    def test_na_pattern(self):
        assert _is_site_dir("Na_2", "Na") is True

    def test_non_site_name(self):
        assert _is_site_dir("outputs", "Li") is False

    def test_empty(self):
        assert _is_site_dir("", "Na") is False


class TestSiteComparisonRow:
    def test_serialize(self):
        row = SiteComparisonRow(
            rank=1,
            site_label="Li_2",
            final_energy_Ry=-398.35288,
            delta_E_meV_per_cell=0.0,
            relax_status="converged",
            max_force=0.0,
            nearest_M_X_ang=3.0,
            inner_X_X_ang=5.0,
            site_migrated=False,
            ph_gamma_status="unknown",
            recommendation="primary",
        )
        d = row.to_dict()
        assert d["rank"] == 1
        assert d["site_label"] == "Li_2"
        assert d["final_energy_Ry"] == -398.35288
        assert d["recommendation"] == "primary"


class TestSiteComparisonResult:
    def test_empty(self):
        r = SiteComparisonResult(reference_site="rx_2", sites=[])
        assert len(r.sites) == 0

    def test_single_site(self):
        row = SiteComparisonRow(
            rank=1, site_label="rx_2", final_energy_Ry=-398.35,
            delta_E_meV_per_cell=0.0, relax_status="converged",
            max_force=0.0, nearest_M_X_ang=3.0, inner_X_X_ang=5.0,
            site_migrated=False, ph_gamma_status="unknown",
            recommendation="primary",
        )
        r = SiteComparisonResult(reference_site="rx_2", sites=[row])
        assert r.sites[0].rank == 1


class TestDiscoverSiteDirs:
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as td:
            result = discover_site_dirs(Path(td), intercalant="Li")
            assert result == []

    def test_single_site(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "Li_2").mkdir()
            result = discover_site_dirs(Path(td), intercalant="Li")
            assert len(result) == 1


class TestFindVcRelaxOutput:
    def test_no_output(self):
        with tempfile.TemporaryDirectory() as td:
            assert find_vc_relax_output(Path(td)) is None

    def test_finds_rx_out(self):
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td) / "outputs"
            outdir.mkdir()
            (outdir / "rx.out").write_text("dummy content")
            assert find_vc_relax_output(Path(td)) is not None
