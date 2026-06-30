"""Batch-2 post-processing parsers for QE dos.x / projwfc.x / bands.x / dynmat.x.

Covers the stdout (.out) physics-quantity extractors that complement the
existing data-file parsers (parse_dos_output / parse_bands_output parse the
``.dos`` / ``.bands`` data files; these new parsers handle the ``.out``
stdout that previously had no content extraction).
"""

from __future__ import annotations

from pathlib import Path

from vibedft.core.analysis import (
    BandsxOutput,
    DosxOutput,
    ProjwfcOutput,
    parse_bandsx_output,
    parse_dosx_output,
    parse_projwfc_output,
)
from vibedft.core.phonon import DynmatOutput, parse_dynmat_output


# ---------------------------------------------------------------------------
# dos.x stdout
# ---------------------------------------------------------------------------

SAMPLE_DOSX_OUT = """\
     Program DOS v.7.1 starts on  6Jun2026 at 15:21:22

     Gaussian broadening (read from input): ngauss,degauss=   0    0.010000
     Emin, Emax, E (eV):    -10.0000   10.0000    0.0100

     DOS          :      2.64s CPU      3.00s WALL

   JOB DONE.
"""

SAMPLE_NON_DOSX_OUT = """\
     Program PWSCF v.7.1 starts on  6Jun2026 at 14:37:44
     convergence has been achieved in 2 iterations
   JOB DONE.
"""


def test_parse_dosx_output(tmp_path: Path):
    out = tmp_path / "dos.out"
    out.write_text(SAMPLE_DOSX_OUT, encoding="utf-8")

    result = parse_dosx_output(out)

    assert isinstance(result, DosxOutput)
    assert result is not None
    assert result.ngauss == 0
    assert abs(result.degauss - 0.01) < 1e-9
    assert abs(result.emin - (-10.0)) < 1e-6
    assert abs(result.emax - 10.0) < 1e-6
    assert abs(result.delta_e - 0.01) < 1e-6
    assert result.job_done is True
    assert result.source_file == str(out)


def test_parse_dosx_not_dos(tmp_path: Path):
    out = tmp_path / "scf.out"
    out.write_text(SAMPLE_NON_DOSX_OUT, encoding="utf-8")

    assert parse_dosx_output(out) is None


def test_parse_dosx_missing_file(tmp_path: Path):
    assert parse_dosx_output(tmp_path / "nonexistent.out") is None


# ---------------------------------------------------------------------------
# projwfc.x stdout
# ---------------------------------------------------------------------------

SAMPLE_PROJWFC_OUT = """\
     Program PROJWFC v.7.1 starts on  6Jun2026 at 15:30:11

     Lowest eigenvalues of the subspace:

     Lowdin Charges:

     Atom #   1: total charge =  11.6018, s =  2.4973, p =  5.9915, d =  3.1130
     Atom #   2: total charge =  11.6018, s =  2.4973, p =  5.9915, d =  3.1130

     Spilling Parameter:   0.0058

   JOB DONE.
"""


def test_parse_projwfc_output(tmp_path: Path):
    out = tmp_path / "projwfc.out"
    out.write_text(SAMPLE_PROJWFC_OUT, encoding="utf-8")

    result = parse_projwfc_output(out)

    assert isinstance(result, ProjwfcOutput)
    assert result is not None
    assert len(result.lowdin_charges) == 2
    assert result.lowdin_charges[0]["atom"] == 1
    assert abs(result.lowdin_charges[0]["total_charge"] - 11.6018) < 1e-6
    assert abs(result.lowdin_charges[0]["s"] - 2.4973) < 1e-6
    assert abs(result.lowdin_charges[0]["p"] - 5.9915) < 1e-6
    assert abs(result.lowdin_charges[0]["d"] - 3.1130) < 1e-6
    assert result.lowdin_charges[1]["atom"] == 2
    assert abs(result.spilling_parameter - 0.0058) < 1e-9
    assert result.job_done is True
    assert result.source_file == str(out)


def test_parse_projwfc_not_projwfc(tmp_path: Path):
    out = tmp_path / "scf.out"
    out.write_text(SAMPLE_NON_DOSX_OUT, encoding="utf-8")

    assert parse_projwfc_output(out) is None


def test_parse_projwfc_missing_file(tmp_path: Path):
    assert parse_projwfc_output(tmp_path / "nonexistent.out") is None


# ---------------------------------------------------------------------------
# bands.x stdout
# ---------------------------------------------------------------------------

SAMPLE_BANDSX_OUT = """\
     Program BANDS v.7.1 starts on  6Jun2026 at 15:26:11

     nbnd =       17
     number of k points =       50

     BANDS        :      0.50s CPU      0.55s WALL

   JOB DONE.
"""


def test_parse_bandsx_output(tmp_path: Path):
    out = tmp_path / "bands.out"
    out.write_text(SAMPLE_BANDSX_OUT, encoding="utf-8")

    result = parse_bandsx_output(out)

    assert isinstance(result, BandsxOutput)
    assert result is not None
    assert result.job_done is True
    assert result.n_bands == 17
    assert result.n_kpoints == 50
    assert result.source_file == str(out)


def test_parse_bandsx_not_bands(tmp_path: Path):
    out = tmp_path / "scf.out"
    out.write_text(SAMPLE_NON_DOSX_OUT, encoding="utf-8")

    assert parse_bandsx_output(out) is None


def test_parse_bandsx_missing_file(tmp_path: Path):
    assert parse_bandsx_output(tmp_path / "nonexistent.out") is None


# ---------------------------------------------------------------------------
# dynmat.x output
# ---------------------------------------------------------------------------

SAMPLE_DYNMAT_OUT = """\
     diagonalizing the dynamical matrix ...

 q =       0.0000      0.0000      0.0000
     freq (    1) =      -4.721556 [THz] =    -157.494161 [cm-1]
 (  0.000000   0.000000    -0.000000   0.000000     0.013659   0.000000   )
     freq (    2) =      -2.704900 [THz] =    -90.230000 [cm-1]
 (  0.000000   0.000000     0.000000   0.000000     0.000000   0.000000   )
     freq (    3) =       5.123456 [THz] =    170.780000 [cm-1]
 (  0.000000   0.000000     0.000000   0.000000     0.000000   0.000000   )

     IR activities are in (D/A)^2/amu units
# mode   [cm-1]    [THz]      IR
    1   -157.49   -4.7216    0.0000
    2    -90.23   -2.7049    0.0000
    3    170.78    5.1235    1.2345

   JOB DONE.
"""

SAMPLE_NON_DYNMAT_OUT = """\
     Program PWSCF v.7.1 starts on  6Jun2026 at 14:37:44
   JOB DONE.
"""


def test_parse_dynmat_output(tmp_path: Path):
    out = tmp_path / "dynmat.out"
    out.write_text(SAMPLE_DYNMAT_OUT, encoding="utf-8")

    result = parse_dynmat_output(out)

    assert isinstance(result, DynmatOutput)
    assert result is not None
    assert len(result.q_point) == 3
    assert all(abs(v - 0.0) < 1e-6 for v in result.q_point)
    assert result.n_modes == 3
    assert len(result.frequencies_cm1) == 3
    assert len(result.frequencies_thz) == 3
    assert abs(result.frequencies_cm1[0] - (-157.494161)) < 1e-4
    assert abs(result.frequencies_thz[0] - (-4.721556)) < 1e-4
    assert result.has_imaginary is True
    assert len(result.ir_activities) == 3
    assert abs(result.ir_activities[2] - 1.2345) < 1e-6
    assert result.source_file == str(out)


def test_parse_dynmat_not_dynmat(tmp_path: Path):
    out = tmp_path / "scf.out"
    out.write_text(SAMPLE_NON_DYNMAT_OUT, encoding="utf-8")

    assert parse_dynmat_output(out) is None


def test_parse_dynmat_missing_file(tmp_path: Path):
    assert parse_dynmat_output(tmp_path / "nonexistent.out") is None
