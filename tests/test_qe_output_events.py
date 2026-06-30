from __future__ import annotations

from dataclasses import is_dataclass

from vibedft.calculator.qe.common import QEOutputEvent, parse_qe_output_events


def categories(items: list[QEOutputEvent]) -> list[str]:
    return [item.category for item in items]


def test_extracts_watch_command_events_from_stdout_text() -> None:
    text = """Program PWSCF
     iteration #  1     total energy              =    -184.77093016 Ry
     estimated scf accuracy    <       1.0E-12 Ry
     convergence has been achieved in   1 iterations
     JOB DONE.
"""

    scan = parse_qe_output_events(text, source="stdout")

    assert is_dataclass(scan)
    assert categories(scan.events) == [
        "scf_iteration",
        "total_energy",
        "scf_accuracy",
        "convergence",
        "job_done",
    ]
    assert scan.issues == []
    assert scan.events[0].line_number == 2
    assert scan.events[0].severity == "info"
    assert scan.events[0].source == "stdout"
    assert scan.events[1].message == "total energy = -184.77093016 Ry"


def test_extracts_qe_warning_and_error_issues_with_source_basename(tmp_path) -> None:
    output = tmp_path / "nested" / "calc.out"
    output.parent.mkdir()
    output.write_text(
        "WARNING: smearing may be too broad\n"
        "Error in routine readpp (1): file not found\n",
        encoding="utf-8",
    )

    scan = parse_qe_output_events(output)

    assert categories(scan.issues) == ["warning", "error", "file_not_found"]
    assert [issue.severity for issue in scan.issues] == ["warning", "error", "error"]
    assert [issue.line_number for issue in scan.issues] == [1, 2, 2]
    assert {issue.source for issue in scan.issues} == {"calc.out"}
    assert str(tmp_path) not in repr(scan)


def test_detects_common_failure_markers_and_truncated_active_output() -> None:
    text = """     q = (    0.000000000   0.000000000   0.000000000 )
MPI_ABORT was invoked on rank 0
Segmentation fault (core dumped)
Out Of Memory: killed process
DUE TO TIME LIMIT
Traceback (most recent call last):
FileNotFoundError: No such file or directory: '/var/tmp/qe-run/pw.out'
"""

    scan = parse_qe_output_events(text, source="/var/tmp/qe-run/ph.err")

    assert categories(scan.issues) == [
        "mpi_abort",
        "segmentation_fault",
        "out_of_memory",
        "time_limit",
        "traceback",
        "file_not_found",
        "truncated_output",
    ]
    assert all(issue.severity == "error" for issue in scan.issues)
    assert {issue.source for issue in scan.issues} == {"ph.err"}
    assert scan.issues[-1].line_number == 7
    assert "/var/tmp/qe-run" not in repr(scan)
    assert "<path>" in scan.issues[5].message


def test_sanitizes_windows_paths_and_uses_basename_source() -> None:
    text = r"FileNotFoundError: No such file or directory: C:\Users\chemist\qe runs\pw.out"

    scan = parse_qe_output_events(text, source=r"C:\Users\chemist\qe runs\pw.err")

    assert {issue.source for issue in scan.issues} == {"pw.err"}
    assert "C:\\Users\\chemist" not in repr(scan)
    assert "<path>" in scan.issues[0].message


def test_total_energy_without_terminal_marker_counts_as_truncated_activity() -> None:
    text = "     total energy              =    -184.77093016 Ry\n"

    scan = parse_qe_output_events(text, source="scf.out")

    assert categories(scan.events) == ["total_energy"]
    assert categories(scan.issues) == ["truncated_output"]


def test_nonfatal_lowercase_error_text_is_not_severe_error() -> None:
    text = "estimated numerical error is small enough for this step\n"

    scan = parse_qe_output_events(text, source="scf.out")

    assert scan.issues == []
