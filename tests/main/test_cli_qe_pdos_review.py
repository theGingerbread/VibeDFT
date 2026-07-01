"""CLI tests for `vibedft qe pdos review`."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import json
import shutil

from vibedft.main.cli import main as cli_main


ROOT = Path(__file__).resolve().parents[2]
PDOS_FIXTURE_1 = ROOT / "tests/fixtures/analyzer_smoke_test/output/HfI2.pdos_atm#1(Hf)_wfc#1(d)"
PDOS_FIXTURE_2 = ROOT / "tests/fixtures/analyzer_smoke_test/output/HfI2.pdos_atm#2(Cl)_wfc#1(p)"


def _write_pdos_text(
    path: Path,
    *,
    status: str,
    include_projection_lines: bool = True,
    include_fermi: bool = True,
    include_spin: bool = True,
) -> None:
    lines = ["Program PROJWFC v.7.3 starts on 30Jul2026"]
    if include_fermi:
        lines.append("the Fermi energy is   -1.2345 eV")
    if include_spin:
        lines.append("nspin = 2")
    if include_projection_lines:
        lines.append("pdos file = HfI2.pdos_atm#1(Hf)_wfc#1(d)")
        lines.append("pdos file = HfI2.pdos_atm#2(Cl)_wfc#1(p)")
    if status == "block":
        lines.append("projections requested")
    else:
        lines.append("JOB DONE.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def test_qe_pdos_review_cli_pass(tmp_path: Path) -> None:
    output_file = tmp_path / "pdos_pass.out"
    p1 = tmp_path / "HfI2.pdos_atm#1(Hf)_wfc#1(d)"
    p2 = tmp_path / "HfI2.pdos_atm#2(Cl)_wfc#1(p)"
    _write_pdos_text(output_file, status="pass")
    shutil.copy(PDOS_FIXTURE_1, p1)
    shutil.copy(PDOS_FIXTURE_2, p2)

    payload_text = _run_cli(["qe", "pdos", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["command"] == "qe.pdos.review"
    assert payload["ok"] is True
    assert payload["result"]["status"] == "pass"
    assert payload["result"]["task"] == "pdos"
    assert payload["result"]["review"]["status"] == "PASS"
    assert payload["result"]["readiness"]["downstream"]["analysis.pdos"]["allowed"] is True


def test_qe_pdos_review_cli_warn(tmp_path: Path) -> None:
    output_file = tmp_path / "pdos_warn.out"
    p1 = tmp_path / "HfI2.pdos_atm#1(Hf)_wfc#1(d)"
    p2 = tmp_path / "HfI2.pdos_atm#2(Cl)_wfc#1(p)"
    _write_pdos_text(output_file, status="warn", include_fermi=False, include_spin=False)
    shutil.copy(PDOS_FIXTURE_1, p1)
    shutil.copy(PDOS_FIXTURE_2, p2)

    payload_text = _run_cli(["qe", "pdos", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["ok"] is True
    assert payload["result"]["status"] == "warn"
    assert payload["result"]["review"]["status"] == "WARN"
    assert payload["result"]["readiness"]["downstream"]["analysis.pdos"]["allowed"] is True


def test_qe_pdos_review_cli_warn_to_block_when_no_projection_file(tmp_path: Path) -> None:
    output_file = tmp_path / "pdos_no_projection.out"
    _write_pdos_text(output_file, status="warn", include_projection_lines=False)

    payload_text = _run_cli(["qe", "pdos", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["ok"] is True
    assert payload["result"]["status"] == "block"
    assert payload["result"]["review"]["status"] == "BLOCK"


def test_qe_pdos_review_cli_block_and_fail_on_block(tmp_path: Path) -> None:
    output_file = tmp_path / "pdos_block.out"
    _write_pdos_text(output_file, status="block")

    payload_text = _run_cli(["qe", "pdos", "review", str(output_file)])
    payload = json.loads(payload_text)
    assert payload["ok"] is True
    assert payload["result"]["status"] == "block"
    assert payload["result"]["review"]["status"] == "BLOCK"

    failure_output = _run_cli(
        ["qe", "pdos", "review", "--fail-on-block", str(output_file)],
        expect_exit_code=2,
    )
    failure_payload = json.loads(failure_output)

    assert failure_payload["command"] == "qe.pdos.review"
    assert failure_payload["ok"] is True
    assert failure_payload["result"]["status"] == "block"


def test_qe_pdos_review_cli_output_file(tmp_path: Path) -> None:
    output_file = tmp_path / "pdos_pass.out"
    p1 = tmp_path / "HfI2.pdos_atm#1(Hf)_wfc#1(d)"
    p2 = tmp_path / "HfI2.pdos_atm#2(Cl)_wfc#1(p)"
    _write_pdos_text(output_file, status="pass")
    shutil.copy(PDOS_FIXTURE_1, p1)
    shutil.copy(PDOS_FIXTURE_2, p2)

    json_file = tmp_path / "pdos_review.json"
    payload_text = _run_cli(
        [
            "qe",
            "pdos",
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
    assert file_payload["result"]["task"] == payload["result"]["task"] == "pdos"
    assert file_payload["result"]["status"] == payload["result"]["status"] == "pass"


def test_qe_pdos_review_cli_output_file_matches_stdout_keys(tmp_path: Path) -> None:
    output_file = tmp_path / "pdos_warn.out"
    p1 = tmp_path / "HfI2.pdos_atm#1(Hf)_wfc#1(d)"
    p2 = tmp_path / "HfI2.pdos_atm#2(Cl)_wfc#1(p)"
    _write_pdos_text(output_file, status="warn")
    shutil.copy(PDOS_FIXTURE_1, p1)
    shutil.copy(PDOS_FIXTURE_2, p2)
    json_file = tmp_path / "pdos_review_warn.json"

    payload_text = _run_cli(
        [
            "qe",
            "pdos",
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
        file_payload["result"]["readiness"]["downstream"]["analysis.pdos"]["allowed"]
        == payload["result"]["readiness"]["downstream"]["analysis.pdos"]["allowed"]
    )
