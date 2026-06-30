from pathlib import Path

from vibedft.research.gates import evaluate_claim
from vibedft.research.models import (
    ArtifactLineage,
    ArtifactType,
    ClaimType,
    EvidenceMaturity,
    GateVerdict,
    ScientificClaim,
)
from vibedft.research.scanner import scan_case


def _claim(claim_type: ClaimType) -> ScientificClaim:
    return ScientificClaim(
        id=f"claim.test.{claim_type.value}",
        question_id="rq.test",
        claim_type=claim_type,
        statement="Test claim for deterministic research gate evaluation.",
    )


def test_negative_result_claim_passes_on_k_soft_mode_without_reporting_tc():
    artifacts = scan_case(Path("tests/fixtures/research/k_soft_mode"))

    decision = evaluate_claim(_claim(ClaimType.NEGATIVE_RESULT), artifacts)

    assert decision.verdict == GateVerdict.PASS
    assert decision.maturity == EvidenceMaturity.PHYSICALLY_USABLE
    assert any("soft mode" in reason.lower() for reason in decision.blocking_reasons)
    assert any("tc" in conclusion.lower() for conclusion in decision.forbidden_conclusions)


def test_epc_mechanism_claim_is_blocked_by_na_finite_q_soft_mode():
    artifacts = scan_case(Path("tests/fixtures/research/na_finite_q_soft_mode"))

    decision = evaluate_claim(_claim(ClaimType.EPC_MECHANISM), artifacts)

    assert decision.verdict == GateVerdict.BLOCKED
    assert decision.maturity == EvidenceMaturity.PHYSICALLY_USABLE
    assert any("finite-q" in reason.lower() for reason in decision.blocking_reasons)
    assert any("mode-following" in action.lower() for action in decision.recommended_next_actions)


def test_stability_claim_fails_when_signed_negative_frequency_is_present():
    artifacts = scan_case(Path("tests/fixtures/research/k_soft_mode"))

    decision = evaluate_claim(_claim(ClaimType.STABILITY), artifacts)

    assert decision.verdict == GateVerdict.FAIL
    assert any("-87.9888" in reason for reason in decision.blocking_reasons)


def test_epc_claim_blocks_on_nan_epc_values_without_soft_mode_explanation(tmp_path):
    lambdax_path = tmp_path / "lambdax.out"
    lambdax_path.write_text(
        "     lambda        omega_log          T_c\n"
        "     0.86          NaN                NaN\n",
        encoding="utf-8",
    )
    lambdax = ArtifactLineage(
        artifact_id="output.lambdax.out",
        artifact_type=ArtifactType.LAMBDAX,
        server="local",
        path=str(lambdax_path),
    )

    decision = evaluate_claim(_claim(ClaimType.TC_ROBUSTNESS), [lambdax])

    assert decision.verdict == GateVerdict.BLOCKED
    assert any("nan" in reason.lower() for reason in decision.blocking_reasons)


def test_matdyn_nbnd_three_frequency_row_is_not_misread_as_q_point(tmp_path):
    matdyn_path = tmp_path / "matdyn.freq"
    matdyn_path.write_text(
        "&plot nbnd= 3, nks= 1 /\n"
        "0.0000000000 0.0000000000 0.0000000000\n"
        "-12.500000 10.000000 20.000000\n",
        encoding="utf-8",
    )
    artifact = ArtifactLineage(
        artifact_id="output.matdyn.freq",
        artifact_type=ArtifactType.DYN,
        server="local",
        path=str(matdyn_path),
    )

    decision = evaluate_claim(_claim(ClaimType.STABILITY), [artifact])

    assert decision.verdict == GateVerdict.FAIL
    assert any("-12.500000" in reason for reason in decision.blocking_reasons)


def test_ph_output_frequency_parser_prefers_explicit_cm_inverse_value(tmp_path):
    ph_path = tmp_path / "ph.out"
    ph_path.write_text(
        "     q = ( 0.000000000 0.000000000 0.000000000 )\n"
        "     freq (    1) = -4.721556 [THz] = -157.494161 [cm-1]\n",
        encoding="utf-8",
    )
    artifact = ArtifactLineage(
        artifact_id="output.ph.out",
        artifact_type=ArtifactType.OUTPUT,
        server="local",
        path=str(ph_path),
    )

    decision = evaluate_claim(_claim(ClaimType.STABILITY), [artifact])

    joined_reasons = "\n".join(decision.blocking_reasons)
    assert "-157.494161" in joined_reasons
    assert "-4.721556" not in joined_reasons


def test_stability_pass_uses_positive_frequency_artifact_as_support(tmp_path):
    ph_path = tmp_path / "ph.out"
    ph_path.write_text(
        "     q = ( 0.000000000 0.000000000 0.000000000 )\n"
        "     freq (    1) =      12.300000 [cm-1]\n"
        "     freq (    2) =      45.600000 [cm-1]\n",
        encoding="utf-8",
    )
    artifact = ArtifactLineage(
        artifact_id="output.ph.out",
        artifact_type=ArtifactType.OUTPUT,
        server="local",
        path=str(ph_path),
    )

    decision = evaluate_claim(_claim(ClaimType.STABILITY), [artifact])

    assert decision.verdict == GateVerdict.PASS
    assert decision.supporting_artifacts == ["output.ph.out"]
