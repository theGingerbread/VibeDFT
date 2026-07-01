from __future__ import annotations

from vibedft.calculator.qe.relax import parse_relax_output
from vibedft.calculator.qe.relax.review import review_relax_output


def _pass_text() -> str:
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


def _warn_text() -> str:
    return """Program PWSCF v.7.4 starts

&CONTROL
  calculation = 'relax'
/
&SYSTEM
  ibrav = 0
  nat = 1
  ntyp = 1
/
&IONS
  ion_dynamics = 'bfgs'
/
 Self-consistent Calculation
iteration #  1     total energy              =    -10.00000000 Ry
estimated scf accuracy    <       2.0D-03 Ry
convergence has been achieved in   1 iterations
c_bands:  1 eigenvalues not converged
Forces acting on atoms (cartesian axes, Ry/au):
 atom    1 type  1   force =     0.001000   0.000000   0.000000
 total force   1.0E-03
BFGS Geometry Optimization
ATOMIC_POSITIONS (angstrom)
Na  0.000000  0.000000  0.000000
JOB DONE.
"""


def _block_text() -> str:
    return """Program PWSCF v.7.4 starts

&CONTROL
  calculation = 'relax'
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
estimated scf accuracy    <       1.0D-03 Ry
convergence NOT achieved after 100 iterations
Forces acting on atoms (cartesian axes, Ry/au):
 atom    1 type  1   force =     0.100000   0.000000   0.000000
 total force   1.0E-01
JOB DONE.
"""


def test_review_relax_output_pass() -> None:
    output = parse_relax_output(_pass_text(), source="relax.out")
    result = review_relax_output(output)

    assert result.status == "PASS"
    assert result.allowed_downstream == ["scf", "nscf", "bands", "dos", "pdos", "pp"]
    assert set(result.blocked_downstream) == {
        "vc_relax",
        "phonon",
        "dielectric",
        "epc",
        "tc",
    }
    assert result.reasons == []
    assert result.evidence
    assert any(ev.field == "job_done" and ev.value is True for ev in result.evidence)


def test_review_relax_output_warn_when_threshold_or_warning_missing() -> None:
    output = parse_relax_output(_warn_text(), source="relax.out")
    result = review_relax_output(output)

    assert result.status == "WARN"
    assert result.allowed_downstream == ["scf", "nscf", "bands", "dos", "pdos", "pp"]
    assert "vc_relax" in result.blocked_downstream
    assert "phonon" in result.blocked_downstream
    assert "Force threshold not available" in " | ".join(result.reasons)


def test_review_relax_output_block_when_not_converged_or_missing_job_done() -> None:
    output = parse_relax_output(_block_text(), source="relax.out")
    result = review_relax_output(output)

    assert result.status == "BLOCK"
    assert not result.allowed_downstream
    assert set(result.blocked_downstream) == {
        "scf",
        "nscf",
        "bands",
        "dos",
        "pdos",
        "pp",
        "vc_relax",
        "phonon",
        "dielectric",
        "epc",
        "tc",
    }
