"""Batch-3 post-processing parsers for QE pp.x / average.x / ELF / magnetism.

Covers:
* ``parse_pp_output`` — pp.x (``Program POST-PROC``) stdout metadata,
  including the ``is_elf`` flag for ``plot_num == 9``.
* ``parse_average_output`` — average.x (``Program AVERAGE``) planar
  average table.
* ``parse_magnetism_output`` — spin-polarized pw.x (``nspin=2``)
  total/absolute magnetization + total energy.
"""

from __future__ import annotations

from pathlib import Path

from vibedft.core.analysis import (
    AverageOutput,
    MagnetismOutput,
    PpOutput,
    parse_average_output,
    parse_magnetism_output,
    parse_pp_output,
)


# ---------------------------------------------------------------------------
# pp.x stdout
# ---------------------------------------------------------------------------

SAMPLE_PP_OUT = """\
     Program POST-PROC v.7.1 starts on  6Jun2026 at 15:21:22

     Reading data from file: rho.dat

     plot_num        = 0
     filplot         = rho
     iflag           = 0
     output_format   = 6
     fileout         = rho.cube

     Writing data to file rho.cube
     Integrated charge=       12.3456

   JOB DONE.
"""

SAMPLE_PP_ELF_OUT = """\
     Program POST-PROC v.7.1 starts on  6Jun2026 at 15:21:22

     plot_num        = 9
     filplot         = elf
     iflag           = 0
     output_format   = 6
     fileout         = elf.cube

   JOB DONE.
"""

SAMPLE_NON_PP_OUT = """\
     Program PWSCF v.7.1 starts on  6Jun2026 at 14:37:44
     convergence has been achieved in 2 iterations
   JOB DONE.
"""


def test_parse_pp_output(tmp_path: Path):
    out = tmp_path / "pp.out"
    out.write_text(SAMPLE_PP_OUT, encoding="utf-8")

    result = parse_pp_output(out)

    assert isinstance(result, PpOutput)
    assert result is not None
    assert result.plot_num == 0
    assert result.filplot == "rho"
    assert result.output_format == 6
    assert result.iflag == 0
    assert result.fileout == "rho.cube"
    assert abs(result.integrated_charge - 12.3456) < 1e-6
    assert result.is_elf is False
    assert result.job_done is True
    assert result.source_file == str(out)


def test_parse_pp_elf(tmp_path: Path):
    out = tmp_path / "pp_elf.out"
    out.write_text(SAMPLE_PP_ELF_OUT, encoding="utf-8")

    result = parse_pp_output(out)

    assert isinstance(result, PpOutput)
    assert result is not None
    assert result.plot_num == 9
    assert result.is_elf is True
    assert result.filplot == "elf"
    assert result.job_done is True


def test_parse_pp_not_pp(tmp_path: Path):
    out = tmp_path / "scf.out"
    out.write_text(SAMPLE_NON_PP_OUT, encoding="utf-8")

    assert parse_pp_output(out) is None


def test_parse_pp_missing_file(tmp_path: Path):
    assert parse_pp_output(tmp_path / "nonexistent.out") is None


# ---------------------------------------------------------------------------
# average.x stdout
# ---------------------------------------------------------------------------

SAMPLE_AVERAGE_OUT = """\
     Program AVERAGE v.7.1 starts on  6Jun2026 at 15:21:22

     Planar average of charge density
#  zcoord     average
   0.0000     0.1234
   0.5000     0.2345
   1.0000     0.3456
   1.5000     0.4567
   2.0000     0.5678

   JOB DONE.
"""

SAMPLE_NON_AVERAGE_OUT = """\
     Program PWSCF v.7.1 starts on  6Jun2026 at 14:37:44
   JOB DONE.
"""


def test_parse_average_output(tmp_path: Path):
    out = tmp_path / "average.out"
    out.write_text(SAMPLE_AVERAGE_OUT, encoding="utf-8")

    result = parse_average_output(out)

    assert isinstance(result, AverageOutput)
    assert result is not None
    assert result.n_points == 5
    assert len(result.z_values) == 5
    assert len(result.averages) == 5
    assert abs(result.z_values[0] - 0.0) < 1e-9
    assert abs(result.z_values[-1] - 2.0) < 1e-9
    assert abs(result.averages[0] - 0.1234) < 1e-9
    assert abs(result.averages[-1] - 0.5678) < 1e-9
    assert result.job_done is True
    assert result.source_file == str(out)


def test_parse_average_not_average(tmp_path: Path):
    out = tmp_path / "scf.out"
    out.write_text(SAMPLE_NON_AVERAGE_OUT, encoding="utf-8")

    assert parse_average_output(out) is None


def test_parse_average_missing_file(tmp_path: Path):
    assert parse_average_output(tmp_path / "nonexistent.out") is None


# ---------------------------------------------------------------------------
# pw.x spin-polarized output  (magnetism)
# ---------------------------------------------------------------------------

SAMPLE_MAGNETISM_OUT = """\
     Program PWSCF v.7.1 starts on  6Jun2026 at 14:37:44

     nspin          = 2
     starting_magnetization(1) = 0.5

     iteration #  1
     total magnetization       =     0.41 Bohr mag/cell
     absolute magnetization    =     0.82 Bohr mag/cell
!    total energy              =   -184.50000000 Ry

     iteration #  2
     total magnetization       =     0.49 Bohr mag/cell
     absolute magnetization    =     0.91 Bohr mag/cell
!    total energy              =   -184.65000000 Ry

     iteration #  3
     total magnetization       =     0.53 Bohr mag/cell
     absolute magnetization    =     0.96 Bohr mag/cell
!    total energy              =   -184.72891118 Ry

     convergence has been achieved in 3 iterations

   JOB DONE.
"""

SAMPLE_NON_MAGNETIC_OUT = """\
     Program PWSCF v.7.1 starts on  6Jun2026 at 14:37:44

     nspin          = 1

     iteration #  1
!    total energy              =   -100.00000000 Ry

   JOB DONE.
"""


def test_parse_magnetism_output(tmp_path: Path):
    out = tmp_path / "scf_mag.out"
    out.write_text(SAMPLE_MAGNETISM_OUT, encoding="utf-8")

    result = parse_magnetism_output(out)

    assert isinstance(result, MagnetismOutput)
    assert result is not None
    assert abs(result.total_magnetization - 0.53) < 1e-9
    assert abs(result.absolute_magnetization - 0.96) < 1e-9
    assert abs(result.total_energy_ry - (-184.72891118)) < 1e-6
    assert result.nspin == 2
    assert result.job_done is True
    assert result.source_file == str(out)


def test_parse_magnetism_not_magnetic(tmp_path: Path):
    out = tmp_path / "scf_nonmag.out"
    out.write_text(SAMPLE_NON_MAGNETIC_OUT, encoding="utf-8")

    assert parse_magnetism_output(out) is None


def test_parse_magnetism_missing_file(tmp_path: Path):
    assert parse_magnetism_output(tmp_path / "nonexistent.out") is None