"""Read-only artifact scanner for research lineage records."""

from __future__ import annotations

import re
from pathlib import Path

from vibedft.parsers.qe_input_parser import parse_qe_input
from vibedft.research.models import ArtifactLineage, ArtifactType


def scan_case(case_dir: str | Path, server: str = "local") -> list[ArtifactLineage]:
    """Scan a local case directory for QE artifacts without modifying it.

    The scanner intentionally only reads local files through :mod:`pathlib`.
    It does not run QE, shell commands, Slurm commands, or remote operations.
    """

    root = Path(case_dir)
    artifacts: list[ArtifactLineage] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".in":
            artifacts.append(_scan_input(root, path, server))
        elif path.suffix in {".out", ".freq"}:
            artifacts.append(_scan_output(root, path, server))
        elif path.suffix == ".log" and _output_type(path) == ArtifactType.REPORT:
            artifacts.append(_scan_output(root, path, server))

    return artifacts


def _scan_input(root: Path, path: Path, server: str) -> ArtifactLineage:
    qe_input = parse_qe_input(path)
    parse_status = "failed" if qe_input.parse_errors else "ok"

    return ArtifactLineage(
        artifact_id=_artifact_id(root, path, ArtifactType.INPUT),
        artifact_type=ArtifactType.INPUT,
        server=server,
        path=str(path),
        producer_program=qe_input.program.value,
        prefix=str(qe_input.get_param("control", "prefix", "") or ""),
        outdir=str(qe_input.get_param("control", "outdir", "") or ""),
        parameter_fingerprint=_parameter_fingerprint(qe_input),
        parse_status=parse_status,
        lineage_warnings=list(qe_input.parse_errors),
    )


def _scan_output(root: Path, path: Path, server: str) -> ArtifactLineage:
    text = path.read_text(encoding="utf-8", errors="replace")
    artifact_type = _output_type(path)

    return ArtifactLineage(
        artifact_id=_artifact_id(root, path, artifact_type),
        artifact_type=artifact_type,
        server=server,
        path=str(path),
        producer_program=_producer_program(text, path),
        job_status=_job_status(text),
        parse_status="ok",
    )


def _artifact_id(root: Path, path: Path, artifact_type: ArtifactType) -> str:
    rel = path.relative_to(root)
    namespace = "input" if artifact_type == ArtifactType.INPUT else "output"
    canonical_container = "inputs" if artifact_type == ArtifactType.INPUT else "outputs"
    parts = rel.parts[1:] if len(rel.parts) > 1 and rel.parts[0] == canonical_container else rel.parts
    return ".".join([namespace, *parts])


def _parameter_fingerprint(qe_input) -> str:
    system = qe_input.namelists.get("system")
    parts: list[str] = []

    if system is not None:
        if "ecutwfc" in system.params:
            parts.append(f"ecutwfc={system.params['ecutwfc']}")
        if "ecutrho" in system.params:
            parts.append(f"ecutrho={system.params['ecutrho']}")

    kmesh = _kmesh(qe_input)
    if kmesh:
        parts.append(f"k={kmesh}")

    return "|".join(parts)


def _kmesh(qe_input) -> str:
    card = qe_input.cards.get("K_POINTS")
    if card is None or card.option != "automatic" or not card.rows:
        return ""

    row = card.rows[0]
    if len(row) < 3:
        return ""
    return "x".join(row[:3])


def _output_type(path: Path) -> ArtifactType:
    name = path.name.lower()
    if "planar_average" in name or "planar-average" in name or "planaraverage" in name:
        return ArtifactType.REPORT
    if name == "lambdax.out" or "lambdax" in name:
        return ArtifactType.LAMBDAX
    if name.endswith(".freq"):
        return ArtifactType.DYN
    return ArtifactType.OUTPUT


def _producer_program(text: str, path: Path) -> str:
    lower_name = path.name.lower()
    if "lambdax" in lower_name:
        return "lambda.x"
    if re.search(r"\bPWSCF\b", text, re.IGNORECASE):
        return "pw.x"
    if re.search(r"\bPHONON\b|\bPH\.X\b", text, re.IGNORECASE):
        return "ph.x"
    return ""


def _job_status(text: str) -> str:
    return "JOB_DONE" if "JOB DONE" in text.upper() else ""
