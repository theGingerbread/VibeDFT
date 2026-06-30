"""Fixture manifest loading for evidence-backed regression data."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from vibedft.research.models import (
    ArtifactType,
    EvidenceRef,
    FixtureManifest,
    ReliabilityLevel,
)


def load_fixture_manifest(path: str | Path) -> FixtureManifest:
    """Load a small JSON fixture manifest without importing heavy artifacts."""

    manifest_path = Path(path)
    if not manifest_path.exists():
        return FixtureManifest(
            id=manifest_path.stem,
            source=str(manifest_path),
            blockers=["fixture manifest file not found"],
        )

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return FixtureManifest(
            id=manifest_path.stem,
            source=str(manifest_path),
            blockers=[f"fixture manifest JSON parse failed: {exc.msg}"],
        )

    return fixture_manifest_from_dict(data, source_path=manifest_path)


def fixture_manifest_from_dict(data: Any, source_path: str | Path | None = None) -> FixtureManifest:
    """Build a :class:`FixtureManifest` from parsed JSON data."""

    fallback_source = str(source_path or "")
    if not isinstance(data, dict):
        return FixtureManifest(
            id=Path(fallback_source).stem if fallback_source else "",
            source=fallback_source,
            blockers=["fixture manifest must be a JSON object"],
        )

    artifacts = []
    manifest_blockers = _as_list(data.get("blockers"))
    for index, item in enumerate(data.get("artifacts") or []):
        if not isinstance(item, dict):
            manifest_blockers.append(f"artifact[{index}] must be a JSON object")
            continue
        artifacts.append(_evidence_ref_from_dict(item))

    return FixtureManifest(
        id=str(data.get("id") or (Path(fallback_source).stem if fallback_source else "")),
        source=str(data.get("source") or fallback_source),
        artifacts=artifacts,
        import_policy=str(data.get("import_policy") or "metadata_only"),
        description=str(data.get("description") or ""),
        warnings=_as_list(data.get("warnings")),
        blockers=manifest_blockers,
        metadata=_as_dict(data.get("metadata")),
    )


def _evidence_ref_from_dict(data: dict[str, Any]) -> EvidenceRef:
    blockers = _as_list(data.get("blockers"))
    warnings = _as_list(data.get("warnings"))
    artifact_path = str(data.get("artifact_path") or "")
    raw_value = data.get("raw_value")

    if not artifact_path:
        blockers.append("artifact_path is required")
    if _is_non_finite(raw_value):
        blockers.append("raw_value is non-finite")

    artifact_type, artifact_type_warning = _artifact_type(data.get("artifact_type"))
    if artifact_type_warning:
        warnings.append(artifact_type_warning)

    reliability, reliability_warning = _reliability(data.get("reliability"))
    if reliability_warning:
        warnings.append(reliability_warning)

    return EvidenceRef(
        artifact_path=artifact_path,
        artifact_type=artifact_type,
        parser_name=str(data.get("parser_name") or "manifest"),
        parsed_quantity=str(data.get("parsed_quantity") or "artifact_metadata"),
        raw_value=raw_value,
        summary=str(data.get("summary") or ""),
        warnings=warnings,
        blockers=blockers,
        confidence=data.get("confidence"),
        reliability=reliability,
        artifact_id=str(data.get("artifact_id") or ""),
        server=str(data.get("server") or ""),
        checksum=str(data.get("checksum") or ""),
        sample=str(data.get("sample") or ""),
        metadata=_as_dict(data.get("metadata")),
    )


def _artifact_type(value: Any) -> tuple[ArtifactType, str]:
    if isinstance(value, ArtifactType):
        return value, ""
    try:
        return ArtifactType(str(value or ArtifactType.UNKNOWN.value)), ""
    except ValueError:
        return ArtifactType.UNKNOWN, f"unknown artifact_type: {value}"


def _reliability(value: Any) -> tuple[ReliabilityLevel, str]:
    if isinstance(value, ReliabilityLevel):
        return value, ""
    try:
        return ReliabilityLevel(str(value or ReliabilityLevel.UNKNOWN.value)), ""
    except ValueError:
        return ReliabilityLevel.UNKNOWN, f"unknown reliability: {value}"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_non_finite(value: Any) -> bool:
    return isinstance(value, float) and not math.isfinite(value)
