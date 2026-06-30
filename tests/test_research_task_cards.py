import json

from vibedft.research.models import (
    ClaimType,
    EvidenceMaturity,
    GateDecision,
    GateVerdict,
    ScientificClaim,
)
from vibedft.research.task_cards import build_task_card_for_decision


def _claim(claim_type: ClaimType) -> ScientificClaim:
    return ScientificClaim(
        id=f"claim.test.{claim_type.value}",
        question_id="rq.test",
        claim_type=claim_type,
        statement="Test claim for LLM task-card generation.",
    )


def test_blocked_epc_decision_generates_stop_report_card():
    decision = GateDecision(
        claim_id="claim.test.epc_mechanism",
        maturity=EvidenceMaturity.PHYSICALLY_USABLE,
        verdict=GateVerdict.BLOCKED,
        blocking_reasons=["Finite-q soft mode at q2 remains negative."],
        supporting_artifacts=["artifact.ph.p3.q2", "artifact.matdyn.freq"],
        forbidden_conclusions=["Do not report Tc until dynamical stability passes."],
        recommended_next_actions=["Follow the finite-q soft mode before EPC."],
    )

    card = build_task_card_for_decision(_claim(ClaimType.EPC_MECHANISM), decision)

    assert card.task_type == "stop_report"
    assert "read_supporting_artifacts" in card.allowed_actions
    assert "submit_slurm_job" in card.forbidden_actions
    assert "run_qe_binary" in card.forbidden_actions
    assert "generate_epc_input" in card.forbidden_actions
    assert "report_tc" in card.forbidden_actions
    assert "rank_tc" in card.forbidden_actions
    assert card.required_files == ["artifact.ph.p3.q2", "artifact.matdyn.freq"]
    assert "forbidden_conclusions" in card.response_schema
    assert any("finite-q soft mode" in stop.lower() for stop in card.stop_if)


def test_blocked_card_detects_lowercase_tc_epc_context_from_text():
    claim = ScientificClaim(
        id="claim.test.stability",
        question_id="rq.test",
        claim_type=ClaimType.STABILITY,
        statement="stability gate before reporting tc or epc context",
    )
    decision = GateDecision(
        claim_id=claim.id,
        maturity=EvidenceMaturity.PHYSICALLY_USABLE,
        verdict=GateVerdict.BLOCKED,
        blocking_reasons=["tc blocked because epc is unsafe for this structure"],
        supporting_artifacts=["artifact.ph.p3.q2"],
    )

    card = build_task_card_for_decision(claim, decision)

    assert "generate_epc_input" in card.forbidden_actions
    assert "report_tc" in card.forbidden_actions
    assert "rank_tc" in card.forbidden_actions


def test_warning_card_requires_escalation():
    decision = GateDecision(
        claim_id="claim.test.band_alignment",
        maturity=EvidenceMaturity.RUN_FINISHED,
        verdict=GateVerdict.WARNING,
        supporting_artifacts=["artifact.report"],
        missing_artifacts=["claim-specific evidence policy"],
    )

    card = build_task_card_for_decision(_claim(ClaimType.BAND_ALIGNMENT), decision)

    assert card.task_type == "escalate"
    assert "escalate_to_stronger_model_or_human" in card.allowed_actions
    assert "submit_slurm_job" in card.forbidden_actions
    assert "run_qe_binary" in card.forbidden_actions
    assert "make_paper_grade_claim" in card.forbidden_actions
    assert "unsupported_rule" in card.escalate_if


def test_task_card_to_dict_is_json_serializable_with_stable_lists_and_schema():
    decision = GateDecision(
        claim_id="claim.test.stability",
        maturity=EvidenceMaturity.NUMERICALLY_CONVERGED,
        verdict=GateVerdict.PASS,
        supporting_artifacts=["artifact.ph.gamma"],
    )

    card = build_task_card_for_decision(_claim(ClaimType.STABILITY), decision)
    data = card.to_dict()

    assert data["claim_id"] == "claim.test.stability"
    assert "submit_slurm_job" in data["forbidden_actions"]
    assert "run_qe_binary" in data["forbidden_actions"]
    assert data["allowed_actions"] == [
        "read_supporting_artifacts",
        "run_local_parser",
        "summarize_evidence",
    ]
    assert data["response_schema"] == {
        "claim_id": "str",
        "verdict": "str",
        "evidence_summary": "str",
        "recommended_next_actions": "list[str]",
    }
    assert json.loads(json.dumps(data)) == data
