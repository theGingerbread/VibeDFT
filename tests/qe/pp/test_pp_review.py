"""Tests for QE pp.x review policy."""

from __future__ import annotations

from pathlib import Path

from vibedft.calculator.qe.pp import parse_pp_output
from vibedft.calculator.qe.pp.review import review_pp_output
from vibedft.calculator.qe.pp.schemas import PP_DOWNSTREAMS


def _pp_text_charge() -> str:
    return """Program PP v.7.3 starts on 01Jul2026
plot_num = 0
Writing data to charge.dat
charge density selected for post-processing
JOB DONE.
"""


def _pp_text_unknown() -> str:
    return """Program PP v.7.3 starts on 01Jul2026
plot_num = 17
Writing data to field.cube
JOB DONE.
"""


def _pp_text_incomplete() -> str:
    return """Program PP v.7.3 starts on 01Jul2026
plot_num = 0
Writing data to charge.dat
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


def test_review_pp_output_pass_with_charge_density_artifact(tmp_path: Path) -> None:
    artifact = _write_numeric_artifact(tmp_path / "charge.dat")
    output = parse_pp_output(_pp_text_charge(), source="pp.out", data_files=[artifact])

    result = review_pp_output(output)

    assert result.status == "PASS"
    assert "analysis.pp" in result.allowed_downstream
    assert "analysis.charge_density" in result.allowed_downstream
    assert "analysis.potential" in result.blocked_downstream
    assert "analysis.spin_density" in result.blocked_downstream
    for downstream in ("phonon", "epc", "tc", "scf", "relax"):
        assert downstream in result.blocked_downstream


def test_review_pp_output_warn_when_field_kind_unknown(tmp_path: Path) -> None:
    artifact = tmp_path / "field.cube"
    artifact.write_text("CUBE payload placeholder\n", encoding="utf-8")
    output = parse_pp_output(_pp_text_unknown(), source="pp.out", data_files=[artifact])

    result = review_pp_output(output)

    assert result.status == "WARN"
    assert "analysis.pp" in result.allowed_downstream
    assert "analysis.charge_density" in result.blocked_downstream
    assert result.recommendations


def test_review_pp_output_blocks_without_job_done(tmp_path: Path) -> None:
    artifact = _write_numeric_artifact(tmp_path / "charge.dat")
    output = parse_pp_output(_pp_text_incomplete(), source="pp.out", data_files=[artifact])

    result = review_pp_output(output)

    assert result.status == "BLOCK"
    assert not result.allowed_downstream
    assert set(result.blocked_downstream) == set(PP_DOWNSTREAMS)
