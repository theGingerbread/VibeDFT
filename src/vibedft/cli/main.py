from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path
from typing import Any, Sequence

import yaml

from vibedft.core.analysis import (
    parse_qe_output,
    parse_dos_output,
    parse_bands_output,
    parse_pdos_file,
    discover_pdos_files,
    parse_pdos_bundle,
)
from vibedft.core.case import init_case
from vibedft.core.html import build_workbench
from vibedft.core.plot import plot_bands_dos
from vibedft.core.registry import Registry, RegistryError
from vibedft.core.runbook import SLURM_RUNBOOK
from vibedft.core.setup import build_setup_bundle
from vibedft.core.slurm import render_slurm_script

def _default_slurm_stages(workflow: str) -> list[dict[str, Any]]:
    """Return a sensible default Slurm stage list for known workflows.

    Heavy parallel stages (pw.x, ph.x) run at full ntasks.
    Light post-processing stages (dos.x, bands.x, q2r.x, matdyn.x, lambda.x) run at np=16.
    """
    if "scf_dos" in workflow:
        return [
            {"label": "SCF", "executable": "pw.x", "input": "scf.in", "output": "scf.out"},
            {"label": "NSCF DOS", "executable": "pw.x", "input": "nscf.in", "output": "nscf_dos.out"},
            {"label": "DOS", "executable": "dos.x", "input": "dos.in", "output": "dos.out", "np": 16},
        ]
    if "nscf_uniform" in workflow:
        return [
            {"label": "NSCF Uniform", "executable": "pw.x", "input": "nscf.in", "output": "nscf_uniform.out",
             "pre_commands": [
                 "PREFIX=$(grep -iw 'prefix' nscf.in | head -1 | awk -F= '{gsub(/[\\047\\042]|^[ \\t]+|[ \\t]+$/, \"\", $2); print $2}')",
                 'echo "Staging SCF save for prefix=${PREFIX}"',
                 'mkdir -p out_nscf',
                 'if [ ! -e "out_nscf/${PREFIX}.save" ]; then '
                 'cp -r ../02_scf/out_scf/${PREFIX}.save ./out_nscf/ 2>/dev/null || '
                 'ln -s ../../02_scf/out_scf/${PREFIX}.save ./out_nscf/${PREFIX}.save 2>/dev/null || '
                 '{ echo "ERROR: cannot stage SCF save for ${PREFIX} — NSCF will fail"; exit 2; }; fi',
             ]},
        ]
    if "rx" in workflow:
        return [
            {"label": "RX", "executable": "pw.x", "input": "relax.in", "output": "relax.out"},
        ]
    if "bands" in workflow:
        return [
            {"label": "NSCF Bands", "executable": "pw.x", "input": "bands.in", "output": "bands_nscf.out"},
            {"label": "BandsX", "executable": "bands.x", "input": "bandsx.in", "output": "bandsx.out", "np": 16},
        ]
    if "ph_epc" in workflow:
        return [
            {"label": "PWXALL", "executable": "pw.x", "input": "pwxall.in", "output": "pwxall.out"},
            {"label": "PWX", "executable": "pw.x", "input": "pwx.in", "output": "pwx.out"},
            {"label": "PHX0", "executable": "ph.x", "input": "phx.in", "output": "phx0.out"},
            {"label": "PHX1", "executable": "ph.x", "input": "phx1.in", "output": "phx1.out"},
            {"label": "PHX2", "executable": "ph.x", "input": "phx2.in", "output": "phx2.out"},
            {"label": "PHX3", "executable": "ph.x", "input": "phx3.in", "output": "phx3.out"},
            {"label": "Q2R", "executable": "q2r.x", "input": "q2r.in", "output": "q2r.out", "np": 16},
            {"label": "MATDYNL", "executable": "matdyn.x", "input": "matdynline.in", "output": "matdynline.out", "np": 16},
            {"label": "LAMBDA", "executable": "lambda.x", "input": "lambdax.in", "output": "lambdax.out", "np": 16},
            {"label": "MATDYNDOS", "executable": "matdyn.x", "input": "matdyndos.in", "output": "matdyndos.out", "np": 16},
        ]
    if "fs" in workflow:
        return [
            {"label": "SCF NSCF", "executable": "pw.x", "input": "fs.in", "output": "fs.out"},
            {"label": "FSX", "executable": "fs.x", "input": "fs.in", "output": "fsx.out", "np": 16},
        ]
    # Generic single-stage fallback
    return [
        {"label": "SCF", "executable": "pw.x", "input": "scf.in", "output": "scf.out"},
    ]




def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="vibedft")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="VibeDFT project root. Defaults to current directory.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ------------------------------------------------------------------
    # plugin
    # ------------------------------------------------------------------
    plugin_parser = subparsers.add_parser("plugin")
    plugin_subparsers = plugin_parser.add_subparsers(dest="plugin_command", required=True)
    plugin_subparsers.add_parser("list")

    # ------------------------------------------------------------------
    # params
    # ------------------------------------------------------------------
    params_parser = subparsers.add_parser("params")
    params_subparsers = params_parser.add_subparsers(dest="params_command", required=True)
    inspect_parser = params_subparsers.add_parser("inspect")
    inspect_parser.add_argument("parameter_id")
    resolve_parser = params_subparsers.add_parser("resolve")
    resolve_parser.add_argument("--software", required=True)
    resolve_parser.add_argument("--workflow", required=True)
    resolve_parser.add_argument("--material", required=True)
    resolve_parser.add_argument("--profile", required=True)
    resolve_parser.add_argument("--strict", action="store_true",
                                 help="Warn on override keys not in workflow 'uses' list")

    # ------------------------------------------------------------------
    # render  (inputs + slurm scripts)
    # ------------------------------------------------------------------
    render_parser = subparsers.add_parser("render")
    render_subparsers = render_parser.add_subparsers(dest="render_command", required=True)

    render_inputs = render_subparsers.add_parser("inputs")
    render_inputs.add_argument("--software", required=True)
    render_inputs.add_argument("--workflow", required=True)
    render_inputs.add_argument("--material", required=True)
    render_inputs.add_argument("--profile", required=True)
    render_inputs.add_argument("--template", default=None,
                               help="Relative path to template under plugins/<software>/")
    render_inputs.add_argument("--output-dir", type=Path, default=None,
                               help="Directory to write all workflow templates (multi-template mode). "
                                    "If omitted, renders a single template to stdout.")

    render_slurm = render_subparsers.add_parser("slurm")
    render_slurm.add_argument("--software", default="qe")
    render_slurm.add_argument("--workflow", default="qe.scf_dos.v1")
    render_slurm.add_argument("--job-name", default=None)
    render_slurm.add_argument("--partition", default="debug")
    render_slurm.add_argument("--nodes", type=int, default=1)
    render_slurm.add_argument("--ntasks", type=int, default=4)
    render_slurm.add_argument("--walltime", default="UNLIMITED")
    render_slurm.add_argument("--work-dir", default=None,
                               help="Remote work directory on cluster (required for remote execution)")
    render_slurm.add_argument("--output", type=Path, default=Path("job.slurm"))

    # ------------------------------------------------------------------
    # analyze  (scf|dos|bands)
    # ------------------------------------------------------------------
    analyze_parser = subparsers.add_parser("analyze")
    analyze_subparsers = analyze_parser.add_subparsers(dest="analyze_command", required=True)

    analyze_scf = analyze_subparsers.add_parser("scf")
    analyze_scf.add_argument("output_file", type=Path, help="QE pw.x output file")

    analyze_dos = analyze_subparsers.add_parser("dos")
    analyze_dos.add_argument("datafile", type=Path, help="HfBr2.dos data file")
    analyze_dos.add_argument("--dos-output", type=Path, default=None,
                             help="dos.x stdout for metadata")

    analyze_bands = analyze_subparsers.add_parser("bands")
    analyze_bands.add_argument("datafile", type=Path, help="HfBr2.bands data file")
    analyze_bands.add_argument("--bands-output", type=Path, default=None,
                               help="bands.x stdout for metadata")
    analyze_bands.add_argument("--json", action="store_true")

    analyze_pdos = analyze_subparsers.add_parser("pdos")
    analyze_pdos.add_argument("pdos_dir", type=Path, help="Directory containing HfBr2.pdos_atm* files")
    analyze_pdos.add_argument("--atom", default=None, help="Filter by atom (e.g. Hf, Br)")
    analyze_pdos.add_argument("--orbital", default=None, help="Filter by orbital (e.g. s, p, d)")
    analyze_pdos.add_argument("--json", action="store_true")

    analyze_relax = analyze_subparsers.add_parser("relax")
    analyze_relax.add_argument(
        "outputs",
        nargs="+",
        type=Path,
        help="One or more QE relax / vc-relax output files",
    )
    analyze_relax.add_argument(
        "--json",
        action="store_true",
        help="Output comparison payload as JSON",
    )

    analyze_tc = analyze_subparsers.add_parser("tc")
    analyze_tc.add_argument("file_a", type=Path, help="First lambda.x output (e.g. ph64/lambdax.out)")
    analyze_tc.add_argument("file_b", type=Path, help="Second lambda.x output (e.g. ph96/lambdax.out)")
    analyze_tc.add_argument("--label-a", default="ph64")
    analyze_tc.add_argument("--label-b", default="ph96")
    analyze_tc.add_argument("--rel-tol-pct", type=float, default=1.0,
                             help="Relative tolerance for Tc overlap (default 1%%)")
    analyze_tc.add_argument("--json", action="store_true")

    analyze_phonon = analyze_subparsers.add_parser("phonon")
    analyze_phonon.add_argument("--freq", type=Path, required=True,
                                 help="QE matdyn.x freq.gp file")
    analyze_phonon.add_argument("--json", action="store_true")

    analyze_fs = analyze_subparsers.add_parser("fs")
    analyze_fs.add_argument("--bxsf", type=Path, required=True,
                             help="QE fs.x .bxsf file")
    analyze_fs.add_argument("--json", action="store_true")
    analyze_structure = analyze_subparsers.add_parser('structure')
    analyze_structure.add_argument('file', type=Path, help='CIF, POSCAR, or QE input file')
    analyze_structure.add_argument('--json', action='store_true')

    analyze_workfunction = analyze_subparsers.add_parser("workfunction", aliases=["wf"])
    analyze_workfunction.add_argument("--case-dir", type=Path, default=Path("."),
                                       help="Case directory containing output/avg.dat (default: .)")
    analyze_workfunction.add_argument("--json", action="store_true")

    analyze_report = analyze_subparsers.add_parser("report")
    analyze_report.add_argument("--case-dir", type=Path, default=Path("."),
                                 help="Case directory to aggregate (default: .)")
    analyze_report.add_argument("--json", action="store_true")


    # ------------------------------------------------------------------
    # qa  (quality assurance)
    # ------------------------------------------------------------------
    qa_parser = subparsers.add_parser("qa")
    qa_subparsers = qa_parser.add_subparsers(dest="qa_command", required=True)

    qa_inputs_parser = qa_subparsers.add_parser("inputs")
    qa_inputs_parser.add_argument("--case-dir", type=Path, required=True,
                                   help="Path to case directory (e.g. cases/HfBr2-test)")

    qa_outputs_parser = qa_subparsers.add_parser("outputs")
    qa_outputs_parser.add_argument("--case-dir", type=Path, required=True,
                                    help="Path to case directory (e.g. cases/HfBr2-test)")

    qa_all_parser = qa_subparsers.add_parser("all")
    qa_all_parser.add_argument("--case-dir", type=Path, required=True,
                                help="Path to case directory (e.g. cases/HfBr2-test)")

    # ------------------------------------------------------------------
    # evidence  (research-layer case pipeline)
    # ------------------------------------------------------------------
    evidence_parser = subparsers.add_parser("evidence")
    evidence_source = evidence_parser.add_mutually_exclusive_group(required=True)
    evidence_source.add_argument("--case-dir", type=Path,
                                 help="Path to case directory to analyze")
    evidence_source.add_argument("--batch-root", type=Path,
                                 help="Path to a directory of case directories to analyze")
    evidence_parser.add_argument("--json", action="store_true",
                                 help="Output JSON evidence pack")

    # ------------------------------------------------------------------
    # goal (project-level governance)
    # ------------------------------------------------------------------
    goal_parser = subparsers.add_parser("goal")
    goal_parser.add_argument("--json", action="store_true",
                              help="Output JSON summary")
    goal_parser.add_argument("--docs-root", type=Path, default=Path("docs"),
                              help="Documentation root (default: docs)")
    goal_parser.add_argument("--index", type=Path, default=Path("docs/INDEX.md"),
                             help="Documentation index file (default: docs/INDEX.md)")
    goal_parser.add_argument(
        "--stages",
        type=Path,
        default=Path("workflows/stages.yaml"),
        help="Workflow stages definition file",
    )
    goal_parser.add_argument(
        "--stage-map",
        type=Path,
        default=Path("docs/reference/physics_layer_stage_map_v2.md"),
        help="Physics layer ↔ stage mapping file",
    )
    goal_parser.add_argument(
        "--skip-cases",
        action="store_true",
        help="Skip case-directory layout audit",
    )
    goal_parser.add_argument(
        "--case-audit",
        action="store_true",
        help="Run qa_all on each case in --case-root",
    )
    goal_parser.add_argument(
        "--case-root",
        type=Path,
        default=Path("cases"),
        help="Case root directory for QA audit",
    )
    goal_parser.add_argument(
        "--case-max",
        type=int,
        default=None,
        help="Max number of cases to audit",
    )

    # ------------------------------------------------------------------
    # validate  (stage-level rules — HfCl2 P2/P3/B1 hardening)
    # ------------------------------------------------------------------
    validate_parser = subparsers.add_parser("validate")
    validate_subparsers = validate_parser.add_subparsers(dest="validate_command", required=True)

    validate_stage_parser = validate_subparsers.add_parser("stage")
    validate_stage_parser.add_argument("--case-dir", type=Path, required=True,
                                       help="Path to case directory (e.g. cases/K-HfCl2/K-screening/K_1)")
    validate_stage_parser.add_argument("--stage", default=None,
                                       choices=["P2", "P3", "P4", "B1"],
                                       help="Stage rule group to run (default: all applicable)")

    # ------------------------------------------------------------------
    # audit  (runtime environment checks)
    # ------------------------------------------------------------------
    audit_parser = subparsers.add_parser("audit")
    audit_subparsers = audit_parser.add_subparsers(dest="audit_command", required=True)

    audit_runtime_parser = audit_subparsers.add_parser("runtime")
    audit_runtime_parser.add_argument("--case-dir", type=Path, default=None,
                                       help="Path to case directory (for pseudo discovery)")
    audit_runtime_parser.add_argument("--qe-bin", type=str, default=None,
                                       help="Path to QE binary directory")
    audit_runtime_parser.add_argument("--pseudo-dir", type=str, default=None,
                                       help="Path to pseudopotential directory")
    audit_runtime_parser.add_argument("--partition", type=str, default="debug",
                                       help="Slurm partition name (default: debug)")
    audit_runtime_parser.add_argument("--json", action="store_true",
                                       help="Output as JSON")

    # ------------------------------------------------------------------
    # remote  (transfer + Slurm lifecycle)
    # ------------------------------------------------------------------
    remote_parser = subparsers.add_parser("remote")
    remote_subparsers = remote_parser.add_subparsers(dest="remote_command", required=True)

    remote_plan_parser = remote_subparsers.add_parser("plan")
    remote_plan_parser.add_argument("--case-dir", type=Path, required=True)
    remote_plan_parser.add_argument("--host", default=None)
    remote_plan_parser.add_argument("--case-id", default=None)

    remote_push_parser = remote_subparsers.add_parser("push")
    remote_push_parser.add_argument("--case-dir", type=Path, required=True)
    remote_push_parser.add_argument("--host", default=None)
    remote_push_parser.add_argument("--case-id", default=None,
                                     help="Remote case name (default: case directory name)")

    remote_submit_parser = remote_subparsers.add_parser("submit")
    remote_submit_parser.add_argument("--case-dir", type=Path, required=True)
    remote_submit_parser.add_argument("--host", default=None)
    remote_submit_parser.add_argument("--case-id", default=None)

    remote_status_parser = remote_subparsers.add_parser("status")
    remote_status_parser.add_argument("--case-dir", type=Path, required=True)
    remote_status_parser.add_argument("--host", default=None)
    remote_status_parser.add_argument("--case-id", default=None)

    remote_pull_parser = remote_subparsers.add_parser("pull")
    remote_pull_parser.add_argument("--case-dir", type=Path, required=True)
    remote_pull_parser.add_argument("--host", default=None)
    remote_pull_parser.add_argument("--case-id", default=None)

    # ------------------------------------------------------------------
    # archive  (case → DFT results bridge)
    # ------------------------------------------------------------------
    archive_parser = subparsers.add_parser("archive")
    archive_subparsers = archive_parser.add_subparsers(dest="archive_command", required=True)

    archive_plan_parser = archive_subparsers.add_parser("plan")
    archive_plan_parser.add_argument("--case-dir", type=Path, required=True)
    archive_plan_parser.add_argument("--system", default="HfX2")
    archive_plan_parser.add_argument("--material", default="HfBr2")
    archive_plan_parser.add_argument("--route", default="dopping",
                                      help="dopping | intercalation | fs")
    archive_plan_parser.add_argument("--target-root", type=Path, required=True,
                                      help="Target root for DFT results archive (e.g. <DFT_RESULTS_DIR>)")

    archive_apply_parser = archive_subparsers.add_parser("apply")
    archive_apply_parser.add_argument("--case-dir", type=Path, required=True)
    archive_apply_parser.add_argument("--system", default="HfX2")
    archive_apply_parser.add_argument("--material", required=True,
                                       help="Material ID (e.g. HfBr2, HfCl2, HfI2)")
    archive_apply_parser.add_argument("--route", required=True,
                                       help="Route: dopping | intercalation | fs")
    archive_apply_parser.add_argument("--target-root", type=Path, required=True,
                                       help="Target root for DFT results archive (e.g. <DFT_RESULTS_DIR>)")
    archive_apply_parser.add_argument("--dry-run", action="store_true")

    # ------------------------------------------------------------------
    # plot
    # ------------------------------------------------------------------
    plot_parser = subparsers.add_parser("plot")
    plot_subparsers = plot_parser.add_subparsers(dest="plot_command", required=True)

    plot_bd = plot_subparsers.add_parser("bands-dos")
    plot_bd.add_argument("--bands", type=Path, required=True, help="HfBr2.bands data file")
    plot_bd.add_argument("--dos", type=Path, required=True, help="HfBr2.dos data file")
    plot_bd.add_argument("--output", type=Path, default=Path("bands_dos.png"),
                         help="Output image path")
    plot_bd.add_argument("--title", default="Bands + DOS")
    plot_bd.add_argument("--e-fermi-ev", type=float, default=None,
                         help="Override Fermi energy (eV). Detected from DOS if omitted.")

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------
    setup_parser = subparsers.add_parser("setup")
    setup_subparsers = setup_parser.add_subparsers(dest="setup_command", required=True)
    setup_build_parser = setup_subparsers.add_parser("build")
    setup_build_parser.add_argument("--software", required=True)
    setup_build_parser.add_argument("--workflow", required=True)
    setup_build_parser.add_argument("--material", required=True)
    setup_build_parser.add_argument("--profile", required=True)
    setup_build_parser.add_argument("--output-dir", type=Path, required=True)
    setup_open_parser = setup_subparsers.add_parser("open")
    setup_open_parser.add_argument("--software", required=True)
    setup_open_parser.add_argument("--workflow", required=True)
    setup_open_parser.add_argument("--material", required=True)
    setup_open_parser.add_argument("--profile", required=True)
    setup_open_parser.add_argument("--output-dir", type=Path, required=True)
    setup_open_parser.add_argument("--dry-run", action="store_true")

    # ------------------------------------------------------------------
    # case
    # ------------------------------------------------------------------
    case_parser = subparsers.add_parser("case")
    case_subparsers = case_parser.add_subparsers(dest="case_command", required=True)
    case_init_parser = case_subparsers.add_parser("init")
    case_init_parser.add_argument("--software", required=True)
    case_init_parser.add_argument("--workflow", required=True)
    case_init_parser.add_argument("--material", required=True)
    case_init_parser.add_argument("--profile", required=True)
    case_init_parser.add_argument("--case-id", required=True)
    case_init_parser.add_argument("--output-dir", type=Path, required=True)

    # ------------------------------------------------------------------
    # inspect  (file inspection — Sprint 1)
    # ------------------------------------------------------------------
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("files", nargs="+", type=Path,
                                help="One or more QE .in / .out files to inspect")
    inspect_parser.add_argument("--json", action="store_true",
                                help="Output full InspectionResult as JSON")

    # ------------------------------------------------------------------
    # review  (case-directory review — Sprint 2)
    # ------------------------------------------------------------------
    review_parser = subparsers.add_parser("review")
    review_parser.add_argument("--case-dir", type=Path, required=True,
                               help="Path to case directory (e.g. cases/HfBr2-test)")
    review_parser.add_argument("--json", action="store_true",
                               help="Output full ReviewResult as JSON")

    # ------------------------------------------------------------------
    # property  (materials properties — Sprint 12)
    # ------------------------------------------------------------------
    prop_parser = subparsers.add_parser("property")
    prop_subparsers = prop_parser.add_subparsers(dest="property_command", required=True)
    prop_analyze = prop_subparsers.add_parser("analyze")
    prop_analyze.add_argument("--case-dir", type=Path, required=True)
    prop_analyze.add_argument("--json", action="store_true")
    prop_analyze.add_argument("--html", type=Path, default=None,
                              help="Write property report to HTML file")

    # ------------------------------------------------------------------
    # decide  (research decision — Sprint 13)
    # ------------------------------------------------------------------
    decide_parser = subparsers.add_parser("decide")
    decide_parser.add_argument("--case-dir", type=Path, required=True)
    decide_parser.add_argument("--json", action="store_true")
    decide_parser.add_argument("--html", type=Path, default=None,
                               help="Write decision report to HTML file")

    # ------------------------------------------------------------------
    # log  (run ledger — Sprint A)
    # ------------------------------------------------------------------
    log_parser = subparsers.add_parser("log")
    log_subparsers = log_parser.add_subparsers(dest="log_command", required=True)
    log_collect = log_subparsers.add_parser("collect")
    log_collect.add_argument("--case-dir", type=Path, required=True)
    log_collect.add_argument("--out", type=Path, default=None,
                             help="Write Markdown to file (default: stdout)")

    # ------------------------------------------------------------------
    # semantics  (case interpretation — Sprint 16)
    # ------------------------------------------------------------------
    sem_parser = subparsers.add_parser("semantics")
    sem_subparsers = sem_parser.add_subparsers(dest="semantics_command", required=True)
    sem_analyze = sem_subparsers.add_parser("analyze")
    sem_analyze.add_argument("--case-dir", type=Path, required=True)
    sem_analyze.add_argument("--json", action="store_true")

    # ------------------------------------------------------------------
    # convergence  (batch review — Sprint 5)
    # ------------------------------------------------------------------
    conv_parser = subparsers.add_parser("convergence")
    conv_parser.add_argument("--root", type=Path, required=True,
                             help="Root directory containing multiple case subdirs")
    conv_parser.add_argument("--title", default="VibeDFT Convergence Report")
    conv_parser.add_argument("--html", type=Path, default=None,
                             help="Write HTML report to file")
    conv_parser.add_argument("--json", action="store_true",
                             help="Output convergence data as JSON")

    # ------------------------------------------------------------------
    # runbook
    # ------------------------------------------------------------------
    runbook_parser = subparsers.add_parser("runbook")
    runbook_subparsers = runbook_parser.add_subparsers(dest="runbook_command", required=True)
    runbook_subparsers.add_parser("slurm")

    # ------------------------------------------------------------------
    # report
    # ------------------------------------------------------------------
    report_parser = subparsers.add_parser("report")
    report_subparsers = report_parser.add_subparsers(dest="report_command", required=True)

    report_build_parser = report_subparsers.add_parser("build")
    report_build_parser.add_argument("--case-dir", type=Path, required=True)
    report_build_parser.add_argument("--title", default="VibeDFT Materials Report")
    report_build_parser.add_argument("--case-id", default=None)
    report_build_parser.add_argument("--material", default="")
    report_build_parser.add_argument("--compare-dir", type=Path, action="append", default=[],
                                      help="Repeatable comparison case directory for overlay bands")
    report_build_parser.add_argument("--json", action="store_true",
                                      help="Output JSON payload to stdout")
    report_build_parser.add_argument("--html", action="store_true",
                                      help="Generate interactive HTML report")
    report_build_parser.add_argument("--output", type=Path, default=None,
                                      help="Write to file (default: case-dir/report.json or report.html)")

    report_html_parser = report_subparsers.add_parser("html")
    report_html_parser.add_argument("--case-dir", type=Path, required=True)
    report_html_parser.add_argument("--title", default="VibeDFT Materials Report")
    report_html_parser.add_argument("--case-id", default=None)
    report_html_parser.add_argument("--material", default="")
    report_html_parser.add_argument("--compare-dir", type=Path, action="append", default=[],
                                    help="Repeatable comparison case directory for overlay bands")
    report_html_parser.add_argument("--output", type=Path, default=None)

    report_generate_parser = report_subparsers.add_parser("generate")
    report_generate_parser.add_argument("--case-dir", type=Path, required=True,
                                        help="Path to case directory (e.g. cases/HfBr2-test)")
    report_generate_parser.add_argument("--title", default="VibeDFT Materials Report")
    report_generate_parser.add_argument("--output", type=Path, default=None,
                                        help="Write HTML to file (default: case-dir/report.html)")
    report_generate_parser.add_argument("--json", action="store_true",
                                        help="Output JSON payload (review + artifacts)")

    # ------------------------------------------------------------------
    # plan  (workflow generator — Sprint 6)
    # ------------------------------------------------------------------
    plan_parser = subparsers.add_parser("plan")
    plan_subparsers = plan_parser.add_subparsers(dest="plan_command", required=True)

    plan_sc = plan_subparsers.add_parser("superconductivity")
    plan_sc.add_argument("--structure", type=Path, required=True,
                         help="Structure file (CIF, POSCAR, or QE input)")
    plan_sc.add_argument("--engine", default="qe", choices=["qe"])
    plan_sc.add_argument("--profile", default="cluster_debug",
                         choices=["cluster_debug", "cluster_prod"])
    plan_sc.add_argument("--out", type=Path, default=Path("runs/sc_workflow"),
                         help="Output root directory")
    plan_sc.add_argument("--prefix", default="material",
                         help="Calculation prefix")
    plan_sc.add_argument("--ecutwfc", type=int, default=60)
    plan_sc.add_argument("--ecutrho", type=int, default=480)
    plan_sc.add_argument("--tot-charge", type=float, default=0.0,
                         help="Total charge for doping (e.g. -0.05 for electron doping)")
    plan_sc.add_argument("--dry-run", action="store_true",
                         help="Print plan without creating files")

    # ------------------------------------------------------------------
    # server  (local API — Sprint 8)
    # ------------------------------------------------------------------
    server_parser = subparsers.add_parser("server")
    server_parser.add_argument("--host", default="127.0.0.1")
    server_parser.add_argument("--port", type=int, default=8765)
    server_parser.add_argument("--reload", action="store_true")
    server_parser.add_argument("--with-frontend", action="store_true",
                               help="Serve the React workbench at /")

    # ------------------------------------------------------------------
    # html
    # ------------------------------------------------------------------
    html_parser = subparsers.add_parser("html")
    html_subparsers = html_parser.add_subparsers(dest="html_command", required=True)
    build_parser = html_subparsers.add_parser("build")
    build_parser.add_argument("--output", type=Path, default=Path("dist/index.html"))
    build_parser.add_argument("--cases-dir", type=Path, default=None,
                               help="Case dir(s), comma-separated for multi-case comparison")
    build_parser.add_argument("--bands", type=Path, default=None, help="Path to HfBr2.bands file")
    build_parser.add_argument("--dos", type=Path, default=None, help="Path to HfBr2.dos file")
    build_parser.add_argument("--scf-output", type=Path, default=None, help="Path to scf.out file")
    build_parser.add_argument("--title", default="VibeDFT Analysis")

    # ==================================================================
    # Dispatch
    # ==================================================================
    args = parser.parse_args(argv)

    try:
        # ---- plugin ----
        if args.command == "plugin" and args.plugin_command == "list":
            registry = Registry.from_project_root(args.root)
            for plugin_id in registry.plugin_ids():
                plugin = registry.plugins[plugin_id]
                print(f"{plugin_id}\t{plugin.get('name', plugin_id)}")
            return

        # ---- params ----
        if args.command == "params" and args.params_command == "inspect":
            registry = Registry.from_project_root(args.root)
            parameter = registry.get_parameter(args.parameter_id)
            print(yaml.safe_dump(parameter, sort_keys=False, allow_unicode=True))
            return

        if args.command == "params" and args.params_command == "resolve":
            registry = Registry.from_project_root(args.root)
            if args.strict:
                resolved = registry.resolve_parameters_strict(
                    software=args.software,
                    workflow=args.workflow,
                    material=args.material,
                    profile=args.profile,
                )
            else:
                resolved = registry.resolve_parameters(
                    software=args.software,
                    workflow=args.workflow,
                    material=args.material,
                    profile=args.profile,
                )
            print(yaml.safe_dump(resolved, sort_keys=False, allow_unicode=True))
            return

        # ---- render ----
        if args.command == "render":
            if args.render_command == "inputs":
                registry = Registry.from_project_root(args.root)
                if args.output_dir:
                    # Multi-template mode: render all workflow templates to directory
                    rendered = registry.render_all_templates(
                        software=args.software,
                        workflow=args.workflow,
                        material=args.material,
                        profile=args.profile,
                        output_dir=args.output_dir,
                    )
                    for name, path in sorted(rendered.items()):
                        print(f"  {name}: {path}")
                    print(f"Rendered {len(rendered)} files to {args.output_dir}")
                else:
                    rendered = registry.render_template(
                        software=args.software,
                        workflow=args.workflow,
                        material=args.material,
                        profile=args.profile,
                        template_rel=args.template,
                    )
                    print(rendered)
                return

            if args.render_command == "slurm":
                from vibedft.core.slurm import render_slurm_script
                stages = _default_slurm_stages(args.workflow)
                script = render_slurm_script(
                    stages=stages,
                    job_name=args.job_name,
                    partition=args.partition,
                    nodes=args.nodes,
                    ntasks=args.ntasks,
                    walltime=args.walltime,
                    work_dir=args.work_dir,
                )
                args.output.write_text(script, encoding="utf-8")
                print(f"Wrote {args.output}")
                return

        # ---- analyze ----
        if args.command == "analyze":
            if args.analyze_command == "scf":
                result = parse_qe_output(args.output_file)
                print(result.summary())
                return

            if args.analyze_command == "dos":
                result = parse_dos_output(
                    datafile=args.datafile,
                    dos_output=args.dos_output,
                )
                print(result.summary())
                return

            if args.analyze_command == "bands":
                result = parse_bands_output(
                    datafile=args.datafile,
                    bands_output=args.bands_output,
                )
                if args.json:
                    import json
                    print(json.dumps({
                        "nbnd": result.nbnd,
                        "nks": result.nks,
                        "k_points": result.k_points,
                        "bands": result.bands,
                    }, indent=2))
                else:
                    print(result.summary())
                return

            if args.analyze_command == "pdos":
                pdos_dir = Path(args.pdos_dir)
                if not pdos_dir.is_dir():
                    parser.exit(2, f"vibedft: PDOS directory not found: {pdos_dir}\n")
                results = parse_pdos_bundle(
                    pdos_dir,
                    atom_label=args.atom,
                    orbital=args.orbital,
                )
                if args.json:
                    import json
                    payload = []
                    for r in results:
                        payload.append({
                            "label": r.label,
                            "fermi_ev": r.fermi_ev,
                            "n_points": r.n_points,
                            "data": r.data,
                        })
                    print(json.dumps(payload, indent=2))
                else:
                    for r in results:
                        fermi = f"EF={r.fermi_ev:.4f} eV" if r.fermi_ev else "EF=N/A"
                        print(f"{r.label:50s}  {r.n_points:5d} pts  {fermi}")
                return

            if args.analyze_command == "relax":
                from vibedft.calculator.qe.relax import compare_relax_outputs
                comparison = compare_relax_outputs(args.outputs)
                if args.json:
                    import json

                    print(
                        json.dumps(
                            comparison.to_schema(),
                            indent=2,
                            ensure_ascii=False,
                        )
                    )
                else:
                    _print_relax_compare_summary(comparison)
                return

            if args.analyze_command == "tc":
                from vibedft.core.tc import compute_tc_overlap
                result = compute_tc_overlap(
                    args.file_a, args.file_b,
                    label_a=args.label_a, label_b=args.label_b,
                    rel_tol_pct=args.rel_tol_pct,
                )
                if args.json:
                    import json
                    print(json.dumps({
                        "tc_point_k": result.tc_point_k,
                        "degauss_ry": result.degauss_ry,
                        "overlap_status": result.overlap_status,
                        "overlap_start_degauss": result.overlap_start_degauss,
                        "overlap_end_degauss": result.overlap_end_degauss,
                        "relative_deviation_pct": result.relative_deviation_pct,
                        "nan_rows_a": result.nan_rows_a,
                        "nan_rows_b": result.nan_rows_b,
                        "message": result.message,
                    }, indent=2))
                else:
                    print(f"Tc Overlap: {result.overlap_status.upper()}")
                    if result.tc_point_k:
                        print(f"  Tc_Point = {result.tc_point_k:.2f} K")
                        print(f"  degauss  = {result.degauss_ry:.4f} Ry")
                        print(f"  ΔTc/Tc   = {result.relative_deviation_pct:.2f}%")
                    print(f"  {result.message}")
                return

            if args.analyze_command == "phonon":
                from vibedft.core.phonon import parse_freq_gp, qa_phonon_frequencies
                disp = parse_freq_gp(args.freq)
                qa = qa_phonon_frequencies(disp)
                if args.json:
                    import json
                    print(json.dumps({
                        "n_qpoints": disp.n_qpoints,
                        "n_branches": disp.n_branches,
                        "min_frequency_cm1": disp.min_frequency_cm1,
                        "max_frequency_cm1": disp.max_frequency_cm1,
                        "n_imaginary": disp.n_imaginary,
                        "n_imaginary_non_gamma": disp.n_imaginary_non_gamma,
                        "imaginary_modes": disp.imaginary_modes[:20],
                        "qa_status": qa.status,
                        "qa_checks": qa.checks,
                    }, indent=2))
                else:
                    print(disp.summary())
                    print()
                    print(qa.summary())
                return

            if args.analyze_command == "fs":
                from vibedft.core.fs import parse_bxsf
                data = parse_bxsf(args.bxsf)
                if args.json:
                    import json
                    print(json.dumps({
                        "n_bands": data.n_bands,
                        "n_k1": data.n_k1, "n_k2": data.n_k2, "n_k3": data.n_k3,
                        "n_kpoints": data.n_kpoints,
                        "fermi_energy_ev": data.fermi_energy_ev,
                        "bands_crossing_ef": data.bands_crossing_ef,
                        "has_fermi_surface": data.has_fermi_surface,
                        "parse_errors": data.parse_errors,
                    }, indent=2))
                else:
                    print(data.summary())
                return

            if args.analyze_command == "structure":
                from vibedft.core.structure import (
                    parse_structure,
                    parse_structure_from_qe_input,
                    parse_structure_from_poscar,
                    parse_structure_from_cif,
                    compute_2d_metrics,
                    compute_symmetry,
                )
                f = args.file
                # Use the unified dispatcher: routes by suffix / file
                # name to the appropriate ASE-backed or legacy parser.
                # CIF is now first-class (requires the ``ase`` extra).
                try:
                    struct = parse_structure(f)
                except RuntimeError as exc:
                    parser.exit(2, f"vibedft: {exc}\n")
                if not struct or not struct.atoms:
                    parser.exit(2, f"vibedft: could not parse structure from {f}\n")
                metrics = compute_2d_metrics(struct)
                sym = compute_symmetry(struct)
                if args.json:
                    import json
                    print(json.dumps({
                        "formula": struct.formula,
                        "n_atoms": struct.n_atoms,
                        "elements": struct.elements,
                        "lattice": {
                            "a": struct.lattice.a if struct.lattice else 0,
                            "b": struct.lattice.b if struct.lattice else 0,
                            "c": struct.lattice.c if struct.lattice else 0,
                            "alpha": struct.lattice.alpha if struct.lattice else 0,
                            "beta": struct.lattice.beta if struct.lattice else 0,
                            "gamma": struct.lattice.gamma if struct.lattice else 0,
                            "volume": struct.lattice.volume if struct.lattice else 0,
                        },
                        "metrics_2d": {
                            "vacuum_thickness_ang": metrics.vacuum_thickness_ang,
                            "layer_thickness_ang": metrics.layer_thickness_ang,
                            "vacuum_sufficient": metrics.vacuum_sufficient,
                            "n_layers": metrics.n_layers,
                            "buckling_ang": metrics.buckling_ang,
                        },
                        "symmetry": sym,
                    }, indent=2, default=str))
                else:
                    lat = struct.lattice
                    print(f"Formula:   {struct.formula or 'N/A'}")
                    print(f"Atoms:     {struct.n_atoms} ({', '.join(struct.elements)})")
                    if lat:
                        print(f"Lattice:   a={lat.a:.3f} b={lat.b:.3f} c={lat.c:.3f} Å")
                        print(f"           α={lat.alpha:.1f}° β={lat.beta:.1f}° γ={lat.gamma:.1f}°")
                        print(f"           V={lat.volume:.2f} Å³")
                    print(f"2D:        vacuum={metrics.vacuum_thickness_ang:.1f} Å, "
                          f"layers={metrics.n_layers}, "
                          f"buckling={metrics.buckling_ang:.3f} Å")
                    if sym.get("space_group_symbol"):
                        print(f"Symmetry:  {sym['space_group_symbol']} (#{sym['space_group_number']}), "
                              f"{sym['n_operations']} ops")
                return

            if args.analyze_command in ("workfunction", "wf"):
                from vibedft.properties.work_function import analyze_work_function
                result = analyze_work_function(args.case_dir)
                if args.json:
                    import json as _json
                    print(_json.dumps({
                        "property": result.property_name,
                        "status": result.status,
                        "data": result.data,
                        "insights": result.insights,
                    }, indent=2))
                else:
                    print(f"Work Function Analysis: {result.status}")
                    for k, v in result.data.items():
                        print(f"  {k}: {v}")
                    for line in result.insights:
                        print(f"  ℹ️ {line}")
                return

            if args.analyze_command == "report":
                import json as _json
                from vibedft.analyzers.orchestrator import run_physics_analysis
                report = run_physics_analysis(args.case_dir)
                if args.json:
                    print(_json.dumps({
                        "case_dir": report.case_dir,
                        "insights": [
                            {"id": i.id, "category": i.category,
                             "level": i.level.value, "message": i.message}
                            for i in report.insights
                        ],
                        "key_values": report.key_values,
                        "scores": {
                            "stability": report.stability_score,
                            "electronic": report.electronic_score,
                            "superconductivity": report.superconductivity_score,
                            "workflow_confidence": report.workflow_confidence,
                        },
                        "overall_verdict": report.overall_verdict,
                        "recommendation": report.recommendation,
                    }, indent=2))
                else:
                    print(f"╔═══ VibeDFT Report — {report.case_dir} ═══╗")
                    print(f"  Overall: {report.overall_verdict}")
                    print(f"  Scores:  stability={report.stability_score:.1f} "
                          f"electronic={report.electronic_score:.1f} "
                          f"sc={report.superconductivity_score:.1f} "
                          f"wf_confidence={report.workflow_confidence:.1f}")
                    print(f"  Key Values:")
                    for k, v in report.key_values.items():
                        print(f"    {k}: {v}")
                    print(f"  Insights ({len(report.insights)}):")
                    for ins in report.insights[:10]:
                        print(f"    [{ins.level.value}] {ins.message}")
                    if len(report.insights) > 10:
                        print(f"    ... and {len(report.insights) - 10} more")
                return

        # ---- plot ----
        if args.command == "plot" and args.plot_command == "bands-dos":
            output = plot_bands_dos(
                bands_file=args.bands,
                dos_file=args.dos,
                output=args.output,
                title=args.title,
                e_fermi_ev=args.e_fermi_ev,
            )
            print(f"Plotted {output}")
            return

        # ---- setup ----
        if args.command == "setup" and args.setup_command == "build":
            registry = Registry.from_project_root(args.root)
            bundle = build_setup_bundle(
                registry=registry,
                software=args.software,
                workflow=args.workflow,
                material=args.material,
                profile=args.profile,
                output_dir=args.output_dir,
            )
            print(f"Built {bundle.html_path}")
            print(f"Wrote {bundle.request_path}")
            return

        if args.command == "setup" and args.setup_command == "open":
            registry = Registry.from_project_root(args.root)
            bundle = build_setup_bundle(
                registry=registry,
                software=args.software,
                workflow=args.workflow,
                material=args.material,
                profile=args.profile,
                output_dir=args.output_dir,
            )
            target = bundle.html_path.resolve().as_uri()
            if args.dry_run:
                print(f"Would open {target}")
            else:
                webbrowser.open(target)
                print(f"Opened {target}")
            print(f"Wrote {bundle.request_path}")
            return

        # ---- case ----
        if args.command == "case" and args.case_command == "init":
            registry = Registry.from_project_root(args.root)
            case_dir = init_case(
                registry=registry,
                software=args.software,
                workflow=args.workflow,
                material=args.material,
                profile=args.profile,
                case_id=args.case_id,
                output_dir=args.output_dir,
            )
            print(f"Initialized {case_dir}")
            print(f"Calculation log: {case_dir / 'logs' / 'calculation.md'}")
            return

        # ---- remote ----
        if args.command == "remote":
            from vibedft.core.remote import (
                RemoteRegistry,
                build_remote_plan,
                validate_no_direct_dft_execution,
            )
            if not args.host:
                parser.exit(2, "vibedft: --host is required for remote commands\n")
            remotes = RemoteRegistry.from_project_root(args.root)
            try:
                host = remotes.get(args.host)
            except KeyError as exc:
                parser.exit(2, f"vibedft: {exc}\n")

            if args.remote_command == "plan":
                plan = build_remote_plan(args.case_dir, host, case_id=args.case_id)
                violations = validate_no_direct_dft_execution(plan)
                print(plan.summary())
                if violations:
                    print("\n⚠️  POLICY VIOLATIONS:")
                    for v in violations:
                        print(f"  ❌ {v}")
                print("\n--- Markdown log rows ---")
                print(plan.markdown_log_rows())
                return

            if args.remote_command in ("push", "submit", "status", "pull"):
                cid = getattr(args, "case_id", None) or None
                plan = build_remote_plan(args.case_dir, host, case_id=cid)
                step_map = {
                    "push": 0, "submit": 1, "status": 2, "pull": 3,
                }
                idx = step_map.get(args.remote_command, 0)
                if idx < len(plan.steps):
                    step = plan.steps[idx]
                    if args.remote_command == "push":
                        print(f"# Push inputs to {host.name}")
                        print(f"# Remote: {step['remote_path']}")
                        print(step["command"])
                    elif args.remote_command == "submit":
                        print("# ⚠️  DFT execution MUST go through Slurm. Direct binary execution is FORBIDDEN.")
                        print(step["command"])
                    elif args.remote_command == "status":
                        print(step["command"])
                    elif args.remote_command == "pull":
                        print(f"# Pull results from {host.name}")
                        print("# ⚠️  Pull outputs BEFORE local post-processing.")
                        print(step["command"])
                return

        # ---- archive ----
        if args.command == "archive":
            from vibedft.core.archive import build_archive_plan, apply_archive

            if args.archive_command == "plan":
                plan = build_archive_plan(
                    case_dir=args.case_dir,
                    system=args.system,
                    material=args.material,
                    route=args.route,
                    target_root=args.target_root,
                )
                print(plan.summary())
                return

            if args.archive_command == "apply":
                report = apply_archive(
                    case_dir=args.case_dir,
                    target_root=args.target_root,
                    dry_run=args.dry_run,
                    system=args.system,
                    material=args.material,
                    route=args.route,
                )
                print(report)
                return

        # ---- qa ----
        if args.command == "qa":
            from vibedft.core.qa import qa_inputs, qa_outputs, qa_all

            if args.qa_command == "inputs":
                report = qa_inputs(args.case_dir)
                print(report.summary())
                if report.status == "fail":
                    parser.exit(1)
                return

            if args.qa_command == "outputs":
                report = qa_outputs(args.case_dir)
                print(report.summary())
                if report.status == "fail":
                    parser.exit(1)
                return

            if args.qa_command == "all":
                report = qa_all(args.case_dir)
                print(report.summary())
                if report.status == "fail":
                    parser.exit(1)
                return

        # ---- evidence ----
        if args.command == "evidence":
            from vibedft.research.case_pipeline import (
                batch_evidence_pipeline_payload,
                case_evidence_pipeline_payload,
                run_batch_evidence_pipeline,
                run_case_evidence_pipeline,
            )

            if args.batch_root is not None:
                result = run_batch_evidence_pipeline(args.batch_root)
                payload = batch_evidence_pipeline_payload(result)
                exit_code = 0
                if payload["overall_status"] == "BLOCK":
                    exit_code = 2
            else:
                result = run_case_evidence_pipeline(args.case_dir)
                payload = case_evidence_pipeline_payload(result)
                exit_code = 0
                if payload["overall_status"] == "BLOCK":
                    exit_code = 2

            if args.json:
                import json
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            elif args.batch_root is not None:
                print(f"Evidence batch: {payload['overall_status']}")
                print(f"Batch: {payload['batch_root']}")
                for case in payload["cases"]:
                    case_name = Path(case["case_dir"]).name
                    print(f"- {case_name}: {case['overall_status']}")
                for case in payload["cases"]:
                    case_name = Path(case["case_dir"]).name
                    print()
                    print(f"## Case report: {case_name}")
                    print()
                    print(case["summary_markdown"].rstrip())
            else:
                print(f"Evidence pipeline: {payload['overall_status']}")
                print(f"Case: {payload['case_dir']}")
                for stage in payload["stages"]:
                    print(f"- {stage['stage_id']}: {stage['status']}")
                print()
                print(payload["summary_markdown"].rstrip())
            if exit_code:
                parser.exit(exit_code)
            return

        # ---- goal ----
        if args.command == "goal":
            from pathlib import Path as _Path

            from vibedft.goal_acceptance import run_goal_acceptance

            root = args.root

            def _resolve(project_path: _Path) -> _Path:
                return project_path if project_path.is_absolute() else root / project_path

            payload = run_goal_acceptance(
                project_root=root,
                docs_root=_resolve(_Path(args.docs_root)),
                index_path=_resolve(_Path(args.index)),
                stages_path=_resolve(_Path(args.stages)),
                stage_map_path=_resolve(_Path(args.stage_map)),
                skip_cases=args.skip_cases,
                audit_cases=args.case_audit,
                case_root=_resolve(_Path(args.case_root)),
                case_max=args.case_max,
            )

            if args.json:
                import json
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(f"Goal acceptance: {payload['overall_status']}")
                if payload["blocked_gates"]:
                    print("Blocked gates:")
                    for gate in payload["blocked_gates"]:
                        print(f"  - {gate}")
                else:
                    print("Blocked gates: none")
                if payload["warning_gates"]:
                    print("Warnings:")
                    for gate in payload["warning_gates"]:
                        print(f"  - {gate}")
                if payload["high_warning_gates"]:
                    print("High warnings:")
                    for gate in payload["high_warning_gates"]:
                        print(f"  - {gate}")
                print(
                    "Docs indexed:",
                    payload["docs"]["indexed"],
                    "/",
                    payload["docs"]["total"],
                )
                print(
                    "Stages mapped:",
                    payload["stages"]["mapped_count"],
                    "/",
                    payload["stages"]["canonical_count"],
                )
                if payload["cases"]["layout_summary"] is not None:
                    print(
                        "Case layouts: "
                        f"{payload['cases']['layout_summary'].get('canonical_full', 0)} canonical / "
                        f"{payload['cases']['layout_summary'].get('noncanonical', 0)} custom / "
                        f"{payload['cases']['layout_summary'].get('total_cases', 0)} total"
                    )
                if payload["cases"].get("total_cases", 0):
                    print(f"Case QA audited: {payload['cases']['total_cases']} cases")
                print(f"Goal score: {payload['score']}")

            if payload["overall_status"] in {"BLOCK", "FAIL"}:
                parser.exit(2)
            return

        # ---- validate (stage-level rules) ----
        if args.command == "validate" and args.validate_command == "stage":
            from vibedft.validators.hfcl2_rules import run_hfcl2_stage_rules
            results = run_hfcl2_stage_rules(args.case_dir, stage=args.stage)
            passed = [r for r in results if r.status == "pass"]
            failed = [r for r in results if r.status == "fail"]
            warned = [r for r in results if r.status == "warn"]
            skipped = [r for r in results if r.status == "skip"]
            print(f"Validation Report: {args.case_dir}")
            if args.stage:
                print(f"Stage rules: {args.stage}")
            print(f"Status: {'FAIL' if failed else 'WARN' if warned else 'PASS'}")
            print(f"Checks: {len(passed)} passed, {len(failed)} failed, "
                  f"{len(warned)} warnings, {len(skipped)} skipped")
            for c in results:
                icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "skip": "⏭️"}.get(c.status, "?")
                stage_tag = f" [{c.stage}]" if c.stage else ""
                print(f"  {icon} [{c.id}]{stage_tag} {c.message}")
                if c.path:
                    print(f"       file: {c.path}")
                if c.detail:
                    for line in c.detail.strip().split("\n"):
                        print(f"       {line}")
            if failed:
                parser.exit(1)
            return

        # ---- audit ----
        if args.command == "audit" and args.audit_command == "runtime":
            from vibedft.core.env_audit import run_environment_audit
            report = run_environment_audit(
                case_dir=args.case_dir,
                qe_bin=args.qe_bin,
                pseudo_dir=args.pseudo_dir,
                slurm_partition=args.partition,
            )
            if args.json:
                import json
                print(json.dumps(report.to_dict(), indent=2))
            else:
                print(f"\nEnvironment Audit Report — {report.hostname}")
                print(f"  Passed: {len(report.passed)}  "
                      f"Warnings: {len(report.warnings)}  "
                      f"Failures: {len(report.failures)}  "
                      f"Critical: {len(report.critical)}\n")
                for item in report.items:
                    icon = {"pass": "✅", "warn": "⚠️", "fail": "❌", "skip": "⏭️"}.get(item.status, "?")
                    cat = f"[{item.category}]"
                    print(f"  {icon} {cat:20s} {item.check}")
                    if item.detail:
                        print(f"       {item.detail}")
                print()
                if report.failures:
                    print("⚠️  Environment has failures — jobs may not run correctly.")
                elif report.warnings:
                    print("⚡ Environment has warnings — performance may be suboptimal.")
                else:
                    print("✅ Environment audit passed — ready for QE calculations.")
            return

        # ---- inspect ----
        if args.command == "inspect":
            from vibedft.classifiers.task_classifier import inspect_files
            result = inspect_files(args.files)
            if args.json:
                print(result.to_json())
            else:
                _print_inspect_summary(result)
            return

        # ---- review ----
        if args.command == "review":
            from vibedft.core.review import review_case
            result = review_case(args.case_dir)
            if args.json:
                print(result.to_json())
            else:
                _print_review_summary(result)
            return

        # ---- property ----
        if args.command == "property" and args.property_command == "analyze":
            from vibedft.properties.base import analyze_all_properties
            bundle = analyze_all_properties(args.case_dir)
            if args.json:
                import json as _json
                print(_json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False, default=str))
            else:
                _print_property_summary(bundle)
            return

        # ---- decide ----
        if args.command == "decide":
            from vibedft.decision.publication_gate import decide
            from vibedft.core.review import review_case
            from vibedft.analyzers.orchestrator import run_physics_analysis
            review = review_case(args.case_dir)
            physics = run_physics_analysis(args.case_dir, review_result=review)
            result = decide(args.case_dir, review_result=review, physics_report=physics)
            if args.json:
                import json as _json
                print(_json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str))
            else:
                _print_decision(result)
            return

        # ---- log ----
        if args.command == "log" and args.log_command == "collect":
            from vibedft.core.log_collector import collect_log
            md = collect_log(args.case_dir, output=args.out)
            if not args.out:
                print(md)
            else:
                print(f"Wrote {args.out}")
            return

        # ---- semantics ----
        if args.command == "semantics" and args.semantics_command == "analyze":
            from vibedft.semantics.orchestrator import analyze_semantics
            result = analyze_semantics(args.case_dir)
            if args.json:
                import json as _json
                print(_json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str))
            else:
                print(result.narrative)
            return

        # ---- convergence ----
        if args.command == "convergence":
            from vibedft.core.batch_review import run_convergence_analysis
            report, artifacts = run_convergence_analysis(
                args.root, title=args.title,
                output=args.html,
            )
            if args.json:
                import json as _json
                print(_json.dumps({
                    "root": report.root_dir,
                    "n_cases": len(report.rows),
                    "varying_params": report.varying_params,
                    "converged": report.converged_params,
                    "unconverged": report.unconverged_params,
                    "overall_confidence": report.overall_confidence,
                    "warnings": report.warnings,
                    "rows": [
                        {
                            "case": r.case_name,
                            "k_grid": r.k_grid,
                            "q_grid": r.q_grid,
                            "lambda_max": r.lambda_max,
                            "tc_max_K": r.tc_max_K,
                            "omega_log_K": r.omega_log_K,
                            "confidence": r.confidence,
                        }
                        for r in report.rows
                    ],
                }, indent=2, ensure_ascii=False, default=str))
            else:
                _print_convergence_summary(report)
            return

        # ---- runbook ----
        if args.command == "runbook" and args.runbook_command == "slurm":
            print(SLURM_RUNBOOK)
            return

        # ---- report ----
        if args.command == "report":
            from vibedft.core.report import build_report, render_report_html

            if args.report_command == "generate":
                from vibedft.core.report_builder import build_static_report
                out = args.output or (args.case_dir / "report.html")
                if args.json:
                    from vibedft.core.review import review_case
                    from vibedft.postprocess.dispatcher import dispatch_postprocess
                    review = review_case(args.case_dir)
                    artifacts = dispatch_postprocess(args.case_dir, review_result=review)
                    import json
                    print(json.dumps({
                        "review": review.to_dict(),
                        "artifacts": [a.to_dict() for a in artifacts],
                    }, indent=2, ensure_ascii=False, default=str))
                else:
                    build_static_report(args.case_dir, title=args.title, output=out)
                    print(f"Built {out}")
                return

            if args.report_command == "html":
                payload = build_report(
                    case_dir=args.case_dir, title=args.title,
                    case_id=args.case_id, material=args.material,
                    compare_dirs=args.compare_dir,
                )
                out = args.output or (args.case_dir / "report.html")
                render_report_html(payload, out)
                print(f"Built {out}")
                return

            if args.report_command == "build":
                payload = build_report(
                    case_dir=args.case_dir, title=args.title,
                    case_id=args.case_id, material=args.material,
                    compare_dirs=args.compare_dir,
                )
                if args.json:
                    print(payload.to_json())
                elif args.html:
                    out = args.output or (args.case_dir / "report.html")
                    render_report_html(payload, out)
                    print(f"Built {out}")
                else:
                    print(f"Report: {payload.title}")
                    print(f"Case:   {payload.case_id}")
                    print(f"Generated: {payload.generated_at}")
                    print(f"Sections: {len(payload.sections)}")
                    for s in payload.sections:
                        icon = {"pass": "✅", "warn": "⚠️", "fail": "❌", "missing": "⏭️"}.get(s.status, "?")
                        print(f"  {icon} {s.section_id:20s} {s.title:30s} ({len(s.insights)} insights)")
                    if args.output:
                        args.output.write_text(payload.to_json(), encoding="utf-8")
                        print(f"Wrote {args.output}")
                    elif not args.json and not args.html:
                        out = args.case_dir / "report.json"
                        out.write_text(payload.to_json(), encoding="utf-8")
                        print(f"Wrote {out}")
                return

        # ---- plan ----
        if args.command == "plan" and args.plan_command == "superconductivity":
            from vibedft.generators.manifest import CLUSTER_DEBUG, CLUSTER_PROD
            from vibedft.generators.workflow_planner import plan_superconductivity
            from vibedft.core.workflow_executor import execute_plan

            profile_map = {"cluster_debug": CLUSTER_DEBUG, "cluster_prod": CLUSTER_PROD}
            profile = profile_map[args.profile]

            plan = plan_superconductivity(
                structure_file=args.structure,
                engine=args.engine,
                profile=profile,
                output_root=args.out,
                material_prefix=args.prefix,
                ecutwfc=args.ecutwfc,
                ecutrho=args.ecutrho,
                tot_charge=args.tot_charge,
            )

            if args.dry_run:
                print(f"Plan: {plan.plan_id}")
                print(f"Output: {plan.output_root}")
                print(f"Stages: {len(plan.stages)}")
                for s in plan.stages:
                    deps = f" (after {', '.join(s.depends_on)})" if s.depends_on else ""
                    print(f"  {s.id:30s} {s.kind.value:15s} {s.cores:3d} cores {s.walltime}{deps}")
            else:
                root = execute_plan(plan)
                print(f"Created {root}")
                print(f"  {len(plan.stages)} stages written")
                print(f"  submit_all.sh ready")
                print(f"  Run: vibedft review --case-dir {root}")
            return

        # ---- server ----
        if args.command == "server":
            try:
                import uvicorn
                from vibedft.server.app import create_app
            except ImportError:
                parser.exit(2, "vibedft: uvicorn and fastapi required for server mode.\n"
                              "Install with: pip install uvicorn fastapi python-multipart\n")
            app = create_app(with_frontend=args.with_frontend)
            print(f"VibeDFT API server starting on http://{args.host}:{args.port}")
            print(f"Docs: http://{args.host}:{args.port}/docs")
            if args.with_frontend:
                print(f"Workbench: http://{args.host}:{args.port}/")
            uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
            return

        # ---- html ----
        if args.command == "html" and args.html_command == "build":
            output = build_workbench(
                args.output,
                cases_dir=str(args.cases_dir) if args.cases_dir else None,
                bands_file=args.bands,
                dos_file=args.dos,
                scf_output=args.scf_output,
                title=args.title,
            )
            print(f"Built {output}")
            return

    except RegistryError as exc:
        parser.exit(2, f"vibedft: {exc}\n")


def _print_inspect_summary(result) -> None:
    """Print a human-readable inspection summary."""
    from vibedft.models.inspection import Severity

    icon = {Severity.ERROR: "❌", Severity.WARNING: "⚠️", Severity.INFO: "ℹ️"}

    print("=" * 60)
    print("VibeDFT Inspection Report")
    print("=" * 60)
    print()
    print("── Files ──")
    for f in result.files:
        status_icon = {"ok": "✅", "partial": "⚠️", "failed": "❌", "pending": "⏳"}.get(f.parse_status, "?")
        print(f"  {status_icon} {f.path}")
        print(f"     type={f.type}  program={f.program.value}  parse={f.parse_status}")
        if f.summary:
            print(f"     {f.summary}")
        if f.parse_errors:
            for e in f.parse_errors[:3]:
                print(f"     ❌ {e}")

    print()
    print("── Tasks ──")
    for t in result.tasks:
        conf_bar = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(t.confidence, "⚪")
        print(f"  {conf_bar} {t.program.value} → {t.task_type.value}")
        if t.source_file:
            print(f"     file: {t.source_file}")
        if t.key_params:
            params_str = ", ".join(f"{k}={v}" for k, v in list(t.key_params.items())[:8])
            print(f"     params: {params_str}")

    print()
    print("── Issues ──")
    if result.issues:
        for iss in result.issues:
            ic = icon.get(iss.severity, "?")
            print(f"  {ic} [{iss.id}] {iss.message}")
            if iss.detail:
                print(f"       {iss.detail}")
    else:
        print("  ✅ No issues found")

    print()
    print(f"Summary: {len(result.files)} files, {len(result.tasks)} tasks, "
          f"{len([i for i in result.issues if i.severity == Severity.ERROR])} errors, "
          f"{len([i for i in result.issues if i.severity == Severity.WARNING])} warnings")


def _print_review_summary(result) -> None:
    """Print a human-readable case-directory review."""
    from vibedft.models.inspection import Severity

    icon = {Severity.ERROR: "❌", Severity.WARNING: "⚠️", Severity.INFO: "ℹ️"}

    print("=" * 70)
    print(f"VibeDFT Case Review: {result.case_dir}")
    print("=" * 70)
    print()
    print(f"Files: {result.files_scanned} scanned, {result.files_inspected} inspected")
    print()

    # ── Tasks ──
    print("── Identified Tasks ──")
    for t in result.inspection.tasks:
        print(f"  • {t.program.value} → {t.task_type.value}  ({t.source_file})")
    if not result.inspection.tasks:
        print("  (none)")

    # ── Workflow ──
    print()
    print("── Workflow Match ──")
    if result.best_match:
        bm = result.best_match
        pct = f"{bm.completeness:.0%}"
        print(f"  Best match: {bm.workflow.label} ({bm.workflow.workflow_id})")
        print(f"  Completeness: {pct}")
        if bm.missing_steps:
            print(f"  Missing steps:")
            for ms in bm.missing_steps:
                print(f"    ⬜ {ms.label} — {ms.description}")
        else:
            print(f"  ✅ All steps present")
    else:
        print("  No workflow matched")
    print(f"  Next step: {result.next_step}")

    # ── Issues ──
    print()
    print(f"── Issues ({result.n_errors} errors, {result.n_warnings} warnings) ──")
    all_issues = result.all_issues
    if all_issues:
        errors = [i for i in all_issues if i.severity == Severity.ERROR]
        warnings = [i for i in all_issues if i.severity == Severity.WARNING]
        infos = [i for i in all_issues if i.severity == Severity.INFO]

        for label, group in [("ERRORS", errors), ("WARNINGS", warnings), ("INFO", infos)]:
            if group:
                print(f"  [{label}]")
                for iss in group[:20]:
                    ic = icon.get(iss.severity, "?")
                    src = iss.source_file or ""
                    if src and len(src) > 50:
                        src = "..." + src[-47:]
                    print(f"    {ic} [{iss.id}] {iss.message}")
                    if src:
                        print(f"       file: {src}")
                    if iss.detail:
                        print(f"       {iss.detail}")
                if len(group) > 20:
                    print(f"    ... and {len(group) - 20} more")
    else:
        print("  ✅ No issues found")

    print()
    print(f"Summary: {result.summary}")


def _print_convergence_summary(report) -> None:
    """Print a human-readable convergence summary."""
    conf_color = {"high": "🟢", "medium": "🟡", "low": "🔴"}

    print("=" * 70)
    print(f"VibeDFT Convergence Report")
    print(f"Root: {report.root_dir}")
    print(f"Cases: {len(report.rows)}")
    print("=" * 70)

    if report.varying_params:
        print(f"Varying: {', '.join(report.varying_params)}")
    print(f"Confidence: {conf_color.get(report.overall_confidence, '?')} {report.overall_confidence.upper()}")
    print()

    if report.rows:
        header = f"{'Case':30s} {'k-grid':12s} {'q-grid':12s} {'λ':8s} {'Tc(K)':8s} {'ωlog(K)':8s} {'DOS@EF':8s} Conf"
        print(header)
        print("-" * len(header))
        for r in report.rows:
            ci = conf_color.get(r.confidence, "⚪")
            print(f"{r.case_name:30s} {r.k_grid:12s} {r.q_grid:12s} "
                  f"{r.lambda_max or '—':>8} {r.tc_max_K or '—':>8} "
                  f"{r.omega_log_K or '—':>8} {r.dos_at_ef or '—':>8} "
                  f"  {ci} {r.confidence}")
        print()

    print(f"Converged: {', '.join(report.converged_params) if report.converged_params else 'none'}")
    print(f"Not converged: {', '.join(report.unconverged_params) if report.unconverged_params else 'none'}")

    if report.warnings:
        print()
        for w in report.warnings:
            print(f"  ⚠ {w}")


def _print_property_summary(bundle) -> None:
    """Print a human-readable property analysis summary."""
    icons = {"ok": "✅", "missing": "⏭️", "error": "❌"}
    print("=" * 50)
    print("VibeDFT Property Analysis")
    print(f"Case: {bundle.case_dir}")
    print("=" * 50)
    for name, pr in bundle.properties.items():
        icon = icons.get(pr.status, "?")
        print(f"\n{icon} {name}")
        for ins in pr.insights:
            print(f"   {ins}")
        if pr.errors:
            for e in pr.errors:
                print(f"   ❌ {e}")


def _print_decision(result) -> None:
    """Print a human-readable decision summary."""
    gate_icon = {
        "BLOCKED": "🔴", "NEEDS_CONVERGENCE": "🟡",
        "PROMISING": "🟢", "READY_FOR_FIGURES": "✅",
    }
    icon = gate_icon.get(result.gate.value, "?")
    print("=" * 60)
    print(f"{icon}  Decision: {result.gate.value}")
    print(f"    Case: {result.case_dir}")
    print("=" * 60)
    if result.primary_blocker:
        print(f"\n  Primary: {result.primary_blocker[:120]}")
    if result.secondary_blockers:
        for b in result.secondary_blockers[:5]:
            print(f"  · {b[:120]}")
    if result.positives:
        print(f"\n  ✅ Positives:")
        for p in result.positives[:5]:
            print(f"     {str(p)[:100]}")
    if result.next_actions:
        print(f"\n  📋 Next Actions:")
        for i, a in enumerate(result.next_actions, 1):
            print(f"     {i}. {a[:120]}")


def _print_relax_compare_summary(payload) -> None:
    """Print a compact CLI summary for relax-vs-relax comparison."""
    print("=" * 72)
    print("VibeDFT Relax Comparison")
    print("=" * 72)

    if not payload.runs:
        print("No runs to compare.")
        return

    print(f"Runs: {len(payload.runs)}")
    print(f"Best run: {payload.best_source} (gap={payload.best_energy_gap_ry!s} Ry)")

    if payload.status_counts:
        status_bits = ", ".join(f"{key}={value}" for key, value in payload.status_counts.items())
        print(f"Status counts: {status_bits}")

    print()
    for run in payload.runs:
        energy = run.final_energy_ry
        energy_str = "N/A" if energy is None else f"{energy:.6f}"
        max_force = "N/A" if run.last_max_force is None else f"{run.last_max_force:.3e}"
        delta = (
            "N/A"
            if run.delta_to_best_energy_ry is None
            else f"{run.delta_to_best_energy_ry:.6f}"
        )
        print(
            f"{run.rank:>2d}. {run.source:24s}  "
            f"status={run.status:10s}  "
            f"energy={energy_str:>14s} Ry  "
            f"ΔE={delta:>12s}  "
            f"maxF={max_force:>10s}  "
            f"risk={run.risk_level}"
        )


# Keep the legacy entry-point import for backwards compat

import sys


def entry_point() -> None:
    """Console script entry point."""
    sys.exit(main())
