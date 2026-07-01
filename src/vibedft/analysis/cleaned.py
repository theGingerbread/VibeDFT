"""Build analysis summaries from cleaned task results."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from vibedft._shared.contracts import CleanedResult
from vibedft.analysis.contracts import AnalysisBundle, AnalysisFinding, AnalysisReport
from vibedft.analysis.routing import _ensure_cleaned_result, blocked_analysis_domains, supported_analysis_domains


def analyze_cleaned_result(result: CleanedResult, *, domain: str | None = None) -> AnalysisReport:
    """Create a task-level analysis report from one cleaned result only."""

    cleaned = _ensure_cleaned_result(result)
    domains = supported_analysis_domains(cleaned)
    blocked = blocked_analysis_domains(cleaned)
    review_status = cleaned.review.status if cleaned.review is not None else None
    key_observables = extract_key_observables(cleaned)
    findings = _build_findings(cleaned, domains, blocked, domain=domain)
    calculator = cleaned.calculator or ""
    source_artifacts = list(cleaned.source_artifacts)
    summary = _build_summary(cleaned, review_status, domain=domain)
    next_actions = list(cleaned.next_actions)
    provenance = _safe_dict(cleaned.provenance.__dict__)

    payload = {
        "calculator": calculator,
        "task": cleaned.task,
        "status": cleaned.status,
        "review_status": review_status,
        "domains": list(domains),
        "blocked_domains": list(blocked),
        "findings": len(findings),
        "key_observables": _safe_dict(key_observables),
    }

    if domain is not None:
        payload["requested_domain"] = domain

    return AnalysisReport(
        calculator=calculator,
        task=cleaned.task,
        status=cleaned.status,
        review_status=review_status,
        domains=list(domains),
        blocked_domains=list(blocked),
        summary=summary,
        key_observables=_safe_dict(key_observables),
        source_artifacts=list(source_artifacts),
        provenance=provenance,
        findings=list(findings),
        next_actions=next_actions,
        payload=payload,
    )


def analyze_cleaned_results(results: Sequence[CleanedResult]) -> AnalysisBundle:
    """Aggregate multiple cleaned-results analyses into one bundle."""

    reports: list[AnalysisReport] = [analyze_cleaned_result(result) for result in results]
    task_order = [report.task for report in reports]
    available_domains = sorted(_union_nested(reports, lambda report: report.domains))
    blocked_domains = sorted(_union_nested(reports, lambda report: report.blocked_domains))
    findings = [finding for report in reports for finding in report.findings]

    payload = {
        "report_count": len(reports),
        "task_order": list(task_order),
        "available_domains": list(available_domains),
        "blocked_domains": list(blocked_domains),
    }
    payload["findings_count"] = len(findings)

    return AnalysisBundle(
        reports=list(reports),
        task_order=task_order,
        available_domains=available_domains,
        blocked_domains=blocked_domains,
        findings=list(findings),
        payload=payload,
    )


def extract_key_observables(result: CleanedResult, *, domain: str | None = None) -> dict[str, object]:
    """Extract task-specific observables for downstream summarization."""

    _ensure_cleaned_result(result)
    task = (result.task or "").strip().lower()
    observables = _safe_dict(result.observables)

    if task == "dos":
        return _extract_observables_for_dos(result, observables)
    if task == "pdos":
        return _extract_observables_for_pdos(result, observables)
    if task == "bands":
        return _extract_observables_for_bands(result, observables)
    if task == "pp":
        return _extract_observables_for_pp(result, observables)
    if task in {"scf", "nscf", "relax", "vc_relax"}:
        return _extract_scalar_observables(result)

    if domain is not None:
        return _shallow_scalar_copy(observables)

    return {key: value for key, value in _safe_dict(result.observables).items()}


def _build_findings(
    result: CleanedResult,
    domains: list[str],
    blocked: list[str],
    *,
    domain: str | None,
) -> list[AnalysisFinding]:
    findings: list[AnalysisFinding] = []

    review_status = result.review.status if result.review is not None else None

    if result.status == "block" or review_status == "BLOCK":
        findings.append(
            AnalysisFinding(
                level="block",
                category="quality_gate",
                message="Task result is blocked.",
            )
        )
    if result.status == "warn" or review_status == "WARN":
        findings.append(
            AnalysisFinding(
                level="warn",
                category="quality_gate",
                message="Task result is marked WARN.",
            )
        )

    if result.diagnostics.errors:
        findings.append(
            AnalysisFinding(
                level="block",
                category="diagnostics",
                message="Diagnostics contains errors.",
                evidence_refs=list(result.diagnostics.errors),
            )
        )
    if result.diagnostics.warnings:
        findings.append(
            AnalysisFinding(
                level="warn",
                category="diagnostics",
                message="Diagnostics contains warnings.",
                evidence_refs=list(result.diagnostics.warnings),
            )
        )

    if not domains:
        findings.append(
            AnalysisFinding(
                level="warn",
                category="routing",
                message="No analysis.* downstream domains are currently allowed.",
            )
        )

    if domain is not None and domain not in domains:
        findings.append(
            AnalysisFinding(
                level="block",
                category="routing",
                message=f"Requested analysis domain '{domain}' is not allowed by CleanedResult readiness.",
                evidence_refs=[domain],
            )
        )

    if blocked:
        findings.append(
            AnalysisFinding(
                level="info",
                category="routing",
                message=f"{len(blocked)} analysis downstream task(s) are blocked.",
            )
        )

    if not findings:
        findings.append(
            AnalysisFinding(
                level="info",
                category="summary",
                message="Task result is analyzable without additional findings.",
            )
        )

    return findings


def _build_summary(
    result: CleanedResult,
    review_status: str | None,
    domain: str | None = None,
) -> str:
    summary = f"{result.task} result status={result.status}"
    if review_status:
        summary = f"{summary}, review={review_status}"
    if domain is not None:
        summary = f"{summary}, requested_domain={domain}"
    if result.readiness.summary:
        summary = f"{summary}, {result.readiness.summary}"
    return summary


def _extract_observables_for_dos(result: CleanedResult, observables: dict[str, Any]) -> dict[str, object]:
    return {
        "fermi_energy_ev": _pick_value(result, "fermi_energy_ev", observables),
        "energy_min_ev": _pick_value(result, "energy_min_ev", observables),
        "energy_max_ev": _pick_value(result, "energy_max_ev", observables),
        "dos_min": _pick_value(result, "dos_min", observables),
        "dos_max": _pick_value(result, "dos_max", observables),
        "data_column_count": _pick_value(result, "data_column_count", observables),
    }


def _extract_observables_for_pdos(result: CleanedResult, observables: dict[str, Any]) -> dict[str, object]:
    return {
        "fermi_energy_ev": _pick_value(result, "fermi_energy_ev", observables),
        "energy_min_ev": _pick_value(result, "energy_min_ev", observables),
        "energy_max_ev": _pick_value(result, "energy_max_ev", observables),
        "projection_file_count": _pick_value(result, "projection_file_count", observables),
        "orbital_channels": _pick_value(result, "orbital_channels", observables),
        "spin_channels": _pick_value(result, "spin_channels", observables),
    }


def _extract_observables_for_bands(result: CleanedResult, observables: dict[str, Any]) -> dict[str, object]:
    return {
        "fermi_energy_ev": _pick_value(result, "fermi_energy_ev", observables),
        "reference_energy_ev": _pick_value(result, "reference_energy_ev", observables),
        "energy_min_ev": _pick_value(result, "energy_min_ev", observables),
        "energy_max_ev": _pick_value(result, "energy_max_ev", observables),
        "estimated_band_gap_ev": _pick_value(result, "estimated_band_gap_ev", observables),
        "band_data_points": _pick_value(result, "band_data_points", observables),
    }


def _extract_observables_for_pp(result: CleanedResult, observables: dict[str, Any]) -> dict[str, object]:
    return {
        "field_kind": _pick_value(result, "field_kind", observables),
        "output_format": _pick_value(result, "output_format", observables),
        "data_sample_count": _pick_value(result, "data_sample_count", observables),
        "data_min": _pick_value(result, "data_min", observables),
        "data_max": _pick_value(result, "data_max", observables),
        "artifact_extensions": _pick_value(result, "artifact_extensions", observables),
        "nonempty_output_files": _pick_value(result, "nonempty_output_files", observables),
    }


def _extract_scalar_observables(result: CleanedResult) -> dict[str, object]:
    values = _safe_dict(result.observables)
    return {key: value for key, value in values.items() if isinstance(value, (int, float, str, bool))}


def _pick_value(result: CleanedResult, key: str, observables: dict[str, object]) -> object:
    if key in observables:
        return observables[key]
    if key in result.outputs:
        return result.outputs[key]
    return result.outputs.get(key)


def _safe_dict(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    return dict(payload)


def _union_nested(
    reports: Sequence[AnalysisReport],
    selector: Callable[[AnalysisReport], list[str]],
) -> set[str]:
    result: set[str] = set()
    for report in reports:
        result.update(selector(report))
    return result


def _shallow_scalar_copy(values: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in values.items()
        if isinstance(value, (str, int, float, bool, type(None)))
    }


__all__ = [
    "analyze_cleaned_result",
    "analyze_cleaned_results",
    "extract_key_observables",
]
