"""Contract-driven QE cross-stage workflow readiness graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from vibedft._shared.contracts import CleanedResult
from vibedft.calculator.qe.common import QEOutputEvent
from vibedft.calculator.qe.phonon.parse import PhononOutput
from vibedft.calculator.qe.scf.parse import ScfOutput
from vibedft.calculator.qe.scf.parse import WorkflowReadiness as ScfWorkflowReadiness


_FATAL_ISSUE_CATEGORIES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}

StageStatus = Literal[
    "missing",
    "no_data",
    "running",
    "complete",
    "warn",
    "blocked",
    "failed",
]


@dataclass(frozen=True)
class StageReadiness:
    """Computed state for a QE workflow stage."""

    stage: str
    status: StageStatus
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
    scf: CleanedResult | None = None,
    phonon: CleanedResult | None = None,
    nscf: CleanedResult | None = None,
    bands: CleanedResult | None = None,
    dos: CleanedResult | None = None,
) -> QeWorkflowReadinessGraph:
    """Build a compact, contract-based workflow gate graph from cleaned results."""

    del nscf, bands, dos  # Keep explicit placeholders for downstream expansion.

    scf_stage = _assess_clean_stage("scf", scf)
    phonon_stage = _assess_clean_stage("phonon", phonon)

    can_run = {
        "dos": _is_task_allowed(scf, "dos"),
        "bands": _is_task_allowed(scf, "bands"),
        "phonon": _is_task_allowed(scf, "phonon"),
        "dielectric": _is_task_allowed(scf, "dielectric"),
        "epc": _is_task_allowed_for_epc_tc(phonon, task="epc"),
        "tc": _is_task_allowed_for_epc_tc(phonon, task="tc"),
    }

    blockers: list[str] = []
    recommended: list[str] = []

    _collect_graph_actions(
        stage=scf_stage,
        result=scf,
        stage_name="SCF",
        blockers=blockers,
        recommended=recommended,
    )
    _collect_graph_actions(
        stage=phonon_stage,
        result=phonon,
        stage_name="phonon",
        blockers=blockers,
        recommended=recommended,
    )

    return QeWorkflowReadinessGraph(
        scf_stage=scf_stage,
        phonon_stage=phonon_stage,
        can_run=can_run,
        recommended_actions=recommended,
        blockers=blockers,
    )


def build_workflow_readiness_graph_from_parsed(
    *,
    scf_output: ScfOutput | None,
    phonon_output: PhononOutput | None = None,
) -> QeWorkflowReadinessGraph:
    """Backward-compatible legacy bridge from parsed outputs.

    This remains for migration and test coverage only.
    """

    scf_stage = _assess_scf_stage(scf_output)
    phonon_stage = _assess_phonon_stage(phonon_output)

    can_run = {
        "dos": False,
        "bands": False,
        "phonon": False,
        "dielectric": False,
        "epc": False,
        "tc": False,
    }

    if scf_stage.ready_for_followup:
        if scf_output is not None and scf_output.workflow_readiness is not None:
            readiness = scf_output.workflow_readiness
            can_run.update(
                {
                    "dos": bool(readiness.dos),
                    "bands": bool(readiness.bands),
                    "phonon": bool(readiness.phonon),
                    "dielectric": bool(readiness.dielectric),
                }
            )

    if phonon_stage.status == "complete":
        can_run["epc"] = True
        can_run["tc"] = True

    blockers: list[str] = []
    recommended: list[str] = []

    if not scf_stage.ready_for_followup:
        blockers.extend(scf_stage.next_actions or [scf_stage.reason])
        if scf_stage.status == "missing":
            recommended.append("run scf")
        elif scf_stage.status == "failed":
            recommended.append("fix SCF fatal issue and rerun")
        elif scf_stage.status in {"blocked", "warn"}:
            recommended.append("re-run SCF with tighter policy")
        elif scf_stage.status == "running":
            recommended.append("continue SCF monitoring")

    elif phonon_stage.status == "missing":
        recommended.append("run phonon on converged SCF prefix")
    elif phonon_stage.status == "running":
        recommended.append("continue phonon monitoring")
    elif phonon_stage.status in {"blocked", "warn"}:
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


def _assess_clean_stage(
    stage: str,
    cleaned: CleanedResult | None,
) -> StageReadiness:
    if cleaned is None:
        return StageReadiness(
            stage=stage,
            status="missing",
            reason=f"No {stage.upper()} cleaned result provided.",
            ready_for_followup=False,
            next_actions=[f"run {stage}"],
            confidence=0.0,
            evidence={"cleaned_present": False},
        )

    status = cleaned.status
    if status == "pass":
        stage_status: StageStatus = "complete"
        ready = True
    elif status == "warn":
        stage_status = "warn"
        ready = _has_allowed_downstream(cleaned)
    elif status == "block":
        stage_status = "blocked"
        ready = False
    elif status == "failed":
        stage_status = "failed"
        ready = False
    elif status == "running":
        stage_status = "running"
        ready = False
    else:
        stage_status = "no_data"
        ready = False

    reason = _clean_stage_reason(stage, cleaned)
    if cleaned.review is not None:
        reasons = [str(reason)] if reason else []
        reasons.extend(cleaned.review.reasons)
        reason = " | ".join([item for item in reasons if item])

    return StageReadiness(
        stage=stage,
        status=stage_status,
        reason=reason,
        ready_for_followup=ready,
        next_actions=list(cleaned.next_actions),
        confidence=0.9 if stage_status == "complete" else 0.8 if ready else 0.3,
        evidence={
            "cleaned_status": status,
            "cleaned_task": cleaned.task,
            "ready_downstream_count": len([
                entry
                for entry in cleaned.readiness.downstream.values()
                if entry.allowed
            ]),
            "cleaned_payload": dict(cleaned.payload),
        },
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
        ready_for_followup = bool(readiness.dos or readiness.bands)
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
            evidence={
                "output_present": True,
                "job_done": phonon_output.job_done,
                "q_points": len(phonon_output.q_points),
                "frequencies": len(phonon_output.frequencies),
            },
        )

    has_negative_frequency = any(freq.frequency_cm1 < 0 for freq in phonon_output.frequencies)

    if phonon_output.job_done and phonon_output.convergence_achieved_lines and not phonon_output.blocked_lines:
        if has_negative_frequency:
            return StageReadiness(
                stage="phonon",
                status="warn",
                reason="Phonon output completed with negative frequencies; downstream EPC/tc should be gated.",
                ready_for_followup=False,
                next_actions=["inspect phonon branch stability and supercell/mesh settings"],
                confidence=0.85,
                evidence={
                    "output_present": True,
                    "job_done": phonon_output.job_done,
                    "q_points": len(phonon_output.q_points),
                    "representations": len(phonon_output.representations),
                    "frequencies": len(phonon_output.frequencies),
                    "negative_frequencies_present": True,
                    "min_frequency_cm1": min(
                        [frequency.frequency_cm1 for frequency in phonon_output.frequencies],
                        default=None,
                    ),
                },
            )

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


def _collect_graph_actions(
    *,
    stage: StageReadiness,
    result: CleanedResult | None,
    stage_name: str,
    blockers: list[str],
    recommended: list[str],
) -> None:
    if stage.status == "missing":
        blockers.extend(stage.next_actions)
        return

    if stage.status in {"no_data", "running"}:
        recommended.extend(stage.next_actions)
        return

    if stage.status in {"warn", "blocked"}:
        blockers.append(f"{stage_name} stage warning: {stage.reason}")
        recommended.extend(stage.next_actions)
        return

    if stage.status == "failed":
        blockers.append(f"{stage_name} failed: {stage.reason}")
        if result is None:
            recommended.append(f"rerun {stage_name.lower()} after issue fix")
        return


def _is_task_allowed(cleaned: CleanedResult | None, task: str) -> bool:
    if cleaned is None:
        return False

    if cleaned.status == "block" or cleaned.status == "failed":
        return False

    entry = cleaned.readiness.downstream.get(task)
    if entry is not None:
        return bool(entry.allowed)
    return False


def _is_task_allowed_for_epc_tc(
    phonon: CleanedResult | None,
    *,
    task: str,
) -> bool:
    if phonon is None:
        return False

    if phonon.status != "pass":
        return False

    if _has_negative_frequencies_hint(phonon):
        return False

    if task not in {"epc", "tc"}:
        return False

    # Prefer explicit downstream policy when clean contract provides it.
    explicit = phonon.readiness.downstream.get(task)
    if explicit is not None:
        return bool(explicit.allowed)

    return False


def _has_negative_frequencies_hint(cleaned: CleanedResult) -> bool:
    metadata_keys = (
        "negative_frequencies",
        "negative_frequency_count",
        "negative_frequency_count_cm1",
    )
    min_value = cleaned.diagnostics.metrics.get("numerical_risk", {}).get("min_frequency_cm1")
    if min_value is not None:
        try:
            return float(min_value) < 0
        except (TypeError, ValueError):
            pass

    for key in metadata_keys:
        value = cleaned.diagnostics.metrics.get("numerical_risk", {}).get(key)
        if isinstance(value, (int, float)):
            if int(value) > 0:
                return True

    return False


def _has_allowed_downstream(cleaned: CleanedResult) -> bool:
    return any(entry.allowed for entry in cleaned.readiness.downstream.values())


def _clean_stage_reason(stage: str, cleaned: CleanedResult) -> str:
    review_status = cleaned.review.status if cleaned.review is not None else "N/A"
    if stage == "scf":
        if cleaned.status == "pass":
            return "SCF clean result passed all required checks."
        if cleaned.status == "warn":
            return "SCF clean result warning; downstream gates may be restricted."
        if cleaned.status == "block":
            return "SCF clean result blocked."
        if cleaned.status == "failed":
            return "SCF clean result failed."
        if cleaned.status == "running":
            return "SCF clean result still running."
        return "SCF clean result has no data."

    if stage == "phonon":
        if cleaned.status == "pass":
            return "Phonon clean result indicates completion readiness for follow-up."
        if cleaned.status == "warn":
            return "Phonon clean result warning; downstream EPC/tc remains gated."
        if cleaned.status == "block":
            return "Phonon clean result blocked."
        if cleaned.status == "failed":
            return "Phonon clean result failed."
        if cleaned.status == "running":
            return "Phonon clean result still running."
        return "Phonon clean result has no data."

    return f"{stage.upper()} clean result status: {cleaned.status}; review status: {review_status}"


def _has_fatal_issues(issues: list[QEOutputEvent]) -> bool:
    return any(issue.category in _FATAL_ISSUE_CATEGORIES for issue in issues)


__all__ = [
    "StageReadiness",
    "QeWorkflowReadinessGraph",
    "build_workflow_readiness_graph",
    "build_workflow_readiness_graph_from_parsed",
]
