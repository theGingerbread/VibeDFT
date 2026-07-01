"""Declarative phonon split task metadata scaffolding."""

from __future__ import annotations

from dataclasses import dataclass

PHONON_LEGACY_TASK = "phonon"

PHONON_SPLIT_TASKS = (
    "phonon_gamma",
    "phonon_qgrid",
    "phonon_dos",
    "dielectric",
    "born",
)

PHONON_MANDATORY_BLOCKED_DOWNSTREAMS = (
    "scf",
    "relax",
    "vc_relax",
    "nscf",
    "bands",
    "dos",
    "pdos",
    "pp",
    "bader",
    "workfunction",
    "epc",
    "tc",
)


@dataclass(frozen=True)
class PhononStageSpec:
    """Static scaffold metadata for a phonon split task."""

    task: str
    qualified_task: str
    legacy_group: str
    qe_commands: tuple[str, ...]
    required_inputs: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    allowed_downstream: tuple[str, ...]
    blocked_downstream: tuple[str, ...]
    analysis_domains: tuple[str, ...]
    implementation_status: str
    notes: tuple[str, ...]


def _tuple(v: tuple[str, ...] | list[str] | set[str]) -> tuple[str, ...]:
    return tuple(sorted(v, key=str))


PHONON_STAGE_SPECS = (
    PhononStageSpec(
        task="phonon_gamma",
        qualified_task="qe.phonon_gamma",
        legacy_group=PHONON_LEGACY_TASK,
        qe_commands=("ph.x",),
        required_inputs=("scf",),
        expected_outputs=(
            "dynG",
            "dyn0",
            "dynamical_matrix",
        ),
        allowed_downstream=("analysis.phonon_gamma",),
        blocked_downstream=_tuple(PHONON_MANDATORY_BLOCKED_DOWNSTREAMS),
        analysis_domains=("analysis.phonon_gamma",),
        implementation_status="scaffold",
        notes=("Gamma-point DFPT phonon split stage.",),
    ),
    PhononStageSpec(
        task="phonon_qgrid",
        qualified_task="qe.phonon_qgrid",
        legacy_group=PHONON_LEGACY_TASK,
        qe_commands=("ph.x",),
        required_inputs=("scf",),
        expected_outputs=("dyn", "qpoint_grid"),
        allowed_downstream=("analysis.phonon_qgrid",),
        blocked_downstream=_tuple(PHONON_MANDATORY_BLOCKED_DOWNSTREAMS),
        analysis_domains=("analysis.phonon_qgrid",),
        implementation_status="scaffold",
        notes=("q-grid DFPT split stage.",),
    ),
    PhononStageSpec(
        task="phonon_dos",
        qualified_task="qe.phonon_dos",
        legacy_group=PHONON_LEGACY_TASK,
        qe_commands=("q2r.x", "matdyn.x"),
        required_inputs=("phonon_qgrid",),
        expected_outputs=("phonon_dos.dat", "matdyn.out"),
        allowed_downstream=("analysis.phonon_dos",),
        blocked_downstream=_tuple(PHONON_MANDATORY_BLOCKED_DOWNSTREAMS),
        analysis_domains=("analysis.phonon_dos",),
        implementation_status="scaffold",
        notes=("phonon DOS and dispersion split stage.",),
    ),
    PhononStageSpec(
        task="dielectric",
        qualified_task="qe.dielectric",
        legacy_group=PHONON_LEGACY_TASK,
        qe_commands=("ph.x",),
        required_inputs=("scf",),
        expected_outputs=("dielectric_tensor", "born_charges"),
        allowed_downstream=("analysis.dielectric",),
        blocked_downstream=_tuple(PHONON_MANDATORY_BLOCKED_DOWNSTREAMS),
        analysis_domains=("analysis.dielectric",),
        implementation_status="scaffold",
        notes=("dielectric tensor split stage.",),
    ),
    PhononStageSpec(
        task="born",
        qualified_task="qe.born",
        legacy_group=PHONON_LEGACY_TASK,
        qe_commands=("ph.x",),
        required_inputs=("dielectric",),
        expected_outputs=("born.dat", "bec_matrix"),
        allowed_downstream=("analysis.born",),
        blocked_downstream=_tuple(PHONON_MANDATORY_BLOCKED_DOWNSTREAMS),
        analysis_domains=("analysis.born",),
        implementation_status="scaffold",
        notes=("Born effective charge split stage.",),
    ),
)


def list_phonon_stage_specs() -> tuple[PhononStageSpec, ...]:
    """Return all declarative phonon split stage specs in stable order."""

    return PHONON_STAGE_SPECS


def get_phonon_stage_spec(task: str) -> PhononStageSpec:
    """Return one stage spec by task name."""

    for spec in PHONON_STAGE_SPECS:
        if spec.task == task:
            return spec
    raise KeyError(f"Unknown phonon split task: {task}")


def phonon_split_task_names() -> tuple[str, ...]:
    """Return split task identifiers in stable order."""

    return tuple(spec.task for spec in PHONON_STAGE_SPECS)


def phonon_split_qualified_task_names() -> tuple[str, ...]:
    """Return qualified split task identifiers in stable order."""

    return tuple(spec.qualified_task for spec in PHONON_STAGE_SPECS)


def phonon_split_analysis_domains() -> tuple[str, ...]:
    """Return unique allowed analysis domains declared by split stages."""

    domains: list[str] = []
    seen: set[str] = set()
    for spec in PHONON_STAGE_SPECS:
        for domain in spec.analysis_domains:
            if domain not in seen:
                seen.add(domain)
                domains.append(domain)
    return tuple(domains)


def validate_phonon_stage_specs() -> list[str]:
    """Validate metadata-only scaffold consistency and return discovered issues."""

    errors: list[str] = []
    seen: set[str] = set()
    seen_qualified: set[str] = set()
    mandatory_blocked = set(PHONON_MANDATORY_BLOCKED_DOWNSTREAMS)

    for spec in PHONON_STAGE_SPECS:
        if spec.implementation_status != "scaffold":
            errors.append(f"{spec.task}: implementation_status must be scaffold")

        if spec.task in seen:
            errors.append(f"Duplicate phonon split task: {spec.task}")
        else:
            seen.add(spec.task)

        if spec.qualified_task in seen_qualified:
            errors.append(f"Duplicate qualified task: {spec.qualified_task}")
        else:
            seen_qualified.add(spec.qualified_task)

        if not spec.qualified_task.startswith("qe.") or spec.qualified_task != f"qe.{spec.task}":
            errors.append(f"{spec.task}: malformed qualified_task {spec.qualified_task}")

        if not spec.analysis_domains:
            errors.append(f"{spec.task}: missing analysis domains")

        for domain in spec.analysis_domains:
            if not domain.startswith("analysis."):
                errors.append(f"{spec.task}: non-analysis domain {domain}")

        if any(downstream in {"epc", "tc"} for downstream in spec.allowed_downstream):
            errors.append(f"{spec.task}: allowed_downstream must not include epc/tc")

        if mandatory_blocked - set(spec.blocked_downstream):
            errors.append(f"{spec.task}: missing mandatory blocked downstream tasks")

    if tuple(spec.task for spec in PHONON_STAGE_SPECS) != PHONON_SPLIT_TASKS:
        errors.append("PHONON_SPLIT_TASKS does not match PHONON_STAGE_SPECS order")

    return errors


__all__ = [
    "PHONON_LEGACY_TASK",
    "PHONON_MANDATORY_BLOCKED_DOWNSTREAMS",
    "PHONON_SPLIT_TASKS",
    "PHONON_STAGE_SPECS",
    "PhononStageSpec",
    "get_phonon_stage_spec",
    "list_phonon_stage_specs",
    "phonon_split_analysis_domains",
    "phonon_split_qualified_task_names",
    "phonon_split_task_names",
    "validate_phonon_stage_specs",
]
