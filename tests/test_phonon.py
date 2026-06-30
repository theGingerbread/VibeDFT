"""Tests for phonon analysis."""

import math
from pathlib import Path

from vibedft.core.phonon import (
    parse_freq_gp,
    qa_phonon_frequencies,
    PhononDispersion,
    PhononQaResult,
)

SAMPLE_FREQ_GP = """\
   0.0000   0.0000  12.3456  25.6789  45.1234
   0.1000  -0.5000  12.4000  25.7000  45.2000
   0.2000   0.0000  12.5000  25.8000  45.3000
   0.3000   1.2000  12.6000  25.9000  45.4000
"""

SAMPLE_WITH_IMAGINARY = """\
   0.0000  -2.0000  12.3456  25.6789  45.1234
   0.1000  -8.0000  12.4000  25.7000  45.2000
   0.2000   0.0000  12.5000  25.8000  45.3000
"""


# ── freq.gp parser ──


def test_parse_freq_gp(tmp_path: Path):
    f = tmp_path / "test.freq.gp"
    f.write_text(SAMPLE_FREQ_GP)

    disp = parse_freq_gp(f)
    assert disp.has_data
    assert disp.n_qpoints == 4
    assert disp.n_branches == 4
    assert len(disp.frequencies) == 4
    assert len(disp.frequencies[0]) == 4


def test_parse_freq_gp_imaginary_modes(tmp_path: Path):
    f = tmp_path / "test.freq.gp"
    f.write_text(SAMPLE_FREQ_GP)

    disp = parse_freq_gp(f)
    # One imaginary mode at q_idx=1, branch=1: -0.5 cm⁻¹
    assert disp.n_imaginary == 1
    assert disp.imaginary_modes[0]["freq_cm1"] == -0.5
    assert disp.imaginary_modes[0]["q_index"] == 1


def test_parse_freq_gp_missing_file(tmp_path: Path):
    disp = parse_freq_gp(tmp_path / "nonexistent")
    assert not disp.has_data
    assert disp.n_qpoints == 0


# ── Virtual-frequency QA ──


def test_qa_clean_dispersion_passes(tmp_path: Path):
    """All frequencies positive → pass."""
    f = tmp_path / "clean.freq.gp"
    f.write_text("""\
   0.0  10.0  20.0  30.0
   0.5  11.0  21.0  31.0
""")

    disp = parse_freq_gp(f)
    qa = qa_phonon_frequencies(disp)
    assert qa.status == "pass"


def test_qa_small_gamma_imaginary_warns(tmp_path: Path):
    """Small Γ-point imaginary mode → warn."""
    f = tmp_path / "small.freq.gp"
    f.write_text(SAMPLE_WITH_IMAGINARY)

    disp = parse_freq_gp(f)
    # q=0: -2.0 cm⁻¹ (small, at Γ) → warn
    # q=1: -8.0 cm⁻¹ (non-Γ, large) → fail
    qa = qa_phonon_frequencies(disp)
    assert qa.status == "fail"  # because of the non-Γ -8.0 mode
    assert any(c["status"] == "fail" for c in qa.checks)


def test_qa_non_gamma_imaginary_fails(tmp_path: Path):
    """Imaginary mode at non-Γ q-point → fail."""
    f = tmp_path / "bad.freq.gp"
    f.write_text("""\
   0.0   5.0  10.0  15.0
   0.5  -3.0  10.0  15.0
""")

    disp = parse_freq_gp(f)
    qa = qa_phonon_frequencies(disp)
    assert qa.status == "fail"


def test_phonon_dispersion_summary():
    disp = PhononDispersion(
        n_qpoints=4, n_branches=3,
        min_frequency_cm1=-2.0, max_frequency_cm1=300.0,
        imaginary_modes=[{"q_index": 0, "branch": 1, "freq_cm1": -2.0}],
        has_data=True,
    )
    summary = disp.summary()
    assert "4 q-points" in summary
    assert "Imaginary" in summary
