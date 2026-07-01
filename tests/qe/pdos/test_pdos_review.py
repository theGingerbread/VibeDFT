"""Tests for QE PDOS review policy."""

from __future__ import annotations

from pathlib import Path

from vibedft.calculator.qe.pdos import parse_pdos_output
from vibedft.calculator.qe.pdos.schemas import PDOS_BASE_DOWNSTREAMS, PDOS_DOWNSTREAMS
from vibedft.calculator.qe.pdos.review import review_pdos_output


ROOT = Path(__file__).resolve().parents[3]
PDOS_FIXTURES = ROOT / "tests/fixtures/analyzer_smoke_test/output"

PDOS_1 = PDOS_FIXTURES / "HfI2.pdos_atm#1(Hf)_wfc#1(d)"
PDOS_2 = PDOS_FIXTURES / "HfI2.pdos_atm#2(Cl)_wfc#1(p)"


def _text_pass() -> str:
    return """Program PROJWFC v.7.3 starts on 30Jul2026
nspin = 2
the Fermi energy is   -1.2345 eV
JOB DONE.
"""


def _text_warn() -> str:
    return """Program PROJWFC v.7.3 starts on 30Jul2026
JOB DONE.
"""


def _text_block() -> str:
    return """Program PROJWFC v.7.3 starts on 30Jul2026
pdos file = HfI2.pdos_atm#1(Hf)_wfc#1(d)
"""


def _empty_pdos_file(path: Path) -> None:
    path.write_text("# empty placeholder\n", encoding="utf-8")


def test_review_pdos_output_pass_with_projection_files() -> None:
    output = parse_pdos_output(
        _text_pass(),
        source="pdos.out",
        pdos_files=[PDOS_1, PDOS_2],
    )
    result = review_pdos_output(output)

    assert result.status == "PASS"
    assert result.allowed_downstream == list(PDOS_BASE_DOWNSTREAMS)
    assert set(result.blocked_downstream) == set(PDOS_DOWNSTREAMS) - set(PDOS_BASE_DOWNSTREAMS)
    assert result.evidence
    assert any(ev.field in {"job_done", "projection_file_count", "energy_grid_count"} for ev in result.evidence)


def test_review_pdos_output_warn_when_projection_payload_incomplete(tmp_path: Path) -> None:
    empty = tmp_path / "sample.pdos_atm#1(Hf)_wfc#1(d)"
    _empty_pdos_file(empty)

    output = parse_pdos_output(
        _text_warn(),
        source="pdos.out",
        pdos_files=[empty],
    )
    result = review_pdos_output(output)

    assert result.status == "WARN"
    assert result.allowed_downstream == list(PDOS_BASE_DOWNSTREAMS)
    assert "projection" in " ".join(result.reasons).lower()
    assert "spin" in " ".join(result.reasons).lower()
    assert set(result.blocked_downstream) == set(PDOS_DOWNSTREAMS) - set(PDOS_BASE_DOWNSTREAMS)


def test_review_pdos_output_block_when_not_job_done() -> None:
    output = parse_pdos_output(
        _text_block(),
        source="pdos.out",
        pdos_files=[PDOS_1],
    )
    result = review_pdos_output(output)

    assert result.status == "BLOCK"
    assert not output.job_done
    assert not result.allowed_downstream
    assert set(result.blocked_downstream) == set(PDOS_DOWNSTREAMS)
