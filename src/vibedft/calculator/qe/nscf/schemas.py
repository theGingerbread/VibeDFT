"""Schema helpers for QE nscf review/clean stages."""

NSCF_TASK = "qe.nscf"
NSCF_TASK_LEGACY = "nscf"

NSCF_BASE_DOWNSTREAMS = (
    "bands",
    "dos",
    "pdos",
    "pp",
)

NSCF_DOWNSTREAMS = (
    "scf",
    "relax",
    "vc_relax",
    "bands",
    "dos",
    "pdos",
    "pp",
    "phonon",
    "dielectric",
    "epc",
    "tc",
)

NSCF_REQUIRED_OUTPUT_FIELDS = (
    "job_done",
    "k_point_count",
    "final_total_energy_ry",
    "convergence_iterations",
)

__all__ = [
    "NSCF_TASK",
    "NSCF_TASK_LEGACY",
    "NSCF_BASE_DOWNSTREAMS",
    "NSCF_DOWNSTREAMS",
    "NSCF_REQUIRED_OUTPUT_FIELDS",
]
