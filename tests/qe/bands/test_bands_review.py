"""Tests for QE bands review policy."""

from __future__ import annotations

from pathlib import Path

from vibedft.calculator.qe.bands import parse_bands_output
from vibedft.calculator.qe.bands.schemas import BANDS_BASE_DOWNSTREAMS, BANDS_DOWNSTREAMS
from vibedft.calculator.qe.bands.review import review_bands_output

ROOT = Path(__file__).resolve().parents[3]
BANDS_DATA = ROOT / "tests/fixtures/analyzer_smoke_test/output/HfI2.bands"


def _text_pass() -> str:
    return """Program PWSCF v.7.3 starts on 30Jul2026
 high-sym (G) (X) (M)
 the Fermi energy is   -1.2345 eV
JOB DONE.
"""


def _text_warn() -> str:
    return """Program PWSCF v.7.3 starts on 30Jul2026
JOB DONE.
"""


def _text_block() -> str:
    return """Program PWSCF v.7.3 starts on 30Jul2026
  number of k points = 5
"""


def test_review_bands_output_pass() -> None:
    output = parse_bands_output(
        _text_pass(),
        source="bands.out",
        data_file=BANDS_DATA,
    )
    result = review_bands_output(output)

    assert result.status == "PASS"
    assert result.allowed_downstream == list(BANDS_BASE_DOWNSTREAMS)
    assert set(result.blocked_downstream) == set(BANDS_DOWNSTREAMS) - set(BANDS_BASE_DOWNSTREAMS)
    assert result.reasons == []
    assert any(ev.field == "band_data_present" and ev.value is True for ev in result.evidence)
    assert result.evidence


def test_review_bands_output_warn_when_reference_and_labels_missing() -> None:
    output = parse_bands_output(
        _text_warn(),
        source="bands.out",
        data_file=BANDS_DATA,
    )
    result = review_bands_output(output)

    assert result.status == "WARN"
    assert result.allowed_downstream == list(BANDS_BASE_DOWNSTREAMS)
    assert "Energy reference is not available" in " ".join(result.reasons)
    assert "high-symmetry labels" in " ".join(result.reasons)
    assert set(result.blocked_downstream) == set(BANDS_DOWNSTREAMS) - set(BANDS_BASE_DOWNSTREAMS)


def test_review_bands_output_block_when_not_job_done() -> None:
    output = parse_bands_output(
        _text_block(),
        source="bands.out",
    )
    result = review_bands_output(output)

    assert result.status == "BLOCK"
    assert not result.allowed_downstream
    assert set(result.blocked_downstream) == set(BANDS_DOWNSTREAMS)
