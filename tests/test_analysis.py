from pathlib import Path

from vibedft.core.analysis import (
    parse_qe_output,
    parse_dos_output,
    parse_bands_output,
    compute_k_distances,
)


SAMPLE_SCF_OUTPUT = """\
     Program PWSCF v.7.1 starts on  6Jun2026 at 14:37:44

     iteration #  1     ecut=    60.00 Ry     beta= 0.40
     total energy              =    -184.75013556 Ry
     estimated scf accuracy    <       0.09088794 Ry

     iteration #  2     ecut=    60.00 Ry     beta= 0.40
     total energy              =    -184.77093016 Ry
     estimated scf accuracy    <       1.0E-12 Ry

     the Fermi energy is    -1.1120 ev

     convergence has been achieved in 2 iterations

     number of scf cycles    =   2

!    total energy              =    -184.77093016 Ry

     PWSCF        :     18.84s CPU     21.47s WALL

   This run was terminated on:  14:38: 5   6Jun2026

   JOB DONE.
"""

SAMPLE_DOS_OUTPUT = """\
     Program DOS v.7.1 starts on  6Jun2026 at 15:21:22
     DOS          :      3.35s CPU      3.69s WALL
   JOB DONE.
"""

SAMPLE_DOS_DATA = """\
#  E (eV)   dos(E)     Int dos(E) EFermi =   -0.463 eV
 -10.000  0.5273E-84  0.5273E-86
  -9.990  0.5273E-84  0.1055E-85
  -9.980  0.5273E-84  0.1582E-85
"""

SAMPLE_BANDS_OUTPUT = """\
     Program BANDS v.7.1 starts on  6Jun2026 at 15:26:11
     BANDS        :      0.50s CPU      0.55s WALL
   JOB DONE.
"""

SAMPLE_BANDS_DATA = """\
 &plot nbnd=  2, nks=    3 /
            0.000000  0.000000  0.000000
  -10.000   -1.000
            0.250000  0.144338  0.000000
   -9.500   -0.500
            0.500000  0.000000  0.000000
   -9.000    0.000
"""


# ---------------------------------------------------------------------------
# SCF
# ---------------------------------------------------------------------------

def test_parse_qe_output_basic(tmp_path: Path):
    out = tmp_path / "scf.out"
    out.write_text(SAMPLE_SCF_OUTPUT)

    result = parse_qe_output(out)

    assert result.program == "PWSCF"
    assert result.version == "7.1"
    assert result.scf_converged is True
    assert result.scf_iterations == 2
    assert abs(result.total_energy_ry - (-184.77093016)) < 1e-8
    assert abs(result.fermi_energy_ev - (-1.1120)) < 1e-6
    assert abs(result.wall_time_sec - 21.47) < 0.01
    assert abs(result.cpu_time_sec - 18.84) < 0.01
    assert len(result.convergence_history) == 2


def test_parse_not_converged(tmp_path: Path):
    out = tmp_path / "scf.out"
    out.write_text("Program PWSCF v.7.2 starts\ntotal energy  =    -100.0 Ry\n")

    result = parse_qe_output(out)

    assert result.program == "PWSCF"
    assert result.version == "7.2"
    assert result.scf_converged is False


# ---------------------------------------------------------------------------
# DOS
# ---------------------------------------------------------------------------

def test_parse_dos_fermi_and_data(tmp_path: Path):
    dos_file = tmp_path / "HfBr2.dos"
    dos_file.write_text(SAMPLE_DOS_DATA)

    result = parse_dos_output(dos_file)

    assert abs(result.e_fermi_ev - (-0.463)) < 1e-6
    assert result.n_points == 3
    assert abs(result.e_min - (-10.0)) < 0.001
    assert abs(result.e_max - (-9.98)) < 0.001
    assert len(result.dos_data) == 3
    assert "energy_ev" in result.dos_data[0]
    assert "dos" in result.dos_data[0]
    assert "int_dos" in result.dos_data[0]


def test_parse_dos_with_stdout(tmp_path: Path):
    dos_file = tmp_path / "HfBr2.dos"
    dos_file.write_text(SAMPLE_DOS_DATA)
    out_file = tmp_path / "dos.out"
    out_file.write_text(SAMPLE_DOS_OUTPUT)

    result = parse_dos_output(dos_file, out_file)

    assert result.program == "DOS"
    assert result.version == "7.1"
    assert abs(result.wall_time_sec - 3.69) < 0.01
    assert abs(result.cpu_time_sec - 3.35) < 0.01
    assert result.n_points == 3


# ---------------------------------------------------------------------------
# Bands
# ---------------------------------------------------------------------------

def test_parse_bands_nbnd_nks(tmp_path: Path):
    bands_file = tmp_path / "HfBr2.bands"
    bands_file.write_text(SAMPLE_BANDS_DATA)

    result = parse_bands_output(bands_file)

    assert result.nbnd == 2
    assert result.nks == 3
    assert len(result.k_points) == 3
    assert len(result.bands) == 2
    # First band has 3 k-points
    assert len(result.bands[0]) == 3
    assert abs(result.bands[0][0] - (-10.0)) < 0.01
    assert abs(result.bands[1][-1] - 0.0) < 0.01


def test_parse_bands_with_stdout(tmp_path: Path):
    bands_file = tmp_path / "HfBr2.bands"
    bands_file.write_text(SAMPLE_BANDS_DATA)
    out_file = tmp_path / "bands.out"
    out_file.write_text(SAMPLE_BANDS_OUTPUT)

    result = parse_bands_output(bands_file, out_file)

    assert result.program == "BANDS"
    assert result.version == "7.1"
    assert abs(result.wall_time_sec - 0.55) < 0.01
    assert result.nbnd == 2


def test_compute_k_distances(tmp_path: Path):
    k_points = [
        [0.0, 0.0, 0.0],
        [0.25, 0.144338, 0.0],
        [0.5, 0.0, 0.0],
    ]
    dists = compute_k_distances(k_points)

    assert dists[0] == 0.0
    assert dists[1] > 0.0
    assert dists[2] > dists[1]
