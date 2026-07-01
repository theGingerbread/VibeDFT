"""Contract-aligned workflow observability tests based on CleanedResult."""

from __future__ import annotations

from vibedft._shared.contracts import (
    CleanedResult,
    DownstreamReadiness,
    Diagnostics,
    Readiness,
    ReviewResult,
)
from vibedft.calculator.qe.observability import build_workflow_readiness_graph


def _make_cleaned_result(
    *,
    task: str,
    status: str,
    downstream: dict[str, bool],
    diagnostics: Diagnostics | None = None,
) -> CleanedResult:
    readiness = Readiness(
        downstream={
            name: DownstreamReadiness(task=name, allowed=allowed)
            for name, allowed in downstream.items()
        }
    )
    review_status = "PASS" if status == "pass" else "WARN" if status == "warn" else "BLOCK"
    if status not in {"pass", "warn", "block", "running", "failed", "no_data"}:
        status = "failed"

    return CleanedResult(
        calculator="qe",
        task=task,
        status=status,  # type: ignore[arg-type]
        diagnostics=diagnostics or Diagnostics(),
        review=ReviewResult(
            status=review_status,
            reasons=[f"{task} synthetic review"],
            allowed_downstream=[name for name, allowed in downstream.items() if allowed],
            blocked_downstream=[name for name, allowed in downstream.items() if not allowed],
        ),
        readiness=readiness,
    )


def test_cleaned_graph_uses_scf_downstream_gating() -> None:
    scf = _make_cleaned_result(
        task="scf",
        status="pass",
        downstream={
            "dos": True,
            "bands": True,
            "phonon": False,
            "dielectric": False,
            "epc": False,
            "tc": False,
        },
    )

    graph = build_workflow_readiness_graph(scf=scf)

    assert graph.scf_stage.status == "complete"
    assert graph.can_run["dos"] is True
    assert graph.can_run["bands"] is True
    assert graph.can_run["phonon"] is False
    assert graph.can_run["dielectric"] is False


def test_cleaned_graph_blocks_all_when_scf_block() -> None:
    scf = _make_cleaned_result(
        task="scf",
        status="block",
        downstream={
            "dos": True,
            "bands": True,
            "phonon": True,
            "dielectric": True,
            "epc": True,
            "tc": True,
        },
    )

    graph = build_workflow_readiness_graph(scf=scf)

    assert graph.scf_stage.status == "blocked"
    assert all(graph.can_run[key] is False for key in graph.can_run)


def test_cleaned_graph_gates_epc_tc_from_phonon_readiness() -> None:
    scf = _make_cleaned_result(
        task="scf",
        status="pass",
        downstream={
            "dos": True,
            "bands": True,
            "phonon": True,
            "dielectric": True,
        },
    )
    phonon = _make_cleaned_result(
        task="phonon",
        status="warn",
        downstream={
            "epc": True,
            "tc": True,
        },
    )

    graph = build_workflow_readiness_graph(scf=scf, phonon=phonon)

    assert graph.can_run["epc"] is False
    assert graph.can_run["tc"] is False


def test_cleaned_graph_negative_frequency_blocks_epc_tc() -> None:
    scf = _make_cleaned_result(
        task="scf",
        status="pass",
        downstream={
            "dos": True,
            "bands": True,
            "phonon": True,
            "dielectric": True,
        },
    )
    phonon = _make_cleaned_result(
        task="phonon",
        status="pass",
        downstream={
            "epc": True,
            "tc": True,
        },
        diagnostics=Diagnostics(
            metrics={
                "numerical_risk": {
                    "min_frequency_cm1": -1.23,
                }
            }
        ),
    )

    graph = build_workflow_readiness_graph(scf=scf, phonon=phonon)

    assert graph.can_run["epc"] is False
    assert graph.can_run["tc"] is False
    assert graph.phonon_stage.status == "complete"


def test_contract_graph_uses_downstream_only_for_epc_tc() -> None:
    scf = _make_cleaned_result(
        task="scf",
        status="pass",
        downstream={
            "dos": True,
            "bands": True,
            "phonon": True,
            "dielectric": True,
        },
    )
    phonon = _make_cleaned_result(
        task="phonon",
        status="pass",
        downstream={},
    )

    graph = build_workflow_readiness_graph(scf=scf, phonon=phonon)

    assert graph.can_run["epc"] is False
    assert graph.can_run["tc"] is False
