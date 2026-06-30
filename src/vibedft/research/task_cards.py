"""Lightweight LLM task cards derived from deterministic gate decisions."""

from __future__ import annotations

from vibedft.research.models import (
    ClaimType,
    GateDecision,
    GateVerdict,
    LLMTaskCard,
    ScientificClaim,
)


BASE_FORBIDDEN_ACTIONS = [
    "edit_remote_files",
    "overwrite_production_outdir",
    "submit_slurm_job",
    "cancel_slurm_job",
    "run_qe_binary",
]


def build_task_card_for_decision(
    claim: ScientificClaim,
    decision: GateDecision,
) -> LLMTaskCard:
    """Build bounded LLM instructions from a deterministic gate decision."""

    if decision.verdict == GateVerdict.BLOCKED:
        forbidden_actions = list(BASE_FORBIDDEN_ACTIONS)
        if _is_epc_or_tc_context(claim, decision):
            forbidden_actions.extend(
                [
                    "generate_epc_input",
                    "report_tc",
                    "rank_tc",
                ]
            )

        return LLMTaskCard(
            id=f"taskcard.{decision.claim_id}.stop_report",
            claim_id=decision.claim_id,
            task_type="stop_report",
            allowed_actions=[
                "read_supporting_artifacts",
                "extract_blocking_evidence",
                "write_stop_report",
            ],
            forbidden_actions=forbidden_actions,
            required_files=list(decision.supporting_artifacts),
            required_checks=[
                "preserve_signed_frequencies",
                "preserve_nan_values",
                "quote_missing_artifacts",
            ],
            expected_outputs=[
                "stop_report",
                "blocking_evidence_summary",
                "recommended_next_actions",
            ],
            stop_if=list(decision.blocking_reasons),
            escalate_if=[],
            response_schema={
                "claim_id": "str",
                "verdict": "str",
                "blocking_reasons": "list[str]",
                "forbidden_conclusions": "list[str]",
                "recommended_next_actions": "list[str]",
            },
        )

    if decision.verdict == GateVerdict.WARNING:
        return LLMTaskCard(
            id=f"taskcard.{decision.claim_id}.escalate",
            claim_id=decision.claim_id,
            task_type="escalate",
            allowed_actions=[
                "summarize_known_evidence",
                "escalate_to_stronger_model_or_human",
            ],
            forbidden_actions=[
                *BASE_FORBIDDEN_ACTIONS,
                "make_paper_grade_claim",
            ],
            required_files=list(decision.supporting_artifacts),
            required_checks=["identify_unsupported_rule", "preserve_uncertainty"],
            expected_outputs=["evidence_summary", "escalation_request"],
            stop_if=[],
            escalate_if=["unsupported_rule"],
            response_schema={
                "claim_id": "str",
                "verdict": "str",
                "evidence_summary": "str",
                "escalate_if": "list[str]",
            },
        )

    return LLMTaskCard(
        id=f"taskcard.{decision.claim_id}.validate",
        claim_id=decision.claim_id,
        task_type="validate",
        allowed_actions=[
            "read_supporting_artifacts",
            "run_local_parser",
            "summarize_evidence",
        ],
        forbidden_actions=list(BASE_FORBIDDEN_ACTIONS),
        required_files=list(decision.supporting_artifacts),
        required_checks=["preserve_signed_frequencies", "preserve_nan_values"],
        expected_outputs=["evidence_summary"],
        stop_if=list(decision.blocking_reasons),
        escalate_if=[],
        response_schema={
            "claim_id": "str",
            "verdict": "str",
            "evidence_summary": "str",
            "recommended_next_actions": "list[str]",
        },
    )


def _is_epc_or_tc_context(claim: ScientificClaim, decision: GateDecision) -> bool:
    if claim.claim_type in {ClaimType.EPC_MECHANISM, ClaimType.TC_ROBUSTNESS}:
        return True

    haystack = " ".join(
        [
            claim.statement,
            *claim.assumptions,
            claim.validity_domain,
            *decision.blocking_reasons,
            *decision.forbidden_conclusions,
            *decision.recommended_next_actions,
        ]
    ).lower()
    return "epc" in haystack or "tc" in haystack or "t_c" in haystack
