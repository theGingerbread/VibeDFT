from __future__ import annotations

from vibedft.calculator.qe.scf import parse_scf_output
from vibedft.calculator.qe.scf.review import (
    SCF_BASE_DOWNSTREAMS,
    review_scf_output,
)


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


def _text_warn() -> str:
    return """Program PWSCF v.7.3 starts on 30Jun2026
     iteration #  1     total energy              =    -20.00000000 Ry
     estimated scf accuracy    <       2.0D-03 Ry
     c_bands:  1 eigenvalues not converged
     iteration #  2     total energy              =    -20.02000000 Ry
     estimated scf accuracy    <       8.0D-04 Ry
     convergence has been achieved in   2 iterations
!    total energy              =    -20.02000000 Ry
     PWSCF        :   0.42s CPU   0.55s WALL
     JOB DONE.
"""


def _text_blocked_non_converged() -> str:
    return """Program PWSCF v.7.3 starts on 30Jun2026
     iteration #  1     total energy              =    -10.10000000 Ry
     estimated scf accuracy    <       2.0E-02 Ry
     convergence NOT achieved after 100 iterations: stopping
     JOB DONE.
"""


def _text_blocked_truncated() -> str:
    return """Program PWSCF v.7.3 starts on 30Jun2026
     iteration #  1     total energy              =    -10.10000000 Ry
     estimated scf accuracy    <       3.0E-02 Ry
"""


def test_review_scf_output_pass() -> None:
    output = parse_scf_output(_text_pass(), source="scf.out")
    result = review_scf_output(output)

    assert result.status == "PASS"
    assert result.allowed_downstream == ["relax", "vc_relax", "nscf", "bands", "dos", "pdos", "pp", "phonon", "dielectric"]
    assert result.blocked_downstream == []
    assert result.evidence
    assert any(ev.field == "job_done" and ev.value is True for ev in result.evidence)
    assert any(ev.field == "converged" and ev.value is True for ev in result.evidence)


def test_review_scf_output_warn_when_stability_non_ideal() -> None:
    output = parse_scf_output(_text_warn(), source="scf.out")
    result = review_scf_output(output)

    assert result.status == "WARN"
    assert "nscf" in result.allowed_downstream
    assert "relax" in result.allowed_downstream
    assert "vc_relax" in result.allowed_downstream
    assert "phonon" in result.blocked_downstream
    assert result.reasons


def test_review_scf_output_block_when_not_converged() -> None:
    output = parse_scf_output(_text_blocked_non_converged(), source="scf.out")
    result = review_scf_output(output)

    assert result.status == "BLOCK"
    assert set(result.blocked_downstream) == set(SCF_BASE_DOWNSTREAMS + ("phonon", "dielectric"))


def test_review_scf_output_block_when_truncated_output() -> None:
    output = parse_scf_output(_text_blocked_truncated(), source="scf.out")
    result = review_scf_output(output)

    assert result.status == "BLOCK"
    assert not output.job_done
    assert not output.converged
    assert any(issue.category == "truncated_output" for issue in output.issues)
