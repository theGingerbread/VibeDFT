"""Tests for EPW Refinement Layer (Sprint 14)."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "epw"


def test_parse_epw_input():
    """Parse EPW input file — extract k/q mesh and Wannier params."""
    from vibedft.epw.input_parser import parse_epw_input
    inp = parse_epw_input(FIXTURES / "epw.in")
    assert inp is not None
    assert inp.nk1 == 6
    assert inp.nq1 == 6
    assert inp.elph is True
    assert inp.wannierize is True
    assert inp.num_wann == 9
    assert inp.muc == 0.1


def test_parse_epw_output():
    """Parse EPW output — extract λ, ωlog, Tc, spreads."""
    from vibedft.epw.output_parser import parse_epw_output
    result = parse_epw_output(FIXTURES / "epw.out")
    assert result is not None
    assert result.has_data
    assert result.lambda_max is not None
    assert abs(result.lambda_max - 1.35) < 0.1
    assert result.tc_max_K is not None
    assert abs(result.tc_max_K - 8.5) < 0.5
    assert result.wannier_num_bands == 3


def test_wannier_quality_good():
    """Good Wannier spreads should assess as good/acceptable."""
    from vibedft.epw.output_parser import EpwResult
    from vibedft.epw.wannier_quality import check_wannier_quality

    epw = EpwResult(has_data=True, wannier_spreads=[1.2, 1.5, 2.3],
                    wannier_max_spread=2.3, wannier_total_spread=5.0,
                    wannier_num_bands=3)
    q = check_wannier_quality(epw)
    assert q["status"] in ("good", "acceptable")


def test_compare_qe_vs_epw():
    """QE vs EPW comparison with close values should agree."""
    from vibedft.epw.output_parser import EpwResult
    from vibedft.epw.epc_analyzer import compare_qe_vs_epw

    epw = EpwResult(has_data=True, lambda_max=1.35, tc_max_K=8.5, omega_log_K=180.0)
    comp = compare_qe_vs_epw(qe_lambda=1.30, qe_tc_K=8.2, qe_omega_log_K=178.0, epw_result=epw)
    assert comp["status"] == "compared"
    assert comp["agreement"] in ("good", "acceptable")


def test_compare_qe_vs_epw_disagree():
    """Large discrepancy should flag disagreement."""
    from vibedft.epw.output_parser import EpwResult
    from vibedft.epw.epc_analyzer import compare_qe_vs_epw

    epw = EpwResult(has_data=True, lambda_max=0.5, tc_max_K=2.0, omega_log_K=100.0)
    comp = compare_qe_vs_epw(qe_lambda=1.3, qe_tc_K=8.0, qe_omega_log_K=180.0, epw_result=epw)
    assert comp["agreement"] == "disagree"


def test_epw_inspect_fixture():
    """vibedft inspect should handle EPW files."""
    import subprocess, sys, os, json
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    r = subprocess.run(
        [sys.executable, "-m", "vibedft", "inspect",
         str(FIXTURES / "epw.in"), str(FIXTURES / "epw.out"), "--json"],
        cwd=PROJECT_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert len(data["files"]) == 2


def test_epw_missing_does_not_break_qe_path():
    """When no EPW files exist, QE-native workflow should work normally."""
    from vibedft.epw.output_parser import parse_epw_output
    result = parse_epw_output("/nonexistent/epw.out")
    assert result is None
