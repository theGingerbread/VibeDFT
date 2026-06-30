"""Tests for 2D materials property analyzers (Sprint 12)."""

import os
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "vibedft", *args],
        cwd=PROJECT_ROOT,
        env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Work Function
# ═══════════════════════════════════════════════════════════════════════════════


def test_work_function_from_avg_dat(tmp_path):
    """Parse work function from avg.dat."""
    avg = tmp_path / "output" / "avg.dat"
    avg.parent.mkdir(parents=True)
    lines = []
    for i in range(10):
        lines.append(f"  {i*4:.3f}   0.500")
    avg.write_text("\n".join(lines))
    # Also need an SCF output for EF
    scf = tmp_path / "output" / "scf.out"
    scf.write_text("the Fermi energy is     1.0000 ev\n JOB DONE\n")

    from vibedft.properties.work_function import analyze_work_function
    result = analyze_work_function(tmp_path)
    assert result.status == "ok"
    assert result.data["fermi_energy_ev"] == 1.0
    assert "work_function_ev" in result.data


def test_work_function_missing(tmp_path):
    """Should return 'missing' when no avg.dat."""
    from vibedft.properties.work_function import analyze_work_function
    result = analyze_work_function(tmp_path)
    assert result.status == "missing"


# ═══════════════════════════════════════════════════════════════════════════════
# Bader Charge
# ═══════════════════════════════════════════════════════════════════════════════


def test_bader_from_acf_dat(tmp_path):
    """Parse Bader ACF.dat."""
    acf = tmp_path / "ACF.dat"
    acf.write_text("""\
   #   X        Y        Z     CHARGE    MIN DIST   ATOMIC VOL
 ---- ------- ------- ------- ---------- ---------- -----------
    1  1.234   2.345   3.456    12.3456     1.2345    123.4567
    2  2.345   3.456   4.567     7.6543     2.3456    234.5678
 -------------------------------------------
  VACUUM CHARGE:    0.0123
  NUMBER OF ELECTRONS:   20.0000
""")
    from vibedft.properties.bader_parser import analyze_bader
    result = analyze_bader(tmp_path)
    assert result.status == "ok"
    assert result.data["n_atoms"] == 2
    assert abs(result.data["total_charge"] - 20.0) < 0.1


def test_bader_missing(tmp_path):
    """Should return 'missing' when no ACF.dat."""
    from vibedft.properties.bader_parser import analyze_bader
    result = analyze_bader(tmp_path)
    assert result.status == "missing"


# ═══════════════════════════════════════════════════════════════════════════════
# ELF
# ═══════════════════════════════════════════════════════════════════════════════


def test_elf_from_2d_file(tmp_path):
    """Parse ELF from .elf2d file."""
    elf = tmp_path / "output" / "test.elf2d"
    elf.parent.mkdir(parents=True)
    elf.write_text("""\
   10   10    1
  0.05 0.10 0.15 0.20 0.25 0.30 0.85 0.90 0.92 0.95
  0.50 0.50 0.50 0.50 0.50 0.50 0.50 0.50 0.50 0.50
  0.01 0.02 0.03 0.04 0.05 0.06 0.07 0.08 0.09 0.10
""")
    from vibedft.properties.elf_analyzer import analyze_elf
    result = analyze_elf(tmp_path)
    assert result.status == "ok"
    assert result.data["n_points"] >= 10
    assert result.data["elf_max"] > 0.9


def test_elf_missing(tmp_path):
    """Should return 'missing' when no ELF file."""
    from vibedft.properties.elf_analyzer import analyze_elf
    result = analyze_elf(tmp_path)
    assert result.status == "missing"


# ═══════════════════════════════════════════════════════════════════════════════
# AIMD
# ═══════════════════════════════════════════════════════════════════════════════


def test_aimd_from_md_output(tmp_path):
    """Parse AIMD stability from md.out."""
    md = tmp_path / "output" / "md.out"
    md.parent.mkdir(parents=True)
    lines = []
    for i in range(50):
        lines.append(f"     temperature   =   {300 + i*0.5} K")
        lines.append(f"!    total energy              =    -100.{i:04d} Ry")
    md.write_text("\n".join(lines))

    from vibedft.properties.aimd_analyzer import analyze_aimd
    result = analyze_aimd(tmp_path)
    assert result.status == "ok"
    assert result.data["n_steps"] == 50
    assert 300 < result.data["temperature_mean_K"] < 330


def test_aimd_detects_melting(tmp_path):
    """Rapid temperature rise should flag melting."""
    md = tmp_path / "md.out"
    lines = []
    for i in range(20):
        lines.append(f"     temperature   =   {300 + i*30} K")
    md.write_text("\n".join(lines))

    from vibedft.properties.aimd_analyzer import analyze_aimd
    result = analyze_aimd(tmp_path)
    assert result.data["is_melting"] or result.data["temperature_drift_K"] > 100


def test_aimd_missing(tmp_path):
    """Should return 'missing' when no MD output."""
    from vibedft.properties.aimd_analyzer import analyze_aimd
    result = analyze_aimd(tmp_path)
    assert result.status == "missing"


# ═══════════════════════════════════════════════════════════════════════════════
# CLI + Bundle
# ═══════════════════════════════════════════════════════════════════════════════


def test_property_cli_json(tmp_path):
    """vibedft property analyze --json should work."""
    # Add a Bader file so at least one property returns 'ok'
    acf = tmp_path / "ACF.dat"
    acf.write_text("""\
    1  0.0 0.0 0.0    6.5000     1.0   10.0
 -------------------------------------------
  NUMBER OF ELECTRONS:    6.5000
""")
    result = run_cli("property", "analyze", "--case-dir", str(tmp_path), "--json")
    assert result.returncode == 0, result.stderr
    import json
    data = json.loads(result.stdout)
    assert "properties" in data
    assert "bader_charge" in data["properties"]


def test_property_bundle_all_analyzers(tmp_path):
    """Bundle should run all analyzers without crashing."""
    from vibedft.properties.base import analyze_all_properties
    bundle = analyze_all_properties(tmp_path)
    assert len(bundle.properties) == 4
    for name, pr in bundle.properties.items():
        assert pr.status in ("ok", "missing", "error")
