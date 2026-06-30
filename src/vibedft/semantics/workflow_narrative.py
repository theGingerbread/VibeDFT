"""Workflow narrative — deterministic natural-language summary of a case study."""

from __future__ import annotations

from vibedft.semantics.material_identifier import MaterialIdentity
from vibedft.semantics.batch_intent import BatchIntent
from vibedft.semantics.ph_chunking import PhChunkingPlan
from vibedft.semantics.parameter_intelligence import ParameterIntelligenceReport


def generate_narrative(
    material: MaterialIdentity | None,
    batch: BatchIntent | None,
    ph_chunking: PhChunkingPlan | None,
    param_intel: ParameterIntelligenceReport | None,
) -> str:
    """Generate a deterministic natural-language narrative of the case study."""
    parts: list[str] = []

    # ── Material ──
    if material and material.formula_from_positions:
        formula = material.formula_from_positions
        elems = ", ".join(material.elements)
        parts.append(
            f"This case targets {formula} ({elems}), "
            f"a {'2D' if material.likely_2d else '3D'} material. "
        )
        if material.formula_conflict:
            parts.append(
                f"⚠ Formula conflict: label suggests '{material.label_formula}', "
                f"but ATOMIC_POSITIONS count gives '{material.formula_from_positions}'. "
            )
        if material.likely_2d:
            parts.append(f"Vacuum layer: {material.c_axis_ang:.0f} Å. ")

    # ── Batch intent ──
    if batch:
        if batch.strain_scan:
            strains = ", ".join(batch.strain_values)
            parts.append(
                f"This is a strain-engineering study with {batch.strain_type} strain "
                f"at {strains}. "
            )
        if batch.dual_grid_epc:
            grids = ", ".join(batch.epc_grids)
            parts.append(
                f"Dual-grid EPC validation is performed using {grids} k-meshes "
                f"for convergence checking. "
            )
        if batch.is_template_library:
            parts.append(
                "This appears to be a template library — parameter values may be "
                "placeholders requiring substitution before execution. "
            )

    # ── PH chunking ──
    if ph_chunking and ph_chunking.is_chunked:
        parts.append(
            f"Phonon/EPC calculations are parallelized across {ph_chunking.chunk_count} "
            f"ph.x jobs using start_q/last_q chunking, covering q-points "
            f"1–{ph_chunking.total_q_points}. "
        )
        if ph_chunking.coverage == "complete":
            parts.append("All irreducible q-points are covered — no gaps. ")
        elif ph_chunking.coverage == "gaps":
            parts.append(
                f"⚠ WARNING: q-points {ph_chunking.missing_q} are not covered "
                f"by any ph.x job. "
            )

    # ── Parameter intelligence ──
    if param_intel:
        strict_params = [i for i in param_intel.insights if i.context == "ultra_strict"]
        if strict_params:
            names = list({i.parameter for i in strict_params})
            parts.append(
                f"Notably strict convergence thresholds: {', '.join(names)}. "
                "This indicates a high-precision calculation suitable for publication. "
            )
        if param_intel.n_placeholders > 0:
            parts.append(
                f"{param_intel.n_placeholders} template placeholder(s) detected — "
                "replace with physical values before execution. "
            )

    if not parts:
        return "No semantic analysis available for this case."

    return "".join(parts)
