"""Workflow matching: given classified tasks, identify QE workflow and missing steps.

The matcher works at the task-type level (SCF, RELAX, PH_EPC, etc.) — not
at the individual-file level — because PH/EPC workflows often have multiple
files for the same task type (e.g. phx0, phx1, phx2, phx3 are all PH_EPC).

Key constraint: PH_STABILITY and PH_EPC are distinct.  Seeing ph.x output
does NOT imply EPC capability.  Seeing lambda.x does NOT imply the preceding
EPC calculation was valid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vibedft.models.inspection import TaskType


# ═══════════════════════════════════════════════════════════════════════════════
# Data models
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class WorkflowStep:
    """One step in a QE workflow."""
    task_type: TaskType
    label: str
    description: str = ""


@dataclass
class KnownWorkflow:
    """A known QE workflow definition."""
    workflow_id: str          # e.g. "qe.scf_dos.v2"
    label: str                # Human-readable
    steps: list[WorkflowStep] = field(default_factory=list)
    notes: str = ""


@dataclass
class WorkflowMatch:
    """Result of matching a set of tasks against a known workflow."""
    workflow: KnownWorkflow
    present_steps: list[TaskType] = field(default_factory=list)
    missing_steps: list[WorkflowStep] = field(default_factory=list)
    completeness: float = 0.0   # 0.0 – 1.0

    @property
    def is_complete(self) -> bool:
        return len(self.missing_steps) == 0

    @property
    def next_step(self) -> WorkflowStep | None:
        """The first missing step, if any."""
        return self.missing_steps[0] if self.missing_steps else None


# ═══════════════════════════════════════════════════════════════════════════════
# Known workflow definitions
# ═══════════════════════════════════════════════════════════════════════════════

KNOWN_WORKFLOWS: list[KnownWorkflow] = [
    KnownWorkflow(
        workflow_id="qe.scf.v1",
        label="SCF (self-consistent field)",
        steps=[
            WorkflowStep(TaskType.SCF, "SCF", "Self-consistent field calculation"),
        ],
        notes="Basic SCF; charge density for downstream stages.",
    ),
    KnownWorkflow(
        workflow_id="qe.rx.v1",
        label="Structure Relaxation",
        steps=[
            WorkflowStep(TaskType.SCF, "Initial SCF", "Reference SCF before relaxation"),
            WorkflowStep(TaskType.RELAX, "Relax / VC-Relax", "Ionic or variable-cell relaxation"),
        ],
        notes="Relaxation may use vdw-DF3-opt1, assume_isolated='2D', cell_dofree='2Dxy' for 2D intercalation.",
    ),
    KnownWorkflow(
        workflow_id="qe.bands.v1",
        label="Band Structure",
        steps=[
            WorkflowStep(TaskType.SCF, "SCF", "SCF for charge density"),
            WorkflowStep(TaskType.BANDS, "Bands NSCF", "NSCF on k-path (Γ-M-K-Γ)"),
        ],
        notes="Requires pre-computed SCF charge density.  Use qe.bands_nscf.v1 → qe.bands_post.v1 granular chain for production.",
    ),
    KnownWorkflow(
        workflow_id="qe.scf_dos.v2",
        label="Electronic Structure (SCF + DOS + PDOS)",
        steps=[
            WorkflowStep(TaskType.SCF, "SCF", "Self-consistent field"),
            WorkflowStep(TaskType.NSCF, "NSCF", "Non-SCF on uniform k-mesh"),
            # DOS and PROJWFC are separate programs (dos.x / projwfc.x) but
            # the task classifier currently detects them as data files, not
            # via task_type.  We track NSCF as the gate.
        ],
        notes="Production electronic structure: qe.scf.v1 → qe.nscf_uniform.v1 → qe.dos.v1 → qe.projwfc.v1.",
    ),
    KnownWorkflow(
        workflow_id="qe.ph_stability.v1",
        label="Phonon Stability",
        steps=[
            WorkflowStep(TaskType.SCF, "SCF", "Coarse k-mesh SCF for ph.x"),
            WorkflowStep(TaskType.PH_STABILITY, "PH (stability)", "ph.x phonon dispersion — NO EPC"),
            WorkflowStep(TaskType.Q2R, "q2r", "Fourier transform dyn → fc"),
            WorkflowStep(TaskType.MATDYN_DISP, "matdyn (dispersion)", "Phonon dispersion along q-path"),
        ],
        notes="PH_STABILITY: ldisp=.true. WITHOUT electron_phonon. "
               "This workflow does NOT produce λ or Tc. "
               "For EPC, use qe.ph_epc.v1.",
    ),
    KnownWorkflow(
        workflow_id="qe.ph_epc.v1",
        label="PH / EPC / Tc (full chain)",
        steps=[
            WorkflowStep(TaskType.SCF, "SCF (dense k)", "Dense k-mesh SCF (pwxall / 64×64)"),
            WorkflowStep(TaskType.SCF, "SCF (coarse k)", "Coarse k-mesh SCF (pwx / 16×16)"),
            WorkflowStep(TaskType.PH_EPC, "PH (EPC)", "ph.x with electron_phonon='dvscf'"),
            WorkflowStep(TaskType.Q2R, "q2r", "Fourier transform dyn → fc"),
            WorkflowStep(TaskType.MATDYN_DISP, "matdyn (dispersion)", "Phonon dispersion"),
            WorkflowStep(TaskType.LAMBDA_TC, "lambda (Tc)", "Eliashberg λ, α²F, Tc (McMillan-Allen-Dynes)"),
            WorkflowStep(TaskType.MATDYN_DOS, "matdyn (DOS)", "Phonon DOS"),
        ],
        notes="CRITICAL ORDERING: pwxall BEFORE pwx.  q2r must NOT have la2F.  "
               "Tc convergence requires at least two k-grids (e.g. 24×24 and 64×64).",
    ),
    KnownWorkflow(
        workflow_id="qe.fs.v1",
        label="Fermi Surface",
        steps=[
            WorkflowStep(TaskType.SCF, "SCF/NSCF", "SCF or NSCF on dense k-mesh"),
        ],
        notes="Requires fs.x post-processing (.bxsf output).",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Matching logic
# ═══════════════════════════════════════════════════════════════════════════════


def match_workflows(present_task_types: list[TaskType]) -> list[WorkflowMatch]:
    """Match a set of present task types against all known workflows.

    Returns matches sorted by completeness (best match first).
    """
    present_set = set(present_task_types)
    matches: list[WorkflowMatch] = []

    for wf in KNOWN_WORKFLOWS:
        wf_types = [s.task_type for s in wf.steps]
        # Count unique required types
        unique_required = set(wf_types)

        # Which required types are present?
        present = [t for t in unique_required if t in present_set]
        missing_steps = [s for s in wf.steps if s.task_type not in present_set]

        # Completeness: fraction of unique required types present
        completeness = len(present) / len(unique_required) if unique_required else 0.0

        matches.append(WorkflowMatch(
            workflow=wf,
            present_steps=list(present),
            missing_steps=missing_steps,
            completeness=completeness,
        ))

    # Sort: best match first
    matches.sort(key=lambda m: (-m.completeness, len(m.workflow.steps)))
    return matches


def identify_workflow(present_task_types: list[TaskType]) -> WorkflowMatch | None:
    """Return the single best-matching workflow, or None if nothing matches."""
    matches = match_workflows(present_task_types)
    if not matches:
        return None
    best = matches[0]
    if best.completeness > 0:
        return best
    return None


def missing_steps_summary(match: WorkflowMatch | None) -> str:
    """Human-readable summary of missing steps."""
    if match is None:
        return "No workflow identified."
    if match.is_complete:
        return f"Workflow '{match.workflow.label}' appears complete."
    missing_labels = [s.label for s in match.missing_steps]
    return (
        f"Workflow '{match.workflow.label}' is {match.completeness:.0%} complete. "
        f"Missing: {', '.join(missing_labels)}."
    )


def next_step_recommendation(match: WorkflowMatch | None) -> str:
    """Recommend the next calculation step."""
    if match is None:
        return "Cannot determine next step — no workflow matched."
    if match.is_complete:
        return "Workflow appears complete. Consider running post-processing or archiving."
    ns = match.next_step
    if ns:
        return f"Next step: {ns.label} — {ns.description}"
    return "No clear next step."
