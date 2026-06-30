import json
import math
from pathlib import Path

from vibedft.research.manifest import load_fixture_manifest
from vibedft.research.regression import REALDATA_REGRESSION_REQUIREMENTS


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "research"


def test_load_fixture_manifest_loads_real_remote_metadata_fixture():
    manifest = load_fixture_manifest(FIXTURES / "real_fixture_manifest.json")

    data = manifest.to_dict()

    assert data["id"] == "realdata.minimum_objective_suite"
    assert data["import_policy"] == "metadata_only"
    assert len(data["artifacts"]) == len(REALDATA_REGRESSION_REQUIREMENTS)
    assert data["artifacts"][0]["artifact_path"].startswith("remote://fs/hfbr2")
    assert data["artifacts"][0]["metadata"]["physics_use"] == "fermi_surface_topology"
    fixture_keys = {artifact["metadata"]["fixture_key"] for artifact in data["artifacts"]}
    assert "bader_hfbr2_tise2_het_acf" in fixture_keys
    assert "elastic_synthetic_until_real_strain" in fixture_keys
    negative_fixture = next(
        artifact
        for artifact in data["artifacts"]
        if artifact["metadata"]["fixture_key"] == "epc_negative_k_hfcl2_top"
    )
    assert negative_fixture["blockers"] == [
        "negative phonon fixture must never pass superconducting Tc verdicts"
    ]

    assert json.loads(json.dumps(data))["source"] == "remote_fixture_inventory"


def test_load_fixture_manifest_missing_file_returns_blocked_manifest(tmp_path):
    manifest = load_fixture_manifest(tmp_path / "missing_fixture_manifest.json")

    data = manifest.to_dict()

    assert data["artifacts"] == []
    assert data["blockers"] == ["fixture manifest file not found"]
    assert data["source"].endswith("missing_fixture_manifest.json")


def test_load_fixture_manifest_marks_incomplete_and_nan_entries_without_crashing(tmp_path):
    manifest_path = tmp_path / "bad_fixture_manifest.json"
    manifest_path.write_text(
        """
        {
          "id": "bad.fixture",
          "source": "synthetic",
          "artifacts": [
            {
              "artifact_type": "dyn",
              "parser_name": "lambda.x",
              "parsed_quantity": "omega_log",
              "raw_value": NaN,
              "summary": "Malformed lambda output produced NaN."
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    manifest = load_fixture_manifest(manifest_path)

    assert manifest.id == "bad.fixture"
    assert len(manifest.artifacts) == 1
    artifact = manifest.artifacts[0]
    assert math.isnan(artifact.raw_value)
    assert "artifact_path is required" in artifact.blockers
    assert "raw_value is non-finite" in artifact.blockers
