from __future__ import annotations

from dataclasses import is_dataclass

from vibedft.calculator.qe.scf import (
    ScfIteration,
    ScfMonitorSnapshot,
    ScfOutput,
    SCFStateMachine,
    monitor_scf_output,
    parse_scf_output,
)
from vibedft.calculator.qe.common import QEOutputEvent


RY_TO_EV = 13.605703976


def test_parse_and_monitor_clean_scf_success() -> None:
    text = """Program PWSCF v.7.3 starts on 30Jun2026
     iteration #  1     total energy              =    -184.77093016 Ry
     estimated scf accuracy    <       1.0D-03 Ry
     iteration #  2     total energy              =    -184.77123456 Ry
     estimated scf accuracy    <       4.2E-10 Ry
     the Fermi energy is    5.4321 ev
     convergence has been achieved in   2 iterations
!    total energy              =    -184.77123456 Ry
     PWSCF        :   0.42s CPU   0.55s WALL
     JOB DONE.
"""

    output = parse_scf_output(text, source="stdout")
    snapshot = monitor_scf_output(text, source="stdout")

    assert is_dataclass(output)
    assert is_dataclass(snapshot)
    assert output.program == "PWSCF"
    assert output.version == "7.3"
    assert output.iterations == [
        ScfIteration(number=1, total_energy_ry=-184.77093016, scf_accuracy_ry=1.0e-3),
        ScfIteration(number=2, total_energy_ry=-184.77123456, scf_accuracy_ry=4.2e-10),
    ]
    assert output.final_total_energy_ry == -184.77123456
    assert output.final_scf_accuracy_ry == 4.2e-10
    assert output.fermi_energy_ev == 5.4321
    assert output.converged is True
    assert output.convergence_iterations == 2
    assert output.job_done is True
    assert output.cpu_seconds == 0.42
    assert output.wall_seconds == 0.55
    assert output.issues == []

    assert snapshot == ScfMonitorSnapshot(
        status="completed",
        job_done=True,
        converged=True,
        last_iteration=2,
        last_total_energy_ry=-184.77123456,
        last_scf_accuracy_ry=4.2e-10,
        issues=[],
        summary="SCF completed after 2 iterations.",
        suggested_actions=[],
    )


def test_parse_scf_output_semantic_schema_preserves_setup_trajectory_and_stability() -> None:
    text = """Program PWSCF v.7.3 starts on 30Jun2026
     &CONTROL
        calculation = 'scf'
        prefix = 'synthetic'
     /
     &SYSTEM
        ibrav = 4
        nat = 2
        ntyp = 1
        ecutwfc = 5.0D+01
        ecutrho = 4.0D+02
        nbnd = 12
        occupations = 'smearing'
     /
     &ELECTRONS
        conv_thr = 1.0d-08
        mixing_beta = 0.30
     /
     number of electrons       =   8.0000
     number of Kohn-Sham states=  12
     kinetic-energy cutoff     =      50.0000  Ry
     charge density cutoff     =     400.0000  Ry
     Dense  grid:    36000 G-vectors     FFT dimensions: (  72,  72,  36)
     Smooth grid:    12000 G-vectors     FFT dimensions: (  36,  36,  18)
     number of k points=    6
     K_POINTS automatic
      6 6 1 0 0 0
     iteration #  1     ecut=    50.00 Ry     beta=0.30
     total energy              =    -20.00000000 Ry
     estimated scf accuracy    <       2.0D-03 Ry
     c_bands:  1 eigenvalues not converged
     iteration #  2     ecut=    50.00 Ry     beta=0.20
     total energy              =    -20.10000000 Ry
     estimated scf accuracy    <       6.0D-04 Ry
     iteration #  3     ecut=    50.00 Ry     beta=0.20
     total energy              =    -20.09990000 Ry
     estimated scf accuracy    <       7.0D-04 Ry
     the Fermi energy is    3.2500 ev
     convergence has been achieved in   3 iterations
!    total energy              =    -20.09990000 Ry
     estimated scf accuracy    <       7.0D-04 Ry
     PWSCF        :   1.20s CPU   1.50s WALL
     JOB DONE.
"""

    output = parse_scf_output(text, source="semantic.out")
    schema = output.to_schema()

    assert list(schema) == [
        "system",
        "input_parameters",
        "numerical_setup",
        "scf_trajectory",
        "convergence",
        "final_observables",
        "diagnostics",
        "stability_assessment",
    ]
    assert output.iterations[0] == ScfIteration(
        number=1,
        total_energy_ry=-20.0,
        scf_accuracy_ry=2.0e-3,
        energy_difference_ry=None,
        mixing_beta=0.30,
        eigenvalue_warning=True,
        warnings=["c_bands:  1 eigenvalues not converged"],
        converged=False,
    )
    assert output.iterations[0].mixing_beta == 0.30
    assert output.iterations[0].eigenvalue_warning is True
    assert output.iterations[0].warnings == ["c_bands:  1 eigenvalues not converged"]
    assert output.iterations[1].energy_difference_ry == -0.1
    assert output.iterations[2].energy_difference_ev == 0.0001 * RY_TO_EV
    assert output.iterations[2].converged is True

    assert schema["system"]["program"] == "PWSCF"
    assert schema["system"]["version"] == "7.3"
    assert schema["system"]["number_of_electrons"] == 8.0
    assert schema["system"]["number_of_bands"] == 12
    assert schema["input_parameters"]["control"]["calculation"] == "scf"
    assert schema["input_parameters"]["system"]["ecutwfc_ry"] == 50.0
    assert schema["input_parameters"]["system"]["ecutrho_ry"] == 400.0
    assert schema["input_parameters"]["electrons"]["conv_thr"] == 1.0e-8
    assert schema["input_parameters"]["electrons"]["mixing_beta"] == 0.30
    assert schema["numerical_setup"]["ecutwfc_ry"] == 50.0
    assert schema["numerical_setup"]["ecutrho_ev"] == 400.0 * RY_TO_EV
    assert schema["numerical_setup"]["k_points"]["count"] == 6
    assert schema["numerical_setup"]["k_points"]["mesh"] == [6, 6, 1]
    assert schema["numerical_setup"]["fft_grids"]["dense"] == [72, 72, 36]

    assert schema["scf_trajectory"] == [
        {
            "iteration": 1,
            "total_energy_ry": -20.0,
            "total_energy_ev": -20.0 * RY_TO_EV,
            "energy_difference_ry": None,
            "energy_difference_ev": None,
            "scf_accuracy_ry": 2.0e-3,
            "mixing_beta": 0.30,
            "eigenvalue_warning": True,
            "warnings": ["c_bands:  1 eigenvalues not converged"],
            "converged": False,
        },
        {
            "iteration": 2,
            "total_energy_ry": -20.1,
            "total_energy_ev": -20.1 * RY_TO_EV,
            "energy_difference_ry": -0.1,
            "energy_difference_ev": -0.1 * RY_TO_EV,
            "scf_accuracy_ry": 6.0e-4,
            "mixing_beta": 0.20,
            "eigenvalue_warning": False,
            "warnings": [],
            "converged": False,
        },
        {
            "iteration": 3,
            "total_energy_ry": -20.0999,
            "total_energy_ev": -20.0999 * RY_TO_EV,
            "energy_difference_ry": 0.0001,
            "energy_difference_ev": 0.0001 * RY_TO_EV,
            "scf_accuracy_ry": 7.0e-4,
            "mixing_beta": 0.20,
            "eigenvalue_warning": False,
            "warnings": [],
            "converged": True,
        },
    ]
    assert schema["convergence"]["converged"] is True
    assert schema["convergence"]["iterations"] == 3
    assert schema["convergence"]["threshold_ry"] == 1.0e-8
    assert schema["convergence"]["final_scf_accuracy_ry"] == 7.0e-4
    assert schema["convergence"]["suitable_for_followup"] is False
    assert schema["final_observables"]["total_energy_ry"] == -20.0999
    assert schema["final_observables"]["total_energy_ev"] == -20.0999 * RY_TO_EV
    assert schema["final_observables"]["fermi_energy_ev"] == 3.25
    assert schema["diagnostics"]["eigenvalue_warnings"] == [
        "c_bands:  1 eigenvalues not converged"
    ]
    assert schema["diagnostics"]["oscillatory_accuracy"] is True
    assert schema["diagnostics"]["mixing_instability_signals"] == [
        "mixing beta changed during SCF trajectory"
    ]
    assert schema["stability_assessment"]["severity"] == "medium"
    assert schema["stability_assessment"]["likely_root_cause"] == (
        "eigenvalue convergence warning; non-monotonic SCF accuracy; changing mixing beta"
    )
    assert schema["stability_assessment"]["impact_on_observables"] == (
        "Final values are parsed but follow-up use should wait for a cleaner low-severity SCF run."
    )
    assert schema["stability_assessment"]["suitable_for_followup"] is False


def test_parse_scf_output_accepts_string_file_path(tmp_path) -> None:
    output_path = tmp_path / "scf.out"
    output_path.write_text(
        """Program PWSCF v.7.3 starts on 30Jun2026
     iteration #  1     total energy              =    -10.00000000 Ry
     estimated scf accuracy    <       1.0E-09 Ry
     convergence has been achieved in   1 iterations
     JOB DONE.
""",
        encoding="utf-8",
    )

    output = parse_scf_output(str(output_path))

    assert output.source == "scf.out"
    assert output.program == "PWSCF"
    assert output.iterations[0].total_energy_ry == -10.0
    assert output.converged is True
    assert output.job_done is True


def test_monitor_running_truncated_scf_progress() -> None:
    text = """Program PWSCF v.7.3 starts on 30Jun2026
     iteration #  1     total energy              =    -10.10000000 Ry
     estimated scf accuracy    <       3.0E-02 Ry
     iteration #  2     total energy              =    -10.20000000 Ry
"""

    output = parse_scf_output(text, source="stdout")
    snapshot = monitor_scf_output(text, source="stdout")

    assert output.converged is False
    assert output.job_done is False
    assert [iteration.number for iteration in output.iterations] == [1, 2]
    assert [issue.category for issue in output.issues] == ["truncated_output"]

    assert snapshot.status == "running"
    assert snapshot.job_done is False
    assert snapshot.converged is False
    assert snapshot.last_iteration == 2
    assert snapshot.last_total_energy_ry == -10.2
    assert snapshot.last_scf_accuracy_ry == 0.03
    assert [issue.category for issue in snapshot.issues] == ["truncated_output"]
    assert snapshot.suggested_actions == ["Wait for convergence or a terminal failure marker."]


def test_monitor_failed_fatal_c_bands_failure() -> None:
    text = """Program PWSCF v.7.3 starts on 30Jun2026
     iteration #  1     total energy              =    -10.10000000 Ry
Error in routine c_bands (1):
     eigenvalues not converged
MPI_ABORT was invoked on rank 0
"""

    snapshot = monitor_scf_output(text, source="stdout")

    assert snapshot.status == "failed"
    assert snapshot.job_done is False
    assert snapshot.converged is False
    assert snapshot.last_iteration == 1
    assert {"error", "mpi_abort", "truncated_output"} <= {
        issue.category for issue in snapshot.issues
    }
    assert snapshot.summary == "SCF failed with severe QE output issue(s): error, mpi_abort."
    assert snapshot.suggested_actions == [
        "Inspect the first severe error and rerun only after correcting the input or runtime failure."
    ]


def test_monitor_job_done_without_convergence_is_blocked() -> None:
    text = """Program PWSCF v.7.3 starts on 30Jun2026
     iteration #  1     total energy              =    -10.10000000 Ry
     estimated scf accuracy    <       2.0E-02 Ry
     convergence NOT achieved after 100 iterations: stopping
     JOB DONE.
"""

    output = parse_scf_output(text, source="stdout")
    snapshot = monitor_scf_output(text, source="stdout")

    assert output.job_done is True
    assert output.converged is False
    assert snapshot.status == "blocked"
    assert snapshot.last_iteration == 1
    assert snapshot.last_total_energy_ry == -10.1
    assert snapshot.last_scf_accuracy_ry == 0.02
    assert snapshot.summary == "SCF reached JOB DONE without convergence."
    assert snapshot.suggested_actions == [
        "Do not treat JOB DONE alone as success; inspect SCF convergence and restart policy."
    ]


def test_monitor_string_file_path_sees_blocked_marker(tmp_path) -> None:
    output_path = tmp_path / "blocked_scf.out"
    output_path.write_text(
        """Program PWSCF v.7.3 starts on 30Jun2026
     iteration #  1     total energy              =    -10.10000000 Ry
     convergence NOT achieved after 100 iterations: stopping
""",
        encoding="utf-8",
    )

    snapshot = monitor_scf_output(str(output_path))

    assert snapshot.status == "blocked"
    assert snapshot.last_iteration == 1


def test_monitor_non_success_marker_without_job_done_is_blocked() -> None:
    text = """Program PWSCF v.7.3 starts on 30Jun2026
     iteration #  1     total energy              =    -10.10000000 Ry
     convergence NOT achieved after 100 iterations: stopping
"""

    snapshot = monitor_scf_output(text, source="stdout")

    assert snapshot.status == "blocked"
    assert snapshot.job_done is False
    assert snapshot.converged is False


def test_monitor_scf_no_data() -> None:
    snapshot = monitor_scf_output("Submitted batch job 123456\n")

    assert snapshot.status == "no_data"
    assert snapshot.job_done is False
    assert snapshot.converged is False
    assert snapshot.issues == []


def test_parse_output_includes_state_sequence_and_dynamics() -> None:
    text = """Program PWSCF v.7.3 starts on 30Jun2026
     &CONTROL
        calculation = 'scf'
     /
     &SYSTEM
        conv_thr = 1.0D-10
     /
     iteration # 1 total energy = -10.00000000 Ry
     estimated scf accuracy < 1.0E-01 Ry
     iteration # 2 total energy = -10.05000000 Ry
     estimated scf accuracy < 1.0D-02 Ry
     iteration # 3 total energy = -10.10000000 Ry
     estimated scf accuracy < 1.0D-03 Ry
     convergence has been achieved in   3 iterations
     JOB DONE.
"""

    output = parse_scf_output(text, source="stdout")
    schema = output.to_schema()

    assert schema["convergence"]["state_sequence"] == [
        {
            "iteration": 1,
            "energy": -10.0,
            "energy_diff": None,
            "scf_error": 0.1,
            "mixing_beta": None,
            "fermi_energy": None,
            "eigen_warning": False,
            "is_converged_step": False,
            "warnings": [],
        },
        {
            "iteration": 2,
            "energy": -10.05,
            "energy_diff": -0.05,
            "scf_error": 0.01,
            "mixing_beta": None,
            "fermi_energy": None,
            "eigen_warning": False,
            "is_converged_step": False,
            "warnings": [],
        },
        {
            "iteration": 3,
            "energy": -10.1,
            "energy_diff": -0.05,
            "scf_error": 0.001,
            "mixing_beta": None,
            "fermi_energy": None,
            "eigen_warning": False,
            "is_converged_step": True,
            "warnings": [],
        },
    ]
    assert schema["convergence"]["dynamics"] is not None
    assert schema["convergence"]["dynamics"]["convergence_rate"] == 0.1
    assert schema["convergence"]["dynamics"]["energy_decay_type"] == "monotonic"
    assert schema["convergence"]["dynamics"]["estimated_asymptotic_error"] == 0.0001
    assert schema["convergence"]["dynamics"]["convergence_half_life"] == 1
    assert schema["convergence"]["workflow_readiness"] == {
        "dos": True,
        "bands": True,
        "phonon": True,
        "dielectric": True,
        "reason": "Converged stable SCF with low-severity signals.",
    }


def test_monitor_event_state_machine_transitions() -> None:
    machine = SCFStateMachine()
    machine.update(
        QEOutputEvent(
            line_number=1,
            category="scf_iteration",
            severity="info",
            message="iteration # 4",
            source="stdout",
        )
    )
    machine.update(
        QEOutputEvent(
            line_number=2,
            category="total_energy",
            severity="info",
            message="total energy = -123.456 Ry",
            source="stdout",
        )
    )
    machine.update(
        QEOutputEvent(
            line_number=3,
            category="scf_accuracy",
            severity="info",
            message="estimated scf accuracy < 2.5e-06 Ry",
            source="stdout",
        )
    )

    assert machine.last_iteration == 4
    assert machine.last_total_energy_ry == -123.456
    assert machine.last_scf_accuracy_ry == 2.5e-06

    machine.update(
        QEOutputEvent(
            line_number=10,
            category="convergence",
            severity="info",
            message="convergence has been achieved in 4 iterations",
            source="stdout",
        )
    )
    machine.update(
        QEOutputEvent(
            line_number=11,
            category="job_done",
            severity="info",
            message="JOB DONE.",
            source="stdout",
        )
    )
    snapshot = machine.to_snapshot()

    assert snapshot.status == "completed"
    assert snapshot.job_done is True
    assert snapshot.converged is True

    snapshot = machine.to_snapshot(output=None)
    assert snapshot.status == "completed"
    assert snapshot.last_iteration == 4
