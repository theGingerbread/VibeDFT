"""Schema helpers for QE dos review/clean stages."""

DOS_TASK = "qe.dos"
DOS_TASK_LEGACY = "dos"

DOS_BASE_DOWNSTREAMS = (
    "analysis.dos",
)

DOS_DOWNSTREAMS = (
    "analysis.dos",
    "pdos",
    "bands",
    "phonon",
    "dielectric",
    "epc",
    "tc",
)

DOS_REQUIRED_OUTPUT_FIELDS = (
    "job_done",
    "energy_grid_count",
    "energy_min_ev",
    "energy_max_ev",
    "dos_max",
)

__all__ = [
    "DOS_TASK",
    "DOS_TASK_LEGACY",
    "DOS_BASE_DOWNSTREAMS",
    "DOS_DOWNSTREAMS",
    "DOS_REQUIRED_OUTPUT_FIELDS",
]
