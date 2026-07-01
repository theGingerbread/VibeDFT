"""Phonon split stage metadata tests."""

from __future__ import annotations

import json
from dataclasses import asdict

from vibedft.calculator.qe.phonon import list_phonon_stage_specs


def test_phonon_split_stage_list_and_task_names() -> None:
    specs = list_phonon_stage_specs()
    assert len(specs) == 5
    assert [spec.task for spec in specs] == [
        "phonon_gamma",
        "phonon_qgrid",
        "phonon_dos",
        "dielectric",
        "born",
    ]


def test_phonon_split_qualified_task_prefix() -> None:
    specs = list_phonon_stage_specs()
    for spec in specs:
        assert spec.qualified_task.startswith("qe.")
        assert spec.qualified_task == f"qe.{spec.task}"


def test_phonon_split_status_is_scaffold() -> None:
    for spec in list_phonon_stage_specs():
        assert spec.implementation_status == "scaffold"


def test_phonon_split_analysis_domains() -> None:
    specs = list_phonon_stage_specs()
    expected = {
        "phonon_gamma": "analysis.phonon_gamma",
        "phonon_qgrid": "analysis.phonon_qgrid",
        "phonon_dos": "analysis.phonon_dos",
        "dielectric": "analysis.dielectric",
        "born": "analysis.born",
    }

    for spec in specs:
        assert spec.analysis_domains == (expected[spec.task],)


def test_phonon_split_mandatory_blocked_downstreams() -> None:
    mandatory = {
        "scf",
        "relax",
        "vc_relax",
        "nscf",
        "bands",
        "dos",
        "pdos",
        "pp",
        "bader",
        "workfunction",
        "epc",
        "tc",
    }

    for spec in list_phonon_stage_specs():
        assert mandatory.issubset(set(spec.blocked_downstream))


def test_phonon_split_allowed_downstream_is_safe() -> None:
    for spec in list_phonon_stage_specs():
        assert all(
            downstream.startswith("analysis.") or downstream.startswith("qe.")
            for downstream in spec.allowed_downstream
        )
        assert "epc" not in spec.allowed_downstream
        assert "tc" not in spec.allowed_downstream


def test_phonon_split_stage_specs_json_serializable() -> None:
    for spec in list_phonon_stage_specs():
        payload = json.dumps(asdict(spec), ensure_ascii=False)
        restored = json.loads(payload)
        assert restored["task"] == spec.task
