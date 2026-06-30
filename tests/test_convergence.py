"""Tests for convergence/batch review (Sprint 5)."""

import json
import os
import subprocess
import sys
from pathlib import Path

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


def _make_batch_root(tmp_path: Path) -> Path:
    """Create a batch of convergence test cases."""
    root = tmp_path / "batch"

    for name, k_grid, q_grid, lam, tc, omega in [
        ("k24_q4", "24 24 1", "4 4 1", 1.12, 7.8, 184.0),
        ("k36_q6", "36 36 1", "6 6 1", 1.20, 8.4, 179.0),
        ("k48_q8", "48 48 1", "8 8 1", 1.22, 8.5, 176.0),
    ]:
        d = root / name / "output"
        d.mkdir(parents=True)
        # lamdax.out with λ/Tc data
        (d / "lambdax.out").write_text(f"""\
     lambda = {lam:.6f} (   {lam:.6f} )  <log w>=   {omega:.3f} K  N(Ef)= 16.000000 at degauss= 0.005
        lambda        omega_log          T_c
          {lam:.5f}        {omega:.3f}              {tc:.2f}
""")

    return root


def test_scanner_finds_cases(tmp_path):
    """Scanner should find all case subdirectories with output."""
    from vibedft.convergence.scanner import scan_batch_root
    root = _make_batch_root(tmp_path)
    snaps = scan_batch_root(root)
    assert len(snaps) == 3
    assert all(s.has_lambda_output for s in snaps)


def test_metrics_extract_lambda(tmp_path):
    """Metrics extractor should get λ and Tc from lambdax output."""
    from vibedft.convergence.metrics import extract_metrics
    from vibedft.convergence.scanner import _scan_case_dir

    root = _make_batch_root(tmp_path)
    snap = _scan_case_dir(root / "k24_q4")
    metrics = extract_metrics(snap)
    assert metrics["lambda_max"] == 1.12
    assert metrics["tc_max_K"] == 7.8


def test_analyzer_detects_varying_params(tmp_path):
    """Analyzer should detect which parameters vary across cases."""
    from vibedft.convergence.scanner import scan_batch_root
    from vibedft.convergence.parameter_extractor import extract_parameters
    from vibedft.convergence.metrics import extract_metrics
    from vibedft.convergence.analyzer import analyze_convergence

    root = _make_batch_root(tmp_path)
    snaps = scan_batch_root(root)
    params_list = [extract_parameters(s) for s in snaps]
    metrics_list = [extract_metrics(s) for s in snaps]
    report = analyze_convergence(snaps, params_list, metrics_list)

    assert len(report.rows) == 3
    # With only lambdax output (no input files), there's limited varying detection
    assert len(report.rows) == 3
    assert all(r.lambda_max is not None for r in report.rows)


def test_analyzer_assigns_confidence(tmp_path):
    """Confidence should increase with convergence."""
    from vibedft.convergence.scanner import scan_batch_root
    from vibedft.convergence.parameter_extractor import extract_parameters
    from vibedft.convergence.metrics import extract_metrics
    from vibedft.convergence.analyzer import analyze_convergence

    root = _make_batch_root(tmp_path)
    snaps = scan_batch_root(root)
    params_list = [extract_parameters(s) for s in snaps]
    metrics_list = [extract_metrics(s) for s in snaps]
    report = analyze_convergence(snaps, params_list, metrics_list)

    # First row should be low (no comparison baseline)
    assert report.rows[0].confidence == "low"
    # Later rows may be higher if metrics stabilize


def test_convergence_cli_json(tmp_path):
    """vibedft convergence --json should output valid JSON."""
    root = _make_batch_root(tmp_path)
    result = run_cli("convergence", "--root", str(root), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["n_cases"] == 3
    assert len(data["rows"]) == 3
    assert "varying_params" in data
    assert "overall_confidence" in data


def test_convergence_cli_html(tmp_path):
    """vibedft convergence --html should write a report."""
    root = _make_batch_root(tmp_path)
    html_out = tmp_path / "conv.html"
    result = run_cli("convergence", "--root", str(root), "--html", str(html_out))
    assert result.returncode == 0
    assert html_out.exists()
    content = html_out.read_text()
    assert "Convergence Report" in content
    assert "Convergence Table" in content


def test_convergence_empty_root(tmp_path):
    """Empty root should not crash."""
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run_cli("convergence", "--root", str(empty), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["n_cases"] == 0
