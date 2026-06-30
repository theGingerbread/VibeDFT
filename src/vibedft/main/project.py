"""Project layout placeholders for the VibeDFT v2 platform."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProjectLayout:
    """Minimal location contract for a VibeDFT project."""

    root: Path
    inputs_dir: Path
    runs_dir: Path
    results_dir: Path

    @classmethod
    def from_root(cls, root: Path | str) -> "ProjectLayout":
        root_path = Path(root)
        return cls(
            root=root_path,
            inputs_dir=root_path / "inputs",
            runs_dir=root_path / "runs",
            results_dir=root_path / "results",
        )
