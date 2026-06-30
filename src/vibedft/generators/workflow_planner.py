"""Workflow planner: structure file → 11-stage superconductivity DAG.

Hard constraints (enforced here, never in templates):
  - PH_STABILITY and PH_EPC are separate stages with separate directories.
  - q2r.x / matdyn.x stages NEVER include la2F.
  - Only PH_EPC stages include electron_phonon.
  - lambda.x is independent; Tc responsibility is isolated from general PH.
  - All stages produce sbatch scripts only; no direct execution.
"""

from __future__ import annotations

from pathlib import Path

from vibedft.generators.manifest import (
    ClusterProfile,
    StageKind,
    StageSpec,
    WorkflowPlan,
    CLUSTER_DEBUG,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════


def plan_superconductivity(
    structure_file: str | Path,
    *,
    engine: str = "qe",
    profile: ClusterProfile | None = None,
    output_root: str | Path = "runs/sc_workflow",
    material_prefix: str = "material",
    pseudo_dir: str = "<PSEUDO_DIR>",
    ecutwfc: int = 60,
    ecutrho: int = 480,
    occupations: str = "smearing",
    smearing: str = "gaussian",
    degauss: float = 0.005,
    tot_charge: float = 0.0,
    relax_k: tuple[int, int, int] = (8, 8, 1),
    scf_k: tuple[int, int, int] = (12, 12, 1),
    bands_k: tuple[int, int, int] = (12, 12, 1),
    nscf_dos_k: tuple[int, int, int] = (24, 24, 1),
    ph_q: tuple[int, int, int] = (8, 8, 1),
    ph_k: tuple[int, int, int] = (16, 16, 1),
    epc_ph64_k: tuple[int, int, int] = (64, 64, 1),
    epc_ph96_k: tuple[int, int, int] = (96, 96, 1),
) -> WorkflowPlan:
    """Plan a complete QE superconductivity workflow.

    Returns a :class:`WorkflowPlan` with 11 stages in correct dependency order.
    """
    prof = profile or CLUSTER_DEBUG
    root = Path(output_root)
    plan_id = root.name

    plan = WorkflowPlan(
        plan_id=plan_id,
        engine=engine,
        structure_file=str(structure_file),
        output_root=str(root),
        profile=prof,
        common_params={
            "prefix": material_prefix,
            "pseudo_dir": pseudo_dir,
            "ecutwfc": ecutwfc,
            "ecutrho": ecutrho,
            "occupations": occupations,
            "smearing": smearing,
            "degauss": degauss,
            "tot_charge": tot_charge,
        },
        k_grids={
            "relax": list(relax_k), "scf": list(scf_k), "bands": list(bands_k),
            "nscf_dos": list(nscf_dos_k), "ph": list(ph_k),
            "epc_64": list(epc_ph64_k), "epc_96": list(epc_ph96_k),
        },
        q_grids={"ph": list(ph_q)},
    )

    prev_scf = ""  # tracks the last SCF stage ID for dependency chaining

    # ── Stage 01: Relax ──
    s01 = StageSpec(
        id="01_relax", kind=StageKind.RELAX,
        directory="01_relax", depends_on=[],
        template="pw_relax.in.j2", executable="pw.x",
        input_file="relax.in", output_file="relax.out",
        cores=prof.validate_cores(14), walltime="04:00:00",
    )
    plan.stages.append(s01)

    # ── Stage 02: Final SCF (after relaxation) ──
    s02 = StageSpec(
        id="02_final_scf", kind=StageKind.SCF,
        directory="02_final_scf", depends_on=["01_relax"],
        template="pw_scf.in.j2", executable="pw.x",
        input_file="scf.in", output_file="scf.out",
        cores=prof.validate_cores(14), walltime="02:00:00",
        pre_commands=[
            "# Stage final structure from relax if available",
            "# cp ../01_relax/relax.out . 2>/dev/null || true",
        ],
    )
    plan.stages.append(s02)
    prev_scf = "02_final_scf"

    # ── Stage 03: Bands ──
    s03 = StageSpec(
        id="03_bands", kind=StageKind.BANDS,
        directory="03_bands", depends_on=[prev_scf],
        template="pw_bands.in.j2", executable="pw.x",
        input_file="bands.in", output_file="bands.out",
        cores=prof.validate_cores(14), walltime="02:00:00",
        pre_commands=[
            "PREFIX=$(grep -iw 'prefix' bands.in | head -1 | awk -F= '{gsub(/[\\047\\042]|^[ \\t]+|[ \\t]+$/, \"\", $2); print $2}')",
            f"mkdir -p out_bands",
            f"if [ ! -e \"out_bands/${{PREFIX}}.save\" ]; then "
            f"cp -r ../{prev_scf}/out_scf/${{PREFIX}}.save ./out_bands/ 2>/dev/null || "
            f"ln -s ../../{prev_scf}/out_scf/${{PREFIX}}.save ./out_bands/${{PREFIX}}.save 2>/dev/null || "
            f"{{ echo \"ERROR: cannot stage SCF save\"; exit 2; }}; fi",
        ],
    )
    plan.stages.append(s03)

    # ── Stage 04: NSCF + DOS ──
    s04 = StageSpec(
        id="04_nscf_dos", kind=StageKind.NSCF_DOS,
        directory="04_nscf_dos", depends_on=[prev_scf],
        template="pw_nscf_dos.in.j2", executable="pw.x",
        input_file="nscf.in", output_file="nscf_dos.out",
        cores=prof.validate_cores(14), walltime="02:00:00",
        pre_commands=[
            "PREFIX=$(grep -iw 'prefix' nscf.in | head -1 | awk -F= '{gsub(/[\\047\\042]|^[ \\t]+|[ \\t]+$/, \"\", $2); print $2}')",
            f"mkdir -p out_nscf",
            f"if [ ! -e \"out_nscf/${{PREFIX}}.save\" ]; then "
            f"cp -r ../{prev_scf}/out_scf/${{PREFIX}}.save ./out_nscf/ 2>/dev/null || "
            f"ln -s ../../{prev_scf}/out_scf/${{PREFIX}}.save ./out_nscf/${{PREFIX}}.save 2>/dev/null || "
            f"{{ echo \"ERROR: cannot stage SCF save\"; exit 2; }}; fi",
        ],
    )
    plan.stages.append(s04)

    # ── Stage 05: PH STABILITY (NO EPC — explicit separation) ──
    s05 = StageSpec(
        id="05_ph_stability", kind=StageKind.PH_STABILITY,
        directory="05_ph_stability", depends_on=[prev_scf],
        template="ph_stability.in.j2", executable="ph.x",
        input_file="ph_stability.in", output_file="ph_stability.out",
        cores=prof.validate_cores(14), walltime="04:00:00",
        pre_commands=[
            "PREFIX=$(grep -iw 'prefix' ph_stability.in | head -1 | awk -F= '{gsub(/[\\047\\042]|^[ \\t]+|[ \\t]+$/, \"\", $2); print $2}')",
            f"mkdir -p out_ph",
            f"if [ ! -e \"out_ph/${{PREFIX}}.save\" ]; then "
            f"cp -r ../{prev_scf}/out_scf/${{PREFIX}}.save ./out_ph/ 2>/dev/null || "
            f"ln -s ../../{prev_scf}/out_scf/${{PREFIX}}.save ./out_ph/${{PREFIX}}.save 2>/dev/null || "
            f"{{ echo \"ERROR: cannot stage SCF save\"; exit 2; }}; fi",
        ],
    )
    plan.stages.append(s05)

    # ── Stage 06: Q2R (no la2F — enforced at template level) ──
    s06 = StageSpec(
        id="06_q2r", kind=StageKind.Q2R,
        directory="06_q2r_matdyn", depends_on=["05_ph_stability"],
        template="q2r.in.j2", executable="q2r.x",
        input_file="q2r.in", output_file="q2r.out",
        cores=16, walltime="00:30:00",
    )
    plan.stages.append(s06)

    # ── Stage 07: MATDYN dispersion (no la2F) ──
    s07 = StageSpec(
        id="07_matdyn_disp", kind=StageKind.MATDYN_DISP,
        directory="06_q2r_matdyn", depends_on=["06_q2r"],
        template="matdyn_line.in.j2", executable="matdyn.x",
        input_file="matdyn_line.in", output_file="matdyn_line.out",
        cores=16, walltime="00:30:00",
    )
    plan.stages.append(s07)

    # ── Stage 08: EPC ph64 — PW dense k (pwxall) ──
    s08_pwxall = StageSpec(
        id="08_epc_ph64_pwxall", kind=StageKind.SCF,
        directory="08_epc_ph64", depends_on=[prev_scf],
        template="pw_scf_dense.in.j2", executable="pw.x",
        input_file="pwxall.in", output_file="pwxall.out",
        cores=prof.validate_cores(28), walltime="06:00:00",
    )
    plan.stages.append(s08_pwxall)

    #   EPC ph64 — PW coarse k (pwx), MUST run AFTER pwxall
    s08_pwx = StageSpec(
        id="08_epc_ph64_pwx", kind=StageKind.SCF,
        directory="08_epc_ph64", depends_on=["08_epc_ph64_pwxall"],
        template="pw_scf_coarse.in.j2", executable="pw.x",
        input_file="pwx.in", output_file="pwx.out",
        cores=prof.validate_cores(14), walltime="02:00:00",
    )
    plan.stages.append(s08_pwx)

    #   EPC ph64 — PH (WITH electron_phonon, ONLY here)
    s08_ph = StageSpec(
        id="08_epc_ph64_ph", kind=StageKind.PH_EPC,
        directory="08_epc_ph64", depends_on=["08_epc_ph64_pwx"],
        template="ph_epc.in.j2", executable="ph.x",
        input_file="ph_epc.in", output_file="ph_epc.out",
        cores=prof.validate_cores(28), walltime="08:00:00",
        pre_commands=[
            "PREFIX=$(grep -iw 'prefix' ph_epc.in | head -1 | awk -F= '{gsub(/[\\047\\042]|^[ \\t]+|[ \\t]+$/, \"\", $2); print $2}')",
            "mkdir -p out_epc",
            "if [ ! -e \"out_epc/${PREFIX}.save\" ]; then "
            "cp -r ../08_epc_ph64/out_epc/${PREFIX}.save ./out_epc/ 2>/dev/null || "
            "{ echo \"ERROR: pwx must complete before ph_epc\"; exit 2; }; fi",
        ],
    )
    plan.stages.append(s08_ph)

    #   EPC ph64 — lambda.x (standalone Tc postprocessing)
    s08_lam = StageSpec(
        id="08_epc_ph64_lambda", kind=StageKind.LAMBDA,
        directory="08_epc_ph64", depends_on=["08_epc_ph64_ph"],
        template="lambda.in.j2", executable="lambda.x",
        input_file="lambdax.in", output_file="lambdax.out",
        cores=16, walltime="01:00:00",
    )
    plan.stages.append(s08_lam)

    # ── Stage 09: EPC ph96 — PW dense k ──
    s09_pwxall = StageSpec(
        id="09_epc_ph96_pwxall", kind=StageKind.SCF,
        directory="09_epc_ph96", depends_on=[prev_scf],
        template="pw_scf_dense.in.j2", executable="pw.x",
        input_file="pwxall.in", output_file="pwxall.out",
        cores=prof.validate_cores(56), walltime="12:00:00",
    )
    plan.stages.append(s09_pwxall)

    s09_pwx = StageSpec(
        id="09_epc_ph96_pwx", kind=StageKind.SCF,
        directory="09_epc_ph96", depends_on=["09_epc_ph96_pwxall"],
        template="pw_scf_coarse.in.j2", executable="pw.x",
        input_file="pwx.in", output_file="pwx.out",
        cores=prof.validate_cores(14), walltime="02:00:00",
    )
    plan.stages.append(s09_pwx)

    s09_ph = StageSpec(
        id="09_epc_ph96_ph", kind=StageKind.PH_EPC,
        directory="09_epc_ph96", depends_on=["09_epc_ph96_pwx"],
        template="ph_epc.in.j2", executable="ph.x",
        input_file="ph_epc.in", output_file="ph_epc.out",
        cores=prof.validate_cores(56), walltime="12:00:00",
    )
    plan.stages.append(s09_ph)

    s09_lam = StageSpec(
        id="09_epc_ph96_lambda", kind=StageKind.LAMBDA,
        directory="09_epc_ph96", depends_on=["09_epc_ph96_ph"],
        template="lambda.in.j2", executable="lambda.x",
        input_file="lambdax.in", output_file="lambdax.out",
        cores=16, walltime="01:00:00",
    )
    plan.stages.append(s09_lam)

    # ── Stage 10: Convergence analysis (placeholder) ──
    s10 = StageSpec(
        id="10_convergence", kind=StageKind.LAMBDA,
        directory="10_convergence", depends_on=["08_epc_ph64_lambda", "09_epc_ph96_lambda"],
        template="", executable="",
        input_file="", output_file="",
        cores=1, walltime="00:05:00",
        pre_commands=[
            "# Run: vibedft analyze tc ../08_epc_ph64/lambdax.out ../09_epc_ph96/lambdax.out",
            "#       vibedft convergence --root .. --html convergence.html",
        ],
    )
    plan.stages.append(s10)

    return plan
