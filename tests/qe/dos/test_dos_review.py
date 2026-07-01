"""Tests for QE DOS review policy."""

from __future__ import annotations

from pathlib import Path

from vibedft.calculator.qe.dos import parse_dos_output
from vibedft.calculator.qe.dos.schemas import DOS_BASE_DOWNSTREAMS, DOS_DOWNSTREAMS
from vibedft.calculator.qe.dos.review import review_dos_output


ROOT = Path(__file__).resolve().parents[3]
DOS_DATA = ROOT / "tests/fixtures/analyzer_smoke_test/output/HfI2.dos"


def _text_pass() -> str:
    return """Program DOS v.7.2 starts on 30Jul2026
  Emin = -10.0 Emax = 10.0 0.01
  the Fermi energy is   -1.2345 eV
JOB DONE.
"""


def _text_warn() -> str:
    return """Program DOS v.7.2 starts on 30Jul2026
  the Fermi energy is   -1.2345 eV
JOB DONE.
"""


def _text_block() -> str:
    return """Program DOS v.7.2 starts on 30Jul2026
  the Fermi energy is   -1.2345 eV
"""


def test_review_dos_output_pass_with_data_file() -> None:
    output = parse_dos_output(_text_pass(), source="dos.out", data_file=DOS_DATA)
    result = review_dos_output(output)

    assert result.status == "PASS"
    assert result.allowed_downstream == list(DOS_BASE_DOWNSTREAMS)
    assert set(result.blocked_downstream) == set(DOS_DOWNSTREAMS) - set(DOS_BASE_DOWNSTREAMS)
    assert result.reasons == []
    assert any(ev.field == "energy_grid_count" and ev.value == 16 for ev in result.evidence)


def test_review_dos_output_warn_when_grid_and_range_missing() -> None:
    output = parse_dos_output(_text_warn(), source="dos.out", data_file=None)
    result = review_dos_output(output)

    assert result.status == "WARN"
    assert result.allowed_downstream == list(DOS_BASE_DOWNSTREAMS)
    assert "energy range metadata" in " ".join(result.reasons)
    assert "data file" in " ".join(result.reasons).lower()
    assert set(result.blocked_downstream) == set(DOS_DOWNSTREAMS) - set(DOS_BASE_DOWNSTREAMS)


def test_review_dos_output_block_when_not_job_done() -> None:
    output = parse_dos_output(_text_block(), source="dos.out", data_file=None)
    result = review_dos_output(output)

    assert result.status == "BLOCK"
    assert not output.job_done
    assert not result.allowed_downstream
    assert set(result.blocked_downstream) == set(DOS_DOWNSTREAMS)
