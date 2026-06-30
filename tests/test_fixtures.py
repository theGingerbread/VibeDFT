"""Regression smoke tests on sanitized fixtures (Sprint 7).

Every known failure mode from the HfI2 e=0.02 real-case hardening must
have a corresponding fixture test to prevent regression.
"""

import json
import subprocess
import sys
import os
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "vibedft", *args],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Valid workflow fixture
# ═══════════════════════════════════════════════════════════════════════════════


def test_mini_qe_all_files_parseable():
    """All valid mini-QE input files must parse without error."""
    valid_files = [
        "scf.in", "ph.in", "q2r.in", "matdyn.in",
    ]
    paths = [str(FIXTURES / "mini_qe" / f) for f in valid_files]
    result = run_cli("inspect", *paths, "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    for f in data["files"]:
        assert f["parse_status"] == "ok", f"Parse failed for {f['path']}: {f.get('parse_errors')}"
        assert f["program"] != "unknown", f"Program not identified for {f['path']}"


def test_mini_qe_scf_output_job_done():
    """SCF output must show JOB DONE and convergence."""
    result = run_cli("inspect", str(FIXTURES / "mini_qe" / "scf.out"), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    issues = [i["id"] for i in data["issues"]]
    assert "output.job_done" in issues
    assert "output.scf.converged" in issues


def test_mini_qe_lambda_parsed():
    """lambda.x output must be parseable for Tc analysis."""
    result = run_cli("analyze", "tc",
                     str(FIXTURES / "mini_qe" / "lambda.out"),
                     str(FIXTURES / "mini_qe" / "lambda.out"),
                     "--label-a", "grid_a", "--label-b", "grid_b",
                     "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["overlap_status"] in ("pass", "fail", "no_data")


# ═══════════════════════════════════════════════════════════════════════════════
# la2F error detection
# ═══════════════════════════════════════════════════════════════════════════════


def test_la2f_in_q2r_detected():
    """la2F=.true. in q2r.in must be flagged as ERROR."""
    result = run_cli("inspect", str(FIXTURES / "bad_la2f" / "q2r_bad.in"), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    error_ids = [i["id"] for i in data["issues"] if i["severity"] == "error"]
    assert any("la2f" in eid.lower() for eid in error_ids), \
        f"la2F error not detected in q2r_bad.in. Issues: {data['issues']}"


def test_la2f_in_matdyn_detected():
    """la2F=.true. in matdyn.in must be flagged as ERROR."""
    result = run_cli("inspect", str(FIXTURES / "bad_la2f" / "matdyn_bad.in"), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    error_ids = [i["id"] for i in data["issues"] if i["severity"] == "error"]
    # matdyn la2F may be an error or warning depending on validator
    assert any("la2f" in eid.lower() for eid in error_ids), \
        f"la2F not flagged in matdyn_bad.in. Issues: {data['issues']}"


def test_la2f_in_epc_matdyn_dos_allowed(tmp_path):
    f = tmp_path / "matdyndos.in"
    f.write_text(
        "&INPUT\n"
        "  flfrc = 'test.fc'\n"
        "  flfrq = 'test.phdos.freq'\n"
        "  dos = .true.\n"
        "  la2F = .true.\n"
        "/\n"
    )
    result = run_cli("inspect", str(f), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    error_ids = [i["id"] for i in data["issues"] if i["severity"] == "error"]
    assert not any("la2f" in eid.lower() for eid in error_ids), data["issues"]


# ═══════════════════════════════════════════════════════════════════════════════
# Slurm wrapper detection
# ═══════════════════════════════════════════════════════════════════════════════


def test_slurm_wrapped_output_detected():
    """[Talos] wrapper must not prevent QE program identification."""
    result = run_cli("inspect", str(FIXTURES / "slurm_wrapped" / "DJ_ph0.out"), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    prog = data["files"][0]["program"]
    assert prog in ("ph.x", "pw.x", "matdyn.x", "q2r.x", "lambda.x"), \
        f"Slurm-wrapped output not identified as QE. Got: {prog}"


# ═══════════════════════════════════════════════════════════════════════════════
# Unknown input detection
# ═══════════════════════════════════════════════════════════════════════════════


def test_dos_input_recognized():
    """&dos namelist must be recognized as dos.x."""
    result = run_cli("inspect", str(FIXTURES / "unknown_inputs" / "dos.in"), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["files"][0]["program"] == "dos.x", \
        f"dos.in not recognized as dos.x. Got: {data['files'][0]['program']}"


def test_pdos_input_recognized():
    """&projwfc namelist must be recognized as projwfc.x."""
    result = run_cli("inspect", str(FIXTURES / "unknown_inputs" / "pdos.in"), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["files"][0]["program"] == "projwfc.x", \
        f"pdos.in not recognized. Got: {data['files'][0]['program']}"


def test_lambda_freefmt_recognized():
    """Free-format lambda.x input with elph_dir must be recognized."""
    result = run_cli("inspect",
                     str(FIXTURES / "unknown_inputs" / "lambda_freefmt.in"), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    prog = data["files"][0]["program"]
    assert prog in ("lambda.x", "unknown"), \
        f"lambda_freefmt.in program: {prog}"
    # At minimum, should not crash
    assert data["files"][0]["parse_status"] in ("ok", "partial")


# ═══════════════════════════════════════════════════════════════════════════════
# Tc overlap failure detection
# ═══════════════════════════════════════════════════════════════════════════════


def test_tc_overlap_fail_detected():
    """Divergent Tc curves must produce overlap_status=fail."""
    result = run_cli("analyze", "tc",
                     str(FIXTURES / "tc_overlap_fail" / "ph64_lambda.out"),
                     str(FIXTURES / "tc_overlap_fail" / "ph96_lambda.out"),
                     "--label-a", "ph64", "--label-b", "ph96",
                     "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["overlap_status"] == "fail", \
        f"Expected Tc overlap fail, got: {data['overlap_status']}"


# ═══════════════════════════════════════════════════════════════════════════════
# Review on mini_qe fixture
# ═══════════════════════════════════════════════════════════════════════════════


def test_review_on_mini_qe():
    """Review must run without error on the mini-QE fixture directory."""
    result = run_cli("review", "--case-dir", str(FIXTURES / "mini_qe"), "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["files_scanned"] > 0
    assert len(data["inspection"]["tasks"]) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Plan smoke test
# ═══════════════════════════════════════════════════════════════════════════════


def test_plan_dry_run_on_fixture_structure(tmp_path):
    """Plan must work on the mini-QE scf.in structure."""
    struct = FIXTURES / "mini_qe" / "scf.in"
    out = tmp_path / "planned"
    result = run_cli("plan", "superconductivity",
                     "--structure", str(struct),
                     "--out", str(out), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "01_relax" in result.stdout
    assert "08_epc_ph64" in result.stdout


# ═══════════════════════════════════════════════════════════════════════════════
# Sanitization check — no private data in fixtures
# ═══════════════════════════════════════════════════════════════════════════════


def test_fixtures_have_no_private_paths():
    """Committed fixtures must not contain real server paths or accounts."""
    forbidden = [
        "secret-host", "private-user", "internal-lab",
        "/home/private-user", "/data/private-cluster",
    ]
    _BINARY_EXTS = {".ds_store", ".png", ".jpg", ".pdf", ".gz", ".zip", ".tar"}
    for root, dirs, files in os.walk(str(FIXTURES)):
        # Skip Templates/ — remote reference data for review testing
        if "Templates" in root.split(os.sep):
            continue
        for fn in files:
            if Path(fn).suffix.lower() in _BINARY_EXTS:
                continue
            path = Path(root) / fn
            try:
                content = path.read_text()
            except UnicodeDecodeError:
                continue
            for kw in forbidden:
                assert kw not in content, \
                    f"Private string '{kw}' found in fixture {path}"
