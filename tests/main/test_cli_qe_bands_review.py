"""CLI tests for `vibedft qe bands review`."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import json
import shutil

from vibedft.main.cli import main as cli_main


ROOT = Path(__file__).resolve().parents[2]
BANDS_FIXTURE = ROOT / "tests/fixtures/analyzer_smoke_test/output/HfI2.bands"


def _write_bands_text(
    path: Path,
    *,
    status: str,
    include_fermi: bool = True,
    include_labels: bool = True,
) -> None:
    lines = ["Program PWSCF v.7.3 starts on 30Jul2026"]
    if include_labels:
        lines.append(" high-sym (G) (X) (M)")
    if include_fermi:
        lines.append(" the Fermi energy is   -1.2345 eV")
    if status == "block":
        lines.append(" bfgs failed")
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


def _copy_bands_data_file(output_file: Path) -> Path:
    data_file = output_file.with_suffix(".bands")
    shutil.copy(BANDS_FIXTURE, data_file)
    return data_file


def test_qe_bands_review_cli_pass(tmp_path: Path) -> None:
    output_file = tmp_path / "bands_pass.out"
    _write_bands_text(output_file, status="pass")
    _copy_bands_data_file(output_file)

    payload_text = _run_cli(["qe", "bands", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["command"] == "qe.bands.review"
    assert payload["ok"] is True
    assert payload["result"]["status"] == "pass"
    assert payload["result"]["task"] == "bands"
    assert payload["result"]["review"]["status"] == "PASS"
    assert payload["result"]["readiness"]["downstream"]["analysis.bands"]["allowed"] is True
    assert payload["result"]["readiness"]["downstream"]["phonon"]["allowed"] is False


def test_qe_bands_review_cli_warn(tmp_path: Path) -> None:
    output_file = tmp_path / "bands_warn.out"
    _write_bands_text(output_file, status="warn", include_fermi=False, include_labels=False)
    _copy_bands_data_file(output_file)

    payload_text = _run_cli(["qe", "bands", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["ok"] is True
    assert payload["result"]["status"] == "warn"
    assert payload["result"]["review"]["status"] == "WARN"
    assert payload["result"]["readiness"]["downstream"]["analysis.bandgap"]["allowed"] is True
    assert payload["result"]["readiness"]["downstream"]["epc"]["allowed"] is False


def test_qe_bands_review_cli_block_and_fail_on_block(tmp_path: Path) -> None:
    output_file = tmp_path / "bands_block.out"
    _write_bands_text(output_file, status="block")

    payload_text = _run_cli(["qe", "bands", "review", str(output_file)])
    payload = json.loads(payload_text)
    assert payload["ok"] is True
    assert payload["result"]["status"] == "block"
    assert payload["result"]["review"]["status"] == "BLOCK"

    failure_output = _run_cli(
        ["qe", "bands", "review", "--fail-on-block", str(output_file)],
        expect_exit_code=2,
    )
    failure_payload = json.loads(failure_output)

    assert failure_payload["command"] == "qe.bands.review"
    assert failure_payload["ok"] is True
    assert failure_payload["result"]["status"] == "block"


def test_qe_bands_review_cli_output_file(tmp_path: Path) -> None:
    output_file = tmp_path / "bands_pass.out"
    json_file = tmp_path / "bands_review.json"
    _write_bands_text(output_file, status="pass")
    _copy_bands_data_file(output_file)

    payload_text = _run_cli(
        [
            "qe",
            "bands",
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
    assert file_payload["result"]["task"] == payload["result"]["task"] == "bands"
    assert file_payload["result"]["status"] == payload["result"]["status"] == "pass"


def test_qe_bands_review_cli_output_file_pretty_matches_stdout(tmp_path: Path) -> None:
    output_file = tmp_path / "bands_warn.out"
    _write_bands_text(output_file, status="warn", include_fermi=False, include_labels=False)
    _copy_bands_data_file(output_file)
    json_file = tmp_path / "bands_review_pretty.json"

    payload_text = _run_cli(
        [
            "qe",
            "bands",
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
    assert payload["result"]["status"] == file_payload["result"]["status"] == "warn"
    assert (
        payload["result"]["readiness"]["downstream"]["analysis.bands"]["allowed"]
        == file_payload["result"]["readiness"]["downstream"]["analysis.bands"]["allowed"]
    )
