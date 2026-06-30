"""Evidence-backed 2D elastic/mechanical stability tests."""

from pathlib import Path

from vibedft.properties.elastic import (
    analyze_mechanical_stability,
    parse_elastic_tensor_summary,
)
from vibedft.research.models import ResultStatus


def _write_elastic_summary(
    path: Path,
    *,
    c11: float = 120.0,
    c12: float = 28.0,
    c66: float = 46.0,
    source: str = "strain_sweep",
    strain_points: int = 7,
) -> Path:
    path.write_text(
        f"C11_N_per_m: {c11:.6f}\n"
        f"C12_N_per_m: {c12:.6f}\n"
        f"C66_N_per_m: {c66:.6f}\n"
        f"source: {source}\n"
        f"strain_points: {strain_points}\n",
        encoding="utf-8",
    )
    return path


def test_parse_elastic_tensor_summary_reads_2d_constants(tmp_path: Path):
    tensor_path = _write_elastic_summary(tmp_path / "elastic_summary.dat")

    tensor = parse_elastic_tensor_summary(tensor_path)

    assert tensor.has_data
    assert tensor.c11_n_per_m == 120.0
    assert tensor.c12_n_per_m == 28.0
    assert tensor.c66_n_per_m == 46.0
    assert tensor.source == "strain_sweep"
    assert tensor.strain_points == 7


def test_analyze_mechanical_stability_outputs_traceable_born_verdict(tmp_path: Path):
    tensor_path = _write_elastic_summary(tmp_path / "elastic_summary.dat")

    result = analyze_mechanical_stability(elastic_tensor_path=tensor_path)

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}
    parser_names = {evidence.parser_name for evidence in result.evidence}

    assert result.status == ResultStatus.PASS
    assert descriptors["elastic_tensor_2d"]["C11_N_per_m"] == 120.0
    assert descriptors["born_criteria_2d"]["C11_positive"] is True
    assert descriptors["born_criteria_2d"]["C66_positive"] is True
    assert descriptors["born_criteria_2d"]["C11_minus_C12_positive"] is True
    assert descriptors["youngs_modulus_2d_N_per_m"] == 113.466667
    assert descriptors["poisson_ratio_2d"] == 0.233333
    assert descriptors["mechanical_stability_classification"] == "mechanically_stable"
    assert "vibedft.properties.elastic.parse_elastic_tensor_summary" in parser_names


def test_analyze_mechanical_stability_is_insufficient_without_strain_sweep():
    result = analyze_mechanical_stability(elastic_tensor_path=None)

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}

    assert result.status == ResultStatus.INSUFFICIENT_EVIDENCE
    assert descriptors["mechanical_stability_classification"] == "insufficient_evidence"
    assert any("strain" in blocker.lower() for blocker in result.blockers)
    assert any(
        "mechanical stability" in conclusion.lower()
        for conclusion in result.metadata["forbidden_conclusions"]
    )


def test_analyze_mechanical_stability_rejects_md_stress_as_elastic_tensor(tmp_path: Path):
    tensor_path = _write_elastic_summary(
        tmp_path / "stress_Rybohr3.dat",
        source="md_stress_time_series",
    )

    result = analyze_mechanical_stability(elastic_tensor_path=tensor_path)

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}

    assert result.status == ResultStatus.BLOCKED
    assert descriptors["mechanical_stability_classification"] == "insufficient_evidence"
    assert any("md stress" in blocker.lower() for blocker in result.blockers)


def test_analyze_mechanical_stability_blocks_failed_2d_born_criteria(tmp_path: Path):
    tensor_path = _write_elastic_summary(
        tmp_path / "elastic_summary.dat",
        c11=50.0,
        c12=72.0,
        c66=-4.0,
    )

    result = analyze_mechanical_stability(elastic_tensor_path=tensor_path)

    descriptors = {descriptor.name: descriptor.value for descriptor in result.descriptors}

    assert result.status == ResultStatus.BLOCKED
    assert descriptors["born_criteria_2d"]["C66_positive"] is False
    assert descriptors["born_criteria_2d"]["C11_minus_C12_positive"] is False
    assert descriptors["mechanical_stability_classification"] == "mechanically_unstable"
    assert any("Born" in blocker for blocker in result.blockers)
