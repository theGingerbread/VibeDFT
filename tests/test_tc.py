"""Tests for TC / EPC analysis."""

import math
from pathlib import Path

from vibedft.core.tc import (
    analyze_superconductivity_reliability,
    parse_lambdax_output,
    parse_alpha2f_dat,
    parse_lambda_dat,
    compute_tc_overlap,
    get_lambda_max,
    get_tc_at_lambda_max,
    LambdaOutput,
    TcOverlapResult,
    _linear_interpolate,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# Sample lambda.x output
SAMPLE_LAMBDAX_A = """\
     lambda.x output
     mu* = 0.10

     lambda  omega_log  T_c
     degauss       lambda      omega_log        T_c
       0.0020      1.4500       115.000        12.500  N(Ef)=  2.350
       0.0040      1.4200       114.500        12.100  N(Ef)=  2.350
       0.0060      1.3800       114.000        11.600  N(Ef)=  2.350
       0.0080      1.3400       113.500        11.200  N(Ef)=  2.350
       0.0100      1.3000       113.000        10.800  N(Ef)=  2.350
       0.0150      1.2000       112.000         9.800  N(Ef)=  2.350
       0.0200      1.1000       111.000         8.900  N(Ef)=  2.350
"""

SAMPLE_LAMBDAX_B = """\
     lambda.x output
     mu* = 0.10

     lambda  omega_log  T_c
     degauss       lambda      omega_log        T_c
       0.0020      1.4400       115.500        12.400  N(Ef)=  2.330
       0.0040      1.4100       114.800        12.000  N(Ef)=  2.330
       0.0060      1.3750       114.200        11.550  N(Ef)=  2.330
       0.0080      1.3350       113.600        11.180  N(Ef)=  2.330
       0.0100      1.2980       113.100        10.780  N(Ef)=  2.330
       0.0150      1.1980       112.100         9.780  N(Ef)=  2.330
       0.0200      1.0980       111.100         8.880  N(Ef)=  2.330
"""

SAMPLE_WITH_NAN = """\
     lambda.x output

     lambda  omega_log  T_c
     degauss       lambda      omega_log        T_c
       0.0020      1.4500       115.000        12.500
       0.0040         NaN          NaN           NaN
       0.0060      1.3800       114.000        11.600
"""

SAMPLE_ALPHA2F = """\
# omega(cm-1) alpha2F
0.0 0.000
10.0 0.050
20.0 0.100
"""

SAMPLE_LAMBDA_DAT = """\
# omega(cm-1) cumulative_lambda
0.0 0.00
10.0 0.40
20.0 1.25
"""

STABLE_FREQ_GP = """\
0.0  10.0  20.0
0.5  12.0  22.0
"""

NEGATIVE_FREQ_GP = """\
0.0  10.0  20.0
0.5  -8.0  22.0
"""


# ── Parser ──


def test_parse_lambdax_output(tmp_path: Path):
    f = tmp_path / "lambdax.out"
    f.write_text(SAMPLE_LAMBDAX_A)

    data = parse_lambdax_output(f)
    assert data.has_data
    assert data.n_rows == 7
    assert abs(data.mustar - 0.10) < 0.01
    assert len(data.degauss_values) == 7
    assert abs(data.lambda_values[0] - 1.45) < 0.01
    assert abs(data.tc_values[0] - 12.5) < 0.1
    assert abs(data.omega_log_values[0] - 115.0) < 0.1
    assert abs(data.nef_values[0] - 2.35) < 0.01


def test_parse_lambdax_missing_file(tmp_path: Path):
    data = parse_lambdax_output(tmp_path / "nonexistent")
    assert not data.has_data
    assert data.n_rows == 0


def test_parse_lambdax_with_nan(tmp_path: Path):
    f = tmp_path / "lambdax.out"
    f.write_text(SAMPLE_WITH_NAN)

    data = parse_lambdax_output(f)
    assert data.n_rows == 3
    assert len(data.nan_rows) == 1
    assert math.isnan(data.lambda_values[1])


def test_parse_lambdax_compact_three_column_table_without_degauss(tmp_path: Path):
    f = tmp_path / "lambdax.out"
    f.write_text(
        "     lambda        omega_log          T_c\n"
        "     0.73          120.0              5.4\n",
        encoding="utf-8",
    )

    data = parse_lambdax_output(f)

    assert data.has_data
    assert data.n_rows == 1
    assert data.degauss_values == [0.0]
    assert data.lambda_values == [0.73]
    assert data.omega_log_values == [120.0]
    assert data.tc_values == [5.4]


def test_parse_alpha2f_dat_summary(tmp_path: Path):
    f = tmp_path / "alpha2F.dat"
    f.write_text(SAMPLE_ALPHA2F)

    data = parse_alpha2f_dat(f)
    assert data.has_data
    assert data.n_points == 3
    assert data.omega_min_cm1 == 0.0
    assert data.omega_max_cm1 == 20.0
    assert abs(data.alpha2f_max - 0.1) < 1e-12


def test_parse_lambda_dat_cumulative(tmp_path: Path):
    f = tmp_path / "lambda.dat"
    f.write_text(SAMPLE_LAMBDA_DAT)

    data = parse_lambda_dat(f)
    assert data.has_data
    assert data.n_points == 3
    assert abs(data.lambda_final - 1.25) < 1e-12


def test_superconductivity_reliability_blocks_negative_phonon(tmp_path: Path):
    lambdax = tmp_path / "lambdax.out"
    freq = tmp_path / "freq.gp"
    lambdax.write_text(SAMPLE_LAMBDAX_A)
    freq.write_text(NEGATIVE_FREQ_GP)

    result = analyze_superconductivity_reliability(
        lambdax,
        phonon_freq_path=freq,
    )

    assert result.status == "blocked"
    assert any("negative phonon" in blocker for blocker in result.blockers)
    assert {e.parser_name for e in result.evidence} == {
        "vibedft.core.tc.parse_lambdax_output",
        "vibedft.core.phonon.parse_freq_gp",
    }
    assert any(d.name == "superconductivity_reliability" for d in result.descriptors)


def test_superconductivity_reliability_blocks_nan_tc(tmp_path: Path):
    lambdax = tmp_path / "lambdax.out"
    lambdax.write_text(SAMPLE_WITH_NAN)

    result = analyze_superconductivity_reliability(lambdax)

    assert result.status == "blocked"
    assert any("non-finite" in blocker for blocker in result.blockers)
    assert result.reliability == "low"


def test_superconductivity_reliability_medium_without_epw_high(tmp_path: Path):
    lambdax = tmp_path / "lambdax.out"
    freq = tmp_path / "freq.gp"
    alpha2f = tmp_path / "alpha2F.dat"
    lambda_dat = tmp_path / "lambda.dat"
    lambdax.write_text(SAMPLE_LAMBDAX_A)
    freq.write_text(STABLE_FREQ_GP)
    alpha2f.write_text(SAMPLE_ALPHA2F)
    lambda_dat.write_text(SAMPLE_LAMBDA_DAT)

    result = analyze_superconductivity_reliability(
        lambdax,
        phonon_freq_path=freq,
        alpha2f_path=alpha2f,
        lambda_dat_path=lambda_dat,
    )

    assert result.status == "pass"
    assert result.reliability == "medium"
    descriptors = {d.name: d.value for d in result.descriptors}
    assert descriptors["superconductivity_reliability"] == "medium"
    assert descriptors["superconductivity_summary"]["lambda_max"] == 1.45
    assert descriptors["superconductivity_summary"]["has_epw"] is False
    assert set(descriptors["mustar_sensitivity"]) == {"0.08", "0.10", "0.15"}


def test_superconductivity_reliability_missing_lambdax_insufficient(tmp_path: Path):
    result = analyze_superconductivity_reliability(tmp_path / "missing_lambdax.out")

    assert result.status == "insufficient_evidence"
    assert result.reliability == "low"
    assert any("lambda.x" in blocker for blocker in result.blockers)


def test_lambda_max_and_tc():
    data = LambdaOutput(
        degauss_values=[0.002, 0.004, 0.006],
        lambda_values=[1.45, 1.42, 1.38],
        tc_values=[12.5, 12.1, 11.6],
        omega_log_values=[115.0, 114.5, 114.0],
        n_rows=3,
    )
    assert abs(get_lambda_max(data) - 1.45) < 0.01
    assert abs(get_tc_at_lambda_max(data) - 12.5) < 0.1


# ── Interpolation ──


def test_linear_interpolate():
    x_src = [0.0, 1.0, 2.0]
    y_src = [10.0, 20.0, 30.0]
    x_target = [0.0, 0.5, 1.0, 1.5, 2.0]

    result = _linear_interpolate(x_target, x_src, y_src)
    assert abs(result[0] - 10.0) < 0.01
    assert abs(result[1] - 15.0) < 0.01
    assert abs(result[2] - 20.0) < 0.01
    assert abs(result[3] - 25.0) < 0.01
    assert abs(result[4] - 30.0) < 0.01


# ── Tc overlap ──


def test_tc_overlap_with_similar_grids(tmp_path: Path):
    fa = tmp_path / "ph64.out"
    fb = tmp_path / "ph96.out"
    fa.write_text(SAMPLE_LAMBDAX_A)
    fb.write_text(SAMPLE_LAMBDAX_B)

    result = compute_tc_overlap(fa, fb, label_a="ph64", label_b="ph96", rel_tol_pct=2.0)

    # With 2% tolerance, these very similar curves should overlap
    assert result.overlap_status == "pass"
    assert result.tc_point_k is not None
    assert result.tc_point_k > 0
    assert result.relative_deviation_pct is not None


def test_tc_overlap_no_files(tmp_path: Path):
    result = compute_tc_overlap(
        tmp_path / "a.out", tmp_path / "b.out",
    )
    assert result.overlap_status == "no_data"


def test_tc_overlap_single_point_fails(tmp_path: Path):
    """A single overlap point must not pass (needs ≥3 consecutive)."""
    fa = tmp_path / "a.out"
    fb = tmp_path / "b.out"
    # Only 3 data points with only 1 overlapping (rel_tol is strict → only exact match at index 1)
    fa.write_text("lambda  omega_log  T_c\n"
                  "  0.002  1.45  115.0  12.5\n"
                  "  0.004  1.42  114.5  12.1\n"
                  "  0.006  1.38  114.0  11.6\n")
    fb.write_text("lambda  omega_log  T_c\n"
                  "  0.002  1.45  115.0  20.0\n"   # big diff → not overlap
                  "  0.004  1.42  114.5  12.1\n"   # exact match → overlap (just 1 consecutive)
                  "  0.006  1.38  114.0  20.0\n")  # big diff → not overlap

    result = compute_tc_overlap(fa, fb, label_a="a", label_b="b", rel_tol_pct=1.0)
    assert result.overlap_status == "fail", f"Expected fail, got {result.overlap_status}: {result.message}"


def test_tc_overlap_two_points_fails(tmp_path: Path):
    """Two consecutive overlap points must not pass (needs ≥3)."""
    fa = tmp_path / "a.out"
    fb = tmp_path / "b.out"
    fa.write_text("lambda  omega_log  T_c\n"
                  "  0.002  1.45  115.0  12.5\n"
                  "  0.004  1.42  114.5  12.1\n"
                  "  0.006  1.38  114.0  11.6\n"
                  "  0.008  1.34  113.5  11.2\n")
    fb.write_text("lambda  omega_log  T_c\n"
                  "  0.002  1.45  115.0  20.0\n"   # no overlap
                  "  0.004  1.42  114.5  12.1\n"   # overlap (1)
                  "  0.006  1.38  114.0  11.6\n"   # overlap (2)
                  "  0.008  1.34  113.5  20.0\n")  # no overlap

    result = compute_tc_overlap(fa, fb, label_a="a", label_b="b", rel_tol_pct=0.5)
    assert result.overlap_status == "fail", f"Expected fail for 2-point overlap, got {result.overlap_status}"


def test_tc_overlap_discontinuous_segments_uses_longest(tmp_path: Path):
    """Two disjoint segments (3 pts + 4 pts, gap between) → should pick the 4-pt one."""
    fa = tmp_path / "a.out"
    fb = tmp_path / "b.out"
    # seg1: degauss 0.002–0.006 (3 pts), then gap at 0.008, then seg2: 0.010–0.016 (4 pts)
    fa.write_text("lambda  omega_log  T_c\n"
                  "  0.002  1.45  115.0  12.5\n"
                  "  0.004  1.42  114.5  12.1\n"
                  "  0.006  1.38  114.0  11.6\n"   # seg1 (3 pts, start=0.002, end=0.006)
                  "  0.008  1.34  113.5  10.0\n"    # GAP
                  "  0.010  1.30  113.0  10.8\n"
                  "  0.012  1.26  112.5  10.5\n"
                  "  0.014  1.22  112.0  10.2\n"
                  "  0.016  1.18  111.5   9.9\n")   # seg2 (4 pts, start=0.010, end=0.016)
    fb.write_text("lambda  omega_log  T_c\n"
                  "  0.002  1.45  115.0  12.4\n"
                  "  0.004  1.41  114.8  12.0\n"
                  "  0.006  1.38  114.2  11.5\n"   # seg1 (matched)
                  "  0.008  1.34  113.6  20.0\n"    # GAP
                  "  0.010  1.30  113.1  10.7\n"
                  "  0.012  1.26  112.6  10.4\n"
                  "  0.014  1.22  112.1  10.1\n"
                  "  0.016  1.18  111.6   9.8\n")   # seg2 (matched)

    result = compute_tc_overlap(fa, fb, label_a="a", label_b="b", rel_tol_pct=2.0)
    assert result.overlap_status == "pass", f"Expected pass, got {result.overlap_status}: {result.message}"
    assert result.tc_point_k is not None
    # The longest segment (seg2) spans 0.010–0.016 Ry
    assert result.overlap_start_degauss is not None
    assert result.overlap_end_degauss is not None
    assert abs(result.overlap_start_degauss - 0.010) < 0.001, (
        f"Expected overlap_start=0.010 (longest segment), got {result.overlap_start_degauss}"
    )
    assert abs(result.overlap_end_degauss - 0.016) < 0.001, (
        f"Expected overlap_end=0.016 (longest segment), got {result.overlap_end_degauss}"
    )


def test_tc_overlap_nan_handling(tmp_path: Path):
    fa = tmp_path / "a.out"
    fb = tmp_path / "b.out"
    fa.write_text(SAMPLE_WITH_NAN)
    fb.write_text(SAMPLE_LAMBDAX_A)

    result = compute_tc_overlap(fa, fb, label_a="nan_grid", label_b="clean")
    # Should warn about NaN but still try to compute overlap
    assert "nan" in result.overlap_status.lower() or result.overlap_status in ("pass", "fail")
