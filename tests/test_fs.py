"""Tests for Fermi surface BXSF parsing."""

from pathlib import Path

import vibedft.core.fs as fs
from vibedft.core.fs import parse_bxsf, BxsfData

SAMPLE_BXSF = """\
BEGIN_INFO
  Fermi Energy: -1.1120
END_INFO
BEGIN_BLOCK_BANDGRID_3D
  band_energies
  BANDGRID_3D_BANDS
  2
  3 3 1
  0.0 0.0 0.0
  0.5 0.0 0.0
  0.0 0.5 0.0
  0.5 0.5 0.0
  0.0 0.0 0.0
  0.5 0.0 0.0
  0.0 0.5 0.0
  0.5 0.5 0.0
  1.0 1.0 0.0
  BAND: 1
  -10.0 -9.0 -8.0
  -7.0 -6.0 -5.0
  -4.0 -3.0 -2.0
  BAND: 2
  -1.5 -1.0 -0.5
  0.0 0.5 1.0
  1.5 2.0 2.5
END_BLOCK_BANDGRID_3D
"""

REAL_DIALECT_BXSF = """\
BEGIN_INFO
  Fermi Energy: -1.0000
END_INFO
BEGIN_BLOCK_BANDGRID_3D
  band_energies
  BANDGRID_BANDS
  2
  3 3 1
  0.0 0.0 0.0
  1.0 0.0 0.0
  0.0 1.0 0.0
  0.0 0.0 1.0
  BAND: 1
  -2.0 -1.5 -0.5
  -1.4 -1.0 -0.2
  -0.4 -0.1 0.3
  BAND: 2
  1.0 1.2 1.4
  1.5 1.6 1.8
  2.0 2.2 2.4
END_BLOCK_BANDGRID_3D
"""

BEGIN_BANDGRID_DIALECT_BXSF = """\
BEGIN_INFO
  Fermi Energy: 0.0000
END_INFO
BEGIN_BANDGRID_3D
  1
  2 2 1
  0.0 0.0 0.0
  1.0 0.0 0.0
  0.0 1.0 0.0
  0.0 0.0 1.0
  BAND: 1
  -1.0 1.0
  1.0 -1.0
END_BANDGRID_3D
"""

SAMPLE_FS_OUT = """\
     Program FERMI v.7.1 starts on 25Jun2026 at 12:00:00

     Fermi surface calculation
     4 bands found crossing Ef = -2.182511

     JOB DONE.
"""


def test_parse_bxsf_basic(tmp_path: Path):
    f = tmp_path / "test.bxsf"
    f.write_text(SAMPLE_BXSF)

    data = parse_bxsf(f)
    assert data.has_data
    assert data.n_bands == 2
    assert data.n_k1 == 3
    assert data.n_k2 == 3
    assert data.n_k3 == 1
    assert data.n_kpoints == 9
    assert abs(data.fermi_energy_ev - (-1.112)) < 0.01


def test_parse_bxsf_fermi_surface_detection(tmp_path: Path):
    f = tmp_path / "test.bxsf"
    f.write_text(SAMPLE_BXSF)

    data = parse_bxsf(f)
    # Band 2 goes from -1.5 to 2.5 → crosses EF=0
    # Band 1 goes from -10 to -2 → does NOT cross
    assert data.has_fermi_surface
    assert 2 in data.bands_crossing_ef
    assert 1 not in data.bands_crossing_ef


def test_parse_bxsf_supports_real_dialects_and_reciprocal_vectors(tmp_path: Path):
    f = tmp_path / "real_dialect.bxsf"
    f.write_text(REAL_DIALECT_BXSF)

    data = parse_bxsf(f)

    assert data.has_data, data.parse_errors
    assert data.n_bands == 2
    assert data.n_k1 == 3
    assert data.n_k2 == 3
    assert data.n_k3 == 1
    assert data.reciprocal_vectors == [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    assert data.band_energies[0][0] == -2.0
    assert data.band_point_counts == [9, 9]
    assert data.bands_crossing_ef == [1]


def test_parse_bxsf_supports_begin_bandgrid_3d_marker(tmp_path: Path):
    f = tmp_path / "begin_bandgrid.bxsf"
    f.write_text(BEGIN_BANDGRID_DIALECT_BXSF)

    data = parse_bxsf(f)

    assert data.has_data, data.parse_errors
    assert data.n_bands == 1
    assert data.n_kpoints == 4
    assert data.bands_crossing_ef == [1]


def test_slice_kx_ky_returns_2d_grid_from_band_values(tmp_path: Path):
    f = tmp_path / "real_dialect.bxsf"
    f.write_text(REAL_DIALECT_BXSF)

    data = parse_bxsf(f)
    grid = fs.slice_kx_ky(data, band_index=1)

    assert grid == [
        [-2.0, -1.5, -0.5],
        [-1.4, -1.0, -0.2],
        [-0.4, -0.1, 0.3],
    ]


def test_parse_fs_out_extracts_crossing_count_and_fermi_energy(tmp_path: Path):
    f = tmp_path / "fs.out"
    f.write_text(SAMPLE_FS_OUT)

    data = fs.parse_fs_out(f)

    assert data.job_done is True
    assert data.crossing_band_count == 4
    assert data.fermi_energy_ev == -2.182511
    assert not data.parse_errors


def test_analyze_fermi_surface_outputs_evidence_descriptors_and_mismatch_warning(tmp_path: Path):
    bxsf = tmp_path / "real_dialect.bxsf"
    fs_out = tmp_path / "fs.out"
    bxsf.write_text(REAL_DIALECT_BXSF)
    fs_out.write_text(SAMPLE_FS_OUT)

    result = fs.analyze_fermi_surface(bxsf, fs_out_path=fs_out, energy_tolerance_ev=0.01)
    data = result.to_dict()

    assert data["status"] == "warning"
    assert any("energy reference mismatch" in warning for warning in data["warnings"])
    assert {item["parser_name"] for item in data["evidence"]} == {
        "vibedft.core.fs.parse_bxsf",
        "vibedft.core.fs.parse_fs_out",
    }
    descriptor_names = {item["name"] for item in data["descriptors"]}
    assert {
        "fs_topology_summary",
        "ef_crossing_bands",
        "nesting_score",
    } <= descriptor_names
    topology = next(item["value"] for item in data["descriptors"] if item["name"] == "fs_topology_summary")
    assert topology["n_pockets"] >= 1
    assert topology["pockets"][0]["carrier_type"] in {"electron", "hole", "mixed"}
    assert topology["fermi_velocity"]["mean_abs_slope_ev"] > 0


def test_parse_bxsf_missing_file(tmp_path: Path):
    data = parse_bxsf(tmp_path / "nonexistent")
    assert not data.has_data
    assert len(data.parse_errors) > 0


def test_parse_bxsf_no_ef(tmp_path: Path):
    """BXSF without explicit Fermi Energy in INFO block."""
    f = tmp_path / "noef.bxsf"
    f.write_text("""\
BEGIN_BLOCK_BANDGRID_3D
  BANDGRID_3D_BANDS
  1
  2 2 2
  0 0 0  1 0 0  0 1 0  1 1 0
  0 0 1  1 0 1  0 1 1  1 1 1
  BAND: 1
  1.0 2.0 3.0 4.0 5.0 6.0 7.0 8.0
END_BLOCK_BANDGRID_3D
""")
    data = parse_bxsf(f)
    assert data.has_data
    assert data.fermi_energy_ev is None
    # With EF=None (→0), band 1 (1.0-8.0) does not cross 0
    assert not data.has_fermi_surface


def test_parse_bxsf_truncated_missing_bands(tmp_path: Path):
    """BXSF with n_bands=2 but only BAND: 1 → must fail with parse error."""
    f = tmp_path / "trunc.bxsf"
    f.write_text("""\
BEGIN_BLOCK_BANDGRID_3D
  BANDGRID_3D_BANDS
  2
  2 2 2
  0 0 0  1 0 0  0 1 0  1 1 0
  0 0 1  1 0 1  0 1 1  1 1 1
  BAND: 1
  1.0 2.0 3.0 4.0 5.0 6.0 7.0 8.0
END_BLOCK_BANDGRID_3D
""")
    data = parse_bxsf(f)
    assert not data.has_data, f"Expected has_data=False for truncated BXSF, got has_data=True"
    assert len(data.band_point_counts) == 1, f"Expected 1 band read, got {len(data.band_point_counts)}"
    assert any("missing BAND" in e for e in data.parse_errors), f"No missing-band error: {data.parse_errors}"


def test_bxsf_summary():
    data = BxsfData(
        filename="test.bxsf",
        n_bands=3, n_k1=10, n_k2=10, n_k3=1, n_kpoints=100,
        fermi_energy_ev=-1.0,
        bands_crossing_ef=[2, 3],
        has_data=True,
    )
    summary = data.summary()
    assert "10×10×1" in summary
    assert "3" in summary
    assert "-1.0" in summary or "-1.00" in summary
    assert "2" in summary  # bands crossing EF
