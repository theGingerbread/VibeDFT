"""DFT-grade quality assurance for VibeDFT cases.

Checks are organised into three stages:
  Stage 1 — input QA: before transfer to remote (placeholder, prefix, la2F, etc.)
  Stage 2 — output QA: after pull-back (JOB DONE, convergence, NaN, file sizes)
  Stage 3 — archive QA: before final archive (light-file policy, provenance)

Discovery supports multi-stage directories:
  - case/input/     (legacy single-input)
  - case/inputs/    (alternative single-input)
  - case/*/inputs/  (stage-structured: 06_scf/inputs/, 08_dos/inputs/, …)
  - case/*/*/inputs/ (nested: HfCl2-K-screening/K_1/08_dos/inputs/)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Check result model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    """Single QA check result."""

    id: str
    status: str  # pass | fail | warn | skip
    message: str
    path: str | None = None
    detail: str | None = None
    stage: str | None = None


@dataclass
class QaReport:
    """Aggregated QA report for a case directory."""

    case_dir: Path
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == "pass"]

    @property
    def failed(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == "fail"]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == "warn"]

    @property
    def status(self) -> str:
        if any(c.status == "fail" for c in self.checks):
            return "fail"
        if any(c.status == "warn" for c in self.checks):
            return "warn"
        return "pass"

    def summary(self) -> str:
        lines = [
            f"QA Report: {self.case_dir}",
            f"Status: {self.status.upper()}",
            f"Checks: {len(self.passed)} passed, {len(self.failed)} failed, {len(self.warnings)} warnings",
        ]
        for c in self.checks:
            icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "skip": "⏭️"}.get(c.status, "?")
            stage_tag = f" [{c.stage}]" if c.stage else ""
            lines.append(f"  {icon} [{c.id}]{stage_tag} {c.message}")
            if c.path:
                lines.append(f"       file: {c.path}")
            if c.detail:
                lines.append(f"       {c.detail}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Multi-stage input discovery
# ---------------------------------------------------------------------------


@dataclass
class StageInput:
    """One discovered input file with stage context."""

    path: Path
    stage: str       # e.g. "06_scf", "08_dos", "input" (legacy)
    program: str = ""  # detected QE program tag


# Programs recognised from common filenames / namelist presence
_KNOWN_PROGRAMS: dict[str, str] = {
    "pw.x": "pw.x",
    "ph.x": "ph.x",
    "q2r.x": "q2r.x",
    "q2rx": "q2r.x",
    "matdyn.x": "matdyn.x",
    "matdynx": "matdyn.x",
    "lambda.x": "lambda.x",
    "lambdax": "lambda.x",
    "dos.x": "dos.x",
    "projwfc.x": "projwfc.x",
    "bands.x": "bands.x",
}

# Files where la2F is forbidden. EPC-oriented matdyn DOS inputs may legitimately
# use la2F; q2r and ordinary line-dispersion matdyn inputs must not.
_FORBIDDEN_LA2F_KEYWORDS = ["q2r", "matdynline"]


def _detect_program(path: Path) -> str:
    """Heuristic program detection from content + filename."""
    # First — try filename patterns
    if "pw" in path.stem.lower():
        return "pw.x"
    if "phx" in path.stem.lower() or "ph_" in path.stem.lower():
        return "ph.x"
    if "q2r" in path.stem.lower():
        return "q2r.x"
    if "matdyn" in path.stem.lower():
        return "matdyn.x"
    if "lambda" in path.stem.lower():
        return "lambda.x"
    if "dos" in path.stem.lower() or "projwfc" in path.stem.lower():
        return path.stem  # keep the program tag for projwfc/dos
    # Second — try namelist detection from first few lines
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:2000]
        if "&INPUTPH" in text:
            return "ph.x"
        if "&PROJWFC" in text:
            return "projwfc.x"
        if "&DOS" in text:
            return "dos.x"
        if "&BANDS" in text:
            return "bands.x"
        if "&CONTROL" in text or "&SYSTEM" in text:
            return "pw.x"
        if "&ELECTRONS" in text:    # also catches pw.x with only &ELECTRONS
            return "pw.x"
        if "&INPUT" in text:
            # q2r usually has fildyn, matdyn has flfrq, lambda has emax/mustar
            if "fildyn" in text:
                return "q2r.x"
            if "flfrq" in text or "flfrc" in text:
                return "matdyn.x"
            if "emax" in text or "mustar" in text:
                return "lambda.x"
    except OSError:
        pass
    return "unknown"


def discover_input_files(case_dir: Path | str) -> list[StageInput]:
    """Discover all QE input files across stage-structured directories.

    Searches in order of specificity:
      1. case/input/
      2. case/inputs/
      3. case/*/inputs/
      4. case/*/*/inputs/

    Returns a flat list of StageInput records.
    """
    d = Path(case_dir)
    if not d.is_dir():
        return []
    found: list[StageInput] = []

    # Helper: add inputs from a given directory, tagging with stage
    def _add_from(dir_path: Path, stage: str) -> None:
        if not dir_path.is_dir():
            return
        for f in sorted(dir_path.rglob("*.in")):
            prog = _detect_program(f)
            found.append(StageInput(path=f, stage=stage, program=prog))

    # Single-input search roots
    _add_from(d / "input", "input")
    _add_from(d / "inputs", "inputs")

    # Multi-stage search roots (exact two-level pattern)
    seen_stage_dirs: set[Path] = set()
    for sub in sorted(d.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        inputs_dir = sub / "inputs"
        if inputs_dir.is_dir() and inputs_dir not in seen_stage_dirs:
            seen_stage_dirs.add(inputs_dir)
            _add_from(inputs_dir, sub.name)

    # Nested case/insertion (e.g. HfCl2-K-screening/K_1/06_scf/inputs/)
    for sub in sorted(d.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        for sub2 in sorted(sub.iterdir()):
            if not sub2.is_dir() or sub2.name.startswith("."):
                continue
            inputs_dir = sub2 / "inputs"
            if inputs_dir.is_dir() and inputs_dir not in seen_stage_dirs:
                seen_stage_dirs.add(inputs_dir)
                # Tag with the deeper stage name
                _add_from(inputs_dir, f"{sub.name}/{sub2.name}/{inputs_dir.parent.name}")

    return found


# ---------------------------------------------------------------------------
# Stage 1: Input QA
# ---------------------------------------------------------------------------


def qa_inputs(case_dir: Path | str) -> QaReport:
    """Run all input-stage QA checks on a case directory.

    Discovers input files across multi-stage ``*/inputs/`` directories.
    """
    d = Path(case_dir)
    report = QaReport(case_dir=d)

    inputs = discover_input_files(d)
    _check_input_files_exist(inputs, report)
    _check_prefix_consistency(inputs, report)
    _check_outdir_consistency(inputs, report)
    _check_forbidden_la2f(inputs, report)
    _check_unresolved_placeholders(inputs, report)
    _check_stage_programs(inputs, report)

    return report


def _check_input_files_exist(inputs: list[StageInput], report: QaReport) -> None:
    """Report discovered input files."""
    if not inputs:
        report.checks.append(
            CheckResult(
                "input.files.exist", "fail",
                "No QE input files found in input/, inputs/, */inputs/, or */*/inputs/",
                path=str(report.case_dir),
            )
        )
        return

    # Group by stage
    stages: dict[str, list[str]] = {}
    for si in inputs:
        stages.setdefault(si.stage, []).append(si.path.name)

    detail_lines = []
    for stage in sorted(stages):
        detail_lines.append(f"  {stage}: {', '.join(sorted(stages[stage]))}")
    detail = "\n" + "\n".join(detail_lines)

    report.checks.append(
        CheckResult(
            "input.files.exist", "pass",
            f"Found {len(inputs)} input files across {len(stages)} stage(s)",
            detail=detail,
        )
    )


def _check_prefix_consistency(inputs: list[StageInput], report: QaReport) -> None:
    """All input files in the same stage should use the same prefix."""
    if not inputs:
        return

    # Group by stage
    by_stage: dict[str, list[StageInput]] = {}
    for si in inputs:
        by_stage.setdefault(si.stage, []).append(si)

    for stage, stage_inputs in by_stage.items():
        prefixes: dict[str, list[str]] = {}
        for si in stage_inputs:
            text = si.path.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"prefix\s*=\s*'([^']+)'", text)
            if not m:
                m = re.search(r'prefix\s*=\s*"([^"]+)"', text)
            if m:
                prefix = m.group(1)
                prefixes.setdefault(prefix, []).append(si.path.name)

        if len(prefixes) == 0:
            report.checks.append(
                CheckResult(
                    "input.prefix.consistency", "skip",
                    f"No prefix found in stage [{stage}]",
                    stage=stage,
                )
            )
        elif len(prefixes) == 1:
            pfx = list(prefixes.keys())[0]
            report.checks.append(
                CheckResult(
                    "input.prefix.consistency", "pass",
                    f"Stage [{stage}] uses prefix='{pfx}'",
                    stage=stage,
                )
            )
        else:
            detail = "; ".join(f"'{p}': {', '.join(fs)}" for p, fs in prefixes.items())
            report.checks.append(
                CheckResult(
                    "input.prefix.consistency", "fail",
                    f"Stage [{stage}]: prefix mismatch ({len(prefixes)} variants)",
                    detail=detail,
                    stage=stage,
                )
            )


def _check_outdir_consistency(inputs: list[StageInput], report: QaReport) -> None:
    """Input files in the same stage should point to a consistent outdir."""
    if not inputs:
        return

    by_stage: dict[str, list[StageInput]] = {}
    for si in inputs:
        by_stage.setdefault(si.stage, []).append(si)

    for stage, stage_inputs in by_stage.items():
        outdirs: dict[str, list[str]] = {}
        for si in stage_inputs:
            text = si.path.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"outdir\s*=\s*'([^']+)'", text)
            if not m:
                m = re.search(r'outdir\s*=\s*"([^"]+)"', text)
            if m:
                od = m.group(1)
                outdirs.setdefault(od, []).append(si.path.name)

        if len(outdirs) <= 1:
            report.checks.append(
                CheckResult(
                    "input.outdir.consistency", "pass",
                    f"Stage [{stage}]: outdir consistent",
                    stage=stage,
                )
            )
        else:
            detail = "; ".join(f"'{od}': {', '.join(fs)}" for od, fs in outdirs.items())
            report.checks.append(
                CheckResult(
                    "input.outdir.consistency", "fail",
                    f"Stage [{stage}]: outdir mismatch ({len(outdirs)} variants)",
                    detail=detail,
                    stage=stage,
                )
            )


def _check_forbidden_la2f(inputs: list[StageInput], report: QaReport) -> None:
    """Ensure la2F=.true. is not present in q2r or ordinary matdyn inputs."""
    if not inputs:
        return

    violations: list[StageInput] = []
    for si in inputs:
        text = si.path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"la2[fF]\s*=\s*\.?\s*true", text, re.IGNORECASE):
            for kw in _FORBIDDEN_LA2F_KEYWORDS:
                if kw in si.path.name.lower():
                    violations.append(si)
                    break

    if violations:
        detail_lines = [f"  [{v.stage}] {v.path.name}" for v in violations]
        detail = "\n" + "\n".join(detail_lines)
        report.checks.append(
            CheckResult(
                "input.ph.no_la2f", "fail",
                f"la2F=.true. found in {len(violations)} forbidden files "
                "(q2r or ordinary matdyn line input). "
                "la2F belongs in EPC-related matdyn.x only, never q2r.x.",
                detail=detail,
            )
        )
    else:
        report.checks.append(
            CheckResult("input.ph.no_la2f", "pass", "No forbidden la2F in q2r or ordinary matdyn line inputs")
        )


def _check_unresolved_placeholders(inputs: list[StageInput], report: QaReport) -> None:
    """Check no Jinja2 placeholders remain in rendered inputs."""
    if not inputs:
        return

    violations: list[tuple[StageInput, list[str]]] = []
    for si in inputs:
        text = si.path.read_text(encoding="utf-8", errors="replace")
        unresolved = re.findall(r'\{\{[^}]+\}\}', text) + re.findall(r'\{%[^}]+\%\}', text)
        if unresolved:
            violations.append((si, unresolved))

    if violations:
        detail_lines = []
        for si, ul in violations:
            detail_lines.append(f"  [{si.stage}] {si.path.name}: {', '.join(ul[:3])}")
        report.checks.append(
            CheckResult(
                "input.placeholders.resolved", "fail",
                f"Unresolved Jinja2 placeholders in {len(violations)} files",
                detail="\n" + "\n".join(detail_lines),
            )
        )
    else:
        report.checks.append(
            CheckResult("input.placeholders.resolved", "pass", "All placeholders resolved")
        )


def _check_stage_programs(inputs: list[StageInput], report: QaReport) -> None:
    """Report program detection per discovered input file."""
    if not inputs:
        return

    # Flag unknown programs — but only if the file has namelist structure
    # that suggests a real input (not a test snippet).
    unknowns = [si for si in inputs if si.program == "unknown"]
    suspicious = []
    for si in unknowns:
        text = si.path.read_text(encoding="utf-8", errors="replace")[:500]
        # Only flag if it has a namelist header (&...) that wasn't recognized
        if re.search(r"^&\w+", text, re.MULTILINE):
            suspicious.append(si)
    if suspicious:
        detail_lines = [f"  [{v.stage}] {v.path.name}" for v in suspicious]
        report.checks.append(
            CheckResult(
                "input.program.detection", "warn",
                f"Program not recognized for {len(suspicious)} file(s) with namelist structure",
                detail="\n" + "\n".join(detail_lines),
            )
        )
    else:
        report.checks.append(
            CheckResult("input.program.detection", "pass", "All input files identified by program")
        )


# ---------------------------------------------------------------------------
# Stage 2: Output QA
# ---------------------------------------------------------------------------


def qa_outputs(case_dir: Path | str) -> QaReport:
    """Run all output-stage QA checks on a case directory."""
    d = Path(case_dir)
    report = QaReport(case_dir=d)

    _check_job_done(d, report)
    _check_scf_convergence(d, report)
    _check_nan_in_outputs(d, report)
    _check_output_file_sizes(d, report)
    _check_no_zero_byte_dyn(d, report)

    return report


def _check_job_done(d: Path, report: QaReport) -> None:
    """Verify JOB DONE in all .out files."""
    output_dir = d / "output"
    if not output_dir.is_dir():
        report.checks.append(
            CheckResult("output.job_done", "fail", "output/ directory missing", path=str(d))
        )
        return

    out_files = sorted(output_dir.rglob("*.out"))
    if not out_files:
        report.checks.append(
            CheckResult("output.job_done", "skip", "No .out files found")
        )
        return

    missing = []
    for f in out_files:
        text = f.read_text(encoding="utf-8", errors="replace")
        if "JOB DONE" not in text:
            missing.append(f.name)

    if missing:
        report.checks.append(
            CheckResult(
                "output.job_done", "fail",
                f"JOB DONE missing in {len(missing)}/{len(out_files)} output files",
                detail=", ".join(missing),
            )
        )
    else:
        report.checks.append(
            CheckResult(
                "output.job_done", "pass",
                f"JOB DONE present in all {len(out_files)} output files",
            )
        )


def _check_scf_convergence(d: Path, report: QaReport) -> None:
    """Check SCF convergence in scf.out."""
    output_dir = d / "output"
    # Find scf.out at any depth — prefer top-level, then scf_dos/, then others
    scf_candidates = sorted(output_dir.rglob("scf.out"), key=lambda p: (
        0 if p.parent == output_dir else 1 if p.parent.name == "scf_dos" else 2,
        str(p),
    ))
    scf_out = scf_candidates[0] if scf_candidates else (output_dir / "scf.out")
    if not scf_out.is_file():
        report.checks.append(
            CheckResult("output.scf.converged", "skip", "scf.out not found")
        )
        return

    text = scf_out.read_text(encoding="utf-8", errors="replace")
    if "convergence has been achieved" in text:
        report.checks.append(
            CheckResult("output.scf.converged", "pass", "SCF converged")
        )
    else:
        # Check if it's a non-scf calculation
        if "JOB DONE" in text:
            report.checks.append(
                CheckResult(
                    "output.scf.converged", "warn",
                    "JOB DONE present but SCF convergence message not found (may be NSCF)",
                )
            )
        else:
            report.checks.append(
                CheckResult("output.scf.converged", "fail", "SCF not converged")
            )


def _check_nan_in_outputs(d: Path, report: QaReport) -> None:
    """Check for NaN in output files."""
    output_dir = d / "output"
    if not output_dir.is_dir():
        return

    nan_files = []
    for f in sorted(output_dir.rglob("*")):
        if f.suffix in (".out", ".dat") and f.is_file():
            text = f.read_text(encoding="utf-8", errors="replace")
            # Check for NaN as a numeric value (not just the letters "nan")
            matches = re.findall(r"(?i)\bnan\b", text)
            if matches:
                nan_files.append((str(f.relative_to(output_dir)), len(matches)))

    if nan_files:
        detail = "; ".join(f"{fn}: {c} NaNs" for fn, c in nan_files)
        report.checks.append(
            CheckResult(
                "output.no_nan",
                "fail" if any(c > 10 for _, c in nan_files) else "warn",
                f"NaN values found in {len(nan_files)} files",
                detail=detail,
            )
        )
    else:
        report.checks.append(
            CheckResult("output.no_nan", "pass", "No NaN values detected")
        )


def _check_output_file_sizes(d: Path, report: QaReport) -> None:
    """Check output file sizes are in reasonable ranges."""
    output_dir = d / "output"
    if not output_dir.is_dir():
        return

    size_checks = {
        "*.dos": (10_000, 200_000),      # 10 KB — 200 KB
        "*pdos_tot": (10_000, 200_000),
        "*.bands*": (5_000, 500_000),
    }

    issues = []
    for pattern, (min_sz, max_sz) in size_checks.items():
        for f in output_dir.rglob(pattern):
            sz = f.stat().st_size
            if sz < min_sz:
                issues.append(f"{f.relative_to(output_dir)}: {sz} bytes (min {min_sz})")
            elif sz > max_sz:
                issues.append(f"{f.relative_to(output_dir)}: {sz} bytes (max {max_sz})")

    if issues:
        report.checks.append(
            CheckResult(
                "output.file_sizes", "warn",
                f"{len(issues)} files outside expected size range",
                detail="; ".join(issues[:5]),
            )
        )
    else:
        report.checks.append(
            CheckResult("output.file_sizes", "pass", "Output file sizes within expected ranges")
        )


def _check_no_zero_byte_dyn(d: Path, report: QaReport) -> None:
    """Check for zero-byte dyn files (indicates ph.x crash)."""
    output_dir = d / "output"

    zero_byte_dyn = []
    for f in output_dir.rglob("*.dyn*"):
        if f.stat().st_size == 0:
            zero_byte_dyn.append(f.name)

    if zero_byte_dyn:
        report.checks.append(
            CheckResult(
                "output.ph.dyn_zero_byte", "fail",
                f"{len(zero_byte_dyn)} zero-byte dyn files (ph.x likely crashed)",
                detail=", ".join(sorted(zero_byte_dyn)),
            )
        )
    elif any(output_dir.glob("*.dyn*")):
        dyn_files = sorted(output_dir.glob("*.dyn*"))
        report.checks.append(
            CheckResult(
                "output.ph.dyn_zero_byte", "pass",
                f"All {len(dyn_files)} dyn files non-empty",
            )
        )
    else:
        report.checks.append(
            CheckResult("output.ph.dyn_zero_byte", "skip", "No dyn files found (not a PH case)")
        )


# ---------------------------------------------------------------------------
# Combined QA (inputs + outputs)
# ---------------------------------------------------------------------------


def qa_all(case_dir: Path | str) -> QaReport:
    """Run input and output QA checks."""
    d = Path(case_dir)
    input_report = qa_inputs(d)
    output_report = qa_outputs(d)

    combined = QaReport(case_dir=d)
    combined.checks = input_report.checks + output_report.checks
    return combined
