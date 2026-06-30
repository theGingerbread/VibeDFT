"""Goal-acceptance checks that combine governance and QA evidence."""

from __future__ import annotations

import contextlib
import importlib.util
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from vibedft.core.qa import QaReport, qa_all


# High-severity warnings that should penalize score beyond ordinary warnings.
HIGH_WARNING_CHECK_IDS = {
    "output.no_nan",
    "output.file_sizes",
    "input.program.detection",
}


@dataclass
class CaseGoalSummary:
    """Aggregated QA verdicts for a single case."""

    case_name: str
    qa_status: str
    qa_passed: int
    qa_failed: int
    qa_warnings: int
    blocked_gates: list[str]
    warning_gates: list[str]


@contextlib.contextmanager
def _chdir(path: Path):
    """Temporarily switch current working directory for deterministic checks."""
    old_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


def _load_health_script(project_root: Path):
    """Load `scripts/reorg_health_check.py` from project root, with fallback to package scripts."""
    module_path = project_root / "scripts" / "reorg_health_check.py"
    fallback_path = Path(__file__).resolve().parents[2] / "scripts" / "reorg_health_check.py"
    if not module_path.exists() and fallback_path.exists():
        module_path = fallback_path

    if not module_path.exists():
        raise FileNotFoundError(f"goal-check script not found: {module_path}")

    spec = importlib.util.spec_from_file_location("reorg_health_check", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load goal-check module")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _normalize_gate(prefix: str, item_id: str) -> str:
    return f"{prefix}.{item_id.replace('.', '_')}"


def _compute_case_gates(report: QaReport) -> tuple[list[str], list[str], list[str]]:
    """Project a case QA report to gate IDs."""
    blocked: list[str] = []
    warning: list[str] = []
    high_warning: list[str] = []

    if report.status == "fail":
        blocked.append("BLOCKED.case.qa_fail")

    for item in report.checks:
        if item.status == "fail":
            blocked.append(_normalize_gate("BLOCKED.qa", item.id))
        elif item.status == "warn":
            if item.id in HIGH_WARNING_CHECK_IDS:
                high_warning.append(_normalize_gate("WARN.qa_high", item.id))
            else:
                warning.append(_normalize_gate("WARN.qa", item.id))

    return blocked, warning, high_warning


def run_goal_acceptance(
    *,
    project_root: Path,
    docs_root: Path,
    index_path: Path,
    stages_path: Path,
    stage_map_path: Path,
    skip_cases: bool = False,
    audit_cases: bool = False,
    case_root: Path | None = None,
    case_max: int | None = None,
) -> dict[str, Any]:
    """Run project goal-acceptance check and return a structured summary."""
    run_case_layout = not (skip_cases or audit_cases)
    case_payload: dict[str, Any]

    try:
        with _chdir(project_root):
            reorg = _load_health_script(project_root)
            summary = reorg.run_checks(
                docs_root=docs_root,
                index_path=index_path,
                stages_path=stages_path,
                stage_map_path=stage_map_path,
                skip_cases=not run_case_layout,
            )
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "overall_status": "FAIL",
            "score": 0.0,
            "blocked_gates": [f"FAIL.goal_script:{exc}"],
            "warning_gates": [],
            "high_warning_gates": [],
            "docs": {},
            "stages": {},
            "cases": {"enabled": audit_cases, "total_cases": 0, "audited": 0, "items": [], "layout_summary": None},
            "checks": {},
            "evidence": [str(exc)],
            "validator_ids": ["goal.script.load"],
        }

    blocked_gates: list[str] = []
    warning_gates: list[str] = []
    high_warning_gates: list[str] = []
    evidence: list[str] = []
    validator_ids: list[str] = ["goal.script.load", "goal.reorg_healthcheck"]

    evidence.append(f"docs_index={index_path}")
    evidence.append(f"stages_yaml={stages_path}")
    evidence.append(f"stage_map={stage_map_path}")
    if summary["cases"] is not None and isinstance(summary["cases"], dict):
        cases_layout = summary["cases"]
        evidence.append(f"cases_layout_total={cases_layout.get('total_cases', 0)}")
    else:
        cases_layout = {"enabled": False, "total_cases": 0, "canonical_full": 0, "noncanonical": 0, "cases": []}

    if summary["checks"]["docs_index_complete"]:
        validator_ids.append("goal.docs_index_complete")
    else:
        blocked_gates.append("BLOCKED.docs_stage_index_mismatch")

    if summary["checks"]["stage_map_complete"]:
        validator_ids.append("goal.stage_map_complete")
    else:
        blocked_gates.append("BLOCKED.stage_map_stage_mismatch")

    if cases_layout.get("noncanonical", 0) > 0:
        warning_gates.append("WARN.case_layout_noncanonical")

    if any(item.get("missing_stages_count", 0) > 0 for item in cases_layout.get("cases", [])):
        warning_gates.append("WARN.case_stage_coverage_missing")

    if audit_cases:
        audit_root = case_root or (project_root / "cases")
        if not audit_root.exists() or not audit_root.is_dir():
            blocked_gates.append(f"BLOCKED.case_audit_root_missing:{audit_root}")
            case_payload = {"enabled": True, "total_cases": 0, "audited": 0, "items": []}
        else:
            cases = sorted(
                (p for p in audit_root.iterdir() if p.is_dir() and not p.name.startswith(".")),
                key=lambda p: p.name,
            )
            if case_max is not None:
                cases = cases[:case_max]

            case_items: list[dict[str, Any]] = []
            for case in cases:
                try:
                    qa_report = qa_all(case)
                except Exception as exc:  # pragma: no cover - defensive
                    blocked_gate = f"BLOCKED.case.qa_exception:{case.name}"
                    blocked_gates.append(blocked_gate)
                    warning_gates.append(f"WARN.case.qa_exception:{case.name}:{exc}")
                    case_items.append(
                        asdict(
                            CaseGoalSummary(
                                case_name=case.name,
                                qa_status="error",
                                qa_passed=0,
                                qa_failed=0,
                                qa_warnings=0,
                                blocked_gates=[blocked_gate],
                                warning_gates=[f"WARN.case.qa_exception:{case.name}:{exc}"],
                            )
                        )
                    )
                    continue

                c_blocked, c_warning, c_high_warning = _compute_case_gates(qa_report)
                blocked_gates.extend(c_blocked)
                warning_gates.extend(c_warning)
                high_warning_gates.extend(c_high_warning)
                case_items.append(
                    asdict(
                        CaseGoalSummary(
                            case_name=case.name,
                            qa_status=qa_report.status,
                            qa_passed=len(qa_report.passed),
                            qa_failed=len(qa_report.failed),
                            qa_warnings=len(qa_report.warnings),
                            blocked_gates=sorted(set(c_blocked)),
                            warning_gates=sorted(set(c_warning + c_high_warning)),
                        )
                    )
                )

            validator_ids.append("goal.qa_audit")
            evidence.append(f"qa_cases_audited={len(cases)}")
            case_payload = {
                "enabled": True,
                "total_cases": len(cases),
                "audited": len(cases),
                "items": case_items,
            }
    else:
        case_payload = {
            "enabled": False,
            "total_cases": 0,
            "audited": 0,
            "items": [],
        }

    case_payload["layout_summary"] = cases_layout

    warning_gates_unique = sorted(set(warning_gates))
    high_warning_gates_unique = sorted(set(high_warning_gates))
    blocked_gates_unique = sorted(set(blocked_gates))

    score = 10.0
    score -= 4.0 * len(blocked_gates_unique)
    score -= 1.5 * len(high_warning_gates_unique)
    score -= 0.8 * len(warning_gates_unique)
    if not blocked_gates_unique and not warning_gates_unique and not high_warning_gates_unique:
        score += 2.0
    score = round(max(0.0, min(10.0, score)), 3)

    if blocked_gates_unique or score < 6.0:
        overall_status = "BLOCK"
    elif warning_gates_unique or high_warning_gates_unique:
        overall_status = "CONCERN"
    else:
        overall_status = "PASS"

    return {
        "overall_status": overall_status,
        "score": score,
        "blocked_gates": blocked_gates_unique,
        "warning_gates": warning_gates_unique,
        "high_warning_gates": high_warning_gates_unique,
        "docs": summary["docs"],
        "stages": summary["stages"],
        "cases": case_payload,
        "checks": summary["checks"],
        "evidence": evidence,
        "validator_ids": sorted(set(validator_ids)),
    }
