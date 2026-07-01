"""Schema helpers for Quantum ESPRESSO pp.x review/clean stages."""

from __future__ import annotations

PP_TASK = "qe.pp"
PP_TASK_LEGACY = "pp"

PP_BASE_DOWNSTREAMS = (
    "analysis.pp",
)

PP_DOWNSTREAMS = (
    "analysis.pp",
    "analysis.charge_density",
    "analysis.potential",
    "analysis.spin_density",
    "bader",
    "workfunction",
    "scf",
    "relax",
    "vc_relax",
    "nscf",
    "bands",
    "dos",
    "pdos",
    "phonon",
    "dielectric",
    "epc",
    "tc",
)

PP_REQUIRED_OUTPUT_FIELDS = (
    "job_done",
    "plot_num",
    "field_kind",
    "output_format",
    "output_files",
    "existing_output_files",
    "nonempty_output_files",
    "data_file_count",
)

__all__ = [
    "PP_TASK",
    "PP_TASK_LEGACY",
    "PP_BASE_DOWNSTREAMS",
    "PP_DOWNSTREAMS",
    "PP_REQUIRED_OUTPUT_FIELDS",
]
