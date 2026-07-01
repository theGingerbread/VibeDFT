"""Tests for QE PDOS cleaned-result mapping."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from vibedft.calculator.qe.pdos import clean_pdos_output, clean_pdos_text, parse_pdos_output
from vibedft.calculator.qe.pdos.schemas import PDOS_TASK, PDOS_TASK_LEGACY


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


def _text_block() -> str:
    return """Program PROJWFC v.7.3 starts on 30Jul2026
"""


def test_clean_pdos_output_pass_structure() -> None:
    output = parse_pdos_output(
        _text_pass(),
        source="pdos.out",
        pdos_files=[PDOS_1, PDOS_2],
    )
    result = clean_pdos_output(output)

    assert result.calculator == "qe"
    assert result.task in {PDOS_TASK, PDOS_TASK_LEGACY}
    assert result.status == "pass"
    assert result.review is not None
    assert result.review.status == "PASS"
    assert result.outputs["job_done"] is True
    assert result.outputs["projection_file_count"] >= 2
    assert result.outputs["pdos_total_present"] is True
    assert result.observables["spin_channels"] == 2
    assert result.readiness.downstream["analysis.pdos"].allowed is True
    assert result.readiness.downstream["dos"].allowed is False


def test_clean_pdos_output_block_and_json_serializable(tmp_path: Path) -> None:
    output_path = tmp_path / "pdos.out"
    output_path.write_text(_text_block(), encoding="utf-8")

    result = clean_pdos_text(output_path, pdos_files=[PDOS_1])

    payload = json.dumps(asdict(result), allow_nan=False)
    data = json.loads(payload)

    assert result.status == "block"
    assert result.source_files == ["pdos.out"]
    assert result.review is not None
    assert result.review.status == "BLOCK"
    assert data["readiness"]["downstream"]["analysis.pdos"]["allowed"] is False
    assert data["task"] in {PDOS_TASK, PDOS_TASK_LEGACY}
