"""Tests for QE pp.x cleaned-result mapping."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from vibedft.calculator.qe.pp import clean_pp_output, clean_pp_text, parse_pp_output
from vibedft.calculator.qe.pp.schemas import PP_DOWNSTREAMS, PP_TASK_LEGACY


def _pp_text_charge() -> str:
    return """Program PP v.7.3 starts on 01Jul2026
plot_num = 0
fileout = 'charge.dat'
charge density selected for post-processing
JOB DONE.
"""


def _pp_text_truncated() -> str:
    return """Program PP v.7.3 starts on 01Jul2026
plot_num = 0
fileout = 'charge.dat'
charge density selected for post-processing
"""


def _write_numeric_artifact(path: Path) -> Path:
    path.write_text(
        """# x y z rho
0.0 0.0 0.0 1.25
0.0 0.0 1.0 2.50
""",
        encoding="utf-8",
    )
    return path


def test_clean_pp_output_pass_structure_and_readiness(tmp_path: Path) -> None:
    artifact = _write_numeric_artifact(tmp_path / "charge.dat")
    output = parse_pp_output(_pp_text_charge(), source="pp.out", data_files=[artifact])

    result = clean_pp_output(output)

    assert result.calculator == "qe"
    assert result.task == PP_TASK_LEGACY
    assert result.status == "pass"
    assert result.review is not None
    assert result.review.status == "PASS"
    assert result.provenance.command == "pp.x"
    assert result.outputs["job_done"] is True
    assert result.outputs["field_kind"] == "charge_density"
    assert result.outputs["data_file_count"] == 1
    assert result.observables["data_sample_count"] == 2
    assert result.observables["data_min"] == 0.0
    assert result.observables["data_max"] == 2.5
    assert result.readiness.downstream["analysis.pp"].allowed is True
    assert result.readiness.downstream["analysis.charge_density"].allowed is True
    for downstream in ("phonon", "epc", "tc", "scf", "relax"):
        assert result.readiness.downstream[downstream].allowed is False
    assert result.payload == result.outputs


def test_clean_pp_output_block_and_json_serializable(tmp_path: Path) -> None:
    output_path = tmp_path / "pp.out"
    artifact = _write_numeric_artifact(tmp_path / "charge.dat")
    output_path.write_text(_pp_text_truncated(), encoding="utf-8")

    result = clean_pp_text(output_path, data_files=[artifact])
    payload = json.dumps(asdict(result), allow_nan=False)
    data = json.loads(payload)

    assert result.status == "block"
    assert result.review is not None
    assert result.review.status == "BLOCK"
    assert set(result.readiness.downstream) == set(PP_DOWNSTREAMS)
    assert all(not edge.allowed for edge in result.readiness.downstream.values())
    assert data["review"]["status"] == "BLOCK"
    assert data["readiness"]["downstream"]["analysis.pp"]["allowed"] is False


def test_clean_pp_text_tracks_source_files_and_artifacts(tmp_path: Path) -> None:
    output_path = tmp_path / "pp.out"
    artifact = _write_numeric_artifact(tmp_path / "charge.dat")
    output_path.write_text(_pp_text_charge(), encoding="utf-8")

    result = clean_pp_text(output_path, data_files=[artifact])

    assert result.source_files[0] == "pp.out"
    assert any("charge.dat" in item for item in result.source_files)
    assert any("charge.dat" in item for item in result.source_artifacts)
    assert result.outputs["existing_output_files"]
    assert result.outputs["nonempty_output_files"]
