"""Generate Slurm job scripts for VibeDFT workflows.

All QE execution MUST go through ``sbatch + srun``.  Direct QE execution
on login nodes (``mpirun pw.x < in > out``) is FORBIDDEN.

The launcher is configurable via the ``launcher`` parameter:
  - ``"srun"`` (default) — ``srun -n {np} {exe} -in {input} > {output}``
  - ``"mpirun"`` (legacy) — ``mpirun -np {np} {exe} < {input} > {output}``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


# Default paths — customize via profile or override arguments.
# All paths use placeholders; replace with your cluster configuration.
_DEFAULTS = {
    "partition": "debug",
    "nodes": 1,
    "ntasks": 4,
    "walltime": "UNLIMITED",
    "omp_threads": 1,
    "qe_bin_dir": "<QE_BIN_DIR>",
    "intel_setvars": "<INTEL_SETVARS_SCRIPT>",
    "work_dir": "<REMOTE_WORKDIR>",
    "job_name": "VibeDFT",
    "launcher": "srun",
}

# Launcher templates:
#   {launcher}  — launcher command (srun | mpirun)
#   {np}       — number of MPI ranks
#   {exe}      — full path to the QE executable
#   {input}    — input file name
#   {output}   — output file name
_LAUNCHER_TEMPLATES = {
    "srun": "{launcher} -n {np} {exe} -in {input} > {output}",
    "mpirun": "{launcher} -np {np} {exe} < {input} > {output}",
}


def render_slurm_script(
    *,
    stages: list[dict[str, Any]],
    job_name: str | None = None,
    partition: str | None = None,
    nodes: int | None = None,
    ntasks: int | None = None,
    walltime: str | None = None,
    work_dir: str | None = None,
    qe_bin_dir: str | None = None,
    intel_setvars: str | None = None,
    omp_threads: int | None = None,
    launcher: str | None = None,
) -> str:
    r"""Render a Slurm job script for a sequence of computation stages.

    Each *stage* dict must have:

    - ``label`` — human-readable stage name
    - ``executable`` — program to run (relative to qe_bin_dir)
    - ``input`` — input file name
    - ``output`` — output file name
    - ``np`` — number of MPI ranks for this stage (default: ntasks)

    Example::

        stages = [
            {"label": "SCF",    "executable": "pw.x",  "input": "scf.in",    "output": "scf.out"},
            {"label": "NSCF",   "executable": "pw.x",  "input": "nscf.in",   "output": "nscf.out",  "np": 4},
            {"label": "DOS",    "executable": "dos.x", "input": "dos.in",    "output": "dos.out",   "np": 1},
        ]

    Returns the Slurm script as a string.
    """
    p = partition or _DEFAULTS["partition"]
    n = nodes or _DEFAULTS["nodes"]
    nt = ntasks or _DEFAULTS["ntasks"]
    wt = walltime or _DEFAULTS["walltime"]
    wd = work_dir or _DEFAULTS["work_dir"]
    qe = qe_bin_dir or _DEFAULTS["qe_bin_dir"]
    isv = intel_setvars or _DEFAULTS["intel_setvars"]
    omp = omp_threads or _DEFAULTS["omp_threads"]
    jn = job_name or _DEFAULTS["job_name"]
    lch = launcher or _DEFAULTS["launcher"]

    launcher_template = _LAUNCHER_TEMPLATES.get(lch)
    if launcher_template is None:
        raise ValueError(
            f"Unknown launcher '{lch}'. Supported: {', '.join(_LAUNCHER_TEMPLATES)}"
        )

    lines = [
        "#!/bin/bash",
        "#SBATCH --mem=0",
        f"#SBATCH -J {jn}",
        f"#SBATCH -p {p}",
        f"#SBATCH --time={wt}",
        f"#SBATCH -N {n}",
        f"#SBATCH -n {nt}",
        f"#SBATCH -o {jn}-%j.out",
        f"#SBATCH -e {jn}-%j.err",
        "",
        "set -u",
        "",
        'if [ -z "${SETVARS_COMPLETED:-}" ]; then',
        "  set +u",
        f"  source {isv} 2>/dev/null",
        "  set -u",
        "fi",
        "",
        f"export OMP_NUM_THREADS={omp}",
        f'PW="{qe}/pw.x"',
        "",
        f'cd "{wd}" || exit 1',
        "",
    ]

    for i, stage in enumerate(stages, 1):
        label = stage.get("label", f"Step-{i}")
        exe = stage.get("executable", "pw.x")
        inp = stage["input"]
        out = stage["output"]
        np_val = stage.get("np", nt)

        lines.append(f'echo "=== Step {i}: {label} ==="')
        # Run any pre-stage commands (e.g. NSCF save staging)
        for cmd in stage.get("pre_commands", []):
            if cmd.strip():
                lines.append(cmd)
        lines.append(
            launcher_template.format(
                launcher=lch,
                np=np_val,
                exe=f'"{qe}/{exe}"' if lch == "mpirun" else f'{qe}/{exe}',
                input=inp,
                output=out,
            )
        )
        lines.append("ret=$?")
        lines.append('if [ "$ret" -ne 0 ]; then')
        lines.append(f'  echo "{label} failed with exit code $ret"')
        lines.append("  exit $ret")
        lines.append("fi")
        lines.append(f'echo "{label} completed"')
        lines.append("")

    lines.append('echo "=== Job Complete ==="')
    return "\n".join(lines) + "\n"


def write_slurm_script(
    output: Path | str,
    **kwargs: Any,
) -> Path:
    """Render and write a Slurm script to *output*.

    Accepts the same keyword arguments as :func:`render_slurm_script`.
    """
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = render_slurm_script(**kwargs)
    output_path.write_text(content, encoding="utf-8")
    return output_path
