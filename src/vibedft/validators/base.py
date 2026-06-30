"""Validator framework: context object and dispatch.

Each per-program validator is a callable::

    (ctx: ValidationContext, task: TaskRecord) -> list[SanityIssue]

The ``validate_all`` function runs every applicable validator for every
identified task in the context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from vibedft.models.inspection import (
    FileRecord,
    InspectionResult,
    QEProgram,
    SanityIssue,
    TaskRecord,
    TaskType,
)
from vibedft.parsers.qe_input_parser import parse_qe_input, QEInput


# ═══════════════════════════════════════════════════════════════════════════════
# Validation context
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ValidationContext:
    """Bundled inspection results with cross-file lookup helpers.

    Provides the shared context that all per-program validators need:
    full inspection results, file→task mapping, and input-file access.
    """

    case_dir: Path
    inspection: InspectionResult = field(default_factory=InspectionResult)
    _parsed_inputs: dict[str, QEInput] = field(default_factory=dict)

    # ── Convenience accessors ──

    @property
    def files(self) -> list[FileRecord]:
        return self.inspection.files

    @property
    def tasks(self) -> list[TaskRecord]:
        return self.inspection.tasks

    @property
    def issues(self) -> list[SanityIssue]:
        return self.inspection.issues

    def tasks_of_program(self, prog: QEProgram) -> list[TaskRecord]:
        """All tasks matching a given program."""
        return [t for t in self.tasks if t.program == prog]

    def tasks_of_type(self, tt: TaskType) -> list[TaskRecord]:
        """All tasks matching a given task type."""
        return [t for t in self.tasks if t.task_type == tt]

    def file_for_task(self, task: TaskRecord) -> FileRecord | None:
        """Find the FileRecord that produced a given task."""
        for f in self.files:
            if f.path == task.source_file:
                return f
        return None

    def get_input(self, task: TaskRecord) -> QEInput | None:
        """Return the parsed QEInput for a task (cached)."""
        src = task.source_file
        if not src:
            return None
        if src not in self._parsed_inputs:
            try:
                self._parsed_inputs[src] = parse_qe_input(src)
            except Exception:
                return None
        return self._parsed_inputs[src]

    def find_paired_output(self, task: TaskRecord) -> Path | None:
        """Heuristic: find a matching .out file for an input-based task.

        Looks in output/ for files with matching stem or program signature.
        """
        out_dir = self.case_dir / "output"
        if not out_dir.is_dir():
            return None

        # Strategy 1: same stem as input file
        in_path = Path(task.source_file) if task.source_file else None
        if in_path and in_path.stem:
            for cand in out_dir.rglob(f"{in_path.stem}.out"):
                return cand

        # Strategy 2: match by program — find any .out with same program
        for f in self.files:
            if f.type == "output" and f.program == task.program:
                p = Path(f.path)
                if p.is_file():
                    return p
        return None

    def find_paired_input(self, task: TaskRecord) -> Path | None:
        """Heuristic: find a matching .in file for an output-based task."""
        in_dir = self.case_dir / "input"
        if not in_dir.is_dir():
            return None
        for f in self.files:
            if f.type == "input" and f.program == task.program:
                p = Path(f.path)
                if p.is_file():
                    return p
        return None

    def output_files(self) -> list[Path]:
        """All .out files in the output directory."""
        out_dir = self.case_dir / "output"
        if not out_dir.is_dir():
            return []
        return sorted(out_dir.rglob("*.out"))

    def input_files(self) -> list[Path]:
        """All .in files in the input directory."""
        in_dir = self.case_dir / "input"
        if not in_dir.is_dir():
            return []
        return sorted(in_dir.rglob("*.in"))


# ═══════════════════════════════════════════════════════════════════════════════
# Validator registry
# ═══════════════════════════════════════════════════════════════════════════════

# Signature: (ValidationContext, TaskRecord) -> list[SanityIssue]
ValidatorFn = Callable[[ValidationContext, TaskRecord], list[SanityIssue]]

# Per-program validators are registered by program enum value.
# Each program may have multiple validator functions.
_VALIDATOR_REGISTRY: dict[QEProgram, list[ValidatorFn]] = {}


def register_validator(prog: QEProgram):
    """Decorator: register a validator function for a QE program."""
    def decorator(fn: ValidatorFn) -> ValidatorFn:
        _VALIDATOR_REGISTRY.setdefault(prog, []).append(fn)
        return fn
    return decorator


def validate_all(ctx: ValidationContext) -> list[SanityIssue]:
    """Run all registered validators against every applicable task.

    Returns a flat list of all SanityIssues found.
    """
    all_issues: list[SanityIssue] = []
    validators_by_prog = dict(_VALIDATOR_REGISTRY)

    for task in ctx.tasks:
        prog = task.program
        if prog not in validators_by_prog:
            continue
        for validator_fn in validators_by_prog[prog]:
            try:
                new_issues = validator_fn(ctx, task)
                all_issues.extend(new_issues)
            except Exception:
                # A validator should never crash the whole pipeline
                pass

    return all_issues
