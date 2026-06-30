"""Real-data regression manifest coverage and gate expectation tests."""

from pathlib import Path

from vibedft.properties.elastic import analyze_mechanical_stability
from vibedft.research.manifest import fixture_manifest_from_dict, load_fixture_manifest
from vibedft.research.models import ResultStatus
from vibedft.research.regression import (
    REALDATA_REGRESSION_REQUIREMENTS,
    run_realdata_parser_smoke,
    validate_realdata_regression_manifest,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "research"


def test_realdata_regression_manifest_covers_objective_minimum_fixture_set():
    manifest = load_fixture_manifest(FIXTURES / "real_fixture_manifest.json")

    result = validate_realdata_regression_manifest(manifest)

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}
    coverage = descriptors["realdata_fixture_coverage"]

    assert result.status == ResultStatus.PASS
    assert coverage["missing_keys"] == []
    assert set(coverage["covered_keys"]) == {
        requirement.key for requirement in REALDATA_REGRESSION_REQUIREMENTS
    }
    assert coverage["required_count"] == len(REALDATA_REGRESSION_REQUIREMENTS)
    assert coverage["present_count"] == len(REALDATA_REGRESSION_REQUIREMENTS)


def test_realdata_regression_validator_blocks_missing_required_fixture():
    manifest = fixture_manifest_from_dict(
        {
            "id": "incomplete.realdata",
            "source": "synthetic",
            "artifacts": [
                {
                    "artifact_path": "remote://fs/hfbr2/hfbr2_fs.bxsf",
                    "artifact_type": "bands",
                    "parsed_quantity": "fermi_surface_bxsf_fixture",
                    "metadata": {
                        "fixture_key": "fs_hfbr2_bxsf",
                        "module": "fs",
                        "expected_outcome": "positive",
                        "expected_status": "pass",
                    },
                }
            ],
        }
    )

    result = validate_realdata_regression_manifest(manifest)

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}

    assert result.status == ResultStatus.BLOCKED
    assert "fs_hfcl2_bxsf" in descriptors["realdata_fixture_coverage"]["missing_keys"]
    assert any("missing required real-data fixture" in blocker for blocker in result.blockers)


def test_realdata_regression_validator_rejects_positive_expectation_for_negative_fixture():
    manifest = fixture_manifest_from_dict(
        {
            "id": "bad.negative.expectation",
            "source": "synthetic",
            "artifacts": [
                {
                    "artifact_path": "remote://phonon_negative/k_hfcl2_top/phonon.freq.gp",
                    "artifact_type": "dyn",
                    "parsed_quantity": "negative_phonon_fixture",
                    "metadata": {
                        "fixture_key": "epc_negative_k_hfcl2_top",
                        "module": "epc",
                        "expected_outcome": "negative_gate",
                        "expected_status": "pass",
                    },
                }
            ],
        }
    )

    result = validate_realdata_regression_manifest(
        manifest,
        required_keys=("epc_negative_k_hfcl2_top",),
    )

    assert result.status == ResultStatus.BLOCKED
    assert any("negative fixture" in blocker for blocker in result.blockers)


def test_realdata_regression_manifest_tracks_missing_elastic_data_as_insufficient():
    manifest = load_fixture_manifest(FIXTURES / "real_fixture_manifest.json")

    result = validate_realdata_regression_manifest(manifest)
    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}
    missing_data = descriptors["realdata_missing_data_expectations"]

    assert missing_data["elastic_synthetic_until_real_strain"]["expected_status"] == (
        "insufficient_evidence"
    )

    mechanical_result = analyze_mechanical_stability(elastic_tensor_path=None)

    assert mechanical_result.status == ResultStatus.INSUFFICIENT_EVIDENCE


def test_realdata_parser_smoke_hydrates_manifest_samples():
    manifest = load_fixture_manifest(FIXTURES / "real_fixture_manifest.json")

    result = run_realdata_parser_smoke(
        manifest,
        fixture_keys=(
            "fs_hfbr2_bxsf",
            "epc_positive_hfi2_ph48_ph64",
            "epc_negative_k_hfcl2_top",
            "elastic_synthetic_until_real_strain",
        ),
        fixture_root=FIXTURES,
    )

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}
    smoke = descriptors["realdata_parser_smoke_results"]

    assert result.status == ResultStatus.PASS
    assert smoke["fs_hfbr2_bxsf"]["parser_status"] == "pass"
    assert smoke["fs_hfbr2_bxsf"]["status_matches_expectation"] is True
    assert smoke["epc_positive_hfi2_ph48_ph64"]["parser_status"] == "pass"
    assert smoke["epc_negative_k_hfcl2_top"]["parser_status"] == "blocked"
    assert smoke["elastic_synthetic_until_real_strain"]["parser_status"] == (
        "insufficient_evidence"
    )


def test_realdata_parser_smoke_hydrates_charge_phonon_and_md_samples():
    manifest = load_fixture_manifest(FIXTURES / "real_fixture_manifest.json")

    result = run_realdata_parser_smoke(
        manifest,
        fixture_keys=(
            "bader_hfbr2_tise2_het_acf",
            "bader_hfbr2_tise2_hfbr2_ref_acf",
            "bader_hfbr2_tise2_tise2_ref_acf",
            "charge_hfbr2_tise2_rho_cube",
            "charge_hfbr2_tise2_rho_hetero",
            "planar_hfbr2_tise2_planar_avg",
            "planar_hfbr2_tise2_pot_z",
            "phonon_asr_na2_p3_asr",
            "phonon_asr_na2_p3_no_asr",
            "md_snse2_md300k_nvt",
        ),
        fixture_root=FIXTURES,
    )

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}
    smoke = descriptors["realdata_parser_smoke_results"]

    assert result.status == ResultStatus.PASS
    assert smoke["bader_hfbr2_tise2_het_acf"]["parser_name"] == (
        "vibedft.properties.charge.analyze_charge_evidence"
    )
    assert smoke["bader_hfbr2_tise2_het_acf"]["parser_status"] == "pass"
    assert smoke["bader_hfbr2_tise2_hfbr2_ref_acf"]["parser_status"] == "pass"
    assert smoke["bader_hfbr2_tise2_tise2_ref_acf"]["parser_status"] == "pass"
    assert smoke["charge_hfbr2_tise2_rho_cube"]["parser_status"] == "pass"
    assert smoke["charge_hfbr2_tise2_rho_hetero"]["parser_status"] == "pass"
    assert smoke["planar_hfbr2_tise2_planar_avg"]["parser_status"] == "pass"
    assert smoke["planar_hfbr2_tise2_pot_z"]["parser_status"] == "pass"
    assert smoke["phonon_asr_na2_p3_asr"]["parser_status"] == "pass"
    assert smoke["phonon_asr_na2_p3_no_asr"]["parser_status"] == "warning"
    assert smoke["md_snse2_md300k_nvt"]["parser_status"] == "pass"


def test_realdata_parser_smoke_hydrates_remaining_fs_electronic_epc_type3_samples():
    manifest = load_fixture_manifest(FIXTURES / "real_fixture_manifest.json")

    result = run_realdata_parser_smoke(
        manifest,
        fixture_keys=(
            "fs_hfcl2_bxsf",
            "fs_hfi2_bxsf",
            "electronic_hfbr2_e0p05_bands_dos",
            "electronic_hfbr2_e0p10_bands_dos",
            "electronic_hfbr2_e0p15_bands_dos",
            "epc_positive_hfbr2_e0p02",
            "type3_blocker_hfbr2_tise2_gamma_unstable",
        ),
        fixture_root=FIXTURES,
    )

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}
    smoke = descriptors["realdata_parser_smoke_results"]

    assert result.status == ResultStatus.PASS
    assert smoke["fs_hfcl2_bxsf"]["parser_status"] == "pass"
    assert smoke["fs_hfi2_bxsf"]["parser_status"] == "pass"
    assert smoke["electronic_hfbr2_e0p05_bands_dos"]["parser_name"] == (
        "vibedft.research.regression.electronic_bands_dos_smoke"
    )
    assert smoke["electronic_hfbr2_e0p05_bands_dos"]["parser_status"] == "pass"
    assert smoke["electronic_hfbr2_e0p10_bands_dos"]["parser_status"] == "pass"
    assert smoke["electronic_hfbr2_e0p15_bands_dos"]["parser_status"] == "pass"
    assert smoke["epc_positive_hfbr2_e0p02"]["parser_status"] == "pass"
    assert smoke["type3_blocker_hfbr2_tise2_gamma_unstable"]["parser_name"] == (
        "vibedft.core.phonon.parse_dynmat_output"
    )
    assert smoke["type3_blocker_hfbr2_tise2_gamma_unstable"]["parser_status"] == "blocked"


def test_realdata_parser_smoke_marks_selected_unhydrated_fixture_insufficient():
    manifest = fixture_manifest_from_dict(
        {
            "id": "unhydrated.realdata",
            "source": "synthetic",
            "artifacts": [
                {
                    "artifact_path": "remote://fs/hfbr2/hfbr2_fs.bxsf",
                    "artifact_type": "bands",
                    "parsed_quantity": "fermi_surface_bxsf_fixture",
                    "metadata": {
                        "fixture_key": "fs_hfbr2_bxsf",
                        "module": "fs",
                        "expected_outcome": "positive",
                        "expected_status": "pass",
                    },
                }
            ],
        }
    )

    result = run_realdata_parser_smoke(
        manifest,
        fixture_keys=("fs_hfbr2_bxsf",),
        fixture_root=FIXTURES,
    )

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}
    smoke = descriptors["realdata_parser_smoke_results"]

    assert result.status == ResultStatus.INSUFFICIENT_EVIDENCE
    assert smoke["fs_hfbr2_bxsf"]["parser_status"] == "insufficient_evidence"
    assert any("sample_path" in blocker for blocker in result.blockers)
