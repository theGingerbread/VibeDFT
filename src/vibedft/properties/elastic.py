"""Evidence-backed 2D elastic tensor and mechanical stability analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibedft.research.models import (
    AnalysisResult,
    ArtifactType,
    EvidenceRef,
    PhysicsDescriptor,
    ReliabilityLevel,
    ResultStatus,
)


@dataclass
class ElasticTensor2D:
    """Minimal in-plane 2D elastic tensor summary."""

    c11_n_per_m: float | None = None
    c12_n_per_m: float | None = None
    c66_n_per_m: float | None = None
    source: str = ""
    strain_points: int | None = None
    source_file: str = ""
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return (
            self.c11_n_per_m is not None
            and self.c12_n_per_m is not None
            and self.c66_n_per_m is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "C11_N_per_m": self.c11_n_per_m,
            "C12_N_per_m": self.c12_n_per_m,
            "C66_N_per_m": self.c66_n_per_m,
            "source": self.source,
            "strain_points": self.strain_points,
            "source_file": self.source_file,
            "parse_errors": list(self.parse_errors),
        }


def parse_elastic_tensor_summary(filepath: Path | str) -> ElasticTensor2D:
    """Parse a small key-value file with 2D elastic constants."""

    path = Path(filepath)
    tensor = ElasticTensor2D(source_file=str(path))
    if not path.is_file():
        tensor.parse_errors.append(f"elastic tensor summary not found: {path}")
        return tensor

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
        elif "=" in stripped:
            key, value = stripped.split("=", 1)
        else:
            continue
        values[_normalize_key(key)] = value.strip()

    tensor.c11_n_per_m = _optional_float(
        values.get("c11nperm") or values.get("c11")
    )
    tensor.c12_n_per_m = _optional_float(
        values.get("c12nperm") or values.get("c12")
    )
    tensor.c66_n_per_m = _optional_float(
        values.get("c66nperm") or values.get("c66")
    )
    tensor.source = values.get("source", "")
    tensor.strain_points = _optional_int(values.get("strainpoints"))

    if tensor.c11_n_per_m is None:
        tensor.parse_errors.append("elastic tensor summary is missing C11_N_per_m")
    if tensor.c12_n_per_m is None:
        tensor.parse_errors.append("elastic tensor summary is missing C12_N_per_m")
    if tensor.c66_n_per_m is None:
        tensor.parse_errors.append("elastic tensor summary is missing C66_N_per_m")
    return tensor


def analyze_mechanical_stability(
    *, elastic_tensor_path: Path | str | None = None
) -> AnalysisResult:
    """Build conservative 2D mechanical stability descriptors."""

    warnings: list[str] = []
    blockers: list[str] = []
    evidence: list[EvidenceRef] = []
    tensor = ElasticTensor2D()

    if elastic_tensor_path is None:
        blockers.append(
            "strain-sweep elastic tensor evidence is required for mechanical stability"
        )
    else:
        tensor = parse_elastic_tensor_summary(elastic_tensor_path)
        blockers.extend(tensor.parse_errors)
        evidence.append(_tensor_evidence_ref(elastic_tensor_path, tensor))

    source_lower = tensor.source.lower()
    has_strain_sweep_source = "strain" in source_lower and "sweep" in source_lower
    source_is_md_stress = "md" in source_lower and "stress" in source_lower

    if tensor.has_data and source_is_md_stress:
        blockers.append(
            "MD stress time series cannot be used as elastic tensor or strain-sweep evidence"
        )
    elif tensor.has_data and not has_strain_sweep_source:
        blockers.append(
            "strain-sweep source metadata is required before applying 2D Born criteria"
        )

    if tensor.has_data and has_strain_sweep_source:
        if tensor.strain_points is None or tensor.strain_points < 3:
            blockers.append(
                "strain sweep must include at least three strain points before mechanical stability claims"
            )

    born_criteria = _born_criteria_2d(tensor)
    youngs_modulus = _youngs_modulus_2d(tensor)
    poisson_ratio = _poisson_ratio_2d(tensor)
    born_failed = tensor.has_data and has_strain_sweep_source and not all(
        born_criteria.values()
    )
    if born_failed:
        failed = ", ".join(name for name, passed in born_criteria.items() if not passed)
        blockers.append(f"2D Born criterion failed: {failed}")

    classification = _classification(
        tensor=tensor,
        has_strain_sweep_source=has_strain_sweep_source,
        source_is_md_stress=source_is_md_stress,
        born_failed=born_failed,
    )
    descriptors = [
        PhysicsDescriptor(
            name="elastic_tensor_2d",
            value=tensor.to_dict(),
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=_descriptor_reliability(tensor, blockers),
        ),
        PhysicsDescriptor(
            name="born_criteria_2d",
            value=born_criteria,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=_descriptor_reliability(tensor, blockers),
        ),
        PhysicsDescriptor(
            name="youngs_modulus_2d_N_per_m",
            value=youngs_modulus,
            unit="N/m",
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=_descriptor_reliability(tensor, blockers),
        ),
        PhysicsDescriptor(
            name="poisson_ratio_2d",
            value=poisson_ratio,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=_descriptor_reliability(tensor, blockers),
        ),
        PhysicsDescriptor(
            name="mechanical_stability_classification",
            value=classification,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=_descriptor_reliability(tensor, blockers),
        ),
    ]

    if not tensor.has_data or elastic_tensor_path is None:
        status = ResultStatus.INSUFFICIENT_EVIDENCE
    elif blockers:
        status = ResultStatus.BLOCKED
    else:
        status = ResultStatus.PASS

    return AnalysisResult(
        id="analysis.mechanical_stability",
        parser_name="vibedft.properties.elastic.analyze_mechanical_stability",
        status=status,
        parsed_quantity="mechanical_stability",
        evidence=evidence,
        descriptors=descriptors,
        raw_value={
            "elastic_tensor_2d": tensor.to_dict(),
            "born_criteria_2d": born_criteria,
            "youngs_modulus_2d_N_per_m": youngs_modulus,
            "poisson_ratio_2d": poisson_ratio,
            "classification": classification,
        },
        summary="Evidence-backed 2D elastic tensor and mechanical stability gate.",
        warnings=warnings,
        blockers=blockers,
        reliability=(
            ReliabilityLevel.MEDIUM
            if status == ResultStatus.PASS
            else ReliabilityLevel.LOW
        ),
        metadata={
            "forbidden_conclusions": _forbidden_conclusions(status, blockers),
        },
    )


def _tensor_evidence_ref(path: Path | str, tensor: ElasticTensor2D) -> EvidenceRef:
    return EvidenceRef(
        artifact_path=str(path),
        artifact_type=ArtifactType.OUTPUT,
        parser_name="vibedft.properties.elastic.parse_elastic_tensor_summary",
        parsed_quantity="elastic_tensor_2d",
        raw_value=tensor.to_dict(),
        summary=(
            f"C11={tensor.c11_n_per_m}, C12={tensor.c12_n_per_m}, "
            f"C66={tensor.c66_n_per_m}, source={tensor.source or 'unknown'}"
        ),
        blockers=list(tensor.parse_errors),
        reliability=ReliabilityLevel.MEDIUM if tensor.has_data else ReliabilityLevel.LOW,
    )


def _born_criteria_2d(tensor: ElasticTensor2D) -> dict[str, bool]:
    if not tensor.has_data:
        return {
            "C11_positive": False,
            "C66_positive": False,
            "C11_minus_C12_positive": False,
        }
    c11 = tensor.c11_n_per_m or 0.0
    c12 = tensor.c12_n_per_m or 0.0
    c66 = tensor.c66_n_per_m or 0.0
    return {
        "C11_positive": c11 > 0.0,
        "C66_positive": c66 > 0.0,
        "C11_minus_C12_positive": (c11 - c12) > 0.0,
    }


def _youngs_modulus_2d(tensor: ElasticTensor2D) -> float | None:
    if not tensor.has_data or tensor.c11_n_per_m in {None, 0.0}:
        return None
    c11 = tensor.c11_n_per_m
    c12 = tensor.c12_n_per_m or 0.0
    return round((c11**2 - c12**2) / c11, 6)


def _poisson_ratio_2d(tensor: ElasticTensor2D) -> float | None:
    if not tensor.has_data or tensor.c11_n_per_m in {None, 0.0}:
        return None
    return round((tensor.c12_n_per_m or 0.0) / tensor.c11_n_per_m, 6)


def _classification(
    *,
    tensor: ElasticTensor2D,
    has_strain_sweep_source: bool,
    source_is_md_stress: bool,
    born_failed: bool,
) -> str:
    if not tensor.has_data or not has_strain_sweep_source or source_is_md_stress:
        return "insufficient_evidence"
    if born_failed:
        return "mechanically_unstable"
    return "mechanically_stable"


def _descriptor_reliability(
    tensor: ElasticTensor2D, blockers: list[str]
) -> ReliabilityLevel:
    if tensor.has_data and not blockers:
        return ReliabilityLevel.MEDIUM
    return ReliabilityLevel.LOW


def _forbidden_conclusions(
    status: ResultStatus, blockers: list[str]
) -> list[str]:
    if status == ResultStatus.PASS and not blockers:
        return []
    return [
        "Do not claim mechanical stability without strain-sweep elastic tensor evidence.",
        "Do not infer Born stability from MD stress time series.",
    ]


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0).replace("D", "E").replace("d", "e"))
    except ValueError:
        return None


def _optional_int(value: str | None) -> int | None:
    parsed = _optional_float(value)
    if parsed is None:
        return None
    return int(parsed)
