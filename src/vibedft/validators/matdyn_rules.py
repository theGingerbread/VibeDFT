"""Validation rules for matdyn.x input files."""

from __future__ import annotations

from vibedft.models.inspection import (
    QEProgram,
    SanityIssue,
    Severity,
    TaskRecord,
    TaskType,
)
from vibedft.validators.base import ValidationContext, register_validator


@register_validator(QEProgram.MATDYN)
def validate_matdyn_required_params(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: matdyn.x must have flfrc."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    inp = qe.namelists.get("input")
    if inp is None:
        return issues

    flfrc = inp.params.get("flfrc", "")
    if not flfrc:
        issues.append(SanityIssue(
            id="matdyn.flfrc_missing", severity=Severity.ERROR,
            message="flfrc is required — matdyn.x needs the force-constant file from q2r.x",
            source_file=task.source_file,
        ))

    return issues


@register_validator(QEProgram.MATDYN)
def validate_matdyn_mode_clarity(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: distinguish dispersion vs DOS mode and validate parameters."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    inp = qe.namelists.get("input")
    if inp is None:
        return issues

    dos = inp.params.get("dos", False)
    flfrq = inp.params.get("flfrq", "")
    q_in_band = inp.params.get("q_in_band_form", None)
    q_in_cryst = inp.params.get("q_in_cryst_coord", None)

    # DOS mode
    if dos is True or str(dos).lower() == ".true.":
        fldos = inp.params.get("fldos", "")
        nk1 = inp.params.get("nk1", None)
        nk2 = inp.params.get("nk2", None)
        nk3 = inp.params.get("nk3", None)

        if not fldos:
            issues.append(SanityIssue(
                id="matdyn.dos_no_fldos", severity=Severity.WARNING,
                message="dos=.true. but fldos not set — output file name defaults to 'matdyn.dos'",
                source_file=task.source_file,
            ))
        if nk1 is None:
            issues.append(SanityIssue(
                id="matdyn.dos_no_nk", severity=Severity.WARNING,
                message="dos=.true. but nk1/nk2/nk3 not set — using default q-mesh for DOS",
                source_file=task.source_file,
            ))

    # Dispersion mode (ordinary matdyn.x for freq.gp)
    else:
        if not flfrq:
            issues.append(SanityIssue(
                id="matdyn.disp_no_flfrq", severity=Severity.WARNING,
                message="flfrq not set — phonon dispersion frequencies will not be saved. "
                        "Set flfrq='freq.gp' for standard output.",
                source_file=task.source_file,
            ))

    # q_in_band_form vs q_in_cryst_coord: at least one should be true
    if q_in_band is False and q_in_cryst is False:
        issues.append(SanityIssue(
            id="matdyn.no_q_format", severity=Severity.WARNING,
            message="Neither q_in_band_form nor q_in_cryst_coord is true — "
                    "matdyn.x may not know how to interpret q-points",
            source_file=task.source_file,
        ))

    return issues


@register_validator(QEProgram.MATDYN)
def validate_matdyn_asr_zasz(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: acoustic sum rule consistency."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    inp = qe.namelists.get("input")
    if inp is None:
        return issues

    asr = inp.params.get("asr", "")
    zasr = inp.params.get("zasr", "")

    if not asr and not zasr:
        issues.append(SanityIssue(
            id="matdyn.no_asr", severity=Severity.WARNING,
            message="Neither asr nor zasr is set — acoustic sum rule not applied. "
                    "Γ-point acoustic modes may be non-zero.",
            source_file=task.source_file,
        ))

    return issues


@register_validator(QEProgram.MATDYN)
def validate_matdyn_fc_file_present(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: .fc file should exist from q2r.x before running matdyn.x."""
    issues: list[SanityIssue] = []
    out_dir = ctx.case_dir / "output"
    if not out_dir.is_dir():
        return issues

    fc_files = sorted(out_dir.rglob("*.fc"))
    if not fc_files:
        # Check in parent or sibling directories
        fc_files = sorted(ctx.case_dir.rglob("*.fc"))

    if not fc_files:
        issues.append(SanityIssue(
            id="matdyn.no_fc_file", severity=Severity.WARNING,
            message="No .fc file found — matdyn.x requires the force-constant file "
                    "from q2r.x. Has q2r.x completed?",
            source_file=task.source_file,
        ))

    return issues
