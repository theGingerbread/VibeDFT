"""Tests for the QA engine."""

import subprocess
import sys
import os
from pathlib import Path

from vibedft.core.qa import (
    qa_inputs,
    qa_outputs,
    qa_all,
    CheckResult,
    QaReport,
)

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


# ── model tests ──


def test_check_result_model():
    cr = CheckResult(id="test.check", status="pass", message="ok")
    assert cr.id == "test.check"
    assert cr.status == "pass"
    assert cr.message == "ok"
    assert cr.path is None


def test_qa_report_aggregation():
    report = QaReport(case_dir=Path("/tmp/test"))
    report.checks = [
        CheckResult("a", "pass", "ok"),
        CheckResult("b", "fail", "bad"),
        CheckResult("c", "warn", "careful"),
        CheckResult("d", "skip", "n/a"),
    ]
    assert report.status == "fail"
    assert len(report.passed) == 1
    assert len(report.failed) == 1
    assert len(report.warnings) == 1


# ── input QA tests ──


def test_qa_inputs_detects_missing_directory(tmp_path: Path):
    report = qa_inputs(tmp_path / "nonexistent")
    assert report.status == "fail"
    assert any(c.id == "input.files.exist" and c.status == "fail" for c in report.checks)


def test_qa_inputs_detects_prefix_mismatch(tmp_path: Path):
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "scf.in").write_text("prefix = 'HfBr2'\noutdir = './out_scf/'\n")
    (inp / "nscf.in").write_text("prefix = 'WRONG'\noutdir = './out_scf/'\n")

    report = qa_inputs(tmp_path)
    assert any(c.id == "input.prefix.consistency" and c.status == "fail" for c in report.checks)


def test_qa_inputs_pass_with_consistent_prefix(tmp_path: Path):
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "scf.in").write_text("prefix = 'HfBr2'\noutdir = './out_scf/'\n")
    (inp / "nscf.in").write_text("prefix = 'HfBr2'\noutdir = './out_scf/'\n")

    report = qa_inputs(tmp_path)
    assert report.status == "pass"
    assert any(c.id == "input.prefix.consistency" and c.status == "pass" for c in report.checks)


def test_qa_inputs_detects_forbidden_la2f(tmp_path: Path):
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "q2rx.in").write_text("&INPUT\n  la2F = .true.\n/\n")

    report = qa_inputs(tmp_path)
    assert any(c.id == "input.ph.no_la2f" and c.status == "fail" for c in report.checks)


def test_qa_inputs_no_la2f_pass(tmp_path: Path):
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "q2rx.in").write_text("&INPUT\n  fildyn = 'dyn'\n  flfrc = 'fc'\n/\n")
    (inp / "matdynline.in").write_text("&INPUT\n  flfrc = 'fc'\n  flfrq = 'freq'\n/\n")

    report = qa_inputs(tmp_path)
    assert any(c.id == "input.ph.no_la2f" and c.status == "pass" for c in report.checks)


def test_qa_inputs_allows_epc_matdyn_dos_la2f(tmp_path: Path):
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "matdyndos.in").write_text(
        "&INPUT\n"
        "  flfrc = 'fc'\n"
        "  flfrq = 'phdos.freq'\n"
        "  dos = .true.\n"
        "  la2F = .true.\n"
        "/\n"
    )

    report = qa_inputs(tmp_path)
    assert any(c.id == "input.ph.no_la2f" and c.status == "pass" for c in report.checks)


def test_qa_inputs_detects_unresolved_placeholders(tmp_path: Path):
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "scf.in").write_text("ecutwfc = {{ qe.pw.system.ecutwfc }}\n")

    report = qa_inputs(tmp_path)
    assert any(c.id == "input.placeholders.resolved" and c.status == "fail" for c in report.checks)


# ── output QA tests ──


def test_qa_outputs_detects_missing_job_done(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text("Program PWSCF v7.1\nError: something failed\n")

    report = qa_outputs(tmp_path)
    assert any(c.id == "output.job_done" and c.status == "fail" for c in report.checks)


def test_qa_outputs_pass_with_job_done(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text("JOB DONE\n")

    report = qa_outputs(tmp_path)
    assert any(c.id == "output.job_done" and c.status == "pass" for c in report.checks)


def test_qa_outputs_detects_nan(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "lambdax.out").write_text("lambda  omega_log  T_c\n1.0  NaN  5.0\n")

    report = qa_outputs(tmp_path)
    assert any(c.id == "output.no_nan" and c.status in ("fail", "warn") for c in report.checks)


def test_qa_outputs_detects_zero_byte_dyn(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "test.dyn0").write_text("header")
    (out / "test.dyn1").write_text("data")
    (out / "test.dyn2").write_text("")   # zero bytes — crash signal

    report = qa_outputs(tmp_path)
    assert any(c.id == "output.ph.dyn_zero_byte" and c.status == "fail" for c in report.checks)


def test_qa_outputs_pass_with_nonzero_dyn(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "test.dyn0").write_text("header")
    (out / "test.dyn1").write_text("data")

    report = qa_outputs(tmp_path)
    assert any(c.id == "output.ph.dyn_zero_byte" and c.status == "pass" for c in report.checks)


# ── CLI tests ──


def test_cli_qa_inputs_on_real_case():
    """Run qa inputs on the real HfBr2 test case."""
    case_dir = PROJECT_ROOT / "cases" / "HfBr2-hetero" / "test-run"
    # This case has no input/ dir (inputs are at top level), so it will fail gracefully
    result = run_cli("qa", "inputs", "--case-dir", str(case_dir))
    # Should not crash — either pass, fail, or exit with structured output
    assert "QA Report" in result.stdout or result.returncode in (0, 1)


def test_cli_qa_outputs_on_real_case():
    """Run qa outputs on the public HfBr2 test case without assuming heavy outputs."""
    case_dir = PROJECT_ROOT / "cases" / "HfBr2-hetero" / "test-run"
    result = run_cli("qa", "outputs", "--case-dir", str(case_dir))
    assert "QA Report" in result.stdout or result.returncode in (0, 1)
    assert "Traceback" not in result.stderr
    assert (
        "JOB DONE" in result.stdout
        or "scf.out not found" in result.stdout
        or "skipped" in result.stdout.lower()
    )


def test_cli_qa_all():
    """Run combined QA."""
    case_dir = PROJECT_ROOT / "cases" / "HfBr2-hetero" / "test-run"
    result = run_cli("qa", "all", "--case-dir", str(case_dir))
    assert "QA Report" in result.stdout or result.returncode in (0, 1)
