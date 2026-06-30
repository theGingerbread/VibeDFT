"""Lineage compatibility checks for research artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from vibedft.research.models import ArtifactLineage, ArtifactType


@dataclass(frozen=True)
class CompatibilityResult:
    """Result of comparing two artifact parameter fingerprints."""

    compatible: bool
    reason: str


def parameter_fingerprints_compatible(
    left: ArtifactLineage,
    right: ArtifactLineage,
    allowed_differences: Iterable[str] | None = None,
) -> CompatibilityResult:
    """Compare ``key=value`` parts in two artifact parameter fingerprints.

    By default every key present in either artifact must match exactly.  Keys in
    ``allowed_differences`` are ignored so callers can explicitly compare
    controlled sweeps such as strain or doping while keeping all other
    parameters fixed.
    """

    allowed = set(allowed_differences or [])
    left_parts = _fingerprint_parts(left.parameter_fingerprint)
    right_parts = _fingerprint_parts(right.parameter_fingerprint)
    keys = sorted((set(left_parts) | set(right_parts)) - allowed)

    differences: list[str] = []
    for key in keys:
        left_value = left_parts.get(key)
        right_value = right_parts.get(key)
        if left_value != right_value:
            differences.append(
                f"{key}: {key}={left_value if left_value is not None else '<missing>'} "
                f"vs {key}={right_value if right_value is not None else '<missing>'}"
            )

    if differences:
        return CompatibilityResult(False, "Parameter fingerprints differ: " + "; ".join(differences))

    ignored = f"; allowed differences ignored: {', '.join(sorted(allowed))}" if allowed else ""
    return CompatibilityResult(True, f"Parameter fingerprints are compatible{ignored}.")


def detect_case_lineage_warnings(artifacts: Iterable[ArtifactLineage]) -> list[str]:
    """Return deterministic lineage warnings visible across a case's artifacts."""

    warnings: list[str] = []
    for artifact in artifacts:
        for warning in artifact.lineage_warnings:
            _append_unique(warnings, f"{artifact.artifact_id}: {warning}")

        if artifact.outdir and _looks_like_old_save(artifact.outdir):
            _append_unique(
                warnings,
                f"{artifact.artifact_id}: references old save directory via outdir={artifact.outdir}",
            )

        if _is_planar_average_artifact(artifact):
            _append_unique(
                warnings,
                f"{artifact.artifact_id}: planar average artifact requires grid-aware provenance checks",
            )
            for text_warning in _planar_average_text_warnings(artifact):
                _append_unique(warnings, f"{artifact.artifact_id}: {text_warning}")

        if _needs_2d_marker_warning(artifact):
            _append_unique(
                warnings,
                f"{artifact.artifact_id}: missing 2D electrostatic marker in pw.x input fingerprint",
            )

    return warnings


def _fingerprint_parts(fingerprint: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for item in fingerprint.split("|"):
        item = item.strip()
        if not item:
            continue
        key, sep, value = item.partition("=")
        if not sep:
            parts[key.strip()] = ""
        else:
            parts[key.strip()] = value.strip()
    return parts


def _looks_like_old_save(value: str) -> bool:
    normalized = value.lower().replace("-", "_")
    return "old" in normalized and ("save" in normalized or "scf" in normalized or "out" in normalized)


def _is_planar_average_artifact(artifact: ArtifactLineage) -> bool:
    text = f"{artifact.artifact_id} {artifact.path} {artifact.producer_program}".lower()
    return "planar_average" in text or "planar average" in text or "average.x" in text


def _planar_average_text_warnings(artifact: ArtifactLineage) -> list[str]:
    path = Path(artifact.path)
    if not path.is_file():
        return []

    text = path.read_text(encoding="utf-8", errors="replace").lower()
    warnings: list[str] = []
    if "fixed 600-line blocks" in text or "600-line" in text:
        warnings.append("planar average log mentions fixed 600-line blocks")
    if "old save" in text or "old_scf_save" in text:
        warnings.append("planar average log references old save provenance")
    if "vacuum plateau fluctuation" in text:
        warnings.append("planar average log reports vacuum plateau fluctuation")
    if re.search(r"\bdelta\s*v\b", text):
        warnings.append("planar average log contains reported deltaV; verify provenance before reuse")
    return warnings


def _needs_2d_marker_warning(artifact: ArtifactLineage) -> bool:
    if artifact.artifact_type != ArtifactType.INPUT:
        return False
    if artifact.producer_program != "pw.x":
        return False
    if not artifact.parameter_fingerprint:
        return False

    parts = _fingerprint_parts(artifact.parameter_fingerprint)
    return "2d" not in parts and "assume_isolated" not in parts and "esm" not in parts


def _append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)
