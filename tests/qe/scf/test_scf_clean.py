from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from vibedft.calculator.qe.scf import clean_scf_output, clean_scf_text, parse_scf_output


def _text_pass() -> str:
    return """Program PWSCF v.7.3 starts on 30Jun2026
     iteration #  1     total energy              =    -184.77093016 Ry
     estimated scf accuracy    <       1.0D-03 Ry
     iteration #  2     total energy              =    -184.77123456 Ry
     estimated scf accuracy    <       4.2E-10 Ry
     the Fermi energy is    5.4321 eV
     convergence has been achieved in   2 iterations
!    total energy              =    -184.77123456 Ry
     PWSCF        :   0.42s CPU   0.55s WALL
     JOB DONE.
"""


def _text_blocked() -> str:
    return """Program PWSCF v.7.3 starts on 30Jun2026
     iteration #  1     total energy              =    -10.10000000 Ry
     estimated scf accuracy    <       2.0E-02 Ry
     convergence NOT achieved after 100 iterations: stopping
"""


def test_clean_scf_output_pass_structure() -> None:
    output = parse_scf_output(_text_pass(), source="scf.out")
    result = clean_scf_output(output)

    assert result.calculator in {"qe", "quantum_espresso"}
    assert result.task in {"scf", "qe.scf"}
    assert result.status == "pass"
    assert result.provenance.calculator == "qe"
    assert result.outputs["program"] == "PWSCF"
    assert result.outputs["job_done"] is True
    assert result.outputs["converged"] is True
    assert "final_total_energy_ry" in result.outputs
    assert result.observables["total_iterations"] == 2
    assert result.diagnostics.errors == []


def test_clean_scf_output_block_and_text_path(tmp_path: Path) -> None:
    output_path = tmp_path / "scf.out"
    output_path.write_text(_text_blocked(), encoding="utf-8")

    result = clean_scf_text(output_path)

    assert result.status == "block"
    assert result.source_files == ["scf.out"]
    assert result.readiness["job_done"] is False
    assert result.readiness["converged"] is False


def test_clean_scf_output_is_json_serializable() -> None:
    output = parse_scf_output(_text_pass(), source="scf.out")
    result = clean_scf_output(output)
    payload = json.dumps(asdict(result), allow_nan=False)

    assert '"status": "pass"' in payload
    data = json.loads(payload)
    assert data["calculator"] == "qe"
    assert "outputs" in data
    assert data["outputs"]["final_total_energy_ry"] is not None
