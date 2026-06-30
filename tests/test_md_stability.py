"""Evidence-backed QE MD thermal stability tests."""

from pathlib import Path

from vibedft.properties.aimd_analyzer import (
    analyze_md_stability,
    parse_energy_series,
    parse_temperature_series,
    parse_xyz_trajectory,
)
from vibedft.research.models import ResultStatus


def _write_complete_md_fixture(case_dir: Path, *, unstable: bool = False) -> None:
    ana = case_dir / "ana_0-1000"
    ana.mkdir(parents=True)
    (case_dir / "md.out").write_text(
        "Program PWSCF\n"
        "     temperature   =   300.0 K\n"
        "!    total energy              =    -100.0000 Ry\n"
        "JOB DONE.\n",
        encoding="utf-8",
    )
    temperatures = [300.0, 301.0, 299.5, 300.5] if not unstable else [300.0, 430.0, 620.0, 780.0]
    energies = [-100.0000, -100.0001, -100.0002, -100.0003] if not unstable else [-100.0, -99.96, -99.90, -99.83]
    (ana / "T_K.dat").write_text(
        "\n".join(f"{i} {temp:.3f}" for i, temp in enumerate(temperatures)),
        encoding="utf-8",
    )
    (ana / "Etot_Ry.dat").write_text(
        "\n".join(f"{i} {energy:.6f}" for i, energy in enumerate(energies)),
        encoding="utf-8",
    )
    (ana / "stress_Rybohr3.dat").write_text(
        "\n".join(f"{i} 0.001 0.002 0.003 0.000 0.000 0.000" for i in range(4)),
        encoding="utf-8",
    )
    (ana / "cell_vectors.dat").write_text(
        "0 3.80 0.00 0.00 0.00 3.80 0.00 0.00 0.00 22.00\n",
        encoding="utf-8",
    )
    if unstable:
        xyz = """\
2
step 0
Sn 0.000 0.000 0.000
Se 0.000 0.000 2.500
2
step 1
Sn 0.000 0.000 0.000
Se 0.000 0.000 4.200
"""
    else:
        xyz = """\
2
step 0
Sn 0.000 0.000 0.000
Se 0.000 0.000 2.500
2
step 1
Sn 0.010 0.000 0.000
Se 0.000 0.010 2.510
"""
    (ana / "traj.xyz").write_text(xyz, encoding="utf-8")


def test_parse_temperature_and_energy_series_from_analysis_files(tmp_path: Path):
    _write_complete_md_fixture(tmp_path)

    temperatures = parse_temperature_series(tmp_path / "ana_0-1000" / "T_K.dat")
    energies = parse_energy_series(tmp_path / "ana_0-1000" / "Etot_Ry.dat")

    assert temperatures == [300.0, 301.0, 299.5, 300.5]
    assert energies[0] == -100.0
    assert energies[-1] == -100.0003


def test_parse_xyz_trajectory_reads_frames_and_atoms(tmp_path: Path):
    _write_complete_md_fixture(tmp_path)

    trajectory = parse_xyz_trajectory(tmp_path / "ana_0-1000" / "traj.xyz")

    assert trajectory.n_frames == 2
    assert trajectory.n_atoms == 2
    assert trajectory.frames[0][1].element == "Se"
    assert trajectory.frames[1][0].x == 0.01


def test_analyze_md_stability_outputs_traceable_thermal_verdict(tmp_path: Path):
    _write_complete_md_fixture(tmp_path)

    result = analyze_md_stability(tmp_path)

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}
    parser_names = {evidence.parser_name for evidence in result.evidence}

    assert result.status == ResultStatus.PASS
    assert descriptors["thermal_stability_verdict"] == "thermally_stable"
    assert descriptors["temperature_average_K"] == 300.25
    assert descriptors["energy_drift_Ry"] == 0.0003
    assert descriptors["rmsd_max_angstrom"] < 0.02
    assert descriptors["bond_stability"]["bond_break_warning"] is False
    assert "vibedft.properties.aimd_analyzer.parse_temperature_series" in parser_names
    assert "vibedft.properties.aimd_analyzer.parse_xyz_trajectory" in parser_names


def test_analyze_md_stability_blocks_unstable_temperature_and_bond_break(tmp_path: Path):
    _write_complete_md_fixture(tmp_path, unstable=True)

    result = analyze_md_stability(tmp_path)

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}

    assert result.status == ResultStatus.BLOCKED
    assert descriptors["thermal_stability_verdict"] == "thermally_unstable"
    assert descriptors["bond_stability"]["bond_break_warning"] is True
    assert any("temperature" in blocker.lower() for blocker in result.blockers)
    assert any("bond" in blocker.lower() for blocker in result.blockers)


def test_analyze_md_stability_is_insufficient_without_trajectory(tmp_path: Path):
    _write_complete_md_fixture(tmp_path)
    (tmp_path / "ana_0-1000" / "traj.xyz").unlink()

    result = analyze_md_stability(tmp_path)

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}

    assert result.status == ResultStatus.INSUFFICIENT_EVIDENCE
    assert descriptors["thermal_stability_verdict"] == "insufficient_md_evidence"
    assert any("trajectory" in blocker.lower() for blocker in result.blockers)
