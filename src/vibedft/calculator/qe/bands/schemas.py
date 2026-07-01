"""Schema helpers for QE bands review/clean stages."""

BANDS_TASK = "qe.bands"
BANDS_TASK_LEGACY = "bands"

BANDS_BASE_DOWNSTREAMS = (
    "analysis.bands",
    "analysis.bandgap",
)

BANDS_DOWNSTREAMS = (
    "analysis.bands",
    "analysis.bandgap",
    "scf",
    "relax",
    "vc_relax",
    "nscf",
    "dos",
    "pdos",
    "pp",
    "phonon",
    "dielectric",
    "epc",
    "tc",
)

BANDS_REQUIRED_OUTPUT_FIELDS = (
    "job_done",
    "band_data_present",
    "band_count",
    "k_point_count",
)

__all__ = [
    "BANDS_TASK",
    "BANDS_TASK_LEGACY",
    "BANDS_BASE_DOWNSTREAMS",
    "BANDS_DOWNSTREAMS",
    "BANDS_REQUIRED_OUTPUT_FIELDS",
]
