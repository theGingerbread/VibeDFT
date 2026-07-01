"""Schema helpers for QE relax and vc-relax review/clean stages."""

RELAX_TASK = "qe.relax"
RELAX_TASK_LEGACY = "relax"

VC_RELAX_TASK = "qe.vc_relax"
VC_RELAX_TASK_LEGACY = "vc_relax"

RELAX_DOWNSTREAMS = (
    "scf",
    "nscf",
    "bands",
    "dos",
    "pdos",
    "pp",
    "vc_relax",
    "phonon",
    "dielectric",
    "epc",
    "tc",
)

RELAX_BASE_DOWNSTREAMS = (
    "scf",
    "nscf",
    "bands",
    "dos",
    "pdos",
    "pp",
)

__all__ = [
    "RELAX_TASK",
    "RELAX_TASK_LEGACY",
    "VC_RELAX_TASK",
    "VC_RELAX_TASK_LEGACY",
    "RELAX_DOWNSTREAMS",
    "RELAX_BASE_DOWNSTREAMS",
]
