"""Tests for QE NSCF review policy."""

from __future__ import annotations

from vibedft.calculator.qe.nscf import parse_nscf_output
from vibedft.calculator.qe.nscf.schemas import NSCF_BASE_DOWNSTREAMS, NSCF_DOWNSTREAMS
from vibedft.calculator.qe.nscf.review import review_nscf_output


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


def _text_warn() -> str:
    return """Program PWSCF v.7.3 starts on 30Jun2026
&CONTROL
  calculation = 'nscf'
/
&SYSTEM
  ibrav = 0
/
     number of electrons =    8.000000
     number of Kohn-Sham states =    40
iteration #  1     total energy              =    -184.77093016 Ry
estimated scf accuracy    <       1.0D-03 Ry
convergence has been achieved in   1 iterations
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


def test_review_nscf_output_pass() -> None:
    output = parse_nscf_output(_text_pass(), source="nscf.out")
    result = review_nscf_output(output)

    assert result.status == "PASS"
    assert result.allowed_downstream == list(NSCF_BASE_DOWNSTREAMS)
    assert set(result.blocked_downstream) == set(NSCF_DOWNSTREAMS) - set(NSCF_BASE_DOWNSTREAMS)
    assert result.reasons == []
    assert any(ev.field == "k_point_count" and ev.value == 64 for ev in result.evidence)


def test_review_nscf_output_warn_when_metadata_missing() -> None:
    output = parse_nscf_output(_text_warn(), source="nscf.out")
    result = review_nscf_output(output)

    assert result.status == "WARN"
    assert result.allowed_downstream == list(NSCF_BASE_DOWNSTREAMS)
    assert "NSCF lacks required completion metadata" in "".join(result.reasons)
    assert "dos" in result.allowed_downstream
    assert "phonon" not in result.allowed_downstream


def test_review_nscf_output_block_when_not_job_done() -> None:
    output = parse_nscf_output(_text_block(), source="nscf.out")
    result = review_nscf_output(output)

    assert result.status == "BLOCK"
    assert not result.allowed_downstream
    assert set(result.blocked_downstream) == set(NSCF_DOWNSTREAMS)
