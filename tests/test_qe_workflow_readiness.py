from __future__ import annotations

from vibedft.calculator.qe import build_workflow_readiness_graph
from vibedft.calculator.qe.phonon import parse_phonon_output
from vibedft.calculator.qe.scf import parse_scf_output


def _scf_complete_text() -> str:
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


def _scf_running_text() -> str:
    return """Program PWSCF v.7.3 starts on 30Jun2026
     iteration #  1     total energy              =    -10.10000000 Ry
     estimated scf accuracy    <       3.0E-02 Ry
     iteration #  2     total energy              =    -10.20000000 Ry
"""


def _phonon_complete_text() -> str:
    return """Program PHONON v.7.3 starts
     q = (    0.000000000   0.000000000   0.000000000 )
     Representation #  1 mode #   1
     freq (    1) =  -1.230000D+00 [THz] =    -41.027000 [cm-1]
     omega(    2) =   2.500000E+00 [THz] =     83.391000 [cm-1]
     Dynamical Matrix in cartesian axes
     convergence has been achieved
     PHONON       :     1.50s CPU     2.25s WALL
     JOB DONE.
"""


def _phonon_job_done_without_progress_text() -> str:
    return """Program PHONON v.7.3 starts
 wrapper: launched command
 JOB DONE.
"""


def test_workflow_graph_complete_scf_and_phonon_is_followup_ready() -> None:
    scf = parse_scf_output(_scf_complete_text(), source="scf.out")
    ph = parse_phonon_output(_phonon_complete_text(), source="ph.out")

    graph = build_workflow_readiness_graph(scf_output=scf, phonon_output=ph)

    assert graph.scf_stage.status == "complete"
    assert graph.scf_stage.ready_for_followup is True
    assert graph.phonon_stage.status == "complete"
    assert graph.phonon_stage.ready_for_followup is True
    assert graph.can_run["dos"] is True
    assert graph.can_run["bands"] is True
    assert graph.can_run["phonon"] is True
    assert graph.can_run["epc"] is True
    assert graph.can_run["tc"] is True
    assert graph.recommended_actions == []
    assert graph.blockers == []
    assert graph.to_schema()["stages"]["scf"]["status"] == "complete"


def test_workflow_graph_running_scf_blocks_followup_and_keeps_actions() -> None:
    scf = parse_scf_output(_scf_running_text(), source="scf.out")
    graph = build_workflow_readiness_graph(scf_output=scf, phonon_output=None)

    assert graph.scf_stage.status == "running"
    assert graph.scf_stage.ready_for_followup is False
    assert graph.phonon_stage.status == "missing"
    assert graph.can_run["dos"] is False
    assert graph.can_run["bands"] is False
    assert graph.can_run["phonon"] is False
    assert any("continue SCF monitoring" == action for action in graph.recommended_actions)


def test_workflow_graph_phonon_job_done_without_progress_is_blocked() -> None:
    scf = parse_scf_output(_scf_complete_text(), source="scf.out")
    ph = parse_phonon_output(_phonon_job_done_without_progress_text(), source="ph.out")

    graph = build_workflow_readiness_graph(scf_output=scf, phonon_output=ph)

    assert graph.phonon_stage.status == "blocked"
    assert graph.phonon_stage.ready_for_followup is False
    assert graph.can_run["epc"] is False
    assert graph.can_run["tc"] is False
    assert any("fix phonon fatal issues" in action for action in graph.recommended_actions) is False
    assert any("validate phonon invocation" in action for action in graph.recommended_actions)
    assert any("JOB DONE seen without phonon progress markers." in blocker for blocker in graph.blockers)
