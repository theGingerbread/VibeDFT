"""CLI tests for `vibedft qe dos review`."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import json
import shutil

from vibedft.main.cli import main as cli_main


ROOT = Path(__file__).resolve().parents[2]
DOS_FIXTURE_DATA = ROOT / "tests/fixtures/analyzer_smoke_test/output/HfI2.dos"


def _write_dos_text(path: Path, *, status: str) -> None:
    if status == "pass":
        body = """Program DOS v.7.2 starts on 30Jul2026
  Emin = -10.0 Emax = 10.0 0.01
  the Fermi energy is   -1.2345 eV
JOB DONE.
"""
    elif status == "warn":
        body = """Program DOS v.7.2 starts on 30Jul2026
  the Fermi energy is   -1.2345 eV
JOB DONE.
"""
    else:
        body = """Program DOS v.7.2 starts on 30Jul2026
  the Fermi energy is   -1.2345 eV
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


def test_qe_dos_review_cli_pass(tmp_path: Path) -> None:
    output_file = tmp_path / "dos_pass.out"
    data_file = tmp_path / "dos_pass.dos"
    _write_dos_text(output_file, status="pass")
    shutil.copy(DOS_FIXTURE_DATA, data_file)

    payload_text = _run_cli(["qe", "dos", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["command"] == "qe.dos.review"
    assert payload["ok"] is True
    assert payload["result"]["status"] == "pass"
    assert payload["result"]["task"] == "dos"
    assert payload["result"]["review"]["status"] == "PASS"
    assert payload["result"]["readiness"]["downstream"]["analysis.dos"]["allowed"] is True


def test_qe_dos_review_cli_warn(tmp_path: Path) -> None:
    output_file = tmp_path / "dos_warn.out"
    _write_dos_text(output_file, status="warn")

    payload_text = _run_cli(["qe", "dos", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["ok"] is True
    assert payload["result"]["status"] == "warn"
    assert payload["result"]["review"]["status"] == "WARN"
    assert payload["result"]["readiness"]["downstream"]["analysis.dos"]["allowed"] is True


def test_qe_dos_review_cli_block_and_fail_on_block(tmp_path: Path) -> None:
    output_file = tmp_path / "dos_block.out"
    _write_dos_text(output_file, status="block")

    payload_text = _run_cli(["qe", "dos", "review", str(output_file)])
    payload = json.loads(payload_text)
    assert payload["ok"] is True
    assert payload["result"]["status"] == "block"
    assert payload["result"]["review"]["status"] == "BLOCK"

    failure_output = _run_cli(
        ["qe", "dos", "review", "--fail-on-block", str(output_file)],
        expect_exit_code=2,
    )
    failure_payload = json.loads(failure_output)

    assert failure_payload["command"] == "qe.dos.review"
    assert failure_payload["ok"] is True
    assert failure_payload["result"]["status"] == "block"


def test_qe_dos_review_cli_output_file(tmp_path: Path) -> None:
    output_file = tmp_path / "dos_pass.out"
    data_file = tmp_path / "dos_pass.dos"
    _write_dos_text(output_file, status="pass")
    shutil.copy(DOS_FIXTURE_DATA, data_file)
    json_file = tmp_path / "dos_review.json"

    payload_text = _run_cli(
        [
            "qe",
            "dos",
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
    assert file_payload["result"]["task"] == payload["result"]["task"] == "dos"
    assert file_payload["result"]["status"] == payload["result"]["status"] == "pass"


def test_qe_dos_review_cli_output_file_pretty_matches_stdout(tmp_path: Path) -> None:
    output_file = tmp_path / "dos_warn.out"
    _write_dos_text(output_file, status="warn")
    json_file = tmp_path / "dos_review_pretty.json"

    payload_text = _run_cli(
        [
            "qe",
            "dos",
            "review",
            "--pretty",
            str(output_file),
            "--output",
            str(json_file),
        ]
    )
    payload = json.loads(payload_text)
    file_payload = json.loads(json_file.read_text(encoding="utf-8"))

    assert payload["ok"] is True
    assert payload["result"]["status"] == file_payload["result"]["status"]
    assert (
        payload["result"]["readiness"]["downstream"]["analysis.dos"]["allowed"]
        == file_payload["result"]["readiness"]["downstream"]["analysis.dos"]["allowed"]
    )
