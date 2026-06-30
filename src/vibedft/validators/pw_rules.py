"""Validation rules for pw.x input files."""

from __future__ import annotations

from vibedft.models.inspection import (
    QEProgram,
    SanityIssue,
    Severity,
    TaskRecord,
    TaskType,
)
from vibedft.validators.base import ValidationContext, register_validator


@register_validator(QEProgram.PW)
def validate_pw_metallic_smearing(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: metallic systems should use smearing."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    occupations = str(qe.get_param("system", "occupations", "")).lower()
    smearing = qe.get_param("system", "smearing", "")
    degauss = qe.get_param("system", "degauss", 0.0)
    tot_charge = qe.get_param("system", "tot_charge", 0.0)

    # If using 'fixed' occupations on a doped/metallic system → warning
    if occupations == "fixed" and tot_charge != 0:
        issues.append(SanityIssue(
            id="pw.fixed_occupations_with_doping", severity=Severity.WARNING,
            message=f"occupations='fixed' with tot_charge={tot_charge} — "
                    "doped systems typically need smearing",
            source_file=task.source_file,
        ))

    # If using smearing but degauss is zero or missing
    if occupations == "smearing" and (degauss is None or float(degauss) <= 0):
        issues.append(SanityIssue(
            id="pw.smearing_no_degauss", severity=Severity.WARNING,
            message="occupations='smearing' but degauss not set — "
                    "broadening may be zero",
            source_file=task.source_file,
        ))

    return issues


@register_validator(QEProgram.PW)
def validate_pw_cutoff_ratio(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: ecutrho should be 4–12× ecutwfc."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    ecutwfc = qe.get_param("system", "ecutwfc", None)
    ecutrho = qe.get_param("system", "ecutrho", None)

    if ecutwfc is None or ecutrho is None:
        return issues

    try:
        wfc = float(ecutwfc)
        rho = float(ecutrho)
        ratio = rho / wfc if wfc > 0 else 0
        if ratio < 3.5:
            issues.append(SanityIssue(
                id="pw.ecutrho_ratio_low", severity=Severity.WARNING,
                message=f"ecutrho/ecutwfc ratio = {ratio:.1f} — "
                        "US/PAW pseudos typically need 8–12×, NC need 4×",
                source_file=task.source_file,
            ))
        elif ratio > 12.5:
            issues.append(SanityIssue(
                id="pw.ecutrho_ratio_high", severity=Severity.INFO,
                message=f"ecutrho/ecutwfc ratio = {ratio:.1f} — "
                        "higher than typical, may waste computation",
                source_file=task.source_file,
            ))
    except (ValueError, TypeError):
        pass

    # ecutwfc below typical minimums
    try:
        if wfc is not None and float(wfc) < 30:
            issues.append(SanityIssue(
                id="pw.ecutwfc_low", severity=Severity.WARNING,
                message=f"ecutwfc = {wfc} Ry — very low; convergence unlikely",
                source_file=task.source_file,
            ))
    except (ValueError, TypeError):
        pass

    return issues


@register_validator(QEProgram.PW)
def validate_pw_vacuum_2d(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: 2D slab vacuum thickness from CELL_PARAMETERS."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    assume_isolated = str(qe.get_param("system", "assume_isolated", "")).strip()
    cell_card = qe.cards.get("CELL_PARAMETERS")

    if cell_card and cell_card.rows and len(cell_card.rows) >= 3:
        try:
            # Row 3 = c vector
            c_row = cell_card.rows[2]
            cz = float(c_row[2]) if len(c_row) >= 3 else 0.0
        except (ValueError, IndexError):
            return issues

        # If c-axis > 15 Å, likely a 2D slab
        if cz > 15 and not assume_isolated:
            issues.append(SanityIssue(
                id="pw.2d_missing_isolated", severity=Severity.WARNING,
                message=f"c-axis = {cz:.1f} Å suggests a 2D slab, "
                        "but assume_isolated='2D' is not set",
                source_file=task.source_file,
                detail="Set assume_isolated='2D' for Coulomb cutoff along z.",
            ))

    return issues


@register_validator(QEProgram.PW)
def validate_pw_kpoints_density(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: k-point density for 2D / metallic systems."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    kp_card = qe.cards.get("K_POINTS")
    if kp_card and kp_card.rows and kp_card.rows[0]:
        row = kp_card.rows[0]
        if len(row) >= 3:
            try:
                nk1, nk2, nk3 = int(row[0]), int(row[1]), int(row[2])
            except (ValueError, IndexError):
                return issues

            # For 2D: nk3 should be 1
            assume_isolated = str(qe.get_param("system", "assume_isolated", ""))
            cell_dofree = str(qe.get_param("system", "cell_dofree", ""))
            is_2d = assume_isolated == "2D" or cell_dofree == "2Dxy"

            if is_2d and nk3 != 1:
                issues.append(SanityIssue(
                    id="pw.2d_kpoints_nk3", severity=Severity.WARNING,
                    message=f"2D calculation but nk3={nk3} — should be 1",
                    source_file=task.source_file,
                ))

            # For metals: k-mesh should be at least 8×8×1
            occupations = str(qe.get_param("system", "occupations", "")).lower()
            tot_charge = qe.get_param("system", "tot_charge", 0.0)
            is_metal = occupations in ("smearing", "tetrahedra", "tetrahedra_opt") or float(tot_charge) != 0

            if is_metal and (nk1 < 8 or nk2 < 8):
                issues.append(SanityIssue(
                    id="pw.kpoints_sparse_metal", severity=Severity.WARNING,
                    message=f"Metallic system with {nk1}×{nk2}×{nk3} k-mesh — "
                            "may be insufficient for convergence",
                    source_file=task.source_file,
                ))

    return issues


@register_validator(QEProgram.PW)
def validate_pw_nspin_consistency(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: nspin/noncolin/SOC consistency."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    nspin = qe.get_param("system", "nspin", None)
    noncolin = qe.get_param("system", "noncolin", None)
    lspinorb = qe.get_param("system", "lspinorb", None)

    if nspin is not None:
        try:
            ns = int(nspin)
            if ns not in (1, 2, 4):
                issues.append(SanityIssue(
                    id="pw.nspin_invalid", severity=Severity.ERROR,
                    message=f"nspin={ns} is invalid — must be 1, 2, or 4",
                    source_file=task.source_file,
                ))
        except (ValueError, TypeError):
            pass

    # noncolin with nspin=2 doesn't make sense
    if noncolin is True:
        if isinstance(nspin, int) and nspin != 2:
            # Actually noncolin requires nspin not set or special handling
            pass

    if lspinorb is True and noncolin is not True:
        issues.append(SanityIssue(
            id="pw.lspinorb_without_noncolin", severity=Severity.WARNING,
            message="lspinorb=.true. typically requires noncolin=.true.",
            source_file=task.source_file,
        ))

    return issues


@register_validator(QEProgram.PW)
def validate_pw_relax_settings(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: relaxation-specific parameters."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    calc = str(qe.get_param("control", "calculation", "")).lower()
    if calc not in ("relax", "vc-relax"):
        return issues

    # Check for force/stress convergence thresholds
    forc_conv_thr = qe.get_param("control", "forc_conv_thr", None)
    etot_conv_thr = qe.get_param("control", "etot_conv_thr", None)

    if forc_conv_thr is not None:
        try:
            fct = float(forc_conv_thr)
            if fct > 1e-3:
                issues.append(SanityIssue(
                    id="pw.relax_forc_thr_loose", severity=Severity.WARNING,
                    message=f"forc_conv_thr={forc_conv_thr} Ry/Bohr is loose — "
                            "forces may not be well-converged",
                    source_file=task.source_file,
                ))
        except (ValueError, TypeError):
            pass

    # vc-relax with 2Dxy should have cell_dofree set
    if calc == "vc-relax":
        cell_dofree = str(qe.get_param("system", "cell_dofree", ""))
        assume_isolated = str(qe.get_param("system", "assume_isolated", ""))
        if assume_isolated == "2D" and cell_dofree != "2Dxy":
            issues.append(SanityIssue(
                id="pw.vc_relax_2d_dofree", severity=Severity.WARNING,
                message="vc-relax with assume_isolated='2D' — consider "
                        "cell_dofree='2Dxy' to fix z-axis",
                source_file=task.source_file,
            ))

    return issues


@register_validator(QEProgram.PW)
def validate_pw_pseudo_matches_species(ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]:
    """Check: ATOMIC_SPECIES count matches ntyp."""
    issues: list[SanityIssue] = []
    qe = ctx.get_input(task)
    if qe is None:
        return issues

    ntyp = qe.get_param("system", "ntyp", None)
    species_card = qe.cards.get("ATOMIC_SPECIES")

    if ntyp is not None and species_card:
        try:
            declared = int(ntyp)
            actual = len(species_card.rows)
            if declared != actual:
                issues.append(SanityIssue(
                    id="pw.ntyp_mismatch", severity=Severity.ERROR,
                    message=f"ntyp={declared} but ATOMIC_SPECIES has {actual} entries",
                    source_file=task.source_file,
                ))
        except (ValueError, TypeError):
            pass

    # Check for placeholder pseudos
    if species_card:
        for row in species_card.rows:
            if len(row) >= 3 and "<" in row[2]:
                issues.append(SanityIssue(
                    id="pw.pseudo_placeholder", severity=Severity.ERROR,
                    message=f"Pseudopotential placeholder found: {row[2]} — replace with real path",
                    source_file=task.source_file,
                ))

    return issues
