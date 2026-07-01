"""CLI tests for `vibedft qe nscf review`."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import json

from vibedft.main.cli import main as cli_main


def _write_nscf_text(path: Path, *, status: str) -> None:
    if status == "pass":
        body = """Program PWSCF v.7.3 starts on 30Jun2026
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
convergence has been achieved in   2 iterations
JOB DONE.
"""
    elif status == "warn":
        body = """Program PWSCF v.7.3 starts on 30Jun2026
&CONTROL
  calculation = 'nscf'
/
&SYSTEM
  ibrav = 0
/
     number of electrons =    8.000000
iteration #  1     total energy              =    -184.77093016 Ry
estimated scf accuracy    <       1.0D-03 Ry
convergence has been achieved in   1 iterations
JOB DONE.
"""
    else:
        body = """Program PWSCF v.7.3 starts on 30Jun2026
&CONTROL
  calculation = 'nscf'
/
&SYSTEM
  ibrav = 0
/
iteration #  1     total energy              =    -184.77093016 Ry
estimated scf accuracy    <       1.0D-03 Ry
"""

    path.write_text(body.strip() + "\n", encoding="utf-8")


def _run_cli(args: list[str], *, expect_exit_code: int = 0) -> str:
    output = StringIO()
    with redirect_stdout(output), redirect_stderr(output):
        try:
            cli_main(args)
            exit_code = 0
        except SystemExit as exc:
            exit_code = int(exc.code or 0)
    assert exit_code == expect_exit_code
    return output.getvalue()


def test_qe_nscf_review_cli_pass(tmp_path: Path) -> None:
    output_file = tmp_path / "nscf_pass.out"
    _write_nscf_text(output_file, status="pass")

    payload_text = _run_cli(["qe", "nscf", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["command"] == "qe.nscf.review"
    assert payload["ok"] is True
    assert payload["result"]["status"] == "pass"
    assert payload["result"]["task"] == "nscf"
    assert payload["result"]["review"]["status"] == "PASS"
    assert payload["result"]["readiness"]["downstream"]["bands"]["allowed"] is True


def test_qe_nscf_review_cli_warn(tmp_path: Path) -> None:
    output_file = tmp_path / "nscf_warn.out"
    _write_nscf_text(output_file, status="warn")

    payload_text = _run_cli(["qe", "nscf", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["ok"] is True
    assert payload["result"]["status"] == "warn"
    assert payload["result"]["review"]["status"] == "WARN"


def test_qe_nscf_review_cli_block_and_fail_on_block(tmp_path: Path) -> None:
    output_file = tmp_path / "nscf_block.out"
    _write_nscf_text(output_file, status="block")

    payload_text = _run_cli(["qe", "nscf", "review", str(output_file)])
    payload = json.loads(payload_text)
    assert payload["ok"] is True
    assert payload["result"]["status"] == "block"
    assert payload["result"]["review"]["status"] == "BLOCK"

    failure_output = _run_cli(
        ["qe", "nscf", "review", "--fail-on-block", str(output_file)],
        expect_exit_code=2,
    )
    failure_payload = json.loads(failure_output)

    assert failure_payload["command"] == "qe.nscf.review"
    assert failure_payload["ok"] is True
    assert failure_payload["result"]["status"] == "block"


def test_qe_nscf_review_cli_output_file(tmp_path: Path) -> None:
    output_file = tmp_path / "nscf_pass.out"
    json_file = tmp_path / "nscf_review.json"
    _write_nscf_text(output_file, status="pass")

    payload_text = _run_cli(
        [
            "qe",
            "nscf",
            "review",
            str(output_file),
            "--output",
            str(json_file),
        ]
    )
    payload = json.loads(payload_text)
    file_payload = json.loads(json_file.read_text(encoding="utf-8"))

    assert json_file.exists()
    assert file_payload["ok"] == payload["ok"] is True
    assert file_payload["result"]["task"] == payload["result"]["task"] == "nscf"
    assert file_payload["result"]["status"] == payload["result"]["status"] == "pass"


def test_qe_nscf_review_cli_output_file_matches_pretty(tmp_path: Path) -> None:
    output_file = tmp_path / "nscf_pass.out"
    json_file = tmp_path / "nscf_review_pretty.json"
    _write_nscf_text(output_file, status="pass")

    payload_text = _run_cli(
        [
            "qe",
            "nscf",
            "review",
            str(output_file),
            "--pretty",
            "--output",
            str(json_file),
        ]
    )
    payload = json.loads(payload_text)
    file_payload = json.loads(json_file.read_text(encoding="utf-8"))

    assert file_payload["result"]["status"] == payload["result"]["status"] == "pass"
    assert file_payload["result"]["readiness"]["downstream"]["dos"]["allowed"] is True
