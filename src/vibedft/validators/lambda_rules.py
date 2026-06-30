"""Validation rules for lambda.x input files."""

from __future__ import annotations

from vibedft.models.inspection import (
    QEProgram,
    SanityIssue,
    Severity,
    TaskRecord,
    TaskType,
)
from vibedft.validators.base import ValidationContext, register_validator


@register_validator(QEProgram.LAMBDA)
def validate_lambda_mustar_range(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: μ* should be in a physically reasonable range."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    inp = qe.namelists.get("input")
    mustar = None
    if inp:
        mustar = inp.params.get("mustar", None)

    if mustar is None:
        issues.append(SanityIssue(
            id="lambda.mustar_missing", severity=Severity.WARNING,
            message="μ* (mustar) not specified — QE default is 0.1. "
                    "Reported Tc depends on this choice.",
            source_file=task.source_file,
        ))
    elif isinstance(mustar, (int, float)):
        if mustar < 0:
            issues.append(SanityIssue(
                id="lambda.mustar_negative", severity=Severity.ERROR,
                message=f"μ* = {mustar} is negative — physically impossible",
                source_file=task.source_file,
            ))
        elif mustar > 0.3:
            issues.append(SanityIssue(
                id="lambda.mustar_high", severity=Severity.WARNING,
                message=f"μ* = {mustar} is unusually high (typical: 0.08–0.15)",
                source_file=task.source_file,
            ))
    return issues


@register_validator(QEProgram.LAMBDA)
def validate_lambda_requires_epc(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: lambda.x requires preceding EPC ph.x calculation."""
    issues: list[SanityIssue] = []

    # Check that at least one PH_EPC task exists in the case
    epc_tasks = ctx.tasks_of_type(TaskType.PH_EPC)
    if not epc_tasks:
        issues.append(SanityIssue(
            id="lambda.no_epc_predecessor", severity=Severity.ERROR,
            message="lambda.x requires a preceding ph.x EPC calculation "
                    "(electron_phonon='dvscf' or similar). "
                    "No PH_EPC task found in this case.",
            source_file=task.source_file,
            detail="Run ph.x with electron_phonon='dvscf' on a dense k-mesh first.",
        ))
    else:
        # Check that output files from EPC exist
        out_dir = ctx.case_dir / "output"
        if out_dir.is_dir():
            elph_files = sorted(out_dir.rglob("elph.inp_lambda.*"))
            if not elph_files:
                # Check deeper
                elph_files = sorted(ctx.case_dir.rglob("elph.inp_lambda.*"))
            if not elph_files:
                issues.append(SanityIssue(
                    id="lambda.no_elph_input", severity=Severity.WARNING,
                    message="No elph.inp_lambda.* files found — lambda.x needs these "
                            "EPC matrix elements from ph.x. Ensure EPC calculation completed.",
                    source_file=task.source_file,
                ))

    return issues


@register_validator(QEProgram.LAMBDA)
def validate_lambda_output_completeness(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: lambda.x output files should be present and non-empty."""
    issues: list[SanityIssue] = []
    out_dir = ctx.case_dir / "output"
    if not out_dir.is_dir():
        return issues

    # Check for lambdax.out
    lambdax_files = sorted(out_dir.rglob("lambdax.out"))
    if not lambdax_files:
        lambdax_files = sorted(ctx.case_dir.rglob("lambdax.out"))

    if not lambdax_files:
        issues.append(SanityIssue(
            id="lambda.no_output", severity=Severity.WARNING,
            message="No lambdax.out found — lambda.x may not have run or output "
                    "was not pulled from the cluster",
            source_file=task.source_file,
        ))
    else:
        for lf in lambdax_files:
            text = lf.read_text(encoding="utf-8", errors="replace")
            if "lambda" not in text.lower():
                issues.append(SanityIssue(
                    id="lambda.output_empty", severity=Severity.ERROR,
                    message=f"{lf.name} does not contain λ data — lambda.x may have failed",
                    source_file=str(lf),
                ))

    # Check for alpha2F.dat and lambda.dat (key output files)
    for req_file in ["alpha2F.dat", "lambda.dat"]:
        found = list(out_dir.rglob(req_file)) or list(ctx.case_dir.rglob(req_file))
        if not found:
            issues.append(SanityIssue(
                id=f"lambda.missing_{req_file.replace('.', '_')}",
                severity=Severity.WARNING,
                message=f"{req_file} not found — lambda.x may not have completed normally",
                source_file=task.source_file,
            ))

    return issues


@register_validator(QEProgram.LAMBDA)
def validate_lambda_tc_reporting(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: Tc should only be reported from two-grid overlap, not single-grid max."""
    issues: list[SanityIssue] = []
    out_dir = ctx.case_dir / "output"
    if not out_dir.is_dir():
        return issues

    # Count how many distinct PH grid directories have lambdax outputs
    lambdax_dirs = set()
    for lf in out_dir.rglob("lambdax.out"):
        rel = lf.relative_to(out_dir)
        parent = str(rel.parent) if str(rel.parent) != "." else "root"
        lambdax_dirs.add(parent)

    # Also check deeper in case_dir
    for lf in ctx.case_dir.rglob("lambdax.out"):
        lambdax_dirs.add(str(lf.parent.name))

    if len(lambdax_dirs) < 2:
        issues.append(SanityIssue(
            id="lambda.single_grid_tc", severity=Severity.WARNING,
            message=f"Only {len(lambdax_dirs)} PH grid(s) with lambda.x output found. "
                    "Tc convergence requires at least two k-mesh densities (e.g., "
                    "k=24×24×1 and k=64×64×1). Single-grid Tc is not reliable.",
            source_file=task.source_file,
            detail="Run lambda.x on both a coarser and a denser k-grid, then use "
                   "Tc overlap analysis to determine convergence.",
        ))

    return issues
