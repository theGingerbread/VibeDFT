"""Batch-4 post-processing analyzers (ROADMAP §3.1).

Exercises the 8 new ``Analyzer`` subclasses in
``vibedft.analyzers.postprocess_analyzers`` against synthetic case
directories whose ``.out`` content is copied from the batch-2/batch-3
parser tests (``tests/test_batch2_parsers.py`` and
``tests/test_batch3_parsers.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

from vibedft.analyzers.base import get_all_analyzers, run_analyzer
from vibedft.analyzers.postprocess_analyzers import (
    AimdAnalyzer,
    AverageAnalyzer,
    BandsxAnalyzer,
    DosAnalyzer,
    DynmatAnalyzer,
    MagnetismAnalyzer,
    PpAnalyzer,
    ProjwfcAnalyzer,
)


SAMPLE_DOSX_OUT = """\
     Program DOS v.7.1 starts on  6Jun2026 at 15:21:22

     Gaussian broadening (read from input): ngauss,degauss=   0    0.010000
     Emin, Emax, E (eV):    -10.0000   10.0000    0.0100

     DOS          :      2.64s CPU      3.00s WALL

   JOB DONE.
"""

SAMPLE_PROJWFC_OUT = """\
     Program PROJWFC v.7.1 starts on  6Jun2026 at 15:30:11

     Lowest eigenvalues of the subspace:

     Lowdin Charges:

     Atom #   1: total charge =  11.6018, s =  2.4973, p =  5.9915, d =  3.1130
     Atom #   2: total charge =  11.6018, s =  2.4973, p =  5.9915, d =  3.1130

     Spilling Parameter:   0.0058

   JOB DONE.
"""

SAMPLE_BANDSX_OUT = """\
     Program BANDS v.7.1 starts on  6Jun2026 at 15:26:11

     nbnd =       17
     number of k points =       50

     BANDS        :      0.50s CPU      0.55s WALL

   JOB DONE.
"""

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

SAMPLE_MD_OUT = """\
     Program PWSCF v.7.1 starts on  6Jun2026 at 14:37:44

     nstep          = 3

   Averaged quantities:

     temperature=  300.02 K
!    total energy  =   -184.50000000 Ry

   Averaged quantities:

     temperature=  300.11 K
!    total energy  =   -184.65000000 Ry

   Averaged quantities:

     temperature=  300.20 K
!    total energy  =   -184.72891118 Ry

   JOB DONE.
"""

SAMPLE_MAGNETISM_OUT = """\
     Program PWSCF v.7.1 starts on  6Jun2026 at 14:37:44

     nspin          = 2
     starting_magnetization(1) = 0.5

     iteration #  1
     total magnetization       =     0.41 Bohr mag/cell
     absolute magnetization    =     0.82 Bohr mag/cell
!    total energy              =   -184.50000000 Ry

     iteration #  3
     total magnetization       =     0.53 Bohr mag/cell
     absolute magnetization    =     0.96 Bohr mag/cell
!    total energy              =   -184.72891118 Ry

     convergence has been achieved in 3 iterations

   JOB DONE.
"""


ANALYZER_CASES = [
    (DosAnalyzer, "dos.out", SAMPLE_DOSX_OUT),
    (ProjwfcAnalyzer, "projwfc.out", SAMPLE_PROJWFC_OUT),
    (BandsxAnalyzer, "bandsx.out", SAMPLE_BANDSX_OUT),
    (DynmatAnalyzer, "dynmat.out", SAMPLE_DYNMAT_OUT),
    (PpAnalyzer, "pp.out", SAMPLE_PP_OUT),
    (AverageAnalyzer, "average.out", SAMPLE_AVERAGE_OUT),
    (AimdAnalyzer, "md.out", SAMPLE_MD_OUT),
    (MagnetismAnalyzer, "scf_sp.out", SAMPLE_MAGNETISM_OUT),
]


def _run_case(tmp_path: Path, analyzer_cls, filename: str, content: str, label: str = "case"):
    case_dir = tmp_path / label
    case_dir.mkdir(exist_ok=True)
    (case_dir / filename).write_text(content, encoding="utf-8")
    analyzer = analyzer_cls()
    return run_analyzer(analyzer, case_dir)


def test_each_analyzer_passes(tmp_path: Path):
    for index, (analyzer_cls, filename, content) in enumerate(ANALYZER_CASES):
        result = _run_case(tmp_path, analyzer_cls, filename, content, label=f"case_{index}")
        assert result.section_id == analyzer_cls.id, analyzer_cls
        assert result.status == "pass", (analyzer_cls, result.status)
        assert result.insights, analyzer_cls
        assert "parser" in result.provenance, analyzer_cls
        assert result.provenance["source_files"], analyzer_cls
        assert result.provenance["parser"].startswith("vibedft.core."), analyzer_cls
        blob = json.dumps(result.to_dict())
        assert analyzer_cls.id in blob


def test_dos_analyzer_fields(tmp_path: Path):
    result = _run_case(tmp_path, DosAnalyzer, "dos.out", SAMPLE_DOSX_OUT)
    assert result.data["ngauss"] == 0
    assert abs(result.data["degauss"] - 0.01) < 1e-9
    assert result.data["job_done"] is True


def test_projwfc_analyzer_fields(tmp_path: Path):
    result = _run_case(tmp_path, ProjwfcAnalyzer, "projwfc.out", SAMPLE_PROJWFC_OUT)
    assert result.data["n_atoms"] == 2
    assert abs(result.data["spilling_parameter"] - 0.0058) < 1e-9


def test_bandsx_analyzer_fields(tmp_path: Path):
    result = _run_case(tmp_path, BandsxAnalyzer, "bandsx.out", SAMPLE_BANDSX_OUT)
    assert result.data["n_bands"] == 17
    assert result.data["n_kpoints"] == 50


def test_dynmat_analyzer_imaginary(tmp_path: Path):
    result = _run_case(tmp_path, DynmatAnalyzer, "dynmat.out", SAMPLE_DYNMAT_OUT)
    assert result.data["n_modes"] == 3
    assert result.data["has_imaginary"] is True
    assert any(
        i.level.value == "warning" and "imaginary" in i.message.lower()
        for i in result.insights
    )


def test_pp_analyzer_fields(tmp_path: Path):
    result = _run_case(tmp_path, PpAnalyzer, "pp.out", SAMPLE_PP_OUT)
    assert result.data["plot_num"] == 0
    assert result.data["is_elf"] is False
    assert result.data["filplot"] == "rho"


def test_average_analyzer_fields(tmp_path: Path):
    result = _run_case(tmp_path, AverageAnalyzer, "average.out", SAMPLE_AVERAGE_OUT)
    assert result.data["n_points"] == 5
    assert abs(result.data["z_min"] - 0.0) < 1e-9
    assert abs(result.data["z_max"] - 2.0) < 1e-9


def test_aimd_analyzer_fields(tmp_path: Path):
    result = _run_case(tmp_path, AimdAnalyzer, "md.out", SAMPLE_MD_OUT)
    assert result.data["n_steps"] == 3
    assert result.data["n_temperatures"] == 3
    assert abs(result.data["last_temperature"] - 300.20) < 1e-2
    assert result.data["job_done"] is True


def test_magnetism_analyzer_fields(tmp_path: Path):
    result = _run_case(tmp_path, MagnetismAnalyzer, "scf_sp.out", SAMPLE_MAGNETISM_OUT)
    assert abs(result.data["total_magnetization"] - 0.53) < 1e-9
    assert abs(result.data["absolute_magnetization"] - 0.96) < 1e-9
    assert result.data["nspin"] == 2


def test_missing_files_yield_missing(tmp_path: Path):
    case_dir = tmp_path / "empty"
    case_dir.mkdir()
    result = run_analyzer(DosAnalyzer(), case_dir)
    assert result.status == "missing"
    assert result.insights
    assert result.data == {}


def test_get_all_analyzers_count():
    ids = [a.id for a in get_all_analyzers()]
    expected = {
        "dos", "projwfc", "bandsx", "dynmat",
        "pp", "average", "aimd", "magnetism",
        "phonon_stability", "superconductivity",
    }
    assert expected.issubset(set(ids))
    assert len(ids) >= 10