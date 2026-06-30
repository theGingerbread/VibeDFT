import subprocess
import sys
import os
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


def _make_relax_output(
    *,
    energy: float,
    converged: bool,
    force: float,
    job_done: bool,
    steps: int = 1,
) -> str:
    lines = [
        " Program PWSCF v.7.2 starts",
    ]

    for index in range(steps):
        lines.append(" Self-consistent Calculation")
        lines.append(f"iteration #  1     total energy              =    {energy:.6f} Ry")
        lines.append("estimated scf accuracy    <       1.0E-03 Ry")
        if converged:
            lines.append("convergence has been achieved in   1 iterations")
        else:
            lines.append("convergence NOT achieved after 100 iterations")
        lines.append("Forces acting on atoms (cartesian axes, Ry/au):")
        lines.append(" atom    1 type  1   force =   0.100000  0.000000  0.000000")
        lines.append(" atom    2 type  1   force =  -0.100000  0.000000  0.000000")
        lines.append(f" total force   {force:.6E}")
        lines.append("     total   stress  (Ry/bohr**3)                   (kbar)     P=      5.0")
        lines.append("  0.10  0.00  0.00   1.00  2.00  3.00")
        lines.append("  0.00  0.10  0.00   4.00  5.00  6.00")
        lines.append("  0.00  0.00  0.10   7.00  8.00  9.00")
        lines.append("BFGS Geometry Optimization")
        lines.append("  number of scf cycles    =   1")
        lines.append("  number of bfgs steps    =   0")
        lines.append("End of BFGS Geometry Optimization")
        lines.append("End of self-consistent calculation")
        if index < steps - 1:
            lines.append("ATOMIC_POSITIONS (crystal)")
            lines.append("Na  0.000100  0.000200  0.000300")

    if job_done:
        lines.append("JOB DONE.")
    return "\n".join(lines)


def test_cli_lists_plugins():
    result = run_cli("plugin", "list")

    assert result.returncode == 0
    assert "qe" in result.stdout
    assert "vasp" in result.stdout


def test_cli_inspects_parameter():
    result = run_cli("params", "inspect", "qe.pw.system.ecutwfc")

    assert result.returncode == 0
    assert "Wavefunction cutoff" in result.stdout
    assert "Ry" in result.stdout


def test_cli_resolves_parameters():
    result = run_cli(
        "params",
        "resolve",
        "--software",
        "qe",
        "--workflow",
        "qe.scf_dos.v1",
        "--material",
        "HfBr2",
        "--profile",
        "qe-hfx2-scf-dos",
    )

    assert result.returncode == 0
    assert "qe.pw.system.ecutwfc" in result.stdout
    assert "value: 80" in result.stdout
    assert "source: profile:qe-hfx2-scf-dos" in result.stdout


def test_cli_analyze_scf(tmp_path):
    scf_out = tmp_path / "scf.out"
    scf_out.write_text("""\
     Program PWSCF v.7.1 starts
     iteration #  1     total energy              =    -184.77093016 Ry
     estimated scf accuracy    <       1.0E-12 Ry
     the Fermi energy is    -1.1120 ev
     convergence has been achieved in 1 iterations
     number of scf cycles    =   1
!    total energy              =    -184.77093016 Ry
     PWSCF        :     18.84s CPU     21.47s WALL
""")
    result = run_cli("analyze", "scf", str(scf_out))
    assert result.returncode == 0
    assert "Total Energy" in result.stdout
    assert "SCF Converged" in result.stdout


def test_cli_analyze_dos(tmp_path):
    dos_file = tmp_path / "HfBr2.dos"
    dos_file.write_text("""\
#  E (eV)   dos(E)     Int dos(E) EFermi =   -0.463 eV
 -10.000  0.5273E-84  0.5273E-86
  -9.990  0.5273E-84  0.1055E-85
""")
    result = run_cli("analyze", "dos", str(dos_file))
    assert result.returncode == 0
    assert "Fermi Energy" in result.stdout
    assert "Data points" in result.stdout


def test_cli_analyze_bands(tmp_path):
    bands_file = tmp_path / "HfBr2.bands"
    bands_file.write_text("""\
 &plot nbnd=  2, nks=    3 /
            0.000000  0.000000  0.000000
  -10.000   -1.000
            0.250000  0.144338  0.000000
   -9.500   -0.500
            0.500000  0.000000  0.000000
   -9.000    0.000
""")
    result = run_cli("analyze", "bands", str(bands_file))
    assert result.returncode == 0
    assert "Bands" in result.stdout
    assert "k-points" in result.stdout


def test_cli_analyze_relax_compare(tmp_path):
    high = tmp_path / "high.out"
    low = tmp_path / "low.out"
    high.write_text(_make_relax_output(energy=-1.0, converged=True, force=0.03, job_done=True))
    low.write_text(_make_relax_output(energy=-2.0, converged=True, force=0.02, job_done=True))

    result = run_cli("analyze", "relax", str(high), str(low))

    assert result.returncode == 0
    assert "VibeDFT Relax Comparison" in result.stdout
    assert "Best run: low.out" in result.stdout


def test_cli_analyze_relax_compare_json(tmp_path):
    blocked = tmp_path / "blocked.out"
    bad = tmp_path / "bad.out"
    blocked.write_text(_make_relax_output(energy=-5.0, converged=False, force=0.05, job_done=True))
    bad.write_text(_make_relax_output(energy=-6.0, converged=True, force=0.02, job_done=False))

    result = run_cli("analyze", "relax", "--json", str(blocked), str(bad))

    assert result.returncode == 0
    payload = result.stdout.strip()
    assert payload.startswith("{")
    assert "\"runs\"" in payload


def test_cli_render_slurm(tmp_path):
    output = tmp_path / "job.slurm"
    result = run_cli(
        "render", "slurm",
        "--output", str(output),
    )
    assert result.returncode == 0
    assert output.exists()
    content = output.read_text()
    assert "#!/bin/bash" in content
    assert "sbatch" not in content  # sbatch directives use #SBATCH
    assert "#SBATCH" in content
    assert "srun" in content


def test_cli_render_ph_epc_slurm_uses_split_ph_inputs(tmp_path):
    output = tmp_path / "ph_epc.slurm"
    result = run_cli(
        "render",
        "slurm",
        "--workflow",
        "qe.ph_epc.v1",
        "--output",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    content = output.read_text()
    assert "-in phx.in > phx0.out" in content
    assert "-in phx1.in > phx1.out" in content
    assert "-in phx2.in > phx2.out" in content
    assert "-in phx3.in > phx3.out" in content


def test_cli_builds_html_workbench(tmp_path):
    output = tmp_path / "index.html"

    result = run_cli("html", "build", "--output", str(output))

    assert result.returncode == 0
    assert output.exists()
    assert "VibeDFT Analysis Workbench" in output.read_text()


def test_cli_builds_setup_window_bundle(tmp_path):
    result = run_cli(
        "setup",
        "build",
        "--software",
        "qe",
        "--workflow",
        "qe.scf_dos.v1",
        "--material",
        "HfBr2",
        "--profile",
        "qe-hfx2-test",
        "--output-dir",
        str(tmp_path),
    )

    assert result.returncode == 0
    assert (tmp_path / "setup.html").exists()
    assert (tmp_path / "vibedft.request.yaml").exists()

    html = (tmp_path / "setup.html").read_text()
    # New setup page has provenance chain and agent closed-loop notice
    assert "来源链" in html
    assert "Agent 闭环交互" in html


def test_cli_opens_setup_window_with_dry_run(tmp_path):
    result = run_cli(
        "setup",
        "open",
        "--software",
        "qe",
        "--workflow",
        "qe.scf_dos.v1",
        "--material",
        "HfBr2",
        "--profile",
        "qe-hfx2-test",
        "--output-dir",
        str(tmp_path),
        "--dry-run",
    )

    assert result.returncode == 0
    assert (tmp_path / "setup.html").exists()
    assert "Would open" in result.stdout


def test_cli_prints_slurm_runbook():
    result = run_cli("runbook", "slurm")

    assert result.returncode == 0
    assert "Slurm is mandatory" in result.stdout
    assert "scp" in result.stdout
    assert "sbatch" in result.stdout
    assert "analyze" in result.stdout


def test_nscf_uniform_slurm_has_pre_commands_before_mpirun(tmp_path):
    """pre_commands for .save staging must appear BEFORE mpirun/srun."""
    output = tmp_path / "nscf_uniform.slurm"
    result = run_cli(
        "render", "slurm",
        "--workflow", "qe.nscf_uniform.v1",
        "--output", str(output),
    )
    assert result.returncode == 0, result.stderr
    content = output.read_text()

    # Verify pre_commands exist
    assert "Staging SCF save" in content
    assert "mkdir -p out_nscf" in content
    assert "cp -r ../02_scf/out_scf" in content

    # Verify pre_commands appear BEFORE srun
    pre_idx = content.find("Staging SCF save")
    srun_idx = content.find("srun")
    assert pre_idx < srun_idx, (
        f"pre_commands (offset {pre_idx}) must appear before srun (offset {srun_idx})"
    )


def test_nscf_uniform_prefix_extraction_handles_all_quote_formats(tmp_path):
    """PREFIX extraction must handle single-quoted, double-quoted, and bare values."""
    output = tmp_path / "nscf_uniform.slurm"
    result = run_cli(
        "render", "slurm",
        "--workflow", "qe.nscf_uniform.v1",
        "--output", str(output),
    )
    assert result.returncode == 0, result.stderr
    content = output.read_text()

    # Verify the PREFIX extraction uses awk (robust) not just tr/sed
    assert "PREFIX=$(grep -iw 'prefix' nscf.in" in content, (
        "Prefix extraction command must grep for prefix in nscf.in"
    )
    assert "awk -F=" in content, (
        "Prefix extraction should use awk (handles all quote styles)"
    )
    # Verify octal escapes for single and double quotes are present
    assert "\\047" in content, "awk must strip single quotes (\\047)"
    assert "\\042" in content, "awk must strip double quotes (\\042)"


def test_nscf_uniform_staging_fails_with_exit_2(tmp_path):
    """Staging failure must exit 2 (not warning-continue)."""
    output = tmp_path / "nscf_uniform.slurm"
    result = run_cli(
        "render", "slurm",
        "--workflow", "qe.nscf_uniform.v1",
        "--output", str(output),
    )
    assert result.returncode == 0, result.stderr
    content = output.read_text()

    assert "exit 2" in content, (
        "NSCF staging failure must exit 2 to avoid wasting queue time"
    )
    # The error message should be clear
    assert "cannot stage SCF save" in content


def test_granular_workflow_slurm_has_pre_commands_reusable(tmp_path):
    """Verify that at least nscf_uniform has pre_commands; the pattern
    is reusable for other stages that need to stage upstream data."""
    output = tmp_path / "nscf_uniform.slurm"
    result = run_cli(
        "render", "slurm",
        "--workflow", "qe.nscf_uniform.v1",
        "--output", str(output),
    )
    assert result.returncode == 0, result.stderr
    content = output.read_text()

    # Verify pre_commands section exists and has expected structure
    lines = content.splitlines()
    stage_section = False
    pre_cmds = []
    for line in lines:
        if "NSCF Uniform" in line:
            stage_section = True
            continue
        if stage_section and ("srun" in line or "mpirun" in line):
            break
        if stage_section and line.strip():
            pre_cmds.append(line.strip())
    assert len(pre_cmds) >= 4, (
        f"Expected at least 4 pre_command lines (PREFIX extraction + echo + mkdir + staging logic), "
        f"got {len(pre_cmds)}: {pre_cmds}"
    )


def test_dos_and_projwfc_outdir_point_to_nscf_uniform(tmp_path):
    """dos.v1 and projwfc.v1 must explicitly read from ../03_nscf_uniform/out_nscf/."""
    import yaml
    # Load workflow YAMLs directly
    workflows_dir = PROJECT_ROOT / "plugins" / "qe" / "workflows"
    for wf_name, param_key in [
        ("dos.yaml", "qe.dos.source_outdir"),
        ("projwfc.yaml", "qe.projwfc.source_outdir"),
    ]:
        wf_path = workflows_dir / wf_name
        wf_data = yaml.safe_load(wf_path.read_text())
        params = wf_data.get("parameters", {})
        source_outdir = params.get(param_key, "")
        assert "nscf_uniform" in str(source_outdir), (
            f"{wf_name}: {param_key}={source_outdir!r} must reference nscf_uniform, not scf_dos"
        )


# ── inspect command tests ──


def test_inspect_pw_input(tmp_path):
    """vibedft inspect should identify a pw.x SCF input file."""
    scf_in = tmp_path / "scf.in"
    scf_in.write_text("""\
&CONTROL
  calculation = 'scf'
  prefix = 'HfBr2'
  outdir = './out_scf/'
  pseudo_dir = '/path/to/pseudo'
/
&SYSTEM
  ibrav = 0
  nat = 3
  ntyp = 2
  ecutwfc = 80
  ecutrho = 640
  occupations = 'smearing'
  smearing = 'gaussian'
  degauss = 3.7d-3
/
&ELECTRONS
  conv_thr = 1.0d-12
/
ATOMIC_SPECIES
  Hf  178.49  Hf.pbe.UPF
  Br   79.904 Br.pbe.UPF
ATOMIC_POSITIONS crystal
  Hf  0.0  0.0  0.5
  Br  0.666666667  0.333333333  0.546176405
  Br  0.666666667  0.333333333  0.453823595
K_POINTS automatic
  12 12 1  0 0 0
CELL_PARAMETERS angstrom
  3.488143121  0.000000000  0.000000000
  -1.744071561  3.020820555  0.000000000
  0.000000000   0.000000000  40.000000000
""")
    result = run_cli("inspect", str(scf_in))
    assert result.returncode == 0, result.stderr
    assert "pw.x" in result.stdout
    assert "scf" in result.stdout
    assert "HfBr2" in result.stdout


def test_inspect_pw_input_json(tmp_path):
    """vibedft inspect --json should output valid JSON with correct structure."""
    import json
    scf_in = tmp_path / "scf.in"
    scf_in.write_text("""\
&CONTROL
  calculation = 'scf'
  prefix = 'test'
  outdir = './out/'
  pseudo_dir = './pseudo/'
/
&SYSTEM
  ibrav = 0
  nat = 1
  ntyp = 1
  ecutwfc = 60
  ecutrho = 480
/
&ELECTRONS
  conv_thr = 1.0d-12
/
ATOMIC_SPECIES
  H 1.0 H.UPF
ATOMIC_POSITIONS crystal
  H 0.0 0.0 0.0
K_POINTS automatic
  4 4 1 0 0 0
CELL_PARAMETERS angstrom
  3.0 0.0 0.0
  0.0 3.0 0.0
  0.0 0.0 20.0
""")
    result = run_cli("inspect", str(scf_in), "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "files" in data
    assert "tasks" in data
    assert "issues" in data
    assert len(data["files"]) == 1
    assert data["files"][0]["program"] == "pw.x"
    assert data["files"][0]["parse_status"] == "ok"
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["task_type"] == "scf"


def test_inspect_ph_epc_input(tmp_path):
    """vibedft inspect should identify a ph.x EPC input."""
    ph_in = tmp_path / "ph.in"
    ph_in.write_text("""\
&INPUTPH
  prefix = 'HfBr2'
  outdir = './out_scf/'
  fildyn = 'dyn'
  ldisp = .true.
  nq1 = 8
  nq2 = 8
  nq3 = 1
  start_q = 1
  last_q = 1
  electron_phonon = 'dvscf'
  tr2_ph = 1.0d-14
/
""")
    result = run_cli("inspect", str(ph_in), "--json")
    assert result.returncode == 0, result.stderr
    import json
    data = json.loads(result.stdout)
    assert data["files"][0]["program"] == "ph.x"
    assert data["tasks"][0]["task_type"] == "ph_epc"


def test_inspect_q2r_input(tmp_path):
    """vibedft inspect should identify a q2r.x input and flag la2F issues."""
    # Test 1: normal q2r input
    q2r_in = tmp_path / "q2r.in"
    q2r_in.write_text("""\
&INPUT
  fildyn = 'dyn'
  flfrc = 'fc'
  zasr = 'crystal'
/
""")
    result = run_cli("inspect", str(q2r_in), "--json")
    assert result.returncode == 0, result.stderr
    import json
    data = json.loads(result.stdout)
    assert data["files"][0]["program"] == "q2r.x"
    assert data["tasks"][0]["task_type"] == "q2r"

    # Test 2: q2r with forbidden la2F
    q2r_bad = tmp_path / "q2r_bad.in"
    q2r_bad.write_text("""\
&INPUT
  fildyn = 'dyn'
  flfrc = 'fc'
  zasr = 'crystal'
  la2F = .true.
/
""")
    result2 = run_cli("inspect", str(q2r_bad), "--json")
    data2 = json.loads(result2.stdout)
    error_ids = [i["id"] for i in data2["issues"]]
    assert "q2r.la2f.forbidden" in error_ids


def test_inspect_pp_input(tmp_path):
    """vibedft inspect should identify pp.x (&INPUTPP with plot_num/filplot).
    Regression for G6: pp.x was previously 'unknown'."""
    pp_in = tmp_path / "pp.in"
    pp_in.write_text("""\
&INPUTPP
  prefix = 'test'
  outdir = './out/'
  filplot = 'rho'
  plot_num = 0
/
&PLOT
  iflag = 3
  output_format = 6
  fileout = 'rho.dat'
/
""")
    result = run_cli("inspect", str(pp_in), "--json")
    assert result.returncode == 0, result.stderr
    import json
    data = json.loads(result.stdout)
    assert data["tasks"][0]["program"] == "pp.x", (
        f"pp.x &INPUTPP should classify as pp.x; got program="
        f"{data['tasks'][0]['program']}"
    )
    assert data["tasks"][0]["task_type"] == "pp_rho"


def test_inspect_dynmat_input(tmp_path):
    """vibedft inspect should identify dynmat.x (&input with fildyn + asr/filmol).
    Regression for G6: dynmat.x was previously 'unknown'."""
    dm_in = tmp_path / "dynmat.in"
    dm_in.write_text("""\
&input
  fildyn = 'dyn'
  filmol = 'modes.mol'
/
""")
    result = run_cli("inspect", str(dm_in), "--json")
    assert result.returncode == 0, result.stderr
    import json
    data = json.loads(result.stdout)
    assert data["tasks"][0]["program"] == "dynmat.x", (
        f"dynmat.x &input+fildyn+filmol should classify as dynmat.x; got "
        f"program={data['tasks'][0]['program']}"
    )
    assert data["tasks"][0]["task_type"] == "dynmat"

    # Variant: fildyn + asr (no filmol) — also dynmat.x
    dm_asr = tmp_path / "dynmat_asr.in"
    dm_asr.write_text("""\
&input
  fildyn = 'dyn'
  asr = 'crystal'
/
""")
    result2 = run_cli("inspect", str(dm_asr), "--json")
    data2 = json.loads(result2.stdout)
    assert data2["tasks"][0]["program"] == "dynmat.x", (
        f"dynmat.x &input+fildyn+asr should classify as dynmat.x; got "
        f"program={data2['tasks'][0]['program']}"
    )


def test_inspect_dynmat_output(tmp_path):
    """vibedft inspect should identify dynmat.x output by its banner
    (no 'Program DYNMAT' header exists). Regression for G4/G6."""
    out = tmp_path / "dynmat.out"
    out.write_text("""\
     diagonalizing the dynamical matrix ...

 q =       0.0000      0.0000      0.0000
     freq (    1) =      -4.721556 [THz] =    -157.494161 [cm-1]
     IR activities are in (D/A)^2/amu units
""")
    result = run_cli("inspect", str(out), "--json")
    assert result.returncode == 0, result.stderr
    import json
    data = json.loads(result.stdout)
    assert data["files"][0]["program"] == "dynmat.x", (
        f"dynmat output banner should detect dynmat.x; got "
        f"program={data['files'][0]['program']}"
    )


def test_inspect_output_file(tmp_path):
    """vibedft inspect should parse QE output and detect JOB DONE."""
    out = tmp_path / "scf.out"
    out.write_text("""\
     Program PWSCF v.7.1 starts
     Self-consistent Calculation
     iteration #  1     total energy              =    -184.77093016 Ry
     estimated scf accuracy    <       1.0E-12 Ry
     the Fermi energy is    -1.1120 ev
     convergence has been achieved
!    total energy              =    -184.77093016 Ry
     PWSCF        :     18.84s CPU     21.47s WALL
     JOB DONE
""")
    result = run_cli("inspect", str(out), "--json")
    assert result.returncode == 0, result.stderr
    import json
    data = json.loads(result.stdout)
    assert data["files"][0]["program"] == "pw.x"
    assert data["files"][0]["type"] == "output"
    assert data["tasks"][0]["task_type"] == "scf"
    issue_ids = [i["id"] for i in data["issues"]]
    assert "output.job_done" in issue_ids
    assert "output.scf.converged" in issue_ids


def test_inspect_multiple_files(tmp_path):
    """vibedft inspect should handle multiple files of different types."""
    # Create an input file
    inp = tmp_path / "scf.in"
    inp.write_text("""\
&CONTROL
  calculation = 'scf'
  prefix = 'test'
  outdir = './out/'
  pseudo_dir = './pseudo/'
/
&SYSTEM ibrav=0 nat=1 ntyp=1 ecutwfc=60 ecutrho=480 /
&ELECTRONS conv_thr=1.0d-12 /
ATOMIC_SPECIES
  H 1.0 H.UPF
ATOMIC_POSITIONS crystal
  H 0.0 0.0 0.0
K_POINTS automatic
  4 4 1 0 0 0
CELL_PARAMETERS angstrom
  3.0 0.0 0.0
  0.0 3.0 0.0
  0.0 0.0 20.0
""")
    # Create an output file
    out = tmp_path / "scf.out"
    out.write_text("""\
     Program PWSCF v.7.1 starts
     Self-consistent Calculation
     convergence has been achieved
!    total energy              =    -100.0 Ry
     JOB DONE
""")
    result = run_cli("inspect", str(inp), str(out))
    assert result.returncode == 0, result.stderr
    assert "2 files" in result.stdout
    assert "2 tasks" in result.stdout
