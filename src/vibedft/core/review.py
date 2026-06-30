"""Case-directory review: scan, inspect, validate, match workflows.

Entry point: ``review_case(case_dir) -> ReviewResult``
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibedft.classifiers.task_classifier import inspect_files
from vibedft.classifiers.workflow_matcher import (
    WorkflowMatch,
    match_workflows,
    missing_steps_summary,
    next_step_recommendation,
)
from vibedft.models.inspection import (
    FileRecord,
    InspectionResult,
    SanityIssue,
    TaskRecord,
    TaskType,
)
from vibedft.validators.base import ValidationContext, validate_all

# Eager-import per-program validator modules so their @register_validator
# decorators fire and populate the registry.
import vibedft.validators.pw_rules       # noqa: F401
import vibedft.validators.ph_rules       # noqa: F401
import vibedft.validators.q2r_rules      # noqa: F401
import vibedft.validators.matdyn_rules   # noqa: F401
import vibedft.validators.lambda_rules   # noqa: F401


# ═══════════════════════════════════════════════════════════════════════════════
# Review result model
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ReviewResult:
    """Complete review of a VibeDFT case directory."""

    case_dir: str = ""
    files_scanned: int = 0
    files_inspected: int = 0
    inspection: InspectionResult = field(default_factory=InspectionResult)
    validation_issues: list[SanityIssue] = field(default_factory=list)
    workflow_matches: list[WorkflowMatch] = field(default_factory=list)
    best_match: WorkflowMatch | None = None
    summary: str = ""
    next_step: str = ""

    @property
    def all_issues(self) -> list[SanityIssue]:
        """Combined inspection + validation issues."""
        return self.inspection.issues + self.validation_issues

    @property
    def n_errors(self) -> int:
        from vibedft.models.inspection import Severity
        return len([i for i in self.all_issues if i.severity == Severity.ERROR])

    @property
    def n_warnings(self) -> int:
        from vibedft.models.inspection import Severity
        return len([i for i in self.all_issues if i.severity == Severity.WARNING])

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "case_dir": self.case_dir,
            "files_scanned": self.files_scanned,
            "files_inspected": self.files_inspected,
            "inspection": self.inspection.to_dict(),
            "validation_issues": [
                {
                    "id": i.id, "severity": i.severity.value,
                    "message": i.message, "source_file": i.source_file,
                    "detail": i.detail,
                }
                for i in self.validation_issues
            ],
            "workflow_matches": [
                {
                    "workflow_id": m.workflow.workflow_id,
                    "label": m.workflow.label,
                    "completeness": m.completeness,
                    "present_steps": [s.value for s in m.present_steps],
                    "missing_steps": [
                        {"task_type": s.task_type.value, "label": s.label,
                         "description": s.description}
                        for s in m.missing_steps
                    ],
                }
                for m in self.workflow_matches[:3]
            ],
            "best_workflow": (
                {
                    "workflow_id": self.best_match.workflow.workflow_id,
                    "label": self.best_match.workflow.label,
                    "completeness": self.best_match.completeness,
                }
                if self.best_match else None
            ),
            "summary": self.summary,
            "next_step": self.next_step,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════════════════════
# Review logic
# ═══════════════════════════════════════════════════════════════════════════════


def review_case(case_dir: Path | str) -> ReviewResult:
    """Run a complete review of a VibeDFT case directory.

    1. Discover all .in and .out files
    2. Run inspect on every file
    3. Run per-program validators against the inspection context
    4. Match the identified tasks against known workflows
    5. Generate summary and next-step recommendation
    """
    d = Path(case_dir).resolve()
    result = ReviewResult(case_dir=str(d))

    # ── 1. Discover files ──
    filepaths = _discover_files(d)
    result.files_scanned = len(filepaths)

    if not filepaths:
        result.summary = f"No .in or .out files found in {d}"
        result.next_step = "Create input files with: vibedft render inputs ..."
        return result

    # ── 2. Inspect every file ──
    inspection = inspect_files(filepaths)
    result.inspection = inspection
    result.files_inspected = len(inspection.files)

    # ── 3. Run validators ──
    ctx = ValidationContext(case_dir=d, inspection=inspection)
    validation_issues = validate_all(ctx)
    result.validation_issues = validation_issues

    # ── 4. Match workflows ──
    present_types = list({t.task_type for t in inspection.tasks})
    matches = match_workflows(present_types)
    result.workflow_matches = matches
    result.best_match = matches[0] if matches else None

    # ── 5. Summary ──
    result.summary = _build_summary(result)
    result.next_step = next_step_recommendation(result.best_match)

    return result


def _discover_files(case_dir: Path) -> list[Path]:
    """Discover all inspectable and data files in a case directory.

    Covers input files, QE output logs, and all common data file types:
    DOS, PDOS, bands, phonon, EPC, Fermi surface, ELF, Bader, work function.
    """
    files: list[Path] = []

    # ── Input files ──
    in_dir = case_dir / "input"
    search_roots = [in_dir] if in_dir.is_dir() else []
    if not search_roots:
        search_roots = [case_dir]

    for root in search_roots:
        files.extend(sorted(root.rglob("*.in")))

    # ── Output logs ──
    out_dir = case_dir / "output"
    log_roots = [out_dir] if out_dir.is_dir() else [case_dir]
    for root in log_roots:
        files.extend(sorted(root.rglob("*.out")))
        files.extend(sorted(root.rglob("*.err")))

    # ── Data files (from all directories) ──
    data_patterns = [
        "*.dos", "*pdos*", "*bands*", "*.gnu",
        "*.freq.gp", "*.fc", "*.dyn*",
        "alpha2F*", "a2F*", "lambda.dat",
        "elph.inp_lambda.*", "elph.gamma.*",
        "*.bxsf", "*.phdos*", "matdyn.dos", "matdyn.modes",
        "avg.dat", "ACF.dat", "*.elf*",
        "gam.lines",
    ]
    search_all = [case_dir]  # data files may be anywhere in the tree
    for root in search_all:
        for pattern in data_patterns:
            files.extend(sorted(root.rglob(pattern)))
            if len(files) > 5000:  # safety limit
                break

    # Deduplicate by resolved path
    seen: set[str] = set()
    unique: list[Path] = []
    for f in files:
        resolved = str(f.resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(f)

    return sorted(unique, key=lambda p: (p.suffix, str(p)))


def _build_summary(result: ReviewResult) -> str:
    """Build a human-readable summary."""
    parts = [
        f"Scanned {result.files_scanned} files, inspected {result.files_inspected}.",
    ]

    # Tasks found
    task_counts: dict[str, int] = {}
    for t in result.inspection.tasks:
        key = t.task_type.value
        task_counts[key] = task_counts.get(key, 0) + 1
    if task_counts:
        parts.append("Tasks: " + ", ".join(
            f"{v}× {k}" for k, v in sorted(task_counts.items())
        ) + ".")

    # Issues
    if result.n_errors:
        parts.append(f"{result.n_errors} error(s), {result.n_warnings} warning(s).")
    elif result.n_warnings:
        parts.append(f"{result.n_warnings} warning(s).")
    else:
        parts.append("No issues found.")

    # Workflow
    if result.best_match:
        parts.append(missing_steps_summary(result.best_match))
    else:
        parts.append("No workflow matched.")

    return " ".join(parts)
