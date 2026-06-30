from __future__ import annotations

from dataclasses import asdict
import pytest

from vibedft._shared.contracts import (
    CleanedResult,
    DownstreamReadiness,
    Evidence,
    Readiness,
    ReviewResult,
)


def test_cleaned_result_accepts_review_as_first_class_field() -> None:
    review = ReviewResult(
        status="PASS",
        reasons=["quality gate reached"],
        evidence=[Evidence(source="scf.out", field="converged", value=True, interpretation="done")],
        allowed_downstream=["relax", "nscf"],
        blocked_downstream=["phonon"],
    )
    readiness = Readiness(
        downstream={
            "relax": DownstreamReadiness(task="relax", allowed=True),
            "nscf": DownstreamReadiness(task="nscf", allowed=True),
            "phonon": DownstreamReadiness(task="phonon", allowed=False, reason="stability issue"),
        },
        summary="ready",
    )
    cleaned = CleanedResult(
        calculator="qe",
        task="scf",
        status="pass",
        review=review,
        readiness=readiness,
    )

    assert cleaned.review is not None
    assert cleaned.review.status == "PASS"
    assert cleaned.readiness.downstream["phonon"].allowed is False


def test_cleaned_result_readiness_is_typed() -> None:
    cleaned = CleanedResult(
        calculator="qe",
        task="scf",
        status="warn",
        review=None,
        readiness=Readiness(downstream={"relax": DownstreamReadiness(task="relax", allowed=True)}),
    )

    assert isinstance(cleaned.readiness, Readiness)
    assert cleaned.readiness.downstream["relax"].allowed is True


def test_downstream_readiness_serializes_with_dataclasses_asdict() -> None:
    readiness = Readiness(
        downstream={
            "relax": DownstreamReadiness(
                task="relax",
                allowed=True,
                reason="converged",
                evidence_refs=["E001", "E002"],
            ),
        },
        summary="ok",
    )
    payload = asdict(readiness)

    assert payload["downstream"]["relax"]["task"] == "relax"
    assert payload["downstream"]["relax"]["allowed"] is True
    assert payload["downstream"]["relax"]["evidence_refs"] == ["E001", "E002"]


def test_evidence_supports_artifact_and_line_range() -> None:
    evidence = Evidence(
        source="scf.out",
        field="fermi_energy_ev",
        value=4.2,
        interpretation="parsed fermi energy",
        line_start=12,
        line_end=15,
        artifact="pwscf.out",
        section="electronic",
        evidence_id="E-FERMI-1",
    )
    payload = asdict(evidence)

    assert payload["line_start"] == 12
    assert payload["line_end"] == 15
    assert payload["artifact"] == "pwscf.out"
    assert payload["section"] == "electronic"
    assert payload["evidence_id"] == "E-FERMI-1"


def test_cleaned_result_legacy_payload_and_source_artifacts_compatibility() -> None:
    cleaned = CleanedResult(
        calculator="qe",
        task="scf",
        status="warn",
        source_artifacts=["scf.out"],
        payload={"final_total_energy_ry": -12.345},
    )

    assert cleaned.source_files == ["scf.out"]
    assert cleaned.payload["final_total_energy_ry"] == -12.345
    assert cleaned.outputs["final_total_energy_ry"] == -12.345


def test_cleaned_result_invalid_status_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unsupported cleaned status"):
        CleanedResult(calculator="qe", task="scf", status="bad")
