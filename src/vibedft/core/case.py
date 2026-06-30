from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from vibedft.core.registry import Registry


def init_case(
    *,
    registry: Registry,
    software: str,
    workflow: str,
    material: str,
    profile: str,
    case_id: str,
    output_dir: Path | str,
) -> Path:
    case_dir = Path(output_dir) / case_id
    (case_dir / "input").mkdir(parents=True, exist_ok=True)
    (case_dir / "output").mkdir(parents=True, exist_ok=True)
    (case_dir / "logs").mkdir(parents=True, exist_ok=True)
    resolved = registry.resolve_parameters(
        software=software,
        workflow=workflow,
        material=material,
        profile=profile,
    )
    metadata = {
        "case_id": case_id,
        "software": software,
        "workflow": workflow,
        "material": material,
        "profile": profile,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution": {
            "scheduler": "slurm",
            "direct_remote_execution_allowed": False,
            "required_commands": ["scp", "sbatch", "squeue/sacct", "scp", "vibedft analyze"],
        },
        "parameters": {key: {"value": value["value"], "source": value["source"]} for key, value in resolved.items()},
    }
    (case_dir / "vibedft.case.yaml").write_text(
        yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (case_dir / "logs" / "calculation.md").write_text(
        _initial_log(case_id=case_id, software=software, workflow=workflow, material=material),
        encoding="utf-8",
    )
    return case_dir


def _initial_log(*, case_id: str, software: str, workflow: str, material: str) -> str:
    return f"""# VibeDFT Calculation Log

## Case

- Case ID: `{case_id}`
- Software: `{software}`
- Workflow: `{workflow}`
- Material: `{material}`

## Execution Policy

Slurm is required for every server-side calculation.

- Direct execution on the remote login node is forbidden.
- The local machine renders and validates input files.
- The workflow must scp input bundle to server.
- The remote calculation must be submitted with `sbatch`.
- The job status must be checked with `squeue` or `sacct`.
- Results must be copied back locally before post-processing.
- Local post-processing must record parser outputs and warnings.

## Timeline

| Time | Stage | Command | Status | Notes |
|---|---|---|---|---|
| pending | setup | vibedft setup build | pending | Parameter review window |
| pending | render | vibedft render | pending | Generate input files |
| pending | transfer-up | scp input bundle to server | pending | Required |
| pending | submit | sbatch job.slurm | pending | Required |
| pending | monitor | squeue/sacct | pending | Required |
| pending | transfer-down | scp results back | pending | Required |
| pending | analyze | vibedft analyze | pending | Local post-processing |
"""
