"""Tests for QE bands cleaned-result mapping."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from vibedft.calculator.qe.bands import clean_bands_output, clean_bands_text, parse_bands_output
from vibedft.calculator.qe.bands.schemas import BANDS_TASK, BANDS_TASK_LEGACY

ROOT = Path(__file__).resolve().parents[3]
BANDS_DATA = ROOT / "tests/fixtures/analyzer_smoke_test/output/HfI2.bands"


def _text_pass() -> str:
    return """Program PWSCF v.7.3 starts on 30Jul2026
 high-sym (G) (X) (M)
 the Fermi energy is   -1.2345 eV
JOB DONE.
"""


def _text_block() -> str:
    return """Program PWSCF v.7.3 starts on 30Jul2026
  number of k points = 5
"""


def test_clean_bands_output_pass_structure() -> None:
    output = parse_bands_output(
        _text_pass(),
        source="bands.out",
        data_file=BANDS_DATA,
    )
    result = clean_bands_output(output)

    assert result.calculator == "qe"
    assert result.task in {BANDS_TASK, BANDS_TASK_LEGACY}
    assert result.status == "pass"
    assert result.review is not None
    assert result.review.status == "PASS"
    assert result.outputs["job_done"] is True
    assert result.outputs["band_data_present"] is True
    assert result.outputs["band_count"] == 4
    assert result.outputs["k_point_count"] == 5
    assert result.observables["fermi_energy_ev"] == -1.2345
    assert result.readiness.downstream["analysis.bands"].allowed is True
    assert result.readiness.downstream["analysis.bandgap"].allowed is True
    assert result.readiness.downstream["phonon"].allowed is False


def test_clean_bands_output_block_and_json_serializable(tmp_path: Path) -> None:
    output_path = tmp_path / "bands.out"
    output_path.write_text(_text_block(), encoding="utf-8")

    result = clean_bands_text(output_path)

    assert result.status == "block"
    assert result.source_files == ["bands.out"]
    assert result.review is not None
    assert result.review.status == "BLOCK"

    payload = json.dumps(asdict(result), allow_nan=False)
    data = json.loads(payload)
    assert data["outputs"]["job_done"] is False
    assert data["review"]["status"] == "BLOCK"
    assert data["readiness"]["downstream"]["analysis.bands"]["allowed"] is False


def test_clean_bands_text_with_data_file_support(tmp_path: Path) -> None:
    output_path = tmp_path / "bands.out"
    output_path.write_text("Program PWSCF v.7.3 starts on 30Jul2026\nJOB DONE.\n", encoding="utf-8")

    result = clean_bands_text(output_path, data_file=BANDS_DATA)

    assert result.outputs["data_file"] is not None
    assert result.outputs["band_data_present"] is True
