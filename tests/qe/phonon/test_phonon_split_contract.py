"""Contract-level checks for phonon split scaffolding."""

from __future__ import annotations

from vibedft.calculator.qe.phonon import (
    PhononFrequency,
    PhononMonitorSnapshot,
    PhononOutput,
    PhononRepresentation,
    get_phonon_stage_spec,
    list_phonon_stage_specs,
    monitor_phonon_output,
    parse_phonon_output,
    phonon_split_analysis_domains,
    phonon_split_qualified_task_names,
    validate_phonon_stage_specs,
)


def test_phonon_split_validation_and_lookup() -> None:
    specs = list_phonon_stage_specs()
    assert specs
    assert validate_phonon_stage_specs() == []
    assert phonon_split_analysis_domains() == (
        "analysis.phonon_gamma",
        "analysis.phonon_qgrid",
        "analysis.phonon_dos",
        "analysis.dielectric",
        "analysis.born",
    )
    assert phonon_split_qualified_task_names() == (
        "qe.phonon_gamma",
        "qe.phonon_qgrid",
        "qe.phonon_dos",
        "qe.dielectric",
        "qe.born",
    )
    assert get_phonon_stage_spec("phonon_gamma").task == "phonon_gamma"


def test_phonon_split_contract_rejects_unknown_task() -> None:
    for task in ("missing", "phonon_debug"):
        try:
            get_phonon_stage_spec(task)
        except KeyError as exc:
            assert task in str(exc)
        else:
            raise AssertionError(f"unknown task {task} must raise KeyError")


def test_phonon_split_allowed_analysis_domains_and_regression_guard() -> None:
    sample = parse_phonon_output(
        """Program PHONON v.7.3 starts on 30Jul2026
 q = (    0.000000000   0.000000000   0.000000000 )
""",
        source="ph.out",
    )
    snapshot = monitor_phonon_output(sample.source, source="ph.out")

    assert isinstance(sample, PhononOutput)
    assert isinstance(snapshot, PhononMonitorSnapshot)
    assert sample.q_points[0] == (0.0, 0.0, 0.0)
    for spec in list_phonon_stage_specs():
        assert all(domain.startswith("analysis.") for domain in spec.analysis_domains)
        assert all(domain in spec.allowed_downstream for domain in spec.analysis_domains)


def test_phonon_split_regression_guard_keeps_existing_exports() -> None:
    assert PhononOutput is not None
    assert PhononRepresentation is not None
    assert PhononFrequency is not None
    assert parse_phonon_output("Program PHONON v.7.3 starts", source="ph.out").source == "ph.out"
