"""Tests for vibedft review command and review module."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

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


# ── Helpers ──


def _make_case_dir(tmp_path: Path, name: str = "test-case") -> Path:
    d = tmp_path / name
    (d / "input").mkdir(parents=True, exist_ok=True)
    (d / "output").mkdir(parents=True, exist_ok=True)
    return d


def _write_scf_input(case_dir: Path, **kwargs) -> Path:
    """Write a minimal SCF input file. Extra kwargs override defaults."""
    defaults = {
        "calculation": "scf",
        "prefix": "test",
        "outdir": "./out_scf/",
        "pseudo_dir": "./pseudo/",
        "ecutwfc": 60,
        "ecutrho": 480,
        "occupations": "smearing",
        "smearing": "gaussian",
        "degauss": "3.7d-3",
        "assume_isolated": "",
        "cell_dofree": "",
        "nk1": 12, "nk2": 12, "nk3": 1,
        "ntyp": 1, "nat": 1,
    }
    params = {**defaults, **kwargs}

    content = f"""\
&CONTROL
  calculation = '{params['calculation']}'
  prefix = '{params['prefix']}'
  outdir = '{params['outdir']}'
  pseudo_dir = '{params['pseudo_dir']}'
/
&SYSTEM
  ibrav = 0
  nat = {params['nat']}
  ntyp = {params['ntyp']}
  ecutwfc = {params['ecutwfc']}
  ecutrho = {params['ecutrho']}
  occupations = '{params['occupations']}'
  smearing = '{params['smearing']}'
  degauss = {params['degauss']}
"""
    if params["assume_isolated"]:
        content += f"  assume_isolated = '{params['assume_isolated']}'\n"
    if params["cell_dofree"]:
        content += f"  cell_dofree = '{params['cell_dofree']}'\n"
    content += """/
&ELECTRONS
  conv_thr = 1.0d-12
/
ATOMIC_SPECIES
  H 1.0 H.UPF
ATOMIC_POSITIONS crystal
  H 0.0 0.0 0.0
K_POINTS automatic
"""
    content += f"  {params['nk1']} {params['nk2']} {params['nk3']}  0 0 0\n"
    content += """CELL_PARAMETERS angstrom
  3.0 0.0 0.0
  0.0 3.0 0.0
  0.0 0.0 30.0
"""
    p = case_dir / "input" / "scf.in"
    p.write_text(content)
    return p


def _write_scf_input_filename(case_dir: Path, filename: str, **kwargs) -> Path:
    """SCF input with an explicit filename (for multi-prefix cases)."""
    defaults = {
        "calculation": "scf",
        "prefix": "test",
        "outdir": "./out_scf/",
        "pseudo_dir": "./pseudo/",
        "ecutwfc": 60,
        "ecutrho": 480,
        "occupations": "smearing",
        "smearing": "gaussian",
        "degauss": "3.7d-3",
        "assume_isolated": "",
        "cell_dofree": "",
        "nk1": 12, "nk2": 12, "nk3": 1,
        "ntyp": 1, "nat": 1,
    }
    params = {**defaults, **kwargs}
    content = f"""\
&CONTROL
  calculation = '{params['calculation']}'
  prefix = '{params['prefix']}'
  outdir = '{params['outdir']}'
  pseudo_dir = '{params['pseudo_dir']}'
/
&SYSTEM
  ibrav = 0
  nat = {params['nat']}
  ntyp = {params['ntyp']}
  ecutwfc = {params['ecutwfc']}
  ecutrho = {params['ecutrho']}
  occupations = '{params['occupations']}'
  smearing = '{params['smearing']}'
  degauss = {params['degauss']}
"""
    if params["assume_isolated"]:
        content += f"  assume_isolated = '{params['assume_isolated']}'\n"
    if params["cell_dofree"]:
        content += f"  cell_dofree = '{params['cell_dofree']}'\n"
    content += """\
&ELECTRONS
  conv_thr = 1.0d-12
/
ATOMIC_SPECIES
  H 1.0 H.UPF
ATOMIC_POSITIONS crystal
  H 0.0 0.0 0.0
K_POINTS automatic
"""
    content += f"  {params['nk1']} {params['nk2']} {params['nk3']}  0 0 0\n"
    content += """CELL_PARAMETERS angstrom
  3.0 0.0 0.0
  0.0 3.0 0.0
  0.0 0.0 30.0
"""
    p = case_dir / "input" / filename
    p.write_text(content)
    return p


def _write_scf_output(case_dir: Path, converged: bool = True) -> Path:
    text = f"""\
     Program PWSCF v.7.1 starts
     Self-consistent Calculation
!    total energy              =    -100.0 Ry
"""
    if converged:
        text += "     convergence has been achieved\n"
    else:
        text += "     convergence NOT achieved after 100 iterations\n"
    text += "     JOB DONE\n"
    p = case_dir / "output" / "scf.out"
    p.write_text(text)
    return p


def _write_vc_relax_output(case_dir: Path) -> Path:
    """A vc-relax output: BFGS header + embedded SCF blocks + variable-cell
    markers. Must classify as vc-relax, NOT scf (regression for G3)."""
    text = """\
     Program PWSCF v.7.1 starts
     A final scf calculation is now performed
     Self-consistent Calculation
!    total energy              =    -447.34 Ry
     convergence has been achieved
     BFGS Geometry Optimization
     variable-cell optimization
     new unit-cell dimensions
     JOB DONE
"""
    p = case_dir / "output" / "vc-relax.out"
    p.write_text(text)
    return p


def _write_ph_epc_input(case_dir: Path, **kwargs) -> Path:
    defaults = {
        "prefix": "test", "outdir": "./out_scf/", "fildyn": "dyn",
        "nq1": 8, "nq2": 8, "nq3": 1, "electron_phonon": "dvscf",
        "tr2_ph": "1.0d-14",
    }
    params = {**defaults, **kwargs}
    content = f"""\
&INPUTPH
  prefix = '{params['prefix']}'
  outdir = '{params['outdir']}'
  fildyn = '{params['fildyn']}'
  ldisp = .true.
  nq1 = {params['nq1']}
  nq2 = {params['nq2']}
  nq3 = {params['nq3']}
  start_q = 1
  last_q = 1
  electron_phonon = '{params['electron_phonon']}'
  tr2_ph = {params['tr2_ph']}
/
"""
    p = case_dir / "input" / "ph_epc.in"
    p.write_text(content)
    return p


def _write_ph_epc_input_filename(case_dir: Path, filename: str, **kwargs) -> Path:
    """PH EPC input with an explicit filename (for multi-prefix cases)."""
    defaults = {
        "prefix": "test", "outdir": "./out_scf/", "fildyn": "dyn",
        "nq1": 8, "nq2": 8, "nq3": 1, "electron_phonon": "dvscf",
        "tr2_ph": "1.0d-14",
    }
    params = {**defaults, **kwargs}
    content = f"""\
&INPUTPH
  prefix = '{params['prefix']}'
  outdir = '{params['outdir']}'
  fildyn = '{params['fildyn']}'
  ldisp = .true.
  nq1 = {params['nq1']}
  nq2 = {params['nq2']}
  nq3 = {params['nq3']}
  start_q = 1
  last_q = 1
  electron_phonon = '{params['electron_phonon']}'
  tr2_ph = {params['tr2_ph']}
/
"""
    p = case_dir / "input" / filename
    p.write_text(content)
    return p


def _write_q2r_input(case_dir: Path, **kwargs) -> Path:
    defaults = {"fildyn": "dyn", "flfrc": "fc", "zasr": "crystal"}
    params = {**defaults, **kwargs}
    content = f"""\
&INPUT
  fildyn = '{params['fildyn']}'
  flfrc = '{params['flfrc']}'
  zasr = '{params['zasr']}'
"""
    if "la2f" in params:
        content += f"  la2F = .{str(params['la2f']).lower()}.\n"
    content += "/\n"
    p = case_dir / "input" / "q2r.in"
    p.write_text(content)
    return p


def _write_lambda_input(case_dir: Path, mustar: float = 0.1) -> Path:
    p = case_dir / "input" / "lambdax.in"
    p.write_text(f"""\
&INPUT
  mustar = {mustar}
/
0.001 0.020 0.001
""")
    return p


# ── Tests ──


def test_review_empty_case_dir(tmp_path):
    """Review of an empty case dir should report no files."""
    d = _make_case_dir(tmp_path)
    result = run_cli("review", "--case-dir", str(d))
    assert result.returncode == 0
    assert "No .in or .out files found" in result.stdout


def test_review_scf_only(tmp_path):
    """Review of a case with only SCF input + output."""
    d = _make_case_dir(tmp_path)
    _write_scf_input(d)
    _write_scf_output(d)

    result = run_cli("review", "--case-dir", str(d))
    assert result.returncode == 0
    assert "pw.x → scf" in result.stdout
    assert "qe.scf.v1" in result.stdout
    assert "JOB DONE" in result.stdout
    assert "SCF converged" in result.stdout


def test_review_scf_only_json(tmp_path):
    """Review JSON output should have correct structure."""
    d = _make_case_dir(tmp_path)
    _write_scf_input(d)
    _write_scf_output(d)

    result = run_cli("review", "--case-dir", str(d), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)

    assert data["files_scanned"] == 2
    assert data["files_inspected"] == 2
    assert len(data["inspection"]["tasks"]) >= 1
    assert data["best_workflow"] is not None
    assert data["best_workflow"]["workflow_id"] == "qe.scf.v1"
    assert "summary" in data
    assert "next_step" in data


def test_review_detects_la2f_in_q2r(tmp_path):
    """Review should flag la2F in q2r.x as an ERROR."""
    d = _make_case_dir(tmp_path)
    _write_scf_input(d)
    _write_q2r_input(d, la2f=True)

    result = run_cli("review", "--case-dir", str(d), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)

    error_ids = []
    for iss in data["inspection"]["issues"]:
        error_ids.append(iss["id"])
    for iss in data["validation_issues"]:
        error_ids.append(iss["id"])
    assert "q2r.la2f.forbidden" in error_ids or "q2r.la2f_forbidden" in error_ids


def test_review_detects_ph_prefix_mismatch(tmp_path):
    """Review should flag PH prefix mismatch with SCF."""
    d = _make_case_dir(tmp_path)
    _write_scf_input(d, prefix="HfBr2")
    _write_ph_epc_input(d, prefix="WrongPrefix")

    result = run_cli("review", "--case-dir", str(d), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)

    all_issues = data["inspection"]["issues"] + data["validation_issues"]
    messages = [i["message"] for i in all_issues]
    assert any(("prefix" in m.lower() and ("match" in m.lower() or "does not match" in m.lower()))
               for m in messages), \
        f"Expected prefix mismatch message, got: {messages}"


def test_review_multi_prefix_no_false_positive(tmp_path):
    """Multiple independent pw→ph sub-calculations in one case-dir must NOT
    each be flagged as mismatched. Regression for the 144 false-positive
    ph.prefix_mismatch/outdir_mismatch errors seen on the cluster-a K-HfCl2
    TOP_clean case (which bundles hfcl2_K_TOP + hfcl2_K_TOP_softq_e120 +
    hfcl2_KTOP_q5_1x2_plus, each with its own pw→ph pair).
    """
    d = _make_case_dir(tmp_path)
    # Sub-calculation A: prefix alpha, outdir ./out_a/
    _write_scf_input(d, prefix="alpha", outdir="./out_a/")
    _write_ph_epc_input_filename(d, "ph_a.in", prefix="alpha", outdir="./out_a/")
    # Sub-calculation B: prefix beta, outdir ./out_b/
    _write_scf_input_filename(d, "scf_b.in", prefix="beta", outdir="./out_b/")
    _write_ph_epc_input_filename(d, "ph_b.in", prefix="beta", outdir="./out_b/")

    result = run_cli("review", "--case-dir", str(d), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)

    val_ids = [i["id"] for i in data["validation_issues"]]
    n_prefix = val_ids.count("ph.prefix_mismatch")
    n_outdir = val_ids.count("ph.outdir_mismatch")
    assert n_prefix == 0, (
        f"Multi-prefix case should NOT raise ph.prefix_mismatch (each PH has a "
        f"matching PW); got {n_prefix}. Issue ids: {val_ids}"
    )
    assert n_outdir == 0, (
        f"Multi-prefix case should NOT raise ph.outdir_mismatch (each PH has a "
        f"matching PW); got {n_outdir}. Issue ids: {val_ids}"
    )


def test_review_multi_prefix_real_mismatch_still_flagged(tmp_path):
    """A PH whose prefix matches NO pw.x in the case must still be flagged,
    even when other (correct) pw→ph pairs exist in the same case-dir."""
    d = _make_case_dir(tmp_path)
    _write_scf_input(d, prefix="alpha", outdir="./out_a/")
    _write_ph_epc_input_filename(d, "ph_a.in", prefix="alpha", outdir="./out_a/")
    # A second PH that references a prefix with no matching pw.x
    _write_ph_epc_input_filename(d, "ph_orphan.in", prefix="orphan", outdir="./out_orphan/")

    result = run_cli("review", "--case-dir", str(d), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)

    val_ids = [i["id"] for i in data["validation_issues"]]
    assert "ph.prefix_mismatch" in val_ids, (
        f"PH with no matching pw.x should still raise ph.prefix_mismatch; "
        f"got ids: {val_ids}"
    )


def test_review_outdir_path_normalization_no_false_positive(tmp_path):
    """PH outdir './out/' and SCF outdir 'out/' (or 'out') refer to the same
    directory and must NOT be flagged as mismatched. Regression for G8:
    string comparison flagged equivalent paths that differed only in
    './' prefix or trailing slash."""
    d = _make_case_dir(tmp_path)
    _write_scf_input_filename(d, "scf.in", prefix="test", outdir="./out/")
    _write_ph_epc_input_filename(d, "ph.in", prefix="test", outdir="out/")

    result = run_cli("review", "--case-dir", str(d), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)

    val_ids = [i["id"] for i in data["validation_issues"]]
    assert "ph.outdir_mismatch" not in val_ids, (
        f"PH outdir 'out/' should match SCF outdir './out/' after normalization; "
        f"got ids: {val_ids}"
    )


def test_review_detects_2d_vacuum_warning(tmp_path):
    """Review should warn about 2D slab without assume_isolated."""
    d = _make_case_dir(tmp_path)
    _write_scf_input(d)  # default c=30Å, no assume_isolated

    result = run_cli("review", "--case-dir", str(d), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)

    all_issues = data["inspection"]["issues"] + data["validation_issues"]
    ids = [i["id"] for i in all_issues]
    assert any("2d" in i.lower() for i in ids), f"Expected 2D warning, got ids: {ids}"


def test_review_vc_relax_output_not_misclassified_as_scf(tmp_path):
    """A vc-relax output (which embeds SCF blocks per ionic step) must
    classify as vc-relax, NOT scf. Regression for G3: the original
    _infer_task_type_from_output checked 'Self-consistent Calculation'
    before BFGS, so every vc-relax run was misclassified as scf."""
    d = _make_case_dir(tmp_path)
    _write_scf_input(d, calculation="vc-relax", prefix="test",
                     outdir="./out_scf/", cell_dofree="2Dxy")
    _write_vc_relax_output(d)

    result = run_cli("inspect", str(d / "output" / "vc-relax.out"), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    tasks = data.get("tasks", [])
    assert tasks, "Expected at least one task from vc-relax.out"
    tt = tasks[0]["task_type"]
    assert tt == "vc-relax", (
        f"vc-relax output should classify as vc-relax, not scf; got task_type={tt!r}. "
        f"Full task: {tasks[0]}"
    )


def test_review_workflow_matches_epc(tmp_path):
    """A case with SCF + PH_EPC + Q2R + lambda should match EPC workflow."""
    d = _make_case_dir(tmp_path)
    _write_scf_input(d)
    _write_ph_epc_input(d)
    _write_q2r_input(d)
    _write_lambda_input(d)

    result = run_cli("review", "--case-dir", str(d), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)

    # EPC workflow parts are present — should appear in workflow matches
    wf_ids = [m["workflow_id"] for m in data["workflow_matches"]]
    assert "qe.ph_epc.v1" in wf_ids

    # EPC workflow should have partial completeness
    epc_match = next(m for m in data["workflow_matches"] if m["workflow_id"] == "qe.ph_epc.v1")
    assert epc_match["completeness"] > 0.3  # SCF + PH_EPC + Q2R + LAMBDA = 4 of 7 present


def test_review_lambda_without_epc(tmp_path):
    """lambda.x without preceding EPC should generate an error."""
    d = _make_case_dir(tmp_path)
    _write_scf_input(d)
    _write_lambda_input(d)  # No PH_EPC input

    result = run_cli("review", "--case-dir", str(d), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)

    all_issues = data["inspection"]["issues"] + data["validation_issues"]
    ids = [i["id"] for i in all_issues]
    assert any("lambda" in i.lower() and ("epc" in i.lower() or "predecessor" in i.lower() or "preceding" in i.lower())
               for i in ids), f"Expected lambda-no-epc error, got ids: {ids}"


def test_review_scf_not_converged(tmp_path):
    """Review should flag non-converged SCF."""
    d = _make_case_dir(tmp_path)
    _write_scf_input(d)
    _write_scf_output(d, converged=False)

    result = run_cli("review", "--case-dir", str(d))
    assert result.returncode == 0
    assert "NOT converged" in result.stdout or "not_converged" in result.stdout or "not converged" in result.stdout.lower()


def test_review_ph_stability_vs_epc(tmp_path):
    """PH_STABILITY should be distinct from PH_EPC in review output."""
    d = _make_case_dir(tmp_path)
    _write_scf_input(d)
    # Write a ph.x input WITHOUT electron_phonon
    ph_stab = d / "input" / "ph_stab.in"
    ph_stab.write_text("""\
&INPUTPH
  prefix = 'test'
  outdir = './out_scf/'
  fildyn = 'dyn'
  ldisp = .true.
  nq1 = 8
  nq2 = 8
  nq3 = 1
  tr2_ph = 1.0d-14
/
""")

    result = run_cli("review", "--case-dir", str(d), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)

    task_types = [t["task_type"] for t in data["inspection"]["tasks"]]
    assert "ph_stability" in task_types, f"Expected ph_stability task, got: {task_types}"
    assert "ph_epc" not in task_types, "PH without electron_phonon should be ph_stability, not ph_epc"
