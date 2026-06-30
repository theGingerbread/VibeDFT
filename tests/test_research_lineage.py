from vibedft.research.lineage import (
    CompatibilityResult,
    detect_case_lineage_warnings,
    parameter_fingerprints_compatible,
)
from vibedft.research.models import ArtifactLineage, ArtifactType
from vibedft.research.scanner import scan_case


def test_detects_invalid_type3_planar_average_fixture():
    artifacts = scan_case("tests/fixtures/research/type3_invalid_potential")

    warnings = detect_case_lineage_warnings(artifacts)

    joined = "\n".join(warnings).lower()
    assert "planar average" in joined
    assert "old save" in joined


def test_parameter_fingerprints_require_exact_match_by_default():
    left = ArtifactLineage(
        artifact_id="input.scf.16",
        artifact_type=ArtifactType.INPUT,
        server="local",
        path="/tmp/scf16.in",
        parameter_fingerprint="ecutwfc=90|ecutrho=720|k=16x16x1|2d=true",
    )
    right = ArtifactLineage(
        artifact_id="input.scf.24",
        artifact_type=ArtifactType.INPUT,
        server="local",
        path="/tmp/scf24.in",
        parameter_fingerprint="ecutwfc=90|ecutrho=720|k=24x24x1|2d=true",
    )

    result = parameter_fingerprints_compatible(left, right)

    assert isinstance(result, CompatibilityResult)
    assert result.compatible is False
    assert "k=16x16x1" in result.reason
    assert "k=24x24x1" in result.reason


def test_planar_average_delta_v_warning_handles_case_and_spacing(tmp_path):
    log = tmp_path / "planar_average.log"
    log.write_text(
        "Planar average electrostatic potential summary.\n"
        "DeltaV = 0.841 eV across the interface.\n",
        encoding="utf-8",
    )
    artifact = ArtifactLineage(
        artifact_id="output.planar_average.log",
        artifact_type=ArtifactType.REPORT,
        server="local",
        path=str(log),
    )

    warnings = detect_case_lineage_warnings([artifact])

    assert any("deltav" in warning.lower() for warning in warnings)
