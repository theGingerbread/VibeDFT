"""Tests for QE NSCF cleaned-result contract."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from vibedft.calculator.qe.nscf import clean_nscf_output, clean_nscf_text, parse_nscf_output
from vibedft.calculator.qe.nscf.schemas import NSCF_TASK, NSCF_TASK_LEGACY


def _text_pass() -> str:
    return """Program PWSCF v.7.3 starts on 30Jun2026
&CONTROL
  calculation = 'nscf'
/
&SYSTEM
  ibrav = 0
/
     number of electrons =    8.000000
     number of Kohn-Sham states =    40
     number of k points =   64
iteration #  1     total energy              =    -184.77093016 Ry
estimated scf accuracy    <       1.0D-03 Ry
iteration #  2     total energy              =    -184.77123456 Ry
estimated scf accuracy    <       4.2D-10 Ry
the Fermi energy is    5.4321 eV
convergence has been achieved in   2 iterations
!    total energy              =    -184.77123456 Ry
PWSCF        :   0.42s CPU   0.55s WALL
JOB DONE.
"""


def _text_block() -> str:
    return """Program PWSCF v.7.3 starts on 30Jun2026
&CONTROL
  calculation = 'nscf'
/
&SYSTEM
  ibrav = 0
/
iteration #  1     total energy              =    -184.77093016 Ry
estimated scf accuracy    <       1.0D-03 Ry
"""


def test_clean_nscf_output_pass_structure() -> None:
    output = parse_nscf_output(_text_pass(), source="nscf.out")
    result = clean_nscf_output(output)

    assert result.calculator == "qe"
    assert result.task in {NSCF_TASK, NSCF_TASK_LEGACY}
    assert result.status == "pass"
    assert result.review is not None
    assert result.review.status == "PASS"
    assert result.outputs["job_done"] is True
    assert result.outputs["number_of_bands"] == 40
    assert result.observables["total_iterations"] == 2
    assert result.readiness.downstream["bands"].allowed is True
    assert result.readiness.downstream["phonon"].allowed is False


def test_clean_nscf_output_block_and_text_path(tmp_path: Path) -> None:
    output_path = tmp_path / "nscf.out"
    output_path.write_text(_text_block(), encoding="utf-8")

    result = clean_nscf_text(output_path)

    assert result.status == "block"
    assert result.source_files == ["nscf.out"]
    assert result.readiness.downstream["bands"].allowed is False
    assert result.review is not None
    assert result.review.status == "BLOCK"


def test_clean_nscf_output_is_json_serializable() -> None:
    output = parse_nscf_output(_text_pass(), source="nscf.out")
    result = clean_nscf_output(output)
    payload = json.dumps(asdict(result), allow_nan=False)

    data = json.loads(payload)
    assert data["calculator"] == "qe"
    assert data["outputs"]["job_done"] is True
    assert data["outputs"]["number_of_bands"] == 40
    assert data["review"]["status"] == "PASS"
    assert "bands" in data["readiness"]["downstream"]
