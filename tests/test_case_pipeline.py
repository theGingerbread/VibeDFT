"""Tests for evidence-backed case pipeline orchestration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from vibedft.research.models import ResultStatus

PROJECT_ROOT = Path(__file__).resolve().parents[1]


SAMPLE_BXSF = """\
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
     Fermi surface calculation
     1 bands found crossing Ef = 0.000000
     JOB DONE.
"""


SAMPLE_LAMBDAX = """\
     lambda        omega_log          T_c
     0.73          120.0              5.4
"""


NAN_LAMBDAX = """\
     lambda        omega_log          T_c
     0.86          NaN                NaN
"""


NEGATIVE_FREQ_GP = """\
0.0  12.0  25.0
0.5  -8.0  22.0
"""


POSITIVE_FREQ_GP = """\
0.0  12.0  25.0
0.5  18.0  29.0
"""


SAMPLE_PW_IN = """\
&CONTROL
  calculation = 'scf'
/
&SYSTEM
  ibrav = 0,
  nat = 2,
  ntyp = 1,
  assume_isolated = '2D',
  tefield = .true.,
  dipfield = .true.,
  vdw_corr = 'dft-d3',
  noncolin = .true.,
  lspinorb = .true.,
/
&ELECTRONS
/
ATOMIC_SPECIES
C 12.011 C.UPF
CELL_PARAMETERS angstrom
  3.0 0.0 0.0
  0.0 3.0 0.0
  0.0 0.0 20.0
ATOMIC_POSITIONS crystal
C 0.0 0.0 0.45
C 0.5 0.5 0.55
K_POINTS automatic
6 6 1 0 0 0
"""


SAMPLE_PH_IN = """\
&INPUTPH
  nq1 = 4,
  nq2 = 4,
  nq3 = 1,
/
"""


SAMPLE_SCF_OUT = """\
     Program PWSCF v.7.5
     iteration # 1
     total energy              =     -20.000000 Ry
     estimated scf accuracy    <       1.0E-10 Ry
     convergence has been achieved
     the Fermi energy is    0.2500 ev
     JOB DONE.
"""


SAMPLE_BANDS = """\
&plot nbnd= 2, nks= 2 /
          0.000000  0.000000  0.000000
 -1.000  1.000
          0.500000  0.000000  0.000000
 -0.500  1.500
"""


SAMPLE_DOS = """\
#  E (eV)   dos(E)     Int dos(E) EFermi =   0.250 eV
-1.000  0.100  0.010
 0.000  1.500  0.500
 1.000  0.200  0.700
"""


SAMPLE_ACF = """\
    #         X           Y           Z        CHARGE     MIN DIST   ATOMIC VOL
    1      0.0000      0.0000      0.4500      3.0000      0.1000      9.0000
    2      1.5000      1.5000      0.5500      3.0000      0.1000      9.0000
VACUUM CHARGE:               0.0000
NUMBER OF ELECTRONS:         6.0000
"""


SAMPLE_PLANAR = """\
0.0  4.90
1.0  5.00
2.0  5.05
3.0  4.95
"""


SAMPLE_CUBE_HEADER = """\
cube sample
generated for test
    2    0.000000    0.000000    0.000000
    2    1.000000    0.000000    0.000000
    2    0.000000    1.000000    0.000000
    2    0.000000    0.000000    1.000000
    6    0.000000    0.000000    0.000000    0.450000
    6    0.000000    1.500000    1.500000    0.550000
"""


SAMPLE_ELASTIC = """\
C11_N_per_m: 120.0
C12_N_per_m: 35.0
C66_N_per_m: 42.0
source: strain sweep
strain_points: 5
"""


SAMPLE_BAND_EDGE_A = """\
label: layer_a
vbm_ev: -4.80
cbm_ev: -3.80
lattice_a_angstrom: 3.20
"""


SAMPLE_BAND_EDGE_B = """\
label: layer_b
vbm_ev: -3.60
cbm_ev: -2.60
lattice_a_angstrom: 3.20
"""


SAMPLE_MD_T = """\
0 300.0
1 305.0
2 302.0
"""


SAMPLE_MD_E = """\
0 -20.0000
1 -20.0005
2 -20.0002
"""


SAMPLE_XYZ = """\
2
frame 0
C 0.0 0.0 0.0
C 1.2 0.0 0.0
2
frame 1
C 0.0 0.0 0.0
C 1.21 0.0 0.0
"""


EXPECTED_STAGE_IDS = [
    "00_structure_validation",
    "01_scf_relax",
    "02_electronic_structure",
    "03_fermi_surface_analysis",
    "04_charge_bader_analysis",
    "05_phonon_dynamics",
    "06_epc_superconductivity",
    "07_mechanical_stability",
    "08_band_alignment",
    "09_md_stability",
    "10_final_report_generator",
]


def test_case_evidence_pipeline_outputs_all_stages_and_blocks_unstable_tc(tmp_path: Path):
    case_dir = _write_mixed_case(tmp_path)

    from vibedft.research.case_pipeline import run_case_evidence_pipeline

    result = run_case_evidence_pipeline(case_dir)

    assert [stage.stage_id for stage in result.stages] == EXPECTED_STAGE_IDS

    stage_by_id = {stage.stage_id: stage for stage in result.stages}
    fs_stage = stage_by_id["03_fermi_surface_analysis"]
    assert fs_stage.status == ResultStatus.PASS
    assert fs_stage.evidence
    assert any(descriptor.name == "fs_topology_summary" for descriptor in fs_stage.descriptors)

    tc_stage = stage_by_id["06_epc_superconductivity"]
    assert tc_stage.status == ResultStatus.BLOCKED
    assert any("negative phonon" in blocker for blocker in tc_stage.blockers)
    assert any(evidence.parser_name == "vibedft.core.phonon.parse_freq_gp" for evidence in tc_stage.evidence)

    charge_stage = stage_by_id["04_charge_bader_analysis"]
    assert charge_stage.status == ResultStatus.INSUFFICIENT_EVIDENCE
    assert charge_stage.next_actions

    final_stage = stage_by_id["10_final_report_generator"]
    assert final_stage.status == ResultStatus.BLOCKED
    assert any("upstream stage blocked" in blocker for blocker in final_stage.blockers)

    assert result.evidence_pack["stages"]
    json.dumps(result.evidence_pack, allow_nan=False)
    forbidden = result.evidence_pack["unsupported_or_forbidden_conclusions"]
    assert any(item["stage_id"] == "06_epc_superconductivity" for item in forbidden)
    assert "Do not report a physical Tc" in result.summary_markdown


def test_cli_evidence_case_pipeline_json_reports_block_without_crashing(tmp_path: Path):
    case_dir = _write_mixed_case(tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "vibedft",
            "evidence",
            "--case-dir",
            str(case_dir),
            "--json",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    json.dumps(payload, allow_nan=False)
    assert payload["overall_status"] == "BLOCK"
    assert payload["stage_counts"]["blocked"] >= 1
    assert any(stage["stage_id"] == "06_epc_superconductivity" for stage in payload["stages"])


def test_cli_evidence_case_pipeline_plain_output_renders_traceable_report(tmp_path: Path):
    case_dir = _write_feature_rich_case(tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "vibedft",
            "evidence",
            "--case-dir",
            str(case_dir),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Evidence pipeline: PASS" in result.stdout
    assert "## Physics Report" in result.stdout
    assert "### phonon_stability" in result.stdout
    assert "- Descriptor: `phonon_stability_summary`" in result.stdout
    assert "path=`" in result.stdout
    assert "parser=`" in result.stdout
    assert "quantity=`" in result.stdout


def test_case_pipeline_payload_is_strict_json_with_nan_lambdax(tmp_path: Path):
    case_dir = tmp_path / "nan_case"
    output = case_dir / "output"
    output.mkdir(parents=True)
    (output / "lambdax.out").write_text(NAN_LAMBDAX, encoding="utf-8")

    from vibedft.research.case_pipeline import (
        case_evidence_pipeline_payload,
        run_case_evidence_pipeline,
    )

    result = run_case_evidence_pipeline(case_dir)
    payload = case_evidence_pipeline_payload(result)

    json.dumps(payload, allow_nan=False)
    epc_stage = next(stage for stage in payload["stages"] if stage["stage_id"] == "06_epc_superconductivity")
    raw_value = epc_stage["evidence"][0]["raw_value"]
    assert raw_value["omega_log_values"] == ["NaN"]
    assert raw_value["tc_values"] == ["NaN"]


def test_case_evidence_pipeline_hydrates_available_analyzers(tmp_path: Path):
    case_dir = _write_feature_rich_case(tmp_path)

    from vibedft.research.case_pipeline import run_case_evidence_pipeline

    result = run_case_evidence_pipeline(case_dir)
    stage_by_id = {stage.stage_id: stage for stage in result.stages}

    expected_non_missing = {
        "00_structure_validation": "two_d_validity_score",
        "01_scf_relax": "scf_relax_summary",
        "02_electronic_structure": "electronic_structure_summary",
        "04_charge_bader_analysis": "bader_charge_table",
        "05_phonon_dynamics": "phonon_stability_summary",
        "07_mechanical_stability": "mechanical_stability_classification",
        "08_band_alignment": "band_alignment_classification",
        "09_md_stability": "thermal_stability_verdict",
    }
    for stage_id, descriptor_name in expected_non_missing.items():
        stage = stage_by_id[stage_id]
        assert stage.status != ResultStatus.INSUFFICIENT_EVIDENCE, stage.blockers
        assert stage.evidence, stage_id
        assert any(descriptor.name == descriptor_name for descriptor in stage.descriptors)

    assert stage_by_id["10_final_report_generator"].status == ResultStatus.PASS
    assert not result.evidence_pack["unsupported_or_forbidden_conclusions"]
    json.dumps(result.evidence_pack, allow_nan=False)


def test_case_payload_contains_traceable_physics_report_sections(tmp_path: Path):
    case_dir = _write_feature_rich_case(tmp_path)

    from vibedft.research.case_pipeline import (
        case_evidence_pipeline_payload,
        run_case_evidence_pipeline,
    )

    payload = case_evidence_pipeline_payload(run_case_evidence_pipeline(case_dir))
    report = payload["physics_report"]

    expected_sections = {
        "phonon_stability": "phonon_stability_summary",
        "mechanical_stability": "mechanical_stability_classification",
        "thermal_stability": "thermal_stability_verdict",
        "electronic_classification": "electronic_structure_summary",
        "fermi_surface_topology": "fs_topology_summary",
        "nesting_score": "nesting_score",
        "charge_transfer_classification": "charge_transfer_classification",
        "band_alignment_classification": "band_alignment_classification",
        "superconductivity_reliability": "superconductivity_reliability",
    }
    assert set(report["sections"]) == set(expected_sections)
    for section_id, descriptor_name in expected_sections.items():
        section = report["sections"][section_id]
        assert section["descriptor_name"] == descriptor_name
        assert section["status"] == "pass"
        assert section["stage_id"]
        assert section["evidence"], section_id
        assert section["evidence"][0]["artifact_path"]
        assert section["evidence"][0]["parser_name"]
        assert section["evidence"][0]["parsed_quantity"]

    assert report["unsupported_or_forbidden_conclusions"] == []
    json.dumps(report, allow_nan=False)


def test_case_summary_markdown_renders_traceable_physics_report_sections(tmp_path: Path):
    case_dir = _write_feature_rich_case(tmp_path)

    from vibedft.research.case_pipeline import run_case_evidence_pipeline

    result = run_case_evidence_pipeline(case_dir)
    markdown = result.summary_markdown

    assert "## Physics Report" in markdown
    expected_sections = {
        "phonon_stability": "phonon_stability_summary",
        "mechanical_stability": "mechanical_stability_classification",
        "thermal_stability": "thermal_stability_verdict",
        "electronic_classification": "electronic_structure_summary",
        "fermi_surface_topology": "fs_topology_summary",
        "nesting_score": "nesting_score",
        "charge_transfer_classification": "charge_transfer_classification",
        "band_alignment_classification": "band_alignment_classification",
        "superconductivity_reliability": "superconductivity_reliability",
    }
    for section_id, descriptor_name in expected_sections.items():
        section_marker = f"### {section_id}"
        assert section_marker in markdown
        section_text = markdown.split(section_marker, 1)[1].split("\n### ", 1)[0]
        assert f"- Descriptor: `{descriptor_name}`" in section_text
        assert "- Evidence:" in section_text
        assert "path=`" in section_text
        assert "parser=`" in section_text
        assert "quantity=`" in section_text


def test_batch_evidence_pipeline_reports_each_case_without_crashing(tmp_path: Path):
    batch_root = tmp_path / "batch"
    good_case = _write_feature_rich_case(batch_root)
    bad_case = batch_root / "empty_case"
    bad_case.mkdir(parents=True)

    from vibedft.research.case_pipeline import (
        batch_evidence_pipeline_payload,
        run_batch_evidence_pipeline,
    )

    result = run_batch_evidence_pipeline(batch_root)
    payload = batch_evidence_pipeline_payload(result)
    cases_by_name = {Path(case["case_dir"]).name: case for case in payload["cases"]}

    assert set(cases_by_name) == {good_case.name, bad_case.name}
    assert payload["case_counts"] == {"pass": 1, "concern": 1, "block": 0}
    assert payload["overall_status"] == "CONCERN"
    assert cases_by_name[good_case.name]["overall_status"] == "PASS"
    assert cases_by_name[bad_case.name]["overall_status"] == "CONCERN"
    assert cases_by_name[bad_case.name]["stage_counts"]["insufficient_evidence"] >= 10
    json.dumps(payload, allow_nan=False)


def test_cli_evidence_batch_root_json_reports_mixed_cases(tmp_path: Path):
    batch_root = tmp_path / "batch"
    _write_feature_rich_case(batch_root)
    (batch_root / "empty_case").mkdir(parents=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "vibedft",
            "evidence",
            "--batch-root",
            str(batch_root),
            "--json",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "CONCERN"
    assert payload["case_counts"]["pass"] == 1
    assert payload["case_counts"]["concern"] == 1
    assert len(payload["cases"]) == 2
    json.dumps(payload, allow_nan=False)


def test_cli_evidence_batch_root_plain_output_renders_case_reports(tmp_path: Path):
    batch_root = tmp_path / "batch"
    passed_case = _write_feature_rich_case(batch_root, name="feature_rich_case")
    (batch_root / "empty_case").mkdir(parents=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "vibedft",
            "evidence",
            "--batch-root",
            str(batch_root),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Evidence batch: CONCERN" in result.stdout
    assert f"## Case report: {passed_case.name}" in result.stdout
    assert "## Case report: empty_case" in result.stdout
    assert "## Physics Report" in result.stdout
    assert "### phonon_stability" in result.stdout
    assert "- Descriptor: `phonon_stability_summary`" in result.stdout
    assert "path=`" in result.stdout
    assert "parser=`" in result.stdout
    assert "quantity=`" in result.stdout


def test_batch_evidence_ranking_uses_only_passed_evidence(tmp_path: Path):
    batch_root = tmp_path / "ranking_batch"
    pass_a = _write_feature_rich_case(batch_root, name="alpha_pass")
    pass_b = _write_feature_rich_case(batch_root, name="zeta_pass")
    blocked_case = batch_root / "blocked_case"
    blocked_output = blocked_case / "output"
    blocked_output.mkdir(parents=True)
    (blocked_output / "lambdax.out").write_text(NAN_LAMBDAX, encoding="utf-8")
    concern_case = batch_root / "empty_case"
    concern_case.mkdir(parents=True)

    from vibedft.research.case_pipeline import (
        batch_evidence_pipeline_payload,
        run_batch_evidence_pipeline,
    )

    payload = batch_evidence_pipeline_payload(run_batch_evidence_pipeline(batch_root))

    ranked_names = [Path(case["case_dir"]).name for case in payload["ranked_cases"]]
    assert ranked_names == [pass_a.name, pass_b.name]
    assert all(case["overall_status"] == "PASS" for case in payload["ranked_cases"])
    assert all(case["rank"] > 0 for case in payload["ranked_cases"])
    assert all(case["rank_score"]["passed_stage_count"] > 0 for case in payload["ranked_cases"])
    assert all(case["rank_score"]["passed_evidence_count"] > 0 for case in payload["ranked_cases"])

    unranked = {Path(case["case_dir"]).name: case for case in payload["unranked_cases"]}
    assert set(unranked) == {blocked_case.name, concern_case.name}
    assert unranked[blocked_case.name]["overall_status"] == "BLOCK"
    assert "blocked" in unranked[blocked_case.name]["reason"]
    assert unranked[concern_case.name]["overall_status"] == "CONCERN"
    assert "insufficient evidence" in unranked[concern_case.name]["reason"]
    json.dumps(payload, allow_nan=False)


def test_cli_evidence_exit_codes_reflect_gate_state(tmp_path: Path):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    blocked_case = tmp_path / "bad_case"
    output = blocked_case / "output"
    output.mkdir(parents=True)
    (output / "fs.bxsf").write_text(SAMPLE_BXSF, encoding="utf-8")
    (output / "lambdax.out").write_text(NAN_LAMBDAX, encoding="utf-8")
    (output / "phonon.freq.gp").write_text(POSITIVE_FREQ_GP, encoding="utf-8")
    blocked_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "vibedft",
            "evidence",
            "--case-dir",
            str(blocked_case),
            "--json",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert blocked_result.returncode == 2
    payload = json.loads(blocked_result.stdout)
    assert payload["overall_status"] == "BLOCK"

    concern_case_root = tmp_path / "concern_case"
    concern_case_root.mkdir()
    concern_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "vibedft",
            "evidence",
            "--case-dir",
            str(concern_case_root),
            "--json",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert concern_result.returncode == 0
    concern_payload = json.loads(concern_result.stdout)
    assert concern_payload["overall_status"] in {"CONCERN", "PASS"}

    batch_root = tmp_path / "batch_exit"
    _write_feature_rich_case(batch_root)
    (batch_root / "bad_case").mkdir()
    (batch_root / "bad_case" / "output").mkdir(parents=True)
    (batch_root / "bad_case" / "output" / "lambdax.out").write_text(NAN_LAMBDAX, encoding="utf-8")

    batch_blocked_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "vibedft",
            "evidence",
            "--batch-root",
            str(batch_root),
            "--json",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert batch_blocked_result.returncode == 2


def _write_mixed_case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    output = case_dir / "output"
    output.mkdir(parents=True)
    (output / "fs.bxsf").write_text(SAMPLE_BXSF, encoding="utf-8")
    (output / "fs.out").write_text(SAMPLE_FS_OUT, encoding="utf-8")
    (output / "lambdax.out").write_text(SAMPLE_LAMBDAX, encoding="utf-8")
    (output / "phonon.freq.gp").write_text(NEGATIVE_FREQ_GP, encoding="utf-8")
    return case_dir


def _write_feature_rich_case(tmp_path: Path, name: str = "feature_rich_case") -> Path:
    case_dir = tmp_path / name
    inputs = case_dir / "inputs"
    output = case_dir / "output"
    charge = case_dir / "charge"
    band_alignment = case_dir / "band_alignment"
    md = case_dir / "md"
    for directory in [inputs, output, charge, band_alignment, md]:
        directory.mkdir(parents=True)

    (inputs / "pw.in").write_text(SAMPLE_PW_IN, encoding="utf-8")
    (inputs / "ph.in").write_text(SAMPLE_PH_IN, encoding="utf-8")
    (output / "scf.out").write_text(SAMPLE_SCF_OUT, encoding="utf-8")
    (output / "sample.bands").write_text(SAMPLE_BANDS, encoding="utf-8")
    (output / "sample.dos").write_text(SAMPLE_DOS, encoding="utf-8")
    (output / "fs.bxsf").write_text(SAMPLE_BXSF, encoding="utf-8")
    (output / "fs.out").write_text(SAMPLE_FS_OUT, encoding="utf-8")
    (output / "phonon.freq.gp").write_text(POSITIVE_FREQ_GP, encoding="utf-8")
    (output / "lambdax.out").write_text(SAMPLE_LAMBDAX, encoding="utf-8")
    (output / "elastic_tensor.dat").write_text(SAMPLE_ELASTIC, encoding="utf-8")

    (charge / "ACF.dat").write_text(SAMPLE_ACF, encoding="utf-8")
    (charge / "planar_avg.dat").write_text(SAMPLE_PLANAR, encoding="utf-8")
    (charge / "rho.cube").write_text(SAMPLE_CUBE_HEADER, encoding="utf-8")

    (band_alignment / "layer_a.band_edges").write_text(SAMPLE_BAND_EDGE_A, encoding="utf-8")
    (band_alignment / "layer_b.band_edges").write_text(SAMPLE_BAND_EDGE_B, encoding="utf-8")
    (band_alignment / "layer_projected_bands.dat").write_text("layer band evidence\n", encoding="utf-8")
    (band_alignment / "relaxed_structure.out").write_text("JOB DONE\n", encoding="utf-8")

    (md / "T_K.dat").write_text(SAMPLE_MD_T, encoding="utf-8")
    (md / "Etot_Ry.dat").write_text(SAMPLE_MD_E, encoding="utf-8")
    (md / "traj.xyz").write_text(SAMPLE_XYZ, encoding="utf-8")
    return case_dir
