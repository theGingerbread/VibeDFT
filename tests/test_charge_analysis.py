"""Evidence-backed Bader, cube, and planar-potential analysis tests."""

from pathlib import Path

from vibedft.properties.charge import (
    analyze_charge_evidence,
    parse_acf_dat,
    parse_cube_metadata,
    parse_planar_profile,
)


def _write_acf(path: Path, rows: list[tuple[int, float, float, float, float, float, float]], electrons: float) -> None:
    lines = [
        "   #   X        Y        Z     CHARGE    MIN DIST   ATOMIC VOL",
        " ---- ------- ------- ------- ---------- ---------- -----------",
    ]
    for idx, x, y, z, charge, min_dist, volume in rows:
        lines.append(
            f"{idx:5d} {x:7.3f} {y:7.3f} {z:7.3f} "
            f"{charge:10.4f} {min_dist:10.4f} {volume:10.4f}"
        )
    lines.extend([
        " -------------------------------------------",
        "  VACUUM CHARGE:    0.0000",
        f"  NUMBER OF ELECTRONS:   {electrons:.4f}",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def test_parse_acf_dat_preserves_full_bader_table(tmp_path: Path):
    acf = tmp_path / "ACF.dat"
    _write_acf(
        acf,
        [
            (1, 1.0, 2.0, 3.0, 12.3456, 1.2345, 123.4567),
            (2, 2.0, 3.0, 4.0, 7.6544, 2.3456, 234.5678),
        ],
        electrons=20.0,
    )

    data = parse_acf_dat(acf)

    assert data.has_data
    assert data.n_atoms == 2
    assert data.number_of_electrons == 20.0
    assert abs(data.charge_conservation_delta_e) < 1e-10
    assert data.atoms[0].index == 1
    assert data.atoms[0].x == 1.0
    assert data.atoms[0].charge == 12.3456
    assert data.atoms[0].min_distance == 1.2345
    assert data.atoms[0].atomic_volume == 123.4567


def test_parse_cube_metadata_reads_grid_shape(tmp_path: Path):
    cube = tmp_path / "rho.cube"
    cube.write_text(
        "CPMD CUBE FILE\n"
        "OUTER LOOP: X, MIDDLE LOOP: Y, INNER LOOP: Z\n"
        "    2    0.000000    0.000000    0.000000\n"
        "   60    0.100000    0.000000    0.000000\n"
        "   60    0.000000    0.100000    0.000000\n"
        "  512    0.000000    0.000000    0.100000\n"
        "    1    0.000000    0.000000    0.000000    0.000000\n"
        "    2    0.000000    0.500000    0.500000    0.500000\n",
        encoding="utf-8",
    )

    metadata = parse_cube_metadata(cube)

    assert metadata.has_data
    assert metadata.n_atoms == 2
    assert metadata.grid == (60, 60, 512)
    assert metadata.origin == (0.0, 0.0, 0.0)


def test_parse_planar_profile_summarizes_vacuum_and_dipole(tmp_path: Path):
    profile = tmp_path / "planar_avg.dat"
    lines = []
    for i in range(20):
        z = float(i)
        value = 0.50 if i < 4 or i >= 16 else 0.10 + i * 0.01
        lines.append(f"{z:.3f} {value:.6f}")
    profile.write_text("\n".join(lines), encoding="utf-8")

    data = parse_planar_profile(profile)

    assert data.has_data
    assert data.n_points == 20
    assert data.vacuum_plateau_fluctuation_ev < 0.01
    assert abs(data.vacuum_level_ev - 0.5) < 1e-12
    assert data.dipole_moment_estimate is not None


def test_parse_planar_profile_detects_malformed_average_log():
    data = parse_planar_profile(
        Path("tests/fixtures/research/type3_invalid_potential/outputs/planar_average.log")
    )

    assert data.malformed
    joined = "\n".join(data.blockers + data.warnings).lower()
    assert "fixed 600-line" in joined
    assert "vacuum plateau" in joined
    assert "deltav" in joined


def test_analyze_charge_evidence_blocks_missing_reference(tmp_path: Path):
    hetero = tmp_path / "bader_het" / "ACF.dat"
    hetero.parent.mkdir()
    _write_acf(hetero, [(1, 0, 0, 0, 5.0, 1.0, 10.0)], electrons=5.0)

    result = analyze_charge_evidence(
        hetero_acf_path=hetero,
        reference_acf_paths={"layer_a": tmp_path / "missing_ref" / "ACF.dat"},
        layer_atom_indices={"layer_a": [1]},
    )

    assert result.status == "blocked"
    assert any("reference" in blocker.lower() for blocker in result.blockers)


def test_analyze_charge_evidence_outputs_layer_transfer_and_planar_blocker(tmp_path: Path):
    hetero = tmp_path / "bader_het" / "ACF.dat"
    ref_a = tmp_path / "bader_a" / "ACF.dat"
    ref_b = tmp_path / "bader_b" / "ACF.dat"
    for path in (hetero, ref_a, ref_b):
        path.parent.mkdir()
    _write_acf(
        hetero,
        [
            (1, 0, 0, 0.2, 5.5, 1.0, 10.0),
            (2, 0, 0, 0.8, 6.5, 1.0, 10.0),
        ],
        electrons=12.0,
    )
    _write_acf(ref_a, [(1, 0, 0, 0.2, 6.0, 1.0, 10.0)], electrons=6.0)
    _write_acf(ref_b, [(1, 0, 0, 0.8, 6.0, 1.0, 10.0)], electrons=6.0)

    result = analyze_charge_evidence(
        hetero_acf_path=hetero,
        reference_acf_paths={"layer_a": ref_a, "layer_b": ref_b},
        layer_atom_indices={"layer_a": [1], "layer_b": [2]},
        planar_profile_path=Path("tests/fixtures/research/type3_invalid_potential/outputs/planar_average.log"),
    )

    assert result.status == "blocked"
    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}
    assert descriptors["layer_charge_transfer"]["layer_a"]["delta_e"] == -0.5
    assert descriptors["layer_charge_transfer"]["layer_b"]["delta_e"] == 0.5
    assert descriptors["charge_transfer_classification"] == "mixed_or_covalent"
    assert any("malformed planar" in blocker.lower() for blocker in result.blockers)
    assert {e.parser_name for e in result.evidence} >= {
        "vibedft.properties.charge.parse_acf_dat",
        "vibedft.properties.charge.parse_planar_profile",
    }
