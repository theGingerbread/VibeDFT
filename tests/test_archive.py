"""Tests for archive bridge."""

import subprocess
import sys
import os
from pathlib import Path

from vibedft.core.archive import (
    build_archive_plan,
    apply_archive,
    _classify_file,
    ARCHIVE_EXCLUDES,
    STAGE_DIRS,
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


# ── File classifier ──


def test_classify_scf_dos_files():
    assert _classify_file("scf.out") == "scf_dos"
    assert _classify_file("HfBr2.dos") == "scf_dos"
    assert _classify_file("HfBr2.pdos_tot") == "scf_dos"
    assert _classify_file("HfBr2.pdos_atm#1(Hf)_wfc#4(d)") == "scf_dos"


def test_classify_bands_files():
    assert _classify_file("HfBr2.bands") == "bands"
    assert _classify_file("HfBr2.bands_v3") == "bands"
    assert _classify_file("bands.dat.gnu") == "bands"


def test_classify_ph_files():
    assert _classify_file("ele_0p05_ph64.freq.gp") == "ph"
    assert _classify_file("ele_0p05_ph64.fc") == "ph"


def test_classify_tc_epc_files():
    assert _classify_file("lambdax.out") == "tc"
    # lambda.dat in root → tc (filename fallback)
    assert _classify_file("lambda.dat") == "tc"
    assert _classify_file("alpha2F.dat") == "epc"
    assert _classify_file("tc_ele_0p05.png") == "tc"


def test_classify_parent_dir_overrides_filename():
    """Parent directory takes priority: epc/lambda.dat → epc, not tc."""
    assert _classify_file("lambda.dat", rel_parent="epc") == "epc"
    assert _classify_file("lambda.dat", rel_parent="ph64") == "ph"
    assert _classify_file("scf.out", rel_parent="scf_dos") == "scf_dos"
    assert _classify_file("freq.gp", rel_parent="ph96") == "ph"
    # In root, filename fallback still works
    assert _classify_file("lambda.dat", rel_parent="") == "tc"
    assert _classify_file("lambdax.out", rel_parent="") == "tc"


def test_archive_plan_respects_parent_dir(tmp_path: Path):
    """lambda.dat in output/epc/ must go to EPC, not Tc."""
    out = tmp_path / "output" / "epc"
    out.mkdir(parents=True)
    (out / "lambda.dat").write_text("0.005 1.45\n")
    (out / "alpha2F.dat").write_text("0.0 0.1\n")

    plan = build_archive_plan(
        tmp_path, system="HfX2", material="HfBr2", route="dopping",
        target_root=tmp_path / "target",
    )
    epc_actions = [a for a in plan.actions if a.stage == "epc"]
    tc_actions = [a for a in plan.actions if a.stage == "tc"]
    assert len(epc_actions) == 2, f"Expected 2 EPC actions, got {len(epc_actions)}"
    assert len(tc_actions) == 0, f"Expected 0 Tc actions, got {len(tc_actions)}: {[(a.source.name, a.stage) for a in tc_actions]}"


def test_classify_fs_files():
    assert _classify_file("hfbr2.bxsf") == "fs"


def test_classify_unknown():
    assert _classify_file("README.md") is None
    assert _classify_file("some_random_file.txt") is None


# ── Archive plan ──


def test_build_archive_plan_finds_outputs(tmp_path: Path):
    """Build archive plan on a synthetic case with known output files."""
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text("JOB DONE\n")
    (out / "HfBr2.dos").write_text("dos data\n")
    (out / "HfBr2.bands_v3").write_text("bands data\n")

    plan = build_archive_plan(
        tmp_path, system="HfX2", material="HfBr2", route="dopping",
        target_root=tmp_path / "archive_target",
    )

    assert plan.n_files == 3
    assert any(a.stage == "scf_dos" for a in plan.actions)
    assert any(a.stage == "bands" for a in plan.actions)


def test_archive_excludes_heavy_files(tmp_path: Path):
    """Archive must skip heavy output files."""
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text("data")
    (out / "CHGCAR").write_text("heavy")
    (out / "WAVECAR").write_text("heavy")

    plan = build_archive_plan(
        tmp_path, system="HfX2", material="HfBr2", route="dopping",
        target_root=tmp_path / "archive_target",
    )

    # CHGCAR and WAVECAR must be excluded
    assert plan.n_files == 1  # only scf.out
    excluded_names = [e.name for e in plan.excluded]
    assert "CHGCAR" in excluded_names
    assert "WAVECAR" in excluded_names


def test_archive_dry_run_does_not_copy(tmp_path: Path):
    """Dry-run should not create files."""
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text("test data")

    target = tmp_path / "archive_target"
    report = apply_archive(
        tmp_path, target_root=target, dry_run=True,
        system="HfX2", material="HfBr2", route="dopping",
    )

    assert "DRY-RUN" in report
    # With dry_run=True, the code still goes through the loop but doesn't copy
    # (the action.source → action.target line shows [DRY-RUN])


def test_archive_plan_empty_case(tmp_path: Path):
    """Archive plan on empty case should return no actions."""
    plan = build_archive_plan(
        tmp_path, target_root=tmp_path / "target",
    )
    assert plan.n_files == 0


# ── CLI ──


def test_cli_archive_plan():
    result = run_cli(
        "archive", "plan",
        "--case-dir", str(PROJECT_ROOT / "cases" / "HfBr2-test-run"),
        "--system", "HfX2", "--material", "HfBr2", "--route", "dopping",
        "--target-root", "/tmp/vibedft-archive-test",
    )
    assert result.returncode == 0
    assert "Archive Plan" in result.stdout
    assert "HfBr2" in result.stdout


def test_cli_archive_apply_dry_run():
    result = run_cli(
        "archive", "apply",
        "--case-dir", str(PROJECT_ROOT / "cases" / "HfBr2-test-run"),
        "--material", "HfBr2",
        "--route", "dopping",
        "--target-root", "/tmp/vibedft-archive-test",
        "--dry-run",
    )
    assert result.returncode == 0


def test_archive_dry_run_creates_no_target_directories(tmp_path: Path):
    """Dry-run must not create target directory structure (side-effect-free)."""
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text("test")

    target = tmp_path / "should_not_exist"
    apply_archive(
        tmp_path, target_root=target, dry_run=True,
        system="HfX2", material="HfBr2", route="dopping",
    )
    assert not target.exists(), f"Dry-run created directory: {target}"


def test_archive_policy_covers_all_heavy_patterns():
    """Verify the archive exclude list covers all required patterns."""
    required = [
        "out/", "*.save/", "_ph0/", "*.wfc*", "CHGCAR", "WAVECAR",
        "elph_dir/", "*.xml",
    ]
    for pat in required:
        assert pat in ARCHIVE_EXCLUDES, f"Missing archive exclude: {pat}"
