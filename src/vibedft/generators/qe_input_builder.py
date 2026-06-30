"""QE input file builder — renders Jinja2 templates with plan parameters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import jinja2
    _HAS_JINJA2 = True
except ImportError:
    _HAS_JINJA2 = False

from vibedft.generators.manifest import StageSpec, WorkflowPlan

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def build_stage_input(stage: StageSpec, plan: WorkflowPlan) -> str:
    """Render the QE input file for a single stage.

    Returns the rendered text, or a placeholder if the template is missing.
    """
    if not stage.template or not _HAS_JINJA2:
        return _fallback_input(stage, plan)

    template_path = _TEMPLATE_DIR / stage.template
    if not template_path.is_file():
        return _fallback_input(stage, plan)

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        undefined=jinja2.StrictUndefined,
    )
    tpl = env.get_template(stage.template)

    ctx = _build_context(stage, plan)
    return tpl.render(**ctx)


def _build_context(stage: StageSpec, plan: WorkflowPlan) -> dict[str, Any]:
    """Build the Jinja2 template context for a stage."""
    cp = plan.common_params
    ctx: dict[str, Any] = {
        "prefix": cp.get("prefix", "material"),
        "pseudo_dir": cp.get("pseudo_dir", "<PSEUDO_DIR>"),
        "ecutwfc": cp.get("ecutwfc", 60),
        "ecutrho": cp.get("ecutrho", 480),
        "occupations": cp.get("occupations", "smearing"),
        "smearing": cp.get("smearing", "gaussian"),
        "degauss": cp.get("degauss", 0.005),
        "tot_charge": cp.get("tot_charge", 0.0),
        "stage_id": stage.id,
        "stage_kind": stage.kind.value,
        "cores": stage.cores,
        # 2D / vdW physics (inject from common_params, with safe defaults)
        "assume_isolated": cp.get("assume_isolated", ""),
        "input_dft": cp.get("input_dft", ""),
        "cell_dofree": cp.get("cell_dofree", ""),
        "force_symmorphic": cp.get("force_symmorphic", False),
        "disk_io": cp.get("disk_io", ""),
        "forc_conv_thr": cp.get("forc_conv_thr", 1.0e-6),
        "etot_conv_thr": cp.get("etot_conv_thr", 1.0e-8),
        "mixing_beta": cp.get("mixing_beta", 0.4),
        "conv_thr": cp.get("conv_thr", 1.0e-10),
        # Structure (injected from common_params, not template-hardcoded)
        "nat": cp.get("nat", 1),
        "ntyp": cp.get("ntyp", 1),
        "atomic_species": cp.get("atomic_species", "X  1.0  X.UPF\n"),
        "cell_parameters": cp.get("cell_parameters", "1.0 0.0 0.0\n0.0 1.0 0.0\n0.0 0.0 30.0"),
        "atomic_positions": cp.get("atomic_positions", "X  0.0 0.0 0.0\n"),
        # Defaults for all template variables
        "fildyn": f"{cp.get('prefix', 'material')}.dyn",
        "stage_prefix": cp.get("prefix", "material"),
        "k_grid": [12, 12, 1],
        "q_grid": [8, 8, 1],
        "electron_phonon": "",
        "el_ph_sigma": 0.005,
        "el_ph_nsigma": 10,
    }

    # Stage-specific prefix
    ctx["stage_prefix"] = f"{ctx['prefix']}_{stage.id}"

    # K-grid selection by stage kind
    kg = plan.k_grids
    ctx["k_grid"] = kg.get("scf", [12, 12, 1])
    if stage.kind.value in ("relax",):
        ctx["k_grid"] = kg.get("relax", kg.get("scf", [8, 8, 1]))
    elif stage.kind.value == "bands":
        ctx["k_grid"] = kg.get("bands", [12, 12, 1])
    elif stage.kind.value == "nscf_dos":
        ctx["k_grid"] = kg.get("nscf_dos", [24, 24, 1])
    elif stage.kind.value == "ph_stability":
        ctx["k_grid"] = kg.get("ph", [16, 16, 1])
    elif stage.kind.value == "ph_epc":
        ctx["k_grid"] = kg.get("ph", [16, 16, 1])
    elif stage.id.startswith("08_epc_ph64"):
        if "pwxall" in stage.id:
            ctx["k_grid"] = kg.get("epc_64", [64, 64, 1])
        elif "pwx" in stage.id:
            ctx["k_grid"] = kg.get("ph", [16, 16, 1])
    elif stage.id.startswith("09_epc_ph96"):
        if "pwxall" in stage.id:
            ctx["k_grid"] = kg.get("epc_96", [96, 96, 1])
        elif "pwx" in stage.id:
            ctx["k_grid"] = kg.get("ph", [16, 16, 1])

    # Q-grid for PH stages
    qg = plan.q_grids.get("ph", [8, 8, 1])
    ctx["q_grid"] = qg

    # PH-specific
    ctx["electron_phonon"] = ""
    ctx["el_ph_sigma"] = 0.005
    ctx["el_ph_nsigma"] = 10
    if stage.kind.value == "ph_epc":
        ctx["electron_phonon"] = "dvscf"

    # EPC phi64/ph96 specific prefixes
    if "ph64" in stage.directory:
        ctx["stage_prefix"] = f"{ctx['prefix']}_epc64"
        ctx["fildyn"] = f"{ctx['prefix']}_epc64.dyn"
    elif "ph96" in stage.directory:
        ctx["stage_prefix"] = f"{ctx['prefix']}_epc96"
        ctx["fildyn"] = f"{ctx['prefix']}_epc96.dyn"
    elif stage.kind.value == "ph_stability":
        ctx["fildyn"] = f"{ctx['prefix']}.dyn"
    elif stage.kind.value in ("q2r", "matdyn_disp", "matdyn_dos"):
        # q2r/matdyn read from the preceding ph_stability; use base prefix
        ctx["fildyn"] = f"{ctx['prefix']}.dyn"

    return ctx


def _fallback_input(stage: StageSpec, plan: WorkflowPlan) -> str:
    """Minimal fallback input when templates are unavailable."""
    cp = plan.common_params
    prefix = cp.get("prefix", "material")
    pd = cp.get("pseudo_dir", "<PSEUDO_DIR>")

    kind = stage.kind.value
    if kind == "relax":
        return (
            f"&CONTROL calculation='relax' prefix='{prefix}' outdir='./out_rx/' pseudo_dir='{pd}' /\n"
            f"&SYSTEM ibrav=0 nat=1 ntyp=1 ecutwfc={cp['ecutwfc']} ecutrho={cp['ecutrho']} "
            f"occupations='{cp['occupations']}' smearing='{cp['smearing']}' degauss={cp['degauss']} /\n"
            f"&ELECTRONS conv_thr=1.0d-12 /\n"
            f"&IONS /\n"
            f"ATOMIC_SPECIES\n  X 1.0 X.UPF\n"
            f"ATOMIC_POSITIONS crystal\n  X 0.0 0.0 0.0\n"
            f"K_POINTS automatic\n  {plan.k_grids['relax'][0]} {plan.k_grids['relax'][1]} {plan.k_grids['relax'][2]} 0 0 0\n"
            f"CELL_PARAMETERS angstrom\n  1.0 0.0 0.0\n  0.0 1.0 0.0\n  0.0 0.0 30.0\n"
        )
    if kind == "scf":
        return (
            f"&CONTROL calculation='scf' prefix='{prefix}' outdir='./out_scf/' pseudo_dir='{pd}' /\n"
            f"&SYSTEM ibrav=0 nat=1 ntyp=1 ecutwfc={cp['ecutwfc']} ecutrho={cp['ecutrho']} "
            f"occupations='{cp['occupations']}' smearing='{cp['smearing']}' degauss={cp['degauss']} /\n"
            f"&ELECTRONS conv_thr=1.0d-12 /\n"
            f"ATOMIC_SPECIES\n  X 1.0 X.UPF\n"
            f"ATOMIC_POSITIONS crystal\n  X 0.0 0.0 0.0\n"
            f"K_POINTS automatic\n  12 12 1 0 0 0\n"
            f"CELL_PARAMETERS angstrom\n  1.0 0.0 0.0\n  0.0 1.0 0.0\n  0.0 0.0 30.0\n"
        )
    if kind == "ph_stability":
        return (
            f"&INPUTPH prefix='{prefix}' outdir='./out_scf/' fildyn='{prefix}.dyn' ldisp=.true. "
            f"nq1=8 nq2=8 nq3=1 tr2_ph=1.0d-14 /\n"
        )
    if kind == "ph_epc":
        return (
            f"&INPUTPH prefix='{prefix}' outdir='./out_epc/' fildyn='{prefix}.dyn' ldisp=.true. "
            f"nq1=8 nq2=8 nq3=1 electron_phonon='dvscf' el_ph_sigma=0.005 el_ph_nsigma=10 tr2_ph=1.0d-14 /\n"
        )
    if kind == "q2r":
        return (
            f"&INPUT fildyn='{prefix}.dyn' flfrc='{prefix}.fc' zasr='crystal' /\n"
        )
    if kind == "matdyn_disp":
        return (
            f"&INPUT asr='simple' flfrc='{prefix}.fc' flfrq='{prefix}.freq.gp' "
            f"q_in_band_form=.true. /\n"
        )
    if kind == "lambda":
        return (
            f"&INPUT mustar=0.1 /\n0.001 0.020 0.001\n"
        )
    return f"! Stage: {stage.id} — template not available\n"
