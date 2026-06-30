"""Evidence-backed 2D validity validator tests."""

from __future__ import annotations

from pathlib import Path

from vibedft.validators.two_d import analyze_2d_validity


def _write_pw_input(
    path: Path,
    *,
    c_ang: float = 32.0,
    assume_isolated: str | None = "2D",
    tot_charge: float = 0.0,
    nk3: int = 1,
    tefield: bool = False,
    dipfield: bool = False,
    noncolin: bool = False,
    lspinorb: bool = False,
    vdw_corr: str | None = None,
    species: tuple[str, ...] = ("Hf", "Br"),
) -> None:
    species_lines = {
        "Hf": "Hf 178.49 Hf.pbe-spn-kjpaw_psl.1.0.0.UPF",
        "Br": "Br 79.904 Br.pbe-n-kjpaw_psl.1.0.0.UPF",
        "Ti": "Ti 47.867 Ti.pbe-spn-kjpaw_psl.1.0.0.UPF",
        "Se": "Se 78.971 Se.pbe-n-kjpaw_psl.1.0.0.UPF",
    }
    system_lines = [
        "&SYSTEM",
        "  ibrav = 0,",
        "  nat = 3,",
        f"  ntyp = {len(species)},",
        "  ecutwfc = 80,",
        "  ecutrho = 640,",
        f"  tot_charge = {tot_charge},",
    ]
    if assume_isolated is not None:
        system_lines.append(f"  assume_isolated = '{assume_isolated}',")
    if tefield:
        system_lines.append("  tefield = .true.,")
    if dipfield:
        system_lines.append("  dipfield = .true.,")
    if noncolin:
        system_lines.append("  noncolin = .true.,")
    if lspinorb:
        system_lines.append("  lspinorb = .true.,")
    if vdw_corr:
        system_lines.append(f"  vdw_corr = '{vdw_corr}',")
    system_lines.append("/")

    path.write_text(
        "\n".join([
            "&CONTROL",
            "  calculation = 'scf',",
            "  prefix = 'valid2d',",
            "  outdir = './out',",
            "/",
            *system_lines,
            "ATOMIC_SPECIES",
            *(species_lines[element] for element in species),
            "CELL_PARAMETERS angstrom",
            "  3.500000  0.000000  0.000000",
            " -1.750000  3.031089  0.000000",
            f"  0.000000  0.000000 {c_ang:.6f}",
            "ATOMIC_POSITIONS crystal",
            "Hf 0.000000 0.000000 0.500000",
            "Br 0.333333 0.666667 0.570000",
            "Br 0.666667 0.333333 0.430000",
            "K_POINTS automatic",
            f"  12 12 {nk3} 0 0 0",
        ]),
        encoding="utf-8",
    )


def _write_ph_input(path: Path, *, nq3: int = 1) -> None:
    path.write_text(
        "\n".join([
            "&INPUTPH",
            "  prefix = 'valid2d',",
            "  outdir = './out',",
            "  ldisp = .true.,",
            "  nq1 = 8,",
            "  nq2 = 8,",
            f"  nq3 = {nq3},",
            "/",
        ]),
        encoding="utf-8",
    )


def test_valid_2d_input_gets_high_score(tmp_path: Path):
    pw = tmp_path / "scf.in"
    ph = tmp_path / "ph.in"
    _write_pw_input(
        pw,
        tefield=True,
        dipfield=True,
        noncolin=True,
        lspinorb=True,
        vdw_corr="dft-d3",
    )
    _write_ph_input(ph)

    result = analyze_2d_validity(
        pw_input_path=pw,
        ph_input_path=ph,
        claim_type="epc_tc",
        is_heterostructure=True,
    )

    assert result.status == "pass"
    assert result.blockers == []
    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}
    assert descriptors["two_d_validity_score"] >= 90
    assert descriptors["two_d_checks"]["assume_isolated_2d"]["status"] == "pass"
    assert descriptors["two_d_checks"]["kz_mesh"]["raw_value"] == 1
    assert {e.parser_name for e in result.evidence} == {
        "vibedft.parsers.qe_input_parser.parse_qe_input",
    }


def test_epc_tc_blocks_legacy_charged_slab_without_2d_cutoff(tmp_path: Path):
    pw = tmp_path / "legacy_scf.in"
    _write_pw_input(pw, assume_isolated=None, tot_charge=-0.10, nk3=2)

    result = analyze_2d_validity(pw_input_path=pw, claim_type="epc_tc")

    assert result.status == "blocked"
    joined = "\n".join(result.blockers + result.warnings).lower()
    assert "assume_isolated" in joined
    assert "charged slab" in joined
    assert "kz" in joined
    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}
    assert descriptors["two_d_validity_score"] < 70
    assert descriptors["two_d_checks"]["charged_slab_consistency"]["status"] == "block"


def test_ph_nq3_not_one_blocks_phonon_claim(tmp_path: Path):
    pw = tmp_path / "scf.in"
    ph = tmp_path / "ph.in"
    _write_pw_input(pw)
    _write_ph_input(ph, nq3=2)

    result = analyze_2d_validity(
        pw_input_path=pw,
        ph_input_path=ph,
        claim_type="phonon_epc",
    )

    assert result.status == "blocked"
    assert any("nq3" in blocker.lower() for blocker in result.blockers)


def test_band_alignment_flags_heavy_elements_soc_and_vdw_policy(tmp_path: Path):
    pw = tmp_path / "type3_scf.in"
    _write_pw_input(
        pw,
        species=("Hf", "Br", "Ti", "Se"),
        noncolin=False,
        lspinorb=False,
        vdw_corr=None,
    )

    result = analyze_2d_validity(
        pw_input_path=pw,
        claim_type="band_alignment",
        is_heterostructure=True,
    )

    assert result.status == "blocked"
    joined = "\n".join(result.blockers + result.warnings + result.metadata["recommendations"]).lower()
    assert "soc" in joined
    assert "vdw" in joined


def test_missing_pw_input_is_insufficient_evidence(tmp_path: Path):
    result = analyze_2d_validity(pw_input_path=tmp_path / "missing.in")

    assert result.status == "insufficient_evidence"
    assert result.reliability == "low"
    assert any("missing" in blocker.lower() for blocker in result.blockers)
