"""Tests for remote execution lifecycle."""

import subprocess
import sys
import os
from pathlib import Path

from vibedft.core.remote import (
    RemoteRegistry,
    RemoteHost,
    build_remote_plan,
    validate_no_direct_dft_execution,
    HEAVY_OUTPUT_EXCLUDES,
    FORBIDDEN_DIRECT_COMMANDS,
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


# ── RemoteRegistry ──


def test_remote_registry_loads_profiles():
    reg = RemoteRegistry.from_project_root(PROJECT_ROOT)
    assert "workstation" in reg.hosts
    assert "cluster-a" in reg.hosts
    assert "cluster-b" in reg.hosts

    cl_a = reg.get("workstation")
    assert cl_a.host == "workstation.example.org"
    assert "screening" in cl_a.preferred_for

    cl_b = reg.get("cluster-a")
    assert "phonon" in cl_b.preferred_for


def test_remote_registry_unknown_host_raises():
    reg = RemoteRegistry.from_project_root(PROJECT_ROOT)
    try:
        reg.get("nonexistent")
        assert False, "Should have raised KeyError"
    except KeyError:
        pass


# ── RemotePlan ──


def test_build_remote_plan_has_all_steps(tmp_path: Path):
    host = RemoteHost(
        name="test", host="testhost", user="testuser",
        root="/home/test/work", qe_bin_dir="/home/test/qe/bin",
        intel_setvars="/data/intel/setvars.sh",
    )
    plan = build_remote_plan(tmp_path, host, case_id="test-case")

    actions = [s["action"] for s in plan.steps]
    assert actions == ["push", "submit", "status", "pull"]

    # Verify push uses rsync
    assert "rsync" in plan.steps[0]["command"]

    # Verify submit uses sbatch
    assert "sbatch" in plan.steps[1]["command"]

    # Verify no direct execution
    assert "pw.x <" not in plan.steps[1]["command"]


def test_remote_plan_markdown_log_rows(tmp_path: Path):
    host = RemoteHost(
        name="test", host="testhost", user="testuser",
        root="/home/test/work", qe_bin_dir="/home/test/qe/bin",
        intel_setvars="/data/intel/setvars.sh",
    )
    plan = build_remote_plan(tmp_path, host)

    rows = plan.markdown_log_rows()
    assert "push" in rows
    assert "submit" in rows
    assert "rsync" in rows
    assert "|" in rows  # Markdown table syntax


# ── Safety enforcement ──


def test_validate_no_direct_dft_execution_passes_clean_plan(tmp_path: Path):
    host = RemoteHost(
        name="test", host="testhost", user="testuser",
        root="/home/test/work", qe_bin_dir="/home/test/qe/bin",
        intel_setvars="/data/intel/setvars.sh",
    )
    plan = build_remote_plan(tmp_path, host)
    violations = validate_no_direct_dft_execution(plan)
    assert len(violations) == 0, f"Unexpected violations: {violations}"


def test_heavy_output_excludes_cover_critical_patterns():
    excludes_str = " ".join(HEAVY_OUTPUT_EXCLUDES)
    required = ["out/", "*.save/", "_ph0/", "*.wfc*", "CHGCAR", "WAVECAR", "elph_dir/"]
    for r in required:
        assert r in excludes_str.replace("--exclude='", "").replace("'", ""), f"Missing exclude: {r}"


# ── CLI ──


def test_cli_remote_plan():
    result = run_cli("remote", "plan", "--case-dir", str(PROJECT_ROOT / "cases" / "HfBr2-test-run"), "--host", "workstation")
    assert result.returncode == 0
    assert "workstation" in result.stdout
    assert "rsync" in result.stdout
    assert "sbatch" in result.stdout


def test_cli_remote_push():
    result = run_cli("remote", "push", "--case-dir", str(PROJECT_ROOT / "cases" / "HfBr2-test-run"), "--host", "workstation")
    assert result.returncode == 0
    assert "rsync" in result.stdout


def test_cli_remote_submit():
    result = run_cli("remote", "submit", "--case-dir", str(PROJECT_ROOT / "cases" / "HfBr2-test-run"), "--host", "workstation")
    assert result.returncode == 0
    assert "sbatch" in result.stdout
    assert "FORBIDDEN" in result.stdout


def test_cli_remote_push_with_custom_case_id():
    """push --case-id custom-name → output must reference custom-name, not dir name."""
    result = run_cli(
        "remote", "push",
        "--case-dir", str(PROJECT_ROOT / "cases" / "HfBr2-test-run"),
        "--host", "workstation",
        "--case-id", "custom-case-name",
    )
    assert result.returncode == 0
    # The remote path must use custom-case-name
    assert "custom-case-name" in result.stdout, (
        f"Remote path must use custom-case-name:\n{result.stdout}"
    )


def test_cli_remote_submit_with_case_id():
    """submit --case-id should use it in remote path."""
    result = run_cli(
        "remote", "submit",
        "--case-dir", str(PROJECT_ROOT / "cases" / "HfBr2-test-run"),
        "--host", "workstation",
        "--case-id", "my-case",
    )
    assert result.returncode == 0
    assert "my-case" in result.stdout


def test_cli_remote_unknown_host():
    result = run_cli("remote", "plan", "--case-dir", str(PROJECT_ROOT / "cases" / "HfBr2-test-run"), "--host", "nonexistent")
    assert result.returncode != 0
