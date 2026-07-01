"""CLI tests for `vibedft qe pp review`."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import json

from vibedft.main.cli import main as cli_main


def _write_pp_text(path: Path, *, status: str) -> None:
    if status == "pass":
        body = """Program PP v.7.3 starts on 30Jul2026
&INPUTPP
  plot_num = 0
/
Writing data to charge.cube
JOB DONE.
"""
    elif status == "warn":
        body = """Program PP v.7.3 starts on 30Jul2026
&INPUTPP
  plot_num = 17
/
Writing data to mystery.bin
JOB DONE.
"""
    else:
        body = """Program PP v.7.3 starts on 30Jul2026
&INPUTPP
  plot_num = 0
/
Writing data to charge.cube
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


def test_qe_pp_review_cli_pass(tmp_path: Path) -> None:
    output_file = tmp_path / "pp_pass.out"
    _write_pp_text(output_file, status="pass")
    (tmp_path / "charge.cube").write_text("0.0 0.0 1.0\n", encoding="utf-8")

    payload_text = _run_cli(["qe", "pp", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["command"] == "qe.pp.review"
    assert payload["ok"] is True
    assert payload["result"]["status"] == "pass"
    assert payload["result"]["task"] == "pp"
    assert payload["result"]["review"]["status"] == "PASS"
    assert payload["result"]["readiness"]["downstream"]["analysis.pp"]["allowed"] is True
    assert (
        payload["result"]["readiness"]["downstream"]["analysis.charge_density"]["allowed"]
        is True
    )
    assert payload["result"]["readiness"]["downstream"]["phonon"]["allowed"] is False
    assert payload["result"]["readiness"]["downstream"]["bader"]["allowed"] is False


def test_qe_pp_review_cli_warn_with_unknown_field(tmp_path: Path) -> None:
    output_file = tmp_path / "pp_warn.out"
    _write_pp_text(output_file, status="warn")
    (tmp_path / "mystery.bin").write_text("1.0 2.0 3.0\n", encoding="utf-8")

    payload_text = _run_cli(["qe", "pp", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["ok"] is True
    assert payload["result"]["status"] == "warn"
    assert payload["result"]["review"]["status"] == "WARN"
    assert payload["result"]["readiness"]["downstream"]["analysis.pp"]["allowed"] is True
    assert payload["result"]["review"]["recommendations"]
    assert payload["result"]["next_actions"]


def test_qe_pp_review_cli_block_and_fail_on_block(tmp_path: Path) -> None:
    output_file = tmp_path / "pp_block.out"
    _write_pp_text(output_file, status="block")

    payload_text = _run_cli(["qe", "pp", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["ok"] is True
    assert payload["result"]["status"] == "block"
    assert payload["result"]["review"]["status"] == "BLOCK"

    fail_payload_text = _run_cli(
        ["qe", "pp", "review", "--fail-on-block", str(output_file)],
        expect_exit_code=2,
    )
    fail_payload = json.loads(fail_payload_text)
    assert fail_payload["command"] == "qe.pp.review"
    assert fail_payload["ok"] is True
    assert fail_payload["result"]["status"] == "block"


def test_qe_pp_review_cli_output_file(tmp_path: Path) -> None:
    output_file = tmp_path / "pp_pass.out"
    _write_pp_text(output_file, status="pass")
    (tmp_path / "charge.cube").write_text("0.0 0.0 1.0\n", encoding="utf-8")
    json_file = tmp_path / "pp_review.json"

    payload_text = _run_cli(
        [
            "qe",
            "pp",
            "review",
            str(output_file),
            "--output",
            str(json_file),
        ]
    )
    payload = json.loads(payload_text)
    file_payload = json.loads(json_file.read_text(encoding="utf-8"))

    assert json_file.exists()
    assert file_payload == payload


def test_qe_pp_review_cli_output_file_pretty_matches_stdout(tmp_path: Path) -> None:
    output_file = tmp_path / "pp_warn.out"
    _write_pp_text(output_file, status="warn")
    (tmp_path / "mystery.bin").write_text("1.0 2.0 3.0\n", encoding="utf-8")
    json_file = tmp_path / "pp_review_pretty.json"

    payload_text = _run_cli(
        [
            "qe",
            "pp",
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
    assert file_payload["result"]["status"] == payload["result"]["status"]
    assert (
        payload["result"]["readiness"]["downstream"]["analysis.pp"]["allowed"]
        == file_payload["result"]["readiness"]["downstream"]["analysis.pp"]["allowed"]
    )
