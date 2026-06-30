"""Evidence-backed band-alignment and Type-III gate tests."""

from pathlib import Path

from vibedft.properties.band_alignment import (
    analyze_band_alignment,
    parse_band_edge_summary,
)
from vibedft.research.models import ResultStatus


def _write_band_edge(
    path: Path,
    *,
    label: str,
    vbm: float,
    cbm: float,
    lattice_a: float = 3.45,
) -> Path:
    path.write_text(
        f"label: {label}\n"
        f"vbm_ev: {vbm:.4f}\n"
        f"cbm_ev: {cbm:.4f}\n"
        f"lattice_a_angstrom: {lattice_a:.4f}\n",
        encoding="utf-8",
    )
    return path


def _write_valid_planar(path: Path) -> Path:
    lines = []
    for i in range(20):
        z = float(i)
        value = 0.25 if i < 4 or i >= 16 else 0.08 + i * 0.005
        lines.append(f"{z:.3f} {value:.6f}")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_soc_input(path: Path, *, with_soc: bool = True) -> Path:
    soc_lines = "  noncolin = .true.,\n  lspinorb = .true.,\n" if with_soc else ""
    path.write_text(
        "&CONTROL\n"
        "  calculation = 'scf',\n"
        "  prefix = 'hfbri2_tise2',\n"
        "/\n"
        "&SYSTEM\n"
        "  ibrav = 0,\n"
        "  nat = 4,\n"
        "  ntyp = 4,\n"
        f"{soc_lines}"
        "/\n"
        "ATOMIC_SPECIES\n"
        "Hf 178.49 Hf.UPF\n"
        "Br 79.904 Br.UPF\n"
        "Ti 47.867 Ti.UPF\n"
        "Se 78.971 Se.UPF\n",
        encoding="utf-8",
    )
    return path


def test_parse_band_edge_summary_reads_absolute_edges(tmp_path: Path):
    edge_file = _write_band_edge(tmp_path / "hfbr2.edges", label="HfBr2", vbm=-4.2, cbm=-2.1)

    edges = parse_band_edge_summary(edge_file)

    assert edges.has_data
    assert edges.label == "HfBr2"
    assert edges.vbm_ev == -4.2
    assert edges.cbm_ev == -2.1
    assert edges.lattice_a_angstrom == 3.45


def test_band_alignment_blocks_invalid_planar_and_missing_type3_evidence(tmp_path: Path):
    ref_a = _write_band_edge(tmp_path / "hfbr2.edges", label="HfBr2", vbm=-4.2, cbm=-2.0)
    ref_b = _write_band_edge(tmp_path / "tise2.edges", label="TiSe2", vbm=-6.0, cbm=-4.8)

    result = analyze_band_alignment(
        reference_band_edge_paths={"HfBr2": ref_a, "TiSe2": ref_b},
        planar_profile_path=Path("tests/fixtures/research/type3_invalid_potential/outputs/planar_average.log"),
    )

    assert result.status == ResultStatus.BLOCKED
    assert any("planar" in blocker.lower() for blocker in result.blockers)
    assert any("layer-projected" in blocker.lower() for blocker in result.blockers)
    assert any("relaxed heterostructure" in blocker.lower() for blocker in result.blockers)
    assert any("Type-III confirmed" in item for item in result.metadata["forbidden_conclusions"])


def test_band_alignment_classifies_type3_only_with_full_evidence_chain(tmp_path: Path):
    ref_a = _write_band_edge(tmp_path / "hfbr2.edges", label="HfBr2", vbm=-4.2, cbm=-2.0)
    ref_b = _write_band_edge(tmp_path / "tise2.edges", label="TiSe2", vbm=-6.0, cbm=-4.8)
    planar = _write_valid_planar(tmp_path / "planar_avg.dat")
    scf_in = _write_soc_input(tmp_path / "scf.in", with_soc=True)
    projected_bands = tmp_path / "layer_projected_bands.dat"
    projected_bands.write_text("layer HfBr2 VBM\nlayer TiSe2 CBM\n", encoding="utf-8")
    relaxed = tmp_path / "relax.out"
    relaxed.write_text("JOB DONE.\nrelaxed heterostructure force < 1e-4\n", encoding="utf-8")

    result = analyze_band_alignment(
        reference_band_edge_paths={"HfBr2": ref_a, "TiSe2": ref_b},
        planar_profile_path=planar,
        heterostructure_input_path=scf_in,
        layer_projected_bands_path=projected_bands,
        relaxed_structure_path=relaxed,
    )

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}
    parser_names = {evidence.parser_name for evidence in result.evidence}

    assert result.status == ResultStatus.PASS
    assert descriptors["band_alignment_classification"] == "type_iii_broken_gap"
    assert descriptors["band_offsets"]["broken_gap_ev"] == 0.6
    assert "vibedft.properties.band_alignment.parse_band_edge_summary" in parser_names
    assert "vibedft.properties.charge.parse_planar_profile" in parser_names
    assert "vibedft.spin.soc_parser.analyze_soc_config" in parser_names


def test_band_alignment_warns_when_heavy_elements_lack_soc(tmp_path: Path):
    ref_a = _write_band_edge(tmp_path / "hfbr2.edges", label="HfBr2", vbm=-4.2, cbm=-2.0)
    ref_b = _write_band_edge(tmp_path / "tise2.edges", label="TiSe2", vbm=-6.0, cbm=-4.8)
    planar = _write_valid_planar(tmp_path / "planar_avg.dat")
    scf_in = _write_soc_input(tmp_path / "scf.in", with_soc=False)
    projected_bands = tmp_path / "layer_projected_bands.dat"
    projected_bands.write_text("layer projected evidence\n", encoding="utf-8")
    relaxed = tmp_path / "relax.out"
    relaxed.write_text("JOB DONE.\n", encoding="utf-8")

    result = analyze_band_alignment(
        reference_band_edge_paths={"HfBr2": ref_a, "TiSe2": ref_b},
        planar_profile_path=planar,
        heterostructure_input_path=scf_in,
        layer_projected_bands_path=projected_bands,
        relaxed_structure_path=relaxed,
    )

    assert result.status == ResultStatus.WARNING
    assert any("soc" in warning.lower() for warning in result.warnings)


def test_band_alignment_blocks_nonconverged_bands_output(tmp_path: Path):
    ref_a = _write_band_edge(tmp_path / "hfbr2.edges", label="HfBr2", vbm=-4.2, cbm=-2.0)
    ref_b = _write_band_edge(tmp_path / "tise2.edges", label="TiSe2", vbm=-6.0, cbm=-4.8)
    bands_out = tmp_path / "bands.out"
    bands_out.write_text(
        "c_bands: 1 eigenvalues not converged\n"
        "     highest occupied, lowest unoccupied level (ev): -4.20 -2.00\n",
        encoding="utf-8",
    )

    result = analyze_band_alignment(
        reference_band_edge_paths={"HfBr2": ref_a, "TiSe2": ref_b},
        planar_profile_path=_write_valid_planar(tmp_path / "planar_avg.dat"),
        bands_output_path=bands_out,
    )

    assert result.status == ResultStatus.BLOCKED
    assert any("eigenvalue" in blocker.lower() for blocker in result.blockers)
