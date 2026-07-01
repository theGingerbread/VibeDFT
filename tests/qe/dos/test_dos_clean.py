"""Tests for QE DOS cleaned-result mapping."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from vibedft.calculator.qe.dos import clean_dos_output, clean_dos_text, parse_dos_output
from vibedft.calculator.qe.dos.schemas import DOS_TASK, DOS_TASK_LEGACY


def _text_pass() -> str:
    return """Program DOS v.7.2 starts on 30Jul2026
  Emin = -10.0 Emax = 10.0 0.01
  the Fermi energy is   -1.2345 eV
JOB DONE.
"""


def _text_block() -> str:
    return """Program DOS v.7.2 starts on 30Jul2026
  the Fermi energy is   -1.2345 eV
"""


def _write_minimal_dos_file(path: Path) -> None:
    path.write_text(
        """#  E (eV)   dos(E)     Int dos(E)  Fermi = -1.2345 eV
 -10.000  2.000000E-01  2.000000E-02
  -9.000  2.222222E-01  2.222222E-02
   0.000  1.000000E+00  1.000000E-01
""",
        encoding="utf-8",
    )


def test_clean_dos_output_pass_structure(tmp_path: Path) -> None:
    data_path = tmp_path / "tmp_dos_data.dos"
    _write_minimal_dos_file(data_path)

    output = parse_dos_output(_text_pass(), source=tmp_path / "dos.out", data_file=data_path)
    result = clean_dos_output(output)

    assert result.calculator == "qe"
    assert result.task in {DOS_TASK, DOS_TASK_LEGACY}
    assert result.status == "pass"
    assert result.review is not None
    assert result.review.status == "PASS"
    assert result.outputs["job_done"] is True
    assert result.outputs["integrated_dos_present"] is True
    assert result.readiness.downstream["analysis.dos"].allowed is True
    assert result.readiness.downstream["bands"].allowed is False
    assert result.readiness.summary is not None


def test_clean_dos_output_block_and_json_serializable(tmp_path: Path) -> None:
    data_path = tmp_path / "dos_data.dos"
    _write_minimal_dos_file(data_path)
    output_path = tmp_path / "dos.out"
    output_path.write_text(_text_block(), encoding="utf-8")

    result = clean_dos_text(output_path, data_file=data_path)
    payload = json.dumps(asdict(result), allow_nan=False)
    data = json.loads(payload)

    assert result.status == "block"
    assert result.review is not None
    assert result.review.status == "BLOCK"
    assert result.source_files == ["dos.out"]
    assert result.source_artifacts == ["dos.out"]
    assert data["task"] in {DOS_TASK, DOS_TASK_LEGACY}
    assert data["status"] == "block"
    assert "readiness" in data and "downstream" in data["readiness"]
