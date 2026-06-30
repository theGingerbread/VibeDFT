"""Material-level analyzer: 2D metrics, symmetry, structural assessment."""

from __future__ import annotations

from pathlib import Path

from vibedft.analyzers.physics_models import (
    EvidenceLink,
    InsightLevel,
    PhysicsInsight,
)
from vibedft.core.structure import (
    parse_structure_from_qe_input,
    parse_structure_from_poscar,
    compute_2d_metrics,
    compute_symmetry,
)


def analyze_material(case_dir: Path | str) -> tuple[list[PhysicsInsight], float]:
    """Produce material-level physics insights and a score (0–10)."""
    d = Path(case_dir)
    insights: list[PhysicsInsight] = []
    score = 7.0  # default — ok

    # Find structure
    struct = None
    src = ""
    for pattern in ["**/scf.in", "**/relax.in", "**/*.in"]:
        for f in d.glob(pattern):
            if "scf.in" in f.name or "relax.in" in f.name:
                struct = parse_structure_from_qe_input(f)
                src = str(f)
                break
        if struct and struct.atoms:
            break

    if not (struct and struct.atoms):
        # Try POSCAR
        for f in d.rglob("POSCAR"):
            struct = parse_structure_from_poscar(f)
            src = str(f)
            if struct and struct.atoms:
                break

    if not (struct and struct.atoms):
        insights.append(PhysicsInsight(
            id="mat.no_structure", category="material",
            level=InsightLevel.NEUTRAL,
            message="No structure data found — cannot assess 2D metrics.",
        ))
        return insights, 5.0

    # ── 2D metrics ──
    metrics = compute_2d_metrics(struct)

    insights.append(PhysicsInsight(
        id="mat.formula", category="material",
        level=InsightLevel.NEUTRAL,
        message=f"Formula: {struct.formula or '?'} — {struct.n_atoms} atoms, "
                f"{', '.join(struct.elements)}.",
        evidence=[EvidenceLink(source_file=src, parser="compute_2d_metrics")],
    ))

    # Vacuum
    vac = metrics.vacuum_thickness_ang
    if vac > 15:
        insights.append(PhysicsInsight(
            id="mat.vacuum_good", category="material",
            level=InsightLevel.POSITIVE,
            message=f"Vacuum: {vac:.1f} Å — sufficient for 2D slab isolation.",
        ))
        score += 1.0
    elif vac > 10:
        insights.append(PhysicsInsight(
            id="mat.vacuum_ok", category="material",
            level=InsightLevel.NEUTRAL,
            message=f"Vacuum: {vac:.1f} Å — adequate but consider ≥15 Å for high precision.",
        ))
    elif vac > 3:
        insights.append(PhysicsInsight(
            id="mat.vacuum_low", category="material",
            level=InsightLevel.WARNING,
            message=f"Vacuum: {vac:.1f} Å — may have spurious interlayer interaction.",
            detail="Increase c-axis to ≥15 Å vacuum for reliable 2D properties.",
            evidence=[EvidenceLink(key="vacuum_thickness_ang", value=vac)],
        ))
        score -= 2.0

    # Buckling
    if metrics.buckling_ang > 0.1:
        insights.append(PhysicsInsight(
            id="mat.buckling", category="material",
            level=InsightLevel.NEUTRAL,
            message=f"Buckling height: {metrics.buckling_ang:.3f} Å — non-planar structure.",
            detail="Buckling can affect electronic properties and symmetry. "
                   "Common in transition metal dichalcogenides.",
        ))

    # ── Symmetry ──
    sym = compute_symmetry(struct)
    if sym.get("space_group_symbol"):
        sg = sym["space_group_symbol"]
        sg_num = sym.get("space_group_number", "?")
        n_ops = sym.get("n_operations", "?")
        insights.append(PhysicsInsight(
            id="mat.symmetry", category="material",
            level=InsightLevel.NEUTRAL,
            message=f"Space group: {sg} (#{sg_num}), {n_ops} symmetry operations.",
            evidence=[EvidenceLink(source_file=src, parser="spglib")],
        ))

        # Common 2D space groups
        if sg_num in (187, 191, 193, 194):  # hexagonal groups for TMDs
            insights.append(PhysicsInsight(
                id="mat.hexagonal", category="material",
                level=InsightLevel.POSITIVE,
                message=f"Hexagonal space group #{sg_num} — typical for 2D TMD materials.",
            ))

    # ── Layer count ──
    if metrics.n_layers > 1:
        insights.append(PhysicsInsight(
            id="mat.multilayer", category="material",
            level=InsightLevel.NEUTRAL,
            message=f"{metrics.n_layers} atomic layers detected — {'few-layer' if metrics.n_layers <= 3 else 'multilayer'} system.",
        ))

    return insights, max(0.0, min(10.0, score))
