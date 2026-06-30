from __future__ import annotations

from dataclasses import is_dataclass

from vibedft.calculator.qe.phonon import (
    PhononFrequency,
    PhononOutput,
    PhononRepresentation,
    monitor_phonon_output,
    parse_phonon_output,
)


def test_clean_phonon_success_parses_progress_and_monitor_completion() -> None:
    text = """Program PHONON v.7.3 starts
     q = (    0.000000000   0.000000000   0.000000000 )
     Representation #  1 mode #   1
     freq (    1) =  -1.230000D+00 [THz] =    -41.027000 [cm-1]
     omega(    2) =   2.500000E+00 [THz] =     83.391000 [cm-1]
     Dynamical Matrix in cartesian axes
     convergence has been achieved
     PHONON       :     1.50s CPU     2.25s WALL
     JOB DONE.
"""

    output = parse_phonon_output(text, source="ph.out")
    snapshot = monitor_phonon_output(text, source="ph.out")

    assert is_dataclass(output)
    assert isinstance(output, PhononOutput)
    assert output.program == "PHONON"
    assert output.version == "7.3"
    assert output.q_points == [(0.0, 0.0, 0.0)]
    assert output.dynamical_matrix_markers == [6]
    assert output.representations == [
        PhononRepresentation(number=1, mode_number=1, line_number=3)
    ]
    assert output.frequencies == [
        PhononFrequency(mode_number=1, frequency_cm1=-41.027, line_number=4),
        PhononFrequency(mode_number=2, frequency_cm1=83.391, line_number=5),
    ]
    assert output.convergence_achieved_lines == [7]
    assert output.job_done is True
    assert output.cpu_seconds == 1.5
    assert output.wall_seconds == 2.25
    assert output.issues == []

    assert is_dataclass(snapshot)
    assert snapshot.status == "completed"
    assert snapshot.job_done is True
    assert snapshot.q_points_seen == 1
    assert snapshot.representations_seen == 1
    assert snapshot.frequencies_seen == 2
    assert snapshot.min_frequency_cm1 == -41.027
    assert snapshot.max_frequency_cm1 == 83.391
    assert snapshot.issues == []
    assert "completed" in snapshot.summary
    assert snapshot.suggested_actions == []


def test_running_phonon_progress_without_job_done() -> None:
    text = """Program PHONON v.7.2 starts
     q = (    0.250000000   0.000000000   0.000000000 )
     Representation #  2 mode #   4
     omega(    4) =  -3.200000D+00 [cm-1]
"""

    snapshot = monitor_phonon_output(text)

    assert snapshot.status == "running"
    assert snapshot.job_done is False
    assert snapshot.q_points_seen == 1
    assert snapshot.representations_seen == 1
    assert snapshot.frequencies_seen == 1
    assert snapshot.min_frequency_cm1 == -3.2
    assert snapshot.max_frequency_cm1 == -3.2
    assert any(issue.category == "truncated_output" for issue in snapshot.issues)
    assert any("wait" in action.lower() for action in snapshot.suggested_actions)


def test_scheduler_wrapper_without_qe_body_is_no_data() -> None:
    text = """Submitted batch job 123456
slurmstepd: job 123456 queued and waiting for resources
"""

    output = parse_phonon_output(text)
    snapshot = monitor_phonon_output(text)

    assert output.program is None
    assert output.q_points == []
    assert output.frequencies == []
    assert output.job_done is False
    assert output.issues == []
    assert snapshot.status == "no_data"
    assert snapshot.summary == "No QE phonon output body detected"
    assert any("phonon stdout" in action.lower() for action in snapshot.suggested_actions)


def test_existing_string_path_is_read_as_phonon_output(tmp_path) -> None:
    output_file = tmp_path / "ph.out"
    output_file.write_text(
        """Program PHONON v.7.3 starts
     q = (    0.000000000   0.000000000   0.000000000 )
     freq (    1) =      1.000000 [THz] =     33.356000 [cm-1]
     JOB DONE.
""",
        encoding="utf-8",
    )

    output = parse_phonon_output(str(output_file))
    snapshot = monitor_phonon_output(str(output_file))

    assert output.source == "ph.out"
    assert output.program == "PHONON"
    assert output.q_points == [(0.0, 0.0, 0.0)]
    assert output.frequencies == [
        PhononFrequency(mode_number=1, frequency_cm1=33.356, line_number=3)
    ]
    assert snapshot.status == "completed"


def test_mpi_environment_failure_is_failed_and_sanitized() -> None:
    text = """Program PHONON v.7.3 starts
     q = (    0.000000000   0.000000000   0.500000000 )
MPI_ABORT was invoked on rank 0
Error in routine phq_readin (1): file not found: C:\\QE\\runs\\ph.in
"""

    output = parse_phonon_output(text, source="C:\\QE\\runs\\ph.err")
    snapshot = monitor_phonon_output(text, source="C:\\QE\\runs\\ph.err")

    assert snapshot.status == "failed"
    assert snapshot.job_done is False
    assert snapshot.q_points_seen == 1
    categories = [issue.category for issue in output.issues]
    assert categories.count("mpi_abort") == 1
    assert categories.count("error") == 1
    assert categories.count("file_not_found") == 1
    assert categories.count("truncated_output") == 1
    assert {issue.source for issue in snapshot.issues} == {"ph.err"}
    assert "C:\\QE\\runs" not in repr(snapshot)
    assert any(
        issue.category == "file_not_found" and "<path>" in issue.message
        for issue in snapshot.issues
    )
    assert any("failure marker" in snapshot.summary.lower() for _ in [snapshot])
    assert any("inspect" in action.lower() for action in snapshot.suggested_actions)


def test_job_done_without_phonon_progress_is_blocked() -> None:
    text = """wrapper: launched command
     JOB DONE.
"""

    snapshot = monitor_phonon_output(text)

    assert snapshot.status == "blocked"
    assert snapshot.job_done is True
    assert snapshot.q_points_seen == 0
    assert snapshot.representations_seen == 0
    assert snapshot.frequencies_seen == 0
    assert any("no phonon progress" in snapshot.summary.lower() for _ in [snapshot])


def test_phonon_progress_with_non_success_marker_is_blocked() -> None:
    text = """Program PHONON v.7.3 starts
     q = (    0.000000000   0.000000000   0.000000000 )
     Representation #  1 mode #   1
     convergence NOT achieved after 100 iterations: stopping
"""

    snapshot = monitor_phonon_output(text)

    assert snapshot.status == "blocked"
    assert snapshot.job_done is False
    assert snapshot.q_points_seen == 1
    assert snapshot.representations_seen == 1
    assert any("non-success" in snapshot.summary.lower() for _ in [snapshot])
