from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from vibedft.calculator.qe.relax import clean_relax_output, clean_relax_text, parse_relax_output
from vibedft.calculator.qe.relax.schemas import RELAX_TASK, RELAX_TASK_LEGACY


def _text_pass() -> str:
    return """Program PWSCF v.7.4 starts

&CONTROL
  calculation = 'relax'
/
&SYSTEM
  ibrav = 0
  nat = 2
  ntyp = 1
  ecutwfc = 40
  ecutrho = 400
/
&IONS
  ion_dynamics = 'bfgs'
  forc_conv_thr = 1.0D-4
/
 Self-consistent Calculation
iteration #  1     total energy              =    -10.00000000 Ry
estimated scf accuracy    <       1.0D-04 Ry
convergence has been achieved in   1 iterations
Forces acting on atoms (cartesian axes, Ry/au):
 atom    1 type  1   force =     0.000020   0.000000   0.000000
 atom    2 type  1   force =    -0.000020   0.000000  -0.000000
 total force   3.0E-05
     total   stress  (Ry/bohr**3)                   (kbar)     P=      5.0
  0.10  0.00  0.00   1.00  2.00  3.00
  0.00  0.10  0.00   4.00  5.00  6.00
  0.00  0.00  0.10   7.00  8.00  9.00
BFGS Geometry Optimization
ATOMIC_POSITIONS (angstrom)
Na  0.000000  0.000000  0.000000
Cl  0.500000  0.500000  0.500000
CELL_PARAMETERS (angstrom)
3.000000 0.000000 0.000000
0.000000 3.000000 0.000000
0.000000 0.000000 3.000000
JOB DONE.
"""


def _text_block() -> str:
    return """Program PWSCF v.7.4 starts

&CONTROL
  calculation = 'relax'
/
&SYSTEM
  ibrav = 0
  nat = 2
  ntyp = 1
/
&IONS
  ion_dynamics = 'bfgs'
  forc_conv_thr = 1.0D-4
/
 Self-consistent Calculation
iteration #  1     total energy              =    -10.00000000 Ry
estimated scf accuracy    <       1.0D-03 Ry
convergence NOT achieved after 100 iterations
"""


def test_clean_relax_output_pass_structure() -> None:
    output = parse_relax_output(_text_pass(), source="relax.out")
    result = clean_relax_output(output)

    assert result.calculator == "qe"
    assert result.task in {RELAX_TASK, RELAX_TASK_LEGACY}
    assert result.status == "pass"
    assert result.review is not None
    assert result.review.status == "PASS"
    assert result.outputs["job_done"] is True
    assert result.observables["max_force"] == 2e-05
    assert result.observables["rms_force"] == 2e-05
    assert result.readiness.downstream["scf"].allowed is True
    assert result.readiness.downstream["phonon"].allowed is False
    assert result.provenance.calculator == "qe"


def test_clean_relax_output_block() -> None:
    output = parse_relax_output(_text_block(), source="relax_block.out")
    result = clean_relax_output(output)

    assert result.status == "block"
    assert result.review is not None
    assert result.review.status == "BLOCK"
    assert result.readiness.downstream["scf"].allowed is False
    assert result.source_files == ["relax_block.out"]


def test_clean_relax_text_and_json_contract() -> None:
    output_path = Path("relax.out")
    output_path.write_text(_text_pass(), encoding="utf-8")

    result = clean_relax_text(output_path)
    payload = json.dumps(asdict(result), allow_nan=False)

    assert result.status == "pass"
    data = json.loads(payload)
    assert data["outputs"]["job_done"] is True
    assert data["review"]["status"] == "PASS"
    assert "scf" in data["readiness"]["downstream"]
    assert data["readiness"]["downstream"]["scf"]["allowed"] is True
