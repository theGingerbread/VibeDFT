"""Batch-1 identification-layer fixes for QE output programs.

Covers:
  - pp.x   ``Program POST-PROC`` header (was wrongly ``Program PP``)
  - average.x ``Program AVERAGE`` header + PLANAR_AVERAGE task type
  - fs.x   ``Program FERMI``  header
  - pw.x  ``calculation='md'``  → AIMD task type (input + output)
  - parse_md_output structured extractor
  - real sample Type-III pp.out regression (skip if file absent)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vibedft.classifiers.task_classifier import (
    _detect_program_from_output,
    _infer_task_type_from_output,
    inspect_files,
)
from vibedft.core.analysis import MdOutput, parse_md_output
from vibedft.models.inspection import QEProgram, TaskType


SAMPLE_PP_OUT = Path(
    "/var/folders/tp/w79cv1_d7mxc0rdsms7m6tx80000gn/T/opencode/"
    "public-type3/hetero/HfBr2_TiSe2/pp.out"
)


# ---------------------------------------------------------------------------
# Task 1a: pp.x POST-PROC header
# ---------------------------------------------------------------------------

PP_POSTPROC_OUTPUT = """\
     Program POST-PROC v.7.1 starts on 18Jun2026 at 14:10:10

     Post-processing of charge density

     JOB DONE.
"""


def test_pp_postproc_header(tmp_path: Path):
    """pp.x prints ``Program POST-PROC v.7.1`` — must classify as pp.x."""
    out = tmp_path / "pp.out"
    out.write_text(PP_POSTPROC_OUTPUT, encoding="utf-8")

    result = inspect_files([out])
    assert result.files[0].program == QEProgram.PP, (
        f"Program POST-PROC header should classify as pp.x; got "
        f"program={result.files[0].program!r}"
    )
    assert result.tasks[0].program == QEProgram.PP
    assert result.tasks[0].task_type == TaskType.PP_RHO

    # Direct helper check too
    assert _detect_program_from_output(PP_POSTPROC_OUTPUT) == QEProgram.PP


def test_pp_postproc_header_sample_real_file():
    """Regression on representative Type-III pp.out (skip if file absent)."""
    if not SAMPLE_PP_OUT.is_file():
        pytest.skip(f"sample pp.out not present: {SAMPLE_PP_OUT}")

    result = inspect_files([SAMPLE_PP_OUT])
    assert result.files[0].program == QEProgram.PP, (
        f"sample pp.out should classify as pp.x; got "
        f"program={result.files[0].program!r}"
    )


# ---------------------------------------------------------------------------
# Task 1b: average.x AVERAGE header
# ---------------------------------------------------------------------------

AVERAGE_OUTPUT = """\
     Program AVERAGE v.7.1 starts on 25Jun2026 at 11:00:00

     Planar average of the charge

     JOB DONE.
"""


def test_average_header(tmp_path: Path):
    """average.x prints ``Program AVERAGE v.7.1`` → average.x / planar_average."""
    out = tmp_path / "avg.out"
    out.write_text(AVERAGE_OUTPUT, encoding="utf-8")

    result = inspect_files([out])
    assert result.files[0].program == QEProgram.AVERAGE, (
        f"Program AVERAGE header should classify as average.x; got "
        f"program={result.files[0].program!r}"
    )
    assert result.tasks[0].program == QEProgram.AVERAGE
    assert result.tasks[0].task_type == TaskType.PLANAR_AVERAGE

    assert _detect_program_from_output(AVERAGE_OUTPUT) == QEProgram.AVERAGE
    assert _infer_task_type_from_output(
        AVERAGE_OUTPUT, QEProgram.AVERAGE
    ) == TaskType.PLANAR_AVERAGE


# ---------------------------------------------------------------------------
# Task 1c: fs.x FERMI header
# ---------------------------------------------------------------------------

FS_FERMI_OUTPUT = """\
     Program FERMI v.7.1 starts on 25Jun2026 at 12:00:00

     Fermi surface calculation

     JOB DONE.
"""


def test_fs_fermi_header(tmp_path: Path):
    """fs.x prints ``Program FERMI v.7.1`` → fs.x."""
    out = tmp_path / "fs.out"
    out.write_text(FS_FERMI_OUTPUT, encoding="utf-8")

    result = inspect_files([out])
    assert result.files[0].program == QEProgram.FS, (
        f"Program FERMI header should classify as fs.x; got "
        f"program={result.files[0].program!r}"
    )
    assert result.tasks[0].program == QEProgram.FS

    assert _detect_program_from_output(FS_FERMI_OUTPUT) == QEProgram.FS


# ---------------------------------------------------------------------------
# Task 1d: AIMD (pw.x calculation='md') detection
# ---------------------------------------------------------------------------

AIMD_OUTPUT = """\
     Program PWSCF v.7.1 starts on 25Jun2026 at 10:00:00

     calculation                 =       'md'

     nstep                       =        100

     Starting temp             =  300.0000 K

     Self-consistent Calculation
     iteration #  1     total energy = -100.0 Ry
!    total energy              =   -100.00000000 Ry

     Averaged quantities
     temperature   =  300.00 K
     Ekin          =  0.00100 Ry
     Epot          =  -100.00100 Ry
     Total energy  =  -100.00000 Ry

     JOB DONE.
"""


def test_aimd_detection(tmp_path: Path):
    """pw.x output with calculation='md' + Starting temp → task_type=aimd.

    Regression: previously MD output fell through to SCF because it embeds
    'Self-consistent Calculation' blocks per MD step.
    """
    out = tmp_path / "md.out"
    out.write_text(AIMD_OUTPUT, encoding="utf-8")

    result = inspect_files([out])
    assert result.files[0].program == QEProgram.PW
    assert result.tasks[0].task_type == TaskType.AIMD, (
        f"pw.x calculation='md' output should classify as aimd; got "
        f"task_type={result.tasks[0].task_type!r}"
    )

    # Direct helper check
    assert _infer_task_type_from_output(
        AIMD_OUTPUT, QEProgram.PW
    ) == TaskType.AIMD


def test_aimd_detection_by_molecular_dynamics_keyword():
    """MD output without the calculation echo but with MD keywords → aimd."""
    text = """\
     Program PWSCF v.7.1 starts

     molecular dynamics simulation

     Self-consistent Calculation
!    total energy              =   -100.0 Ry

     JOB DONE.
"""
    assert _infer_task_type_from_output(text, QEProgram.PW) == TaskType.AIMD


def test_aimd_input_classification(tmp_path: Path):
    """pw.x input with calculation='md' → task_type=aimd."""
    inp = tmp_path / "md.in"
    inp.write_text(
        """\
&CONTROL
  calculation = 'md'
  prefix = 'test'
  outdir = './out/'
  pseudo_dir = './pseudo/'
/
&SYSTEM ibrav=0 nat=1 ntyp=1 ecutwfc=60 ecutrho=480 /
&ELECTRONS conv_thr=1.0d-12 /
&IONS ion_temperature='nose' /
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
""",
        encoding="utf-8",
    )

    result = inspect_files([inp])
    assert result.files[0].program == QEProgram.PW
    assert result.tasks[0].task_type == TaskType.AIMD, (
        f"pw.x calculation='md' input should classify as aimd; got "
        f"task_type={result.tasks[0].task_type!r}"
    )


# ---------------------------------------------------------------------------
# Task 1d: parse_md_output structured extractor
# ---------------------------------------------------------------------------

MD_OUTPUT_3_STEPS = """\
     Program PWSCF v.7.1 starts on 25Jun2026 at 10:00:00

     calculation                 =       'md'

     nstep                       =        100

     Self-consistent Calculation
     iteration #  1     total energy = -100.0 Ry
!    total energy              =   -100.00000000 Ry

     Averaged quantities
     temperature   =  300.00 K
     Ekin          =  0.00100 Ry
     Epot          =  -100.00100 Ry
     Total energy  =  -100.00000 Ry

     Self-consistent Calculation
     iteration #  1     total energy = -100.01 Ry
!    total energy              =   -100.01000000 Ry

     Averaged quantities
     temperature   =  301.50 K
     Ekin          =  0.00150 Ry
     Epot          =  -100.01150 Ry
     Total energy  =  -100.01000 Ry

     Self-consistent Calculation
     iteration #  1     total energy = -100.02 Ry
!    total energy              =   -100.02000000 Ry

     Averaged quantities
     temperature   =  298.50 K
     Ekin          =  0.00098 Ry
     Epot          =  -100.02098 Ry
     Total energy  =  -100.02000 Ry

     PWSCF        :     300.0s CPU     360.0s WALL

   JOB DONE.
"""


def test_parse_md_output(tmp_path: Path):
    """parse_md_output extracts n_steps, temperatures, energies, job_done."""
    out = tmp_path / "md.out"
    out.write_text(MD_OUTPUT_3_STEPS, encoding="utf-8")

    md = parse_md_output(out)
    assert isinstance(md, MdOutput)
    assert md.program == "PWSCF"
    assert md.version.startswith("7.1")
    assert md.n_steps == 3, f"expected 3 MD steps, got {md.n_steps}"
    assert md.job_done is True
    assert md.temperatures == [300.00, 301.50, 298.50], (
        f"temperatures mismatch: {md.temperatures}"
    )
    assert md.energies == [-100.0, -100.01, -100.02], (
        f"energies mismatch: {md.energies}"
    )
    assert md.cpu_time_sec == 300.0
    assert md.wall_time_sec == 360.0


def test_parse_md_output_fallback_to_energy_lines(tmp_path: Path):
    """Without 'Averaged quantities' blocks, n_steps counts energy lines."""
    text = """\
     Program PWSCF v.7.1 starts

     calculation = 'md'

!    total energy              =   -1.0 Ry
!    total energy              =   -2.0 Ry
     JOB DONE.
"""
    out = tmp_path / "md_no_avg.out"
    out.write_text(text, encoding="utf-8")

    md = parse_md_output(out)
    assert md.n_steps == 2
    assert md.energies == [-1.0, -2.0]
    assert md.temperatures == []
    assert md.job_done is True


def test_parse_md_output_no_job_done(tmp_path: Path):
    """Missing JOB DONE → job_done=False, still parses steps."""
    text = """\
     Program PWSCF v.7.1 starts

     calculation = 'md'

!    total energy              =   -1.0 Ry

     Averaged quantities
     temperature   =  300.00 K
"""
    out = tmp_path / "md_crashed.out"
    out.write_text(text, encoding="utf-8")

    md = parse_md_output(out)
    assert md.job_done is False
    assert md.n_steps == 1
    assert md.temperatures == [300.00]
    assert md.energies == [-1.0]
