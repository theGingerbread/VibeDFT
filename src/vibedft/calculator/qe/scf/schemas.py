"""Schema helpers for QE SCF clean/review stages."""

SCF_TASK = "qe.scf"
SCF_TASK_LEGACY = "scf"

SCF_DOWNSTREAMS = (
    "relax",
    "vc_relax",
    "nscf",
    "bands",
    "dos",
    "pdos",
    "pp",
    "phonon",
    "dielectric",
)

SCF_BASE_DOWNSTREAMS = (
    "relax",
    "vc_relax",
    "nscf",
    "bands",
    "dos",
    "pdos",
    "pp",
)

SCF_REQUIRED_OUTPUT_FIELDS = (
    "job_done",
    "converged",
    "final_total_energy_ry",
    "final_scf_accuracy_ry",
    "ecutwfc_ry",
    "ecutrho_ry",
    "k_point_count",
)

__all__ = [
    "SCF_TASK",
    "SCF_TASK_LEGACY",
    "SCF_DOWNSTREAMS",
    "SCF_BASE_DOWNSTREAMS",
    "SCF_REQUIRED_OUTPUT_FIELDS",
]
