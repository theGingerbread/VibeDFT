"""Tests for Phase 12 P0: Bands + Projected DOS Joint Panel."""

from pathlib import Path

from vibedft.core.kpath import detect_high_symmetry, compute_k_distances
from vibedft.core.bands_advanced import (
    build_joint_bands_pdos_panel,
    ProjectedDosPanel,
    BandPanelData,
    OverlayCase,
    OverlayBands,
    build_overlay_bands,
)

SAMPLE_BANDS = """\
 &plot nbnd=  2, nks=    3 /
            0.000000  0.000000  0.000000
  -10.000   -1.000
            0.250000  0.144338  0.000000
   -9.500   -0.500
            0.500000  0.000000  0.000000
   -9.000    0.000
"""

SAMPLE_DOS = """\
#  E (eV)   dos(E)     Int dos(E) EFermi =   -0.009 eV
 -10.000  0.0000  0.0000
  -5.000  0.5000  0.2500
   0.000  0.0010  1.0000
   5.000  1.5000  5.0000
  10.000  0.0000  8.0000
"""

SAMPLE_DOS_EF_1 = """\
#  E (eV)   dos(E)     Int dos(E) EFermi =    1.000 eV
  -2.000  0.0000  0.0000
   0.000  0.1000  0.2000
   1.000  0.2000  0.4000
   2.000  0.5000  1.0000
"""

SAMPLE_GAP_BANDS = """\
 &plot nbnd=  2, nks=    3 /
            0.000000  0.000000  0.000000
   -2.000    1.200
            0.250000  0.000000  0.000000
   -1.000    1.400
            0.500000  0.000000  0.000000
   0.200    1.600
"""

GOOD_PDOS_WFC1 = """\
#  E (eV)   dos(E)     Int dos(E)
 -1.000  0.1000  0.1000
  0.000  0.2000  0.3000
  1.000  0.3000  0.6000
"""

GOOD_PDOS_WFC2_DIFFERENT_GRID = """\
#  E (eV)   dos(E)     Int dos(E)
 -0.500  0.4000  0.4000
  0.500  0.5000  0.9000
"""

BAD_PDOS = """\
#  E (eV)   dos(E)     Int dos(E)
 -1.000  0.1000  0.1000
  not-a-number  0.2000  0.3000
  1.000  0.3000  0.6000
"""

OVERLAY_MAIN_BANDS = """\
 &plot nbnd=  2, nks=    3 /
            0.000000  0.000000  0.000000
   -1.000    1.000
            0.250000  0.000000  0.000000
   -0.500    1.200
            0.500000  0.000000  0.000000
   0.200    1.400
"""

OVERLAY_COMPARE_BANDS = """\
 &plot nbnd=  2, nks=    3 /
            0.000000  0.000000  0.000000
   -0.800    1.200
            0.250000  0.000000  0.000000
   -0.300    1.400
            0.500000  0.000000  0.000000
   0.400    1.600
"""

OVERLAY_MISMATCH_BANDS = """\
 &plot nbnd=  2, nks=    3 /
            0.000000  0.000000  0.000000
   -0.800    1.200
            0.250000  0.000000  0.000000
   -0.300    1.400
            0.500200  0.000000  0.000000
   0.400    1.600
"""


def _write_overlay_case(case_dir: Path, bands_text: str, *, ef: float, label: str) -> Path:
    out = case_dir / "output"
    out.mkdir(parents=True)
    (out / "scf.out").write_text(
        f"the Fermi energy is    {ef:.4f} ev\n"
        "convergence has been achieved in 4 iterations\n"
        "!    total energy              =    -10.000000 Ry\n"
        "JOB DONE.\n",
        encoding="utf-8",
    )
    (out / f"{label}.bands.dat.gnu").write_text(bands_text, encoding="utf-8")
    return case_dir


# ── kpath tests ──


def test_detect_high_symmetry_gamma_only():
    k_points = [[0,0,0], [0.1,0.05,0], [0.2,0.1,0]]
    k_dists = compute_k_distances(k_points)
    hs = detect_high_symmetry(k_points, k_dists)
    # Straight 3-point path → only Γ at start (no corners detected)
    assert len(hs) >= 1
    assert hs[0]["label"] == "Γ"


def test_detect_high_symmetry_gamma_m_k_gamma():
    """Standard hexagonal path: Γ→M→K→Γ."""
    k_points = [
        [0.0, 0.0, 0.0],
        [0.25, 0.144, 0.0],
        [0.5, 0.289, 0.0],
        [0.417, 0.433, 0.0],
        [0.333, 0.577, 0.0],
        [0.167, 0.289, 0.0],
        [0.0, 0.0, 0.0],
    ]
    k_dists = compute_k_distances(k_points)
    hs = detect_high_symmetry(k_points, k_dists)
    labels = [h["label"] for h in hs]
    assert "Γ" in labels
    # Should have at least 3 distinct labels (Γ, something, Γ)
    assert len(hs) >= 2


def test_compute_k_distances():
    k_points = [[0,0,0], [0.5,0,0], [1,0,0]]
    dists = compute_k_distances(k_points)
    assert dists[0] == 0.0
    assert dists[1] > 0.0
    assert dists[2] > dists[1]


# ── Joint panel tests ──


def test_build_joint_panel_with_bands_only(tmp_path: Path):
    bands_f = tmp_path / "bands.dat.gnu"
    bands_f.write_text(SAMPLE_BANDS)

    panel = build_joint_bands_pdos_panel(bands_file=bands_f)
    assert panel["bands"] is not None
    assert panel["bands"].nbnd == 2
    assert panel["bands"].nks == 3
    assert panel["k_labels"] is not None


def test_build_joint_panel_with_bands_and_dos(tmp_path: Path):
    bands_f = tmp_path / "bands.dat.gnu"
    dos_f = tmp_path / "hfi2.dos"
    bands_f.write_text(SAMPLE_BANDS)
    dos_f.write_text(SAMPLE_DOS)

    panel = build_joint_bands_pdos_panel(bands_file=bands_f, dos_file=dos_f)
    assert panel["bands"] is not None
    assert panel["pdos"] is not None
    assert len(panel["pdos"].tdos) == 5


def test_projected_dos_panel_model():
    pp = ProjectedDosPanel(
        tdos=[{"energy_ev": 0.0, "dos": 1.5}],
        pdos_groups={"Hf-d": [{"energy_ev": 0.0, "dos": 0.8}]},
    )
    assert pp.group_labels == ["Hf-d"]
    assert pp.e_fermi_ev == 0.0


def test_band_panel_data_model():
    bp = BandPanelData(
        nbnd=2, nks=3,
        k_distances=[0.0, 0.5, 1.0],
        bands=[[-10, -9.5, -9], [-1, -0.5, 0]],
        k_labels=[{"label": "Γ", "distance": 0.0}],
    )
    assert bp.nbnd == 2
    assert bp.k_labels[0]["label"] == "Γ"


def test_joint_panel_missing_file(tmp_path: Path):
    panel = build_joint_bands_pdos_panel(bands_file=tmp_path / "nonexistent")
    assert panel["bands"] is None


def test_joint_panel_without_scf_uses_dos_header_fermi_for_gap(tmp_path: Path):
    """No-SCF report path resolves EF from DOS before computing gap."""
    bands_f = tmp_path / "bands.dat.gnu"
    dos_f = tmp_path / "material.dos"
    bands_f.write_text(SAMPLE_GAP_BANDS)
    dos_f.write_text(SAMPLE_DOS_EF_1)

    panel = build_joint_bands_pdos_panel(bands_file=bands_f, dos_file=dos_f)

    assert panel["fermi_source"] == "dos_header"
    assert panel["fermi_energy_ev"] == 1.0
    assert panel["bands"].gap_ev == 1.0


def test_joint_panel_splits_mismatched_pdos_grids_by_wfc_index(tmp_path: Path):
    """Same element/orbital on different grids must not merge silently."""
    bands_f = tmp_path / "bands.dat.gnu"
    dos_f = tmp_path / "material.dos"
    bands_f.write_text(SAMPLE_BANDS)
    dos_f.write_text(SAMPLE_DOS)
    (tmp_path / "material.pdos_atm#1(I)_wfc#1(p)").write_text(GOOD_PDOS_WFC1)
    (tmp_path / "material.pdos_atm#1(I)_wfc#2(p)").write_text(GOOD_PDOS_WFC2_DIFFERENT_GRID)

    panel = build_joint_bands_pdos_panel(
        bands_file=bands_f,
        dos_file=dos_f,
        pdos_dir=tmp_path,
    )

    groups = panel["pdos"].pdos_groups
    assert "I-p_wfc1" in groups
    assert "I-p_wfc2" in groups
    assert "I-p" not in groups
    assert any("PDOS grid mismatch" in err for err in panel["errors"])


def test_joint_panel_malformed_pdos_warns_without_losing_valid_files(tmp_path: Path):
    """One malformed PDOS file should surface an error and keep good groups."""
    bands_f = tmp_path / "bands.dat.gnu"
    dos_f = tmp_path / "material.dos"
    bands_f.write_text(SAMPLE_BANDS)
    dos_f.write_text(SAMPLE_DOS)
    (tmp_path / "material.pdos_atm#1(I)_wfc#1(p)").write_text(GOOD_PDOS_WFC1)
    (tmp_path / "material.pdos_atm#2(I)_wfc#1(p)").write_text(BAD_PDOS)

    panel = build_joint_bands_pdos_panel(
        bands_file=bands_f,
        dos_file=dos_f,
        pdos_dir=tmp_path,
    )

    assert "I-p" in panel["pdos"].pdos_groups
    assert any("PDOS parse error" in err for err in panel["errors"])


def test_overlay_bands_model_and_delta_shape_for_compatible_cases(tmp_path: Path):
    main = _write_overlay_case(tmp_path / "case-a", OVERLAY_MAIN_BANDS, ef=0.0, label="main")
    compare = _write_overlay_case(tmp_path / "case-b", OVERLAY_COMPARE_BANDS, ef=0.1, label="compare")

    overlay = build_overlay_bands(main, [compare])

    assert isinstance(overlay, OverlayBands)
    assert isinstance(overlay.cases[0], OverlayCase)
    assert overlay.k_path_compatible is True
    assert len(overlay.cases) == 2
    assert overlay.delta_e_ev is not None
    assert len(overlay.delta_e_ev) == 2
    assert len(overlay.delta_e_ev[0]) == 3
    assert overlay.delta_e_ev[0] == [0.1, 0.1, 0.1]


def test_overlay_bands_kpath_mismatch_warns_without_crash(tmp_path: Path):
    main = _write_overlay_case(tmp_path / "case-a", OVERLAY_MAIN_BANDS, ef=0.0, label="main")
    compare = _write_overlay_case(tmp_path / "case-b", OVERLAY_MISMATCH_BANDS, ef=0.1, label="compare")

    overlay = build_overlay_bands(main, [compare])

    assert overlay.k_path_compatible is False
    assert overlay.delta_e_ev is None
    assert any("k coordinate mismatch" in warning for warning in overlay.warnings)
