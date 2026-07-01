"""Schema helpers for QE vc-relax review/clean stages."""

from vibedft.calculator.qe.relax.schemas import (
    VC_RELAX_TASK,
    VC_RELAX_TASK_LEGACY,
)

VC_RELAX_DOWNSTREAMS = (
    "scf",
    "nscf",
    "bands",
    "dos",
    "pdos",
    "pp",
    "phonon",
    "dielectric",
    "epc",
    "tc",
)

VC_RELAX_BASE_DOWNSTREAMS = (
    "scf",
    "nscf",
    "bands",
    "dos",
    "pdos",
    "pp",
)

__all__ = [
    "VC_RELAX_TASK",
    "VC_RELAX_TASK_LEGACY",
    "VC_RELAX_BASE_DOWNSTREAMS",
    "VC_RELAX_DOWNSTREAMS",
]
