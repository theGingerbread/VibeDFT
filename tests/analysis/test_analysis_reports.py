"""Tests for analysis report generation and serialization contracts."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from vibedft.analysis import (
    analyze_cleaned_result,
    analyze_cleaned_results,
    extract_key_observables,
)
from ._helpers import make_cleaned_result


def _asjson(payload: object) -> str:
    return json.dumps(payload, sort_keys=True)


def test_dos_report_key_observables_and_summary() -> None:
    result = make_cleaned_result(
        task="dos",
        status="pass",
        review_status="PASS",
        allowed=("analysis.dos",),
        observables={
            "fermi_energy_ev": 3.1,
            "energy_min_ev": -15.3,
            "energy_max_ev": 8.7,
            "dos_min": 0.0,
            "dos_max": 12.4,
            "data_column_count": 3,
        },
    )

    report = analyze_cleaned_result(result)
    key_observables = extract_key_observables(result)

    assert report.status == "pass"
    assert report.review_status == "PASS"
    assert report.key_observables["fermi_energy_ev"] == 3.1
    assert key_observables["data_column_count"] == 3
    assert key_observables["energy_min_ev"] == -15.3
    assert key_observables["dos_max"] == 12.4
    assert key_observables["dos_min"] == 0.0
    assert _asjson(asdict(report))


def test_bands_report_warn_status_yields_warn_finding() -> None:
    result = make_cleaned_result(
        task="bands",
        status="warn",
        review_status="WARN",
        allowed=("analysis.bands", "analysis.bandgap"),
        observables={
            "fermi_energy_ev": 6.2,
            "reference_energy_ev": 0.0,
            "energy_min_ev": -4.5,
            "energy_max_ev": 7.2,
            "estimated_band_gap_ev": 0.0,
            "band_data_points": 1200,
        },
    )

    report = analyze_cleaned_result(result)
    key_observables = extract_key_observables(result)

    assert key_observables["estimated_band_gap_ev"] == 0.0
    assert key_observables["band_data_points"] == 1200
    assert any(finding.level == "warn" for finding in report.findings)


def test_pp_report_key_observables_and_domain_support() -> None:
    result = make_cleaned_result(
        task="pp",
        status="pass",
        review_status="PASS",
        allowed=("analysis.pp", "analysis.charge_density"),
        observables={
            "field_kind": "charge_density",
            "output_format": "cube",
            "data_sample_count": 42,
            "data_min": -1.0,
            "data_max": 1.0,
            "artifact_extensions": [".cube", ".dat"],
        },
        outputs={
            "nonempty_output_files": ["charge.cube"],
        },
    )

    report = analyze_cleaned_result(result)
    key_observables = extract_key_observables(result)

    assert "analysis.pp" in report.domains
    assert "analysis.charge_density" in report.domains
    assert key_observables["field_kind"] == "charge_density"
    assert key_observables["artifact_extensions"] == [".cube", ".dat"]


def test_blocked_result_generates_block_findings_and_preserves_next_actions() -> None:
    result = make_cleaned_result(
        task="nscf",
        status="block",
        review_status="BLOCK",
        allowed=(),
        blocked=("analysis.charge_density",),
        next_actions=["rerun nscf with tighter settings"],
    )

    report = analyze_cleaned_result(result)
    assert report.status == "block"
    assert report.review_status == "BLOCK"
    assert report.next_actions == ["rerun nscf with tighter settings"]
    assert any(finding.level == "block" for finding in report.findings)


def test_bundle_analysis_collects_reports_and_domains() -> None:
    dos = make_cleaned_result(
        task="dos",
        status="pass",
        review_status="PASS",
        allowed=("analysis.dos",),
    )
    bands = make_cleaned_result(
        task="bands",
        status="pass",
        review_status="PASS",
        allowed=("analysis.bands", "analysis.bandgap"),
    )
    pp = make_cleaned_result(
        task="pp",
        status="pass",
        review_status="PASS",
        allowed=("analysis.pp",),
    )

    bundle = analyze_cleaned_results([dos, bands, pp])

    assert len(bundle.reports) == 3
    assert bundle.task_order == ["dos", "bands", "pp"]
    assert bundle.available_domains == sorted(
        ["analysis.dos", "analysis.bands", "analysis.bandgap", "analysis.pp"]
    )
    assert bundle.payload["report_count"] == 3
    assert bundle.payload["task_order"] == ["dos", "bands", "pp"]
    assert _asjson(asdict(bundle))


def test_analysis_files_do_not_import_parser_or_read_raw_outputs() -> None:
    analysis_dir = Path(__file__).resolve().parents[2] / "src" / "vibedft" / "analysis"
    forbidden = [
        "vibedft.calculator",
        "parse_scf_output",
        "parse_dos_output",
        "clean_scf_text",
        "clean_dos_text",
        ".read_text(",
        "open(",
    ]

    for path in analysis_dir.glob("*.py"):
        content = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in content
