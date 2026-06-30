"""Property analyzer framework — plugs into existing artifact/report/agent pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibedft.postprocess.artifacts import Artifact


@dataclass
class PropertyResult:
    """One property analysis result with data, insights, and evidence."""
    property_name: str
    status: str = "missing"       # ok | missing | error
    data: dict[str, Any] = field(default_factory=dict)
    insights: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_artifact(self) -> Artifact | None:
        """Convert to an Artifact for report integration."""
        if self.status == "missing":
            return None
        if self.data:
            return Artifact.json_artifact(
                id=f"property.{self.property_name}",
                title=self.property_name.replace("_", " ").title(),
                payload={"status": self.status, "data": self.data,
                         "insights": self.insights},
                source_files=self.source_files,
            )
        return None


@dataclass
class PropertyBundle:
    """All property analyses for one case directory."""
    case_dir: str = ""
    properties: dict[str, PropertyResult] = field(default_factory=dict)

    @property
    def all_artifacts(self) -> list[Artifact]:
        arts: list[Artifact] = []
        for pr in self.properties.values():
            a = pr.to_artifact()
            if a:
                arts.append(a)
        return arts

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_dir": self.case_dir,
            "properties": {
                k: {
                    "status": v.status, "data": v.data,
                    "insights": v.insights, "errors": v.errors,
                }
                for k, v in self.properties.items()
            }
        }


def analyze_all_properties(case_dir: Path | str) -> PropertyBundle:
    """Run all available property analyzers on a case directory."""
    d = Path(case_dir).resolve()
    bundle = PropertyBundle(case_dir=str(d))

    # Work function
    from vibedft.properties.work_function import analyze_work_function
    bundle.properties["work_function"] = analyze_work_function(d)

    # Bader charge
    from vibedft.properties.bader_parser import analyze_bader
    bundle.properties["bader_charge"] = analyze_bader(d)

    # ELF
    from vibedft.properties.elf_analyzer import analyze_elf
    bundle.properties["elf"] = analyze_elf(d)

    # AIMD stability
    from vibedft.properties.aimd_analyzer import analyze_aimd
    bundle.properties["aimd_stability"] = analyze_aimd(d)

    return bundle
