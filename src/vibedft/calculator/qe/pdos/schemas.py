"""Schema helpers for QE pdos review/clean stages."""

PDOS_TASK = "qe.pdos"
PDOS_TASK_LEGACY = "pdos"

PDOS_BASE_DOWNSTREAMS = (
    "analysis.pdos",
    "analysis.orbital",
)

PDOS_DOWNSTREAMS = (
    "analysis.pdos",
    "analysis.orbital",
    "analysis.charge_projection",
    "bands",
    "dos",
    "phonon",
    "epc",
    "tc",
)

PDOS_REQUIRED_OUTPUT_FIELDS = (
    "job_done",
    "projection_file_count",
    "energy_grid_count",
    "energy_min_ev",
    "energy_max_ev",
)

__all__ = [
    "PDOS_TASK",
    "PDOS_TASK_LEGACY",
    "PDOS_BASE_DOWNSTREAMS",
    "PDOS_DOWNSTREAMS",
    "PDOS_REQUIRED_OUTPUT_FIELDS",
]
