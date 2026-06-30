"""Cross-stage QE observability model and workflow readiness graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vibedft.calculator.qe.common import QEOutputEvent
from vibedft.calculator.qe.phonon.parse import PhononOutput
from vibedft.calculator.qe.scf.parse import WorkflowReadiness as ScfWorkflowReadiness
from vibedft.calculator.qe.scf.parse import ScfOutput


_FATAL_ISSUE_CATEGORIES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}


@dataclass(frozen=True)
class StageReadiness:
    """Computed state for a QE workflow stage."""

    stage: str
    status: str
    reason: str
    ready_for_followup: bool
    next_actions: list[str] = field(default_factory=list)
    confidence: float = 1.0
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_schema(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "status": self.status,
            "reason": self.reason,
            "ready_for_followup": self.ready_for_followup,
            "next_actions": list(self.next_actions),
            "confidence": self.confidence,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class QeWorkflowReadinessGraph:
    """Decision-oriented workflow readiness summary across QE stages."""

    scf_stage: StageReadiness
    phonon_stage: StageReadiness
    can_run: dict[str, bool]
    recommended_actions: list[str]
    blockers: list[str]

    def to_schema(self) -> dict[str, object]:
        return {
            "stages": {
                "scf": self.scf_stage.to_schema(),
                "phonon": self.phonon_stage.to_schema(),
            },
            "can_run": dict(self.can_run),
            "recommended_actions": list(self.recommended_actions),
            "blockers": list(self.blockers),
        }


def build_workflow_readiness_graph(
    *,
    scf_output: ScfOutput | None,
    phonon_output: PhononOutput | None = None,
) -> QeWorkflowReadinessGraph:
    """Build a compact, machine-consumable workflow gate graph."""

    scf_stage = _assess_scf_stage(scf_output)
    phonon_stage = _assess_phonon_stage(phonon_output)

    if scf_stage.ready_for_followup:
        can_run = {
            "dos": True,
            "bands": True,
            "phonon": True,
            "dielectric": True,
            "epc": phonon_stage.ready_for_followup,
            "tc": phonon_stage.ready_for_followup,
        }
    else:
        can_run = {key: False for key in ("dos", "bands", "phonon", "dielectric", "epc", "tc")}

    blockers: list[str] = []
    recommended: list[str] = []

    if not scf_stage.ready_for_followup:
        blockers.extend(scf_stage.next_actions or [scf_stage.reason])
        if scf_stage.status == "missing":
            recommended.append("run scf")
        elif scf_stage.status == "failed":
            recommended.append("fix SCF fatal issue and rerun")
        elif scf_stage.status == "blocked":
            recommended.append("re-run SCF with stricter convergence strategy")
        elif scf_stage.status == "running":
            recommended.append("continue SCF monitoring")

    elif phonon_stage.status == "missing" and scf_stage.ready_for_followup:
        recommended.append("run phonon on converged SCF prefix")
    elif phonon_stage.status == "running":
        recommended.append("continue phonon monitoring")
    elif phonon_stage.status == "blocked":
        blockers.append(phonon_stage.reason)
        recommended.extend(
            phonon_stage.next_actions
            or ["fix phonon issues then rerun phonon with corrected inputs"]
        )

    return QeWorkflowReadinessGraph(
        scf_stage=scf_stage,
        phonon_stage=phonon_stage,
        can_run=can_run,
        recommended_actions=recommended,
        blockers=blockers,
    )


def _assess_scf_stage(scf_output: ScfOutput | None) -> StageReadiness:
    if scf_output is None:
        return StageReadiness(
            stage="scf",
            status="missing",
            reason="No SCF output provided.",
            ready_for_followup=False,
            next_actions=["run scf"],
            confidence=0.0,
            evidence={"output_present": False},
        )

    if _has_fatal_issues(scf_output.issues):
        reason = "Fatal SCF issue detected; restart required."
        return StageReadiness(
            stage="scf",
            status="failed",
            reason=reason,
            ready_for_followup=False,
            next_actions=["rerun scf", "fix runtime/config issue"],
            confidence=0.95,
            evidence={
                "output_present": True,
                "job_done": scf_output.job_done,
                "converged": scf_output.converged,
                "stable_readiness": getattr(scf_output.workflow_readiness, "reason", None),
                "issues": len(scf_output.issues),
            },
        )

    if scf_output.converged and scf_output.job_done:
        readiness = scf_output.workflow_readiness or ScfWorkflowReadiness(
            dos=False,
            bands=False,
            phonon=False,
            dielectric=False,
            reason="SCF parser did not produce readiness metadata.",
        )
        ready_for_followup = bool(readiness.dos and readiness.bands and readiness.phonon)
        if ready_for_followup:
            reason = "SCF completed and stable enough for follow-up work."
            status = "complete"
            next_actions: list[str] = []
        else:
            reason = readiness.reason
            status = "blocked"
            next_actions = ["inspect input and rerun SCF"]
        return StageReadiness(
            stage="scf",
            status=status,
            reason=reason,
            ready_for_followup=ready_for_followup,
            next_actions=next_actions,
            confidence=0.9 if ready_for_followup else 0.7,
            evidence={
                "output_present": True,
                "job_done": scf_output.job_done,
                "converged": scf_output.converged,
                "iterations": len(scf_output.iterations),
                "workflow_readiness": readiness.to_schema(),
            },
        )

    if scf_output.iterations:
        return StageReadiness(
            stage="scf",
            status="running",
            reason="SCF running but not yet converged.",
            ready_for_followup=False,
            next_actions=["continue SCF monitoring"],
            confidence=0.6,
            evidence={
                "output_present": True,
                "job_done": scf_output.job_done,
                "converged": scf_output.converged,
                "iterations": len(scf_output.iterations),
            },
        )

    return StageReadiness(
        stage="scf",
        status="no_data",
        reason="SCF output has no recognized iteration markers.",
        ready_for_followup=False,
        next_actions=["rerun SCF and ensure stdout is captured"],
        confidence=0.1,
        evidence={
            "output_present": True,
            "job_done": scf_output.job_done,
            "converged": scf_output.converged,
            "issues": len(scf_output.issues),
        },
    )


def _assess_phonon_stage(phonon_output: PhononOutput | None) -> StageReadiness:
    if phonon_output is None:
        return StageReadiness(
            stage="phonon",
            status="missing",
            reason="No phonon output provided.",
            ready_for_followup=False,
            next_actions=["run phonon"],
            confidence=0.0,
            evidence={"output_present": False},
        )

    severe = _has_fatal_issues(phonon_output.issues)
    if severe:
        return StageReadiness(
            stage="phonon",
            status="failed",
            reason="Fatal phonon issue detected; rerun with clean inputs/runtime.",
            ready_for_followup=False,
            next_actions=["fix phonon runtime or input issue", "rerun phonon"],
            confidence=0.95,
            evidence={"output_present": True, "job_done": phonon_output.job_done, "q_points": len(phonon_output.q_points), "frequencies": len(phonon_output.frequencies)},
        )

    if phonon_output.job_done and phonon_output.convergence_achieved_lines and not phonon_output.blocked_lines:
        return StageReadiness(
            stage="phonon",
            status="complete",
            reason="Phonon output reached completion markers with frequencies.",
            ready_for_followup=True,
            next_actions=[],
            confidence=0.9,
            evidence={
                "output_present": True,
                "job_done": phonon_output.job_done,
                "q_points": len(phonon_output.q_points),
                "representations": len(phonon_output.representations),
                "frequencies": len(phonon_output.frequencies),
            },
        )

    if phonon_output.job_done and not phonon_output.q_points and not phonon_output.frequencies:
        return StageReadiness(
            stage="phonon",
            status="blocked",
            reason="JOB DONE seen without phonon progress markers.",
            ready_for_followup=False,
            next_actions=["validate phonon invocation and output routing"],
            confidence=0.8,
            evidence={
                "output_present": True,
                "job_done": phonon_output.job_done,
                "q_points": len(phonon_output.q_points),
                "frequencies": len(phonon_output.frequencies),
            },
        )

    if phonon_output.q_points or phonon_output.representations or phonon_output.frequencies:
        return StageReadiness(
            stage="phonon",
            status="running",
            reason="Phonon activity detected; convergence/job done not yet reached.",
            ready_for_followup=False,
            next_actions=["continue phonon monitoring"],
            confidence=0.7,
            evidence={
                "output_present": True,
                "job_done": phonon_output.job_done,
                "q_points": len(phonon_output.q_points),
                "frequencies": len(phonon_output.frequencies),
            },
        )

    if phonon_output.job_done:
        return StageReadiness(
            stage="phonon",
            status="blocked",
            reason="Phonon job done but no q-point output was parsed.",
            ready_for_followup=False,
            next_actions=["inspect phonon input file and invocation"],
            confidence=0.8,
            evidence={"output_present": True, "job_done": phonon_output.job_done},
        )

    return StageReadiness(
        stage="phonon",
        status="no_data",
        reason="Phonon output contains no progress markers.",
        ready_for_followup=False,
        next_actions=["continue phonon monitoring"],
        confidence=0.3,
        evidence={"output_present": True, "job_done": phonon_output.job_done},
    )


def _has_fatal_issues(issues: list[QEOutputEvent]) -> bool:
    return any(issue.category in _FATAL_ISSUE_CATEGORIES for issue in issues)


__all__ = [
    "StageReadiness",
    "QeWorkflowReadinessGraph",
    "build_workflow_readiness_graph",
]
