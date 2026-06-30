from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import json

from vibedft.main.cli import main as cli_main


def _write_qe_text(path: Path, *, status: str) -> None:
    if status == "pass":
        body = """Program PWSCF v.7.1 starts
     iteration #  1
 total energy              =    -4.1234 Ry
 estimated scf accuracy    <       1.0D-12 Ry
 the Fermi energy is    2.5000 eV
 convergence has been achieved in 1 iterations
 JOB DONE.
"""
    elif status == "warn":
        body = """Program PWSCF v.7.1 starts
     iteration #  1
 total energy              =    -4.1234 Ry
 estimated scf accuracy    <       1.0D-12 Ry
 c_bands eigenvalues not converged
 the Fermi energy is    2.5000 eV
 convergence has been achieved in 1 iterations
 JOB DONE.
"""
    else:
        body = """Program PWSCF v.7.1 starts
     iteration #  1
 total energy              =    -4.1234 Ry
 estimated scf accuracy    <       1.0D-12 Ry
 the Fermi energy is    2.5000 eV
 convergence has been achieved in 1 iterations
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


def test_qe_scf_review_cli_pass(tmp_path: Path) -> None:
    output_file = tmp_path / "scf_pass.out"
    _write_qe_text(output_file, status="pass")

    payload_text = _run_cli(["qe", "scf", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["command"] == "qe.scf.review"
    assert payload["ok"] is True
    assert payload["result"]["status"] == "pass"
    assert payload["result"]["task"] == "scf"
    assert payload["result"]["outputs"]["job_done"] is True
    assert payload["result"]["review"]["status"] == "PASS"
    assert payload["result"]["readiness"]["downstream"]["relax"]["allowed"] is True


def test_qe_scf_review_cli_warn(tmp_path: Path) -> None:
    output_file = tmp_path / "scf_warn.out"
    _write_qe_text(output_file, status="warn")

    payload_text = _run_cli(["qe", "scf", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["ok"] is True
    assert payload["result"]["status"] == "warn"


def test_qe_scf_review_cli_block_and_fail_on_block(tmp_path: Path) -> None:
    output_file = tmp_path / "scf_block.out"
    _write_qe_text(output_file, status="block")

    payload_text = _run_cli(["qe", "scf", "review", str(output_file)])
    payload = json.loads(payload_text)
    assert payload["ok"] is True
    assert payload["result"]["status"] == "block"
    assert payload["result"]["review"]["status"] == "BLOCK"
    assert payload["result"]["readiness"]["downstream"]["phonon"]["allowed"] is False

    failure_output = _run_cli(
        ["qe", "scf", "review", "--fail-on-block", str(output_file)],
        expect_exit_code=2,
    )
    failure_payload = json.loads(failure_output)
    assert failure_payload["command"] == "qe.scf.review"
    assert failure_payload["ok"] is True


def test_qe_scf_review_cli_missing_file() -> None:
    payload_text = _run_cli(["qe", "scf", "review", "missing.out"], expect_exit_code=1)
    payload = json.loads(payload_text)

    assert payload["ok"] is False
    assert payload["error"]["type"] == "FileNotFoundError"


def test_qe_scf_review_cli_pretty_output_parsable(tmp_path: Path) -> None:
    output_file = tmp_path / "scf_pretty.out"
    _write_qe_text(output_file, status="pass")

    payload_text = _run_cli(["qe", "scf", "review", "--pretty", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["ok"] is True


def test_qe_scf_review_cli_output_file(tmp_path: Path) -> None:
    output_file = tmp_path / "scf_pass.out"
    json_file = tmp_path / "scf_review.json"
    _write_qe_text(output_file, status="pass")

    payload_text = _run_cli([
        "qe",
        "scf",
        "review",
        str(output_file),
        "--output",
        str(json_file),
    ])
    payload = json.loads(payload_text)
    assert json_file.exists()

    file_payload = json.loads(json_file.read_text(encoding="utf-8"))
    assert file_payload == payload


def test_qe_scf_review_cli_output_matches_stdout_keys(tmp_path: Path) -> None:
    output_file = tmp_path / "scf_warn.out"
    json_file = tmp_path / "scf_review_warn.json"
    _write_qe_text(output_file, status="warn")

    payload_text = _run_cli([
        "qe",
        "scf",
        "review",
        str(output_file),
        "--output",
        str(json_file),
    ])
    payload = json.loads(payload_text)
    file_payload = json.loads(json_file.read_text(encoding="utf-8"))

    assert file_payload["ok"] == payload["ok"] is True
    assert file_payload["result"]["task"] == payload["result"]["task"] == "scf"
    assert file_payload["result"]["status"] == payload["result"]["status"] == "warn"
