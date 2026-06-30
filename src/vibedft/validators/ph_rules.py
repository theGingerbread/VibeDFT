"""Validation rules for ph.x input files."""

from __future__ import annotations

import os

from vibedft.models.inspection import (
    QEProgram,
    SanityIssue,
    Severity,
    TaskRecord,
    TaskType,
)
from vibedft.validators.base import ValidationContext, register_validator


def _norm_outdir(path: str) -> str:
    """Normalize an outdir string for comparison.

    QE inputs use a mix of ``./out/``, ``../out/``, ``out/``, ``./out``.
    These all refer to the same physical directory when resolved relative
    to the case root. Strip trailing slashes and collapse ``./`` / ``../``
    segments so a ph.x referencing ``../out_scf_120/`` matches a pw.x
    referencing ``./out_scf_120/`` (regression for a Type-III
    HfBr2_TiSe2 false positive).
    """
    if not path:
        return ""
    p = path.strip().rstrip("/")
    # normpath collapses ./ and ../ but treats the input as relative to CWD.
    # Since both ph.x and pw.x outdir are relative to the same case root,
    # applying the same normalization to both makes them comparable.
    try:
        return os.path.normpath(p)
    except (ValueError, OSError):
        return p


@register_validator(QEProgram.PH)
def validate_ph_prefix_outdir_match(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: ph.x prefix/outdir must match *some* pw.x in the case.

    Real cluster work directories often bundle several independent
    sub-calculations, each with its own pw→ph pair (different prefixes).
    The correct semantics is "at least one matching pw.x exists", not
    "every pw.x must match". Emitting one error per non-matching pw.x
    produced large numbers of false positives (e.g. 72 spurious errors
    in a 4-sub-calculation K-HfCl2 case).

    Outdir paths are normalized (``./``/``../``/trailing slash collapsed)
    before comparison, so ``../out_scf_120/`` matches ``./out_scf_120/``.
    """
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    ph_prefix = str(qe.get_param("inputph", "prefix", ""))
    ph_outdir = _norm_outdir(str(qe.get_param("inputph", "outdir", "")))

    scf_tasks = ctx.tasks_of_program(QEProgram.PW)
    has_prefix_match = False
    has_outdir_match = False
    for scf in scf_tasks:
        scf_input = ctx.get_input(scf)
        if scf_input is None:
            continue
        scf_prefix = str(scf_input.get_param("control", "prefix", ""))
        scf_outdir = _norm_outdir(str(scf_input.get_param("control", "outdir", "")))
        if scf_prefix and ph_prefix and scf_prefix == ph_prefix:
            has_prefix_match = True
        if scf_outdir and ph_outdir and scf_outdir == ph_outdir:
            has_outdir_match = True

    if ph_prefix and scf_tasks and not has_prefix_match:
        issues.append(SanityIssue(
            id="ph.prefix_mismatch", severity=Severity.ERROR,
            message=f"PH prefix='{ph_prefix}' matches no pw.x in the case — "
                    "ph.x will fail to find the save directory",
            source_file=task.source_file,
            detail="The ph.x prefix must match some pw.x prefix that generated "
                   "a save/ directory.",
        ))
    if ph_outdir and scf_tasks and not has_outdir_match:
        issues.append(SanityIssue(
            id="ph.outdir_mismatch", severity=Severity.ERROR,
            message=f"PH outdir='{ph_outdir}' matches no pw.x outdir in the case",
            source_file=task.source_file,
        ))

    return issues


@register_validator(QEProgram.PH)
def validate_ph_nq3_for_2d(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: 2D materials must have nq3=1 for phonon calculations."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    nq3 = qe.get_param("inputph", "nq3", None)
    if nq3 is not None:
        try:
            if int(nq3) != 1:
                issues.append(SanityIssue(
                    id="ph.2d_nq3_not_one", severity=Severity.ERROR,
                    message=f"nq3={nq3} — for 2D materials, nq3 must be 1",
                    source_file=task.source_file,
                    detail="Phonon dispersion along z has no physical meaning for 2D slabs. "
                           "Set nq3=1.",
                ))
        except (ValueError, TypeError):
            pass
    return issues


@register_validator(QEProgram.PH)
def validate_ph_epc_kpoints(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: EPC calculations need sufficiently dense k-mesh."""
    issues: list[SanityIssue] = []
    if task.task_type != TaskType.PH_EPC:
        return issues

    qe = ctx.get_input(task)
    if qe is None:
        return issues

    # EPC quality depends on the k-mesh from the SCF step, not ph.x itself.
    # But we can check ph.x's own q-grid and warn about sparse sampling.
    nq1 = qe.get_param("inputph", "nq1", 8)
    nq2 = qe.get_param("inputph", "nq2", 8)

    try:
        if int(nq1) < 6 or int(nq2) < 6:
            issues.append(SanityIssue(
                id="ph.epc_qgrid_sparse", severity=Severity.WARNING,
                message=f"EPC calculation with q-grid {nq1}×{nq2}×1 — "
                        "may be too sparse for converged λ",
                source_file=task.source_file,
                detail="Standard EPC convergence: q≥8×8×1, k≥16×16×1 for HfX2.",
            ))
    except (ValueError, TypeError):
        pass

    # Check el_ph_sigma and el_ph_nsigma are set
    sigma = qe.get_param("inputph", "el_ph_sigma", None)
    nsigma = qe.get_param("inputph", "el_ph_nsigma", None)
    if sigma is None and nsigma is None:
        issues.append(SanityIssue(
            id="ph.epc_sigma_missing", severity=Severity.WARNING,
            message="EPC enabled but el_ph_sigma/el_ph_nsigma not set — "
                    "using QE defaults, may affect convergence quality",
            source_file=task.source_file,
        ))

    return issues


@register_validator(QEProgram.PH)
def validate_ph_task_purpose_clarity(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: PH_STABILITY vs PH_EPC should be explicitly distinguishable."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    elph = str(qe.get_param("inputph", "electron_phonon", "")).strip()
    ldisp = qe.get_param("inputph", "ldisp", None)

    # If ldisp is true but electron_phonon is not set → pure stability, not EPC
    if ldisp is True and not elph:
        issues.append(SanityIssue(
            id="ph.stability_only", severity=Severity.INFO,
            message="ldisp=.true. without electron_phonon — this is a phonon stability "
                    "calculation, NOT an EPC calculation. Do not expect λ or Tc output.",
            source_file=task.source_file,
        ))

    # If electron_phonon is set but ldisp is false → single-q EPC (unusual)
    if elph and ldisp is False:
        issues.append(SanityIssue(
            id="ph.epc_single_q", severity=Severity.WARNING,
            message=f"electron_phonon='{elph}' but ldisp=.false. — "
                    "single-q EPC is unusual; typically ldisp=.true. for full dispersion",
            source_file=task.source_file,
        ))

    # tr2_ph should be strict enough for EPC
    tr2_ph = qe.get_param("inputph", "tr2_ph", None)
    if elph and tr2_ph is not None:
        try:
            if float(tr2_ph) > 1e-12:
                issues.append(SanityIssue(
                    id="ph.epc_tr2_ph_loose", severity=Severity.WARNING,
                    message=f"tr2_ph={tr2_ph} may be too loose for EPC — "
                            "consider 1e-14 or tighter",
                    source_file=task.source_file,
                ))
        except (ValueError, TypeError):
            pass

    return issues


@register_validator(QEProgram.PH)
def validate_ph_start_q_last_q(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: start_q/last_q settings for parallel PH runs."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    start_q = qe.get_param("inputph", "start_q", None)
    last_q = qe.get_param("inputph", "last_q", None)

    if start_q is not None and last_q is not None:
        try:
            sq = int(start_q)
            lq = int(last_q)
            if sq > lq:
                issues.append(SanityIssue(
                    id="ph.start_q_gt_last_q", severity=Severity.ERROR,
                    message=f"start_q={sq} > last_q={lq} — no q-points will be calculated",
                    source_file=task.source_file,
                ))
        except (ValueError, TypeError):
            pass

    return issues
