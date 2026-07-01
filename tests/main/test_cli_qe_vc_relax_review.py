"""CLI tests for `vibedft qe vc-relax review`."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import json

from vibedft.main.cli import main as cli_main


def _write_vc_relax_text(path: Path, *, status: str) -> None:
    if status == "pass":
        body = """Program PWSCF v.7.4 starts

&CONTROL
  calculation = 'vc-relax'
/
&SYSTEM
  ibrav = 0
  nat = 1
  ntyp = 1
  ecutwfc = 40
  ecutrho = 400
/
&IONS
  ion_dynamics = 'bfgs'
  forc_conv_thr = 1.0D-4
/
 Self-consistent Calculation
iteration #  1     total energy              =    -10.00000000 Ry
estimated scf accuracy    <       1.0D-04 Ry
convergence has been achieved in   1 iterations
Forces acting on atoms (cartesian axes, Ry/au):
 atom    1 type  1   force =     0.000020   0.000000   0.000000
 total force   3.0E-05
     total   stress  (Ry/bohr**3)                   (kbar)     P=      5.0
  0.10  0.00  0.00   1.00  2.00  3.00
  0.00  0.10  0.00   4.00  5.00  6.00
  0.00  0.00  0.10   7.00  8.00  9.00
BFGS Geometry Optimization
ATOMIC_POSITIONS (angstrom)
Na  0.000000  0.000000  0.000000
CELL_PARAMETERS (angstrom)
3.000000 0.000000 0.000000
0.000000 3.000000 0.000000
0.000000 0.000000 3.000000
JOB DONE.
"""
    else:
        body = """Program PWSCF v.7.4 starts

&CONTROL
  calculation = 'vc-relax'
/
&SYSTEM
  ibrav = 0
  nat = 1
  ntyp = 1
/
&IONS
  ion_dynamics = 'bfgs'
  forc_conv_thr = 1.0D-4
/
 Self-consistent Calculation
iteration #  1     total energy              =    -10.00000000 Ry
estimated scf accuracy    <       1.0D-03 Ry
convergence NOT achieved after 100 iterations
Forces acting on atoms (cartesian axes, Ry/au):
 atom    1 type  1   force =     0.100000   0.000000   0.000000
 total force   1.0E-01
JOB END.
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


def test_qe_vc_relax_review_cli_pass(tmp_path: Path) -> None:
    output_file = tmp_path / "vc_relax_pass.out"
    _write_vc_relax_text(output_file, status="pass")

    payload_text = _run_cli(["qe", "vc-relax", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["command"] == "qe.vc_relax.review"
    assert payload["ok"] is True
    assert payload["result"]["status"] == "pass"
    assert payload["result"]["task"] == "vc_relax"
    assert payload["result"]["review"]["status"] == "PASS"
    assert payload["result"]["readiness"]["downstream"]["scf"]["allowed"] is True


def test_qe_vc_relax_review_cli_block_and_fail_on_block(tmp_path: Path) -> None:
    output_file = tmp_path / "vc_relax_block.out"
    _write_vc_relax_text(output_file, status="block")

    payload_text = _run_cli(["qe", "vc-relax", "review", str(output_file)])
    payload = json.loads(payload_text)

    assert payload["ok"] is True
    assert payload["result"]["status"] == "block"
    assert payload["result"]["review"]["status"] == "BLOCK"

    failure_output = _run_cli(
        ["qe", "vc-relax", "review", "--fail-on-block", str(output_file)],
        expect_exit_code=2,
    )
    failure_payload = json.loads(failure_output)

    assert failure_payload["command"] == "qe.vc_relax.review"
    assert failure_payload["ok"] is True
    assert failure_payload["result"]["status"] == "block"


def test_qe_vc_relax_review_cli_output_file(tmp_path: Path) -> None:
    output_file = tmp_path / "vc_relax_pass.out"
    json_file = tmp_path / "vc_relax_review.json"
    _write_vc_relax_text(output_file, status="pass")

    payload_text = _run_cli(
        [
            "qe",
            "vc-relax",
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
    assert file_payload["result"]["task"] == payload["result"]["task"] == "vc_relax"
    assert file_payload["result"]["status"] == payload["result"]["status"] == "pass"
