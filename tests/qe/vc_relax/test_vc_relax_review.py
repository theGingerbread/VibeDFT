from __future__ import annotations

from vibedft.calculator.qe.relax.parse import parse_relax_output
from vibedft.calculator.qe.vc_relax import parse_vc_relax_output
from vibedft.calculator.qe.vc_relax.review import review_vc_relax_output
from vibedft.calculator.qe.vc_relax.schemas import VC_RELAX_BASE_DOWNSTREAMS, VC_RELAX_DOWNSTREAMS


def _vc_pass_text() -> str:
    return """Program PWSCF v.7.4 starts

&CONTROL
  calculation = 'vc-relax'
/
&SYSTEM
  ibrav = 0
  nat = 1
  ntyp = 1
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
 total force   3.0E-05
     total   stress  (Ry/bohr**3)                   (kbar)     P=      5.0
  0.10  0.00  0.00   1.00  2.00  3.00
  0.00  0.10  0.00   4.00  5.00  6.00
  0.00  0.00  0.10   7.00  8.00  9.00
BFGS Geometry Optimization
ATOMIC_POSITIONS (angstrom)
Na  0.000000  0.000000  0.000000
CELL_PARAMETERS (angstrom)
3.000000 0.000000 0.000000
0.000000 3.000000 0.000000
0.000000 0.000000 3.000000
JOB DONE.
"""


def _vc_warn_pressure_text() -> str:
    return """Program PWSCF v.7.4 starts

&CONTROL
  calculation = 'vc-relax'
/
&SYSTEM
  ibrav = 0
  nat = 1
  ntyp = 1
/
&IONS
  ion_dynamics = 'bfgs'
  forc_conv_thr = 1.0D-4
/
 Self-consistent Calculation
iteration #  1     total energy              =    -10.10000000 Ry
estimated scf accuracy    <       1.0D-04 Ry
convergence has been achieved in   1 iterations
Forces acting on atoms (cartesian axes, Ry/au):
 atom    1 type  1   force =     0.000020   0.000000   0.000000
 total force   3.0E-05
BFGS Geometry Optimization
ATOMIC_POSITIONS (angstrom)
Na  0.000000  0.000000  0.000000
CELL_PARAMETERS (angstrom)
3.000000 0.000000 0.000000
0.000000 3.000000 0.000000
0.000000 0.000000 3.000000
JOB DONE.
"""


def test_review_vc_relax_output_pass_with_cell() -> None:
    output = parse_vc_relax_output(_vc_pass_text(), source="vc-relax.out")
    result = review_vc_relax_output(output)

    assert result.status == "PASS"
    assert result.allowed_downstream == list(VC_RELAX_BASE_DOWNSTREAMS)
    assert result.blocked_downstream == [name for name in VC_RELAX_DOWNSTREAMS if name not in VC_RELAX_BASE_DOWNSTREAMS]
    assert result.recommendations == []


def test_review_vc_relax_output_warn_when_pressure_missing() -> None:
    output = parse_vc_relax_output(_vc_warn_pressure_text(), source="vc-relax.out")
    result = review_vc_relax_output(output)

    assert result.status == "WARN"
    assert result.allowed_downstream == list(VC_RELAX_BASE_DOWNSTREAMS)
    assert "phonon" in result.blocked_downstream
    assert "dielectric" in result.blocked_downstream
    assert any("pressure" in reason.lower() for reason in result.reasons)

def test_review_vc_relax_output_block_when_variable_cell_not_enabled() -> None:
    output = parse_relax_output(_vc_pass_text(), source="vc-relax.out", variable_cell=False)
    result = review_vc_relax_output(output)

    assert result.status == "BLOCK"
    assert result.allowed_downstream == []
    assert set(result.blocked_downstream) == set(VC_RELAX_DOWNSTREAMS)


def test_review_vc_relax_output_block_propagates_policy_blocked_downstream() -> None:
    output = parse_vc_relax_output(_vc_pass_text().replace("JOB DONE.", "JOB END."), source="vc-relax.out")
    result = review_vc_relax_output(output)

    assert result.status == "BLOCK"
    assert result.allowed_downstream == []
    assert set(result.blocked_downstream) == set(VC_RELAX_DOWNSTREAMS)
