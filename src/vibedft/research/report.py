"""Claim-first Markdown reporting for deterministic research gate decisions."""

from __future__ import annotations

from enum import Enum

from vibedft.research.models import (
    AnalysisResult,
    GateDecision,
    ResultStatus,
    WorkflowStageResult,
)


def render_claim_report(
    decisions: list[GateDecision],
    title: str = "VibeDFT research claim report",
) -> str:
    """Render gate decisions as a claim-first Markdown report."""

    lines = [f"# {title}", ""]
    if not decisions:
        return "\n".join([*lines, "No gate decisions were provided."]) + "\n"

    for decision in decisions:
        lines.extend(
            [
                f"## Claim {decision.claim_id}",
                "",
                f"- Claim id: {decision.claim_id}",
                f"- Verdict: `{_value(decision.verdict)}`",
                f"- Maturity: `{_value(decision.maturity)}`",
                "",
                "### Blocking reasons",
                *_bullet_list(decision.blocking_reasons),
                "",
                "### Supporting artifacts",
                *_bullet_list(decision.supporting_artifacts),
                "",
                "### Missing artifacts",
                *_bullet_list(decision.missing_artifacts),
                "",
                "### Forbidden conclusions",
                *_bullet_list(decision.forbidden_conclusions),
                "",
                "### Recommended next actions",
                *_bullet_list(decision.recommended_next_actions),
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def workflow_stage_from_analysis(
    stage_id: str,
    analysis: AnalysisResult,
    *,
    next_actions: list[str] | None = None,
) -> WorkflowStageResult:
    """Convert one analyzer result into a workflow stage result.

    A PASS analysis without evidence is demoted to ``insufficient_evidence`` so
    report generation cannot accidentally turn an unsupported result into a
    final scientific claim.
    """

    status = analysis.status
    blockers = list(analysis.blockers)
    if status == ResultStatus.PASS and not analysis.evidence:
        status = ResultStatus.INSUFFICIENT_EVIDENCE
        blockers.append("supporting evidence is required for a pass stage")

    return WorkflowStageResult(
        stage_id=stage_id,
        status=status,
        descriptors=list(analysis.descriptors),
        evidence=list(analysis.evidence),
        warnings=list(analysis.warnings),
        blockers=blockers,
        next_actions=list(next_actions or []),
        reliability=analysis.reliability,
        metadata={
            "analysis_id": analysis.id,
            "parser_name": analysis.parser_name,
            "parsed_quantity": analysis.parsed_quantity,
        },
    )


def render_evidence_backed_summary(
    stages: list[WorkflowStageResult],
    title: str = "VibeDFT evidence-backed workflow summary",
) -> str:
    """Render workflow stages with explicit descriptor and evidence traces."""

    lines = [f"# {title}", ""]
    if not stages:
        return "\n".join([*lines, "No workflow stages were provided."]) + "\n"

    for stage in stages:
        lines.extend([
            f"## {stage.stage_id}",
            "",
            f"- Status: `{_value(stage.status)}`",
            f"- Reliability: `{_value(stage.reliability)}`",
            f"- Conclusion: {_stage_conclusion(stage)}",
            "",
            "### Descriptors",
        ])
        if stage.descriptors:
            for descriptor in stage.descriptors:
                lines.append(
                    f"- `{descriptor.name}`"
                    f"{f' ({descriptor.unit})' if descriptor.unit else ''}: "
                    f"{_compact_value(descriptor.value)}"
                )
        else:
            lines.append("- None")

        lines.extend(["", "### Evidence"])
        if stage.evidence:
            for evidence in stage.evidence:
                lines.append(
                    "- "
                    f"path=`{evidence.artifact_path}`; "
                    f"parser=`{evidence.parser_name}`; "
                    f"quantity=`{evidence.parsed_quantity}`; "
                    f"summary={evidence.summary or _compact_value(evidence.raw_value)}"
                )
        else:
            lines.append("- None")

        lines.extend([
            "",
            "### Blockers",
            *_bullet_list(stage.blockers),
            "",
            "### Warnings",
            *_bullet_list(stage.warnings),
            "",
            "### Next Actions",
            *_bullet_list(stage.next_actions),
            "",
        ])

    return "\n".join(lines).rstrip() + "\n"


def build_evidence_pack_from_stages(stages: list[WorkflowStageResult]) -> dict:
    """Build a JSON-safe evidence pack from workflow stage results."""

    pack = {
        "stages": [],
        "unsupported_or_forbidden_conclusions": [],
    }
    for stage in stages:
        stage_dict = {
            "stage_id": stage.stage_id,
            "status": _value(stage.status),
            "reliability": _value(stage.reliability),
            "descriptors": [descriptor.to_dict() for descriptor in stage.descriptors],
            "evidence": [evidence.to_dict() for evidence in stage.evidence],
            "warnings": list(stage.warnings),
            "blockers": list(stage.blockers),
            "next_actions": list(stage.next_actions),
            "metadata": dict(stage.metadata),
        }
        pack["stages"].append(stage_dict)
        if stage.status in {
            ResultStatus.BLOCKED,
            ResultStatus.INSUFFICIENT_EVIDENCE,
            ResultStatus.ERROR,
        }:
            pack["unsupported_or_forbidden_conclusions"].append(
                {
                    "stage_id": stage.stage_id,
                    "status": _value(stage.status),
                    "reason": "; ".join(stage.blockers)
                    if stage.blockers
                    else "stage is not supported by sufficient evidence",
                }
            )
    return pack


def _bullet_list(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]


def _value(value: object) -> str:
    if isinstance(value, Enum):
        return value.value
    return str(value)


def _stage_conclusion(stage: WorkflowStageResult) -> str:
    status = stage.status
    if status == ResultStatus.PASS:
        return "stage passes with traceable evidence."
    if status == ResultStatus.WARNING:
        return "stage has warnings; conclusions remain provisional."
    if status == ResultStatus.BLOCKED:
        return "stage is blocked; do not promote this to a final scientific claim."
    if status == ResultStatus.INSUFFICIENT_EVIDENCE:
        return "stage has insufficient evidence; do not make a scientific claim."
    if status == ResultStatus.CANDIDATE_ONLY:
        return "stage is candidate-only; use for screening, not final claims."
    return "stage is not ready for a scientific conclusion."


def _compact_value(value: object) -> str:
    if value is None:
        return "None"
    text = str(value)
    if len(text) <= 160:
        return text
    return text[:157] + "..."
