from pathlib import Path

from vibedft.research import ArtifactType, scan_case


FIXTURE = Path("tests/fixtures/research/hfi2_e005_legacy")


def test_scan_case_finds_qe_artifacts_and_extracts_lineage():
    artifacts = scan_case(FIXTURE)
    by_id = {artifact.artifact_id: artifact for artifact in artifacts}

    assert "input.scf.in" in by_id
    assert "output.scf.out" in by_id
    assert "output.lambdax.out" in by_id

    scf_input = by_id["input.scf.in"]
    assert scf_input.artifact_type == ArtifactType.INPUT
    assert scf_input.prefix == "hfi2_e005"
    assert scf_input.outdir == "./out"
    assert scf_input.parameter_fingerprint == "ecutwfc=90|ecutrho=720|k=16x16x1"
    assert scf_input.parse_status == "ok"

    scf_output = by_id["output.scf.out"]
    assert scf_output.artifact_type == ArtifactType.OUTPUT
    assert scf_output.producer_program == "pw.x"
    assert scf_output.job_status == "JOB_DONE"
    assert scf_output.parse_status == "ok"

    lambdax_output = by_id["output.lambdax.out"]
    assert lambdax_output.artifact_type == ArtifactType.LAMBDAX


def test_scan_case_keeps_nested_artifact_ids_unique(tmp_path):
    stage1 = tmp_path / "stage1"
    stage2 = tmp_path / "stage2"
    stage1.mkdir()
    stage2.mkdir()
    stage1_input = stage1 / "scf.in"
    stage2_input = stage2 / "scf.in"
    stage1_input.write_text("&CONTROL\n  prefix = 'one',\n/\n", encoding="utf-8")
    stage2_input.write_text("&CONTROL\n  prefix = 'two',\n/\n", encoding="utf-8")

    artifact_ids = {artifact.artifact_id for artifact in scan_case(tmp_path)}

    assert "input.stage1.scf.in" in artifact_ids
    assert "input.stage2.scf.in" in artifact_ids
    assert len(artifact_ids) == 2
