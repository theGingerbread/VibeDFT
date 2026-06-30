"""Quantum ESPRESSO backend placeholders for the VibeDFT v2 platform."""

from .observability import (
    QeWorkflowReadinessGraph,
    StageReadiness,
    build_workflow_readiness_graph,
)

QE_TASKS = (
    "scf",
    "nscf",
    "relax",
    "vc_relax",
    "bands",
    "dos",
    "pdos",
    "phonon",
    "charge",
    "bader",
    "workfunction",
)

__all__ = ["QE_TASKS"]

__all__ += [
    "QeWorkflowReadinessGraph",
    "StageReadiness",
    "build_workflow_readiness_graph",
]
