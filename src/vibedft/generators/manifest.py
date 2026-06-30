"""Manifest data models for generated workflow plans."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class StageKind(str, enum.Enum):
    RELAX = "relax"
    SCF = "scf"
    BANDS = "bands"
    NSCF_DOS = "nscf_dos"
    DOS = "dos"
    PROJWFC = "projwfc"
    PH_STABILITY = "ph_stability"
    Q2R = "q2r"
    MATDYN_DISP = "matdyn_disp"
    PH_EPC = "ph_epc"
    LAMBDA = "lambda"
    MATDYN_DOS = "matdyn_dos"


@dataclass
class StageSpec:
    """Specification for one stage in the workflow."""
    id: str                          # e.g. "01_relax"
    kind: StageKind
    directory: str                   # relative path
    depends_on: list[str] = field(default_factory=list)
    template: str = ""               # Jinja2 template name
    executable: str = ""             # QE binary name
    input_file: str = ""             # output .in filename
    output_file: str = ""            # expected .out filename
    cores: int = 14                  # MPI ranks
    walltime: str = "02:00:00"
    pre_commands: list[str] = field(default_factory=list)


@dataclass
class ClusterProfile:
    """Cluster configuration constraints."""
    name: str
    partition: str = "debug"
    qe_bin_dir: str = "<QE_BIN_DIR>"
    intel_setvars: str = "<INTEL_SETVARS_SCRIPT>"
    pseudo_dir: str = "<PSEUDO_DIR>"
    launcher: str = "srun"  # srun (default) | mpirun (legacy)
    allowed_cores: list[int] = field(default_factory=lambda: [7, 14, 28, 56])
    max_cores: int = 56
    max_nodes: int = 1

    def validate_cores(self, cores: int) -> int:
        """Clamp cores to nearest allowed value."""
        if cores in self.allowed_cores:
            return cores
        for allowed in sorted(self.allowed_cores):
            if cores <= allowed:
                return allowed
        return self.max_cores


@dataclass
class WorkflowPlan:
    """A complete workflow plan with ordered stages, cluster config, and parameters."""
    plan_id: str
    engine: str = "qe"
    structure_file: str = ""
    output_root: str = ""
    profile: ClusterProfile = field(default_factory=lambda: ClusterProfile(name="debug"))
    stages: list[StageSpec] = field(default_factory=list)
    common_params: dict[str, Any] = field(default_factory=dict)
    k_grids: dict[str, list[int]] = field(default_factory=dict)
    q_grids: dict[str, list[int]] = field(default_factory=dict)

    def to_manifest(self) -> dict[str, Any]:
        """Serialise to manifest.json format."""
        return {
            "plan_id": self.plan_id,
            "engine": self.engine,
            "structure_file": self.structure_file,
            "output_root": self.output_root,
            "profile": {
                "name": self.profile.name,
                "partition": self.profile.partition,
                "max_cores": self.profile.max_cores,
            },
            "stages": [
                {
                    "id": s.id, "kind": s.kind.value,
                    "directory": s.directory, "depends_on": s.depends_on,
                    "cores": s.cores, "walltime": s.walltime,
                }
                for s in self.stages
            ],
            "parameters": {
                "k_grids": self.k_grids,
                "q_grids": self.q_grids,
                "common": {k: v for k, v in self.common_params.items()
                          if k not in ("k_grids", "q_grids")},
            },
        }


# ── Predefined profiles ──

CLUSTER_DEBUG = ClusterProfile(
    name="cluster_debug",
    partition="debug",
    allowed_cores=[7, 14, 28, 56],
    max_cores=56,
)

CLUSTER_PROD = ClusterProfile(
    name="cluster_prod",
    partition="production",
    allowed_cores=[28, 56, 112, 224],
    max_cores=224,
    max_nodes=2,
)
