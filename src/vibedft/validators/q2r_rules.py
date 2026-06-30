"""Validation rules for q2r.x input files."""

from __future__ import annotations

from vibedft.models.inspection import (
    QEProgram,
    SanityIssue,
    Severity,
    TaskRecord,
)
from vibedft.validators.base import ValidationContext, register_validator


@register_validator(QEProgram.Q2R)
def validate_q2r_required_params(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: q2r.x must have fildyn, flfrc, and zasr."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    inp = qe.namelists.get("input")
    if inp is None:
        return issues

    fildyn = inp.params.get("fildyn", "")
    flfrc = inp.params.get("flfrc", "")
    zasr = inp.params.get("zasr", "")

    if not fildyn:
        issues.append(SanityIssue(
            id="q2r.fildyn_missing", severity=Severity.ERROR,
            message="fildyn is required — q2r.x needs dynamical matrix files to read",
            source_file=task.source_file,
        ))
    if not flfrc:
        issues.append(SanityIssue(
            id="q2r.flfrc_missing", severity=Severity.ERROR,
            message="flfrc is required — q2r.x needs an output force-constant file",
            source_file=task.source_file,
        ))
    if not zasr:
        issues.append(SanityIssue(
            id="q2r.zasr_missing", severity=Severity.WARNING,
            message="zasr not set — acoustic sum rule may not be applied; phonon "
                    "frequencies at Γ may be non-zero",
            source_file=task.source_file,
        ))

    return issues


@register_validator(QEProgram.Q2R)
def validate_q2r_no_la2f(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: la2F=.true. in q2r.x will crash — it belongs in matdyn.x only."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    inp = qe.namelists.get("input")
    if inp is None:
        return issues

    la2f = inp.params.get("la2f", None)
    if la2f is True:
        issues.append(SanityIssue(
            id="q2r.la2f_forbidden", severity=Severity.ERROR,
            message="la2F=.true. is FORBIDDEN in q2r.x — it WILL crash. "
                    "la2F belongs in matdyn.x for EPC-related calculations only.",
            source_file=task.source_file,
            detail="Remove la2F from q2r input. q2r.x only does Fourier transform dyn→fc.",
        ))

    return issues


@register_validator(QEProgram.Q2R)
def validate_q2r_dyn_files_present(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: dyn files should exist in the output directory."""
    issues: list[SanityIssue] = []
    out_dir = ctx.case_dir / "output"
    if not out_dir.is_dir():
        return issues

    dyn_files = sorted(out_dir.rglob("*.dyn*"))
    if not dyn_files:
        issues.append(SanityIssue(
            id="q2r.no_dyn_files", severity=Severity.WARNING,
            message="No dyn* files found in output/ — q2r.x requires PH output. "
                    "Has ph.x completed successfully?",
            source_file=task.source_file,
        ))
    else:
        # Check for zero-byte dyn files
        zero_byte = [d.name for d in dyn_files if d.stat().st_size == 0]
        if zero_byte:
            issues.append(SanityIssue(
                id="q2r.zero_byte_dyn", severity=Severity.ERROR,
                message=f"{len(zero_byte)} zero-byte dyn files: {', '.join(zero_byte[:5])} — "
                        "ph.x likely crashed",
                source_file=task.source_file,
            ))

    return issues
