"""Post-process dispatcher: ReviewResult → Artifact list.

Maps detected tasks and output files to artifact generators.
Each generator checks for required files; returns None if data is missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibedft.core.analysis import parse_qe_output, parse_dos_output
from vibedft.models.inspection import TaskType
from vibedft.postprocess.artifacts import Artifact
from vibedft.postprocess.band_plot import generate_band_plot
from vibedft.postprocess.dos_plot import generate_dos_plot
from vibedft.postprocess.phonon_plot import generate_phonon_plot
from vibedft.postprocess.a2f_plot import generate_epc_plot, generate_tc_table


# ═══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════════


def dispatch_postprocess(
    case_dir: Path | str,
    review_result: Any | None = None,
) -> list[Artifact]:
    """Run all applicable postprocess generators for a case directory.

    *review_result* is optional; if provided, uses its detected tasks to
    guide generator selection.  Otherwise, generators probe the filesystem
    directly.

    Returns a flat list of Artifacts (may be empty if no data is found).
    """
    d = Path(case_dir).resolve()
    artifacts: list[Artifact] = []

    # ── Determine Fermi energy from SCF output ──
    ef = _resolve_fermi_energy(d)

    # ── Determine which generators to run ──
    task_types: set[TaskType] = set()
    if review_result is not None:
        for task in review_result.inspection.tasks:
            task_types.add(task.task_type)

    # ── SCF overview (always if SCF output exists) ──
    scf_out = _find_scf_output(d)
    if scf_out:
        art = _scf_overview_table(d, scf_out)
        if art:
            artifacts.append(art)

    # ── Bands ──
    bands_files = sorted(d.rglob("*bands*"))
    if bands_files and any(f.suffix not in (".out",) and "GA" not in f.name.upper()
                          for f in bands_files):
        art = generate_band_plot(d, e_fermi_ev=ef)
        if art:
            artifacts.append(art)

    # ── DOS / PDOS ──
    dos_files = sorted((d / "output").rglob("*.dos")) if (d / "output").is_dir() else []
    if dos_files:
        art = generate_dos_plot(d, e_fermi_ev=ef)
        if art:
            artifacts.append(art)

    # ── Phonon ──
    if TaskType.PH_STABILITY in task_types or TaskType.PH_EPC in task_types or \
       TaskType.Q2R in task_types or TaskType.MATDYN_DISP in task_types:
        art = generate_phonon_plot(d)
        if art:
            artifacts.append(art)

    # ── EPC / Tc ──
    if TaskType.PH_EPC in task_types or TaskType.LAMBDA_TC in task_types:
        art_epc = generate_epc_plot(d)
        if art_epc:
            artifacts.append(art_epc)
        art_tc = generate_tc_table(d)
        if art_tc:
            artifacts.append(art_tc)

    # ── Workflow summary table (from review) ──
    if review_result is not None and review_result.workflow_matches:
        art = _workflow_summary_table(review_result)
        if art:
            artifacts.append(art)

    # ── Issues table (from review) ──
    if review_result is not None and review_result.all_issues:
        art = _issues_table(review_result)
        if art:
            artifacts.append(art)

    return artifacts


# ═══════════════════════════════════════════════════════════════════════════════
# Helper generators
# ═══════════════════════════════════════════════════════════════════════════════


def _find_scf_output(case_dir: Path) -> Path | None:
    """Find the SCF output file (prefer output/scf.out)."""
    out = case_dir / "output"
    if (out / "scf.out").is_file():
        return out / "scf.out"
    scf_files = sorted(out.rglob("scf.out")) if out.is_dir() else []
    return scf_files[0] if scf_files else None


def _resolve_fermi_energy(case_dir: Path) -> float:
    """Extract Fermi energy from SCF output."""
    scf = _find_scf_output(case_dir)
    if scf:
        try:
            qe = parse_qe_output(scf)
            if qe.fermi_energy_ev is not None:
                return qe.fermi_energy_ev
        except Exception:
            pass
    # Try DOS
    out = case_dir / "output"
    dos_files = sorted(out.rglob("*.dos")) if out.is_dir() else []
    if dos_files:
        try:
            dos = parse_dos_output(dos_files[0])
            if dos.e_fermi_ev is not None:
                return dos.e_fermi_ev
        except Exception:
            pass
    return 0.0


def _scf_overview_table(case_dir: Path, scf_out: Path) -> Artifact | None:
    """Extract SCF summary as a table artifact."""
    try:
        qe = parse_qe_output(scf_out)
    except Exception:
        return None

    d = case_dir
    rows = [
        ["Program", f"{qe.program} v{qe.version}"],
        ["Total Energy (Ry)", f"{qe.total_energy_ry:.6f}" if qe.total_energy_ry else "N/A"],
        ["Total Energy (eV)", f"{qe.total_energy_ev:.4f}" if qe.total_energy_ev else "N/A"],
        ["Fermi Energy (eV)", f"{qe.fermi_energy_ev:.4f}" if qe.fermi_energy_ev else "N/A"],
        ["SCF Converged", "Yes" if qe.scf_converged else "NO"],
        ["SCF Iterations", str(qe.scf_iterations)],
        ["Wall Time (s)", f"{qe.wall_time_sec:.1f}" if qe.wall_time_sec else "N/A"],
    ]
    src = str(scf_out.relative_to(d)) if scf_out.is_relative_to(d) else str(scf_out)

    return Artifact.table(
        id="scf_overview", title="SCF Summary",
        headers=["Property", "Value"],
        rows=rows,
        source_files=[src],
        provenance={"parser": "parse_qe_output"},
    )


def _workflow_summary_table(review_result: Any) -> Artifact | None:
    """Build a workflow completeness table from review result."""
    if not review_result.workflow_matches:
        return None

    rows: list[list[str]] = []
    for m in review_result.workflow_matches[:5]:
        pct = f"{m.completeness:.0%}"
        missing = ", ".join(s.label for s in m.missing_steps) if m.missing_steps else "None"
        rows.append([m.workflow.workflow_id, m.workflow.label, pct, missing])

    return Artifact.table(
        id="workflow_matches", title="Workflow Completeness",
        headers=["Workflow ID", "Label", "Complete", "Missing Steps"],
        rows=rows,
        provenance={"source": "workflow_matcher"},
        caption="Top-5 workflow matches ranked by completeness.",
    )


def _issues_table(review_result: Any) -> Artifact | None:
    """Build an issues summary table from review result."""
    all_issues = review_result.all_issues
    if not all_issues:
        return None

    rows: list[list[str]] = []
    for iss in all_issues[:50]:
        rows.append([
            iss.severity.value.upper(),
            iss.id,
            iss.message[:120],
            iss.source_file or "",
        ])

    return Artifact.table(
        id="issues", title="Issues Found",
        headers=["Severity", "Check ID", "Message", "Source"],
        rows=rows,
        provenance={"source": "validators"},
        caption=f"{len(all_issues)} issues found during inspection and validation.",
    )
