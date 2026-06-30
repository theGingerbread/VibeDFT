"""HfCl2 workflow recipes — reusable plan generators.

Each recipe captures the workflow stages, parameter defaults, and
acceptance criteria for a specific HfCl2 calculation path.

Usage::

    recipe = HfCl2KFatbandRecipe()
    plan = recipe.build_plan(case_dir="cases/K-HfCl2/K-screening/K_1")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════════
# Base recipe types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class RecipeStage:
    """One stage in a recipe plan."""
    id: str
    program: str
    input_pattern: str
    output_pattern: str
    cores: int = 1
    walltime: str = "01:00:00"
    depends_on: list[str] = field(default_factory=list)


@dataclass
class RecipePlan:
    """A complete recipe plan for a specific HfCl2 calculation path."""
    recipe_id: str
    description: str
    stages: list[RecipeStage] = field(default_factory=list)
    expected_inputs: list[str] = field(default_factory=list)
    validation_rules: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Predefined recipes
# ═══════════════════════════════════════════════════════════════════════════════


def hfcl2_k_fatband_v1() -> RecipePlan:
    """P2: K-HfCl2 k-resolved fatband projection."""
    return RecipePlan(
        recipe_id="qe.hfcl2_k_fatband.v1",
        description="K-HfCl2 k-resolved fatband: project Hf-d, K-s/p, Cl-p along Γ-M-K-Γ",
        stages=[
            RecipeStage("07_bands", "projwfc.x", "projwfc_fatband.in", "projwfc_fatband.out",
                        cores=1, walltime="00:30:00"),
        ],
        expected_inputs=[
            "07_bands/inputs/projwfc_fatband.in",
        ],
        validation_rules=[
            "hfcl2.p2.fatband.location",
            "hfcl2.p2.fatband.kresolveddos",
            "hfcl2.p2.fatband.prefix_outdir",
        ],
        acceptance_criteria=[
            "projwfc_fatband.in in 07_bands/inputs/ (not 08_dos/inputs/)",
            "kresolveddos=.true.",
            "prefix matches K bands prefix (hfcl2_k_1)",
            "outdir points to bands save context",
        ],
    )


def hfcl2_k_smearing_sensitivity_v1() -> RecipePlan:
    """P3: K-HfCl2 smearing sensitivity analysis."""
    return RecipePlan(
        recipe_id="qe.hfcl2_k_smearing_sensitivity.v1",
        description="K-HfCl2 DOS smearing sensitivity: reference vs 0.002 vs 0.005 Ry",
        stages=[
            RecipeStage("08_dos", "pw.x", "nscf_degauss_002.in", "nscf_degauss_002.out",
                        cores=28, walltime="01:00:00"),
            RecipeStage("08_dos", "pw.x", "nscf_degauss_005.in", "nscf_degauss_005.out",
                        cores=28, walltime="01:00:00"),
        ],
        expected_inputs=[
            "08_dos/inputs/nscf.in",
            "08_dos/inputs/nscf_degauss_002.in",
            "08_dos/inputs/nscf_degauss_005.in",
        ],
        validation_rules=[
            "hfcl2.p3.smearing.variants_exist",
            "hfcl2.p3.smearing.degauss_values",
            "hfcl2.p3.smearing.distinct_variants",
            "hfcl2.p3.smearing.param_consistency",
        ],
        acceptance_criteria=[
            "degauss_002.in parses to 0.002 Ry",
            "degauss_005.in parses to 0.005 Ry",
            "degauss ≠ 0.0 Ry in either variant",
            "Both files have different content hash",
            "Only degauss differs; prefix/pseudos/ecut/kmesh/nbnd match",
        ],
    )


def hfcl2_pristine_rrkjus_reference_v1() -> RecipePlan:
    """B1: Pristine HfCl2 canonical rrkjus reference."""
    return RecipePlan(
        recipe_id="qe.hfcl2_pristine_rrkjus_reference.v1",
        description="Pristine HfCl2 rrkjus SCF/vc-relax — canonical 2D reference",
        stages=[
            RecipeStage("rrkjus", "pw.x", "rx.in", "rx.out",
                        cores=28, walltime="04:00:00"),
        ],
        expected_inputs=[
            "rrkjus/inputs/rx.in",
        ],
        validation_rules=[
            "hfcl2.b1.pristine.elements",
            "hfcl2.b1.pristine.pseudo_family",
            "hfcl2.b1.pristine.ecut",
            "hfcl2.b1.pristine.cell",
        ],
        acceptance_criteria=[
            "Only Hf and Cl present (no Li/Na/K)",
            "All pseudopotentials are rrkjus family",
            "ecutwfc=90, ecutrho=720",
            "c ≥ 30 Å vacuum",
            "assume_isolated='2D'",
            "cell_dofree='2Dxy'",
        ],
    )
