"""Claim-specific deterministic gate evaluation for research artifacts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from vibedft.research.models import (
    ArtifactLineage,
    ArtifactType,
    ClaimType,
    EvidenceMaturity,
    GateDecision,
    GateVerdict,
    ScientificClaim,
)


@dataclass(frozen=True)
class FrequencyEvidence:
    """Signed phonon frequency evidence parsed from an artifact."""

    artifact_id: str
    frequency_cm1: float
    q_point: tuple[float, float, float] | None = None

    @property
    def is_finite_q(self) -> bool:
        if self.q_point is None:
            return False
        return any(not math.isclose(component, 0.0, abs_tol=1.0e-8) for component in self.q_point)


@dataclass(frozen=True)
class EpcEvidence:
    """Minimal lambda.x evidence needed by gate policies."""

    artifact_id: str
    has_nan_epc_value: bool


def evaluate_claim(claim: ScientificClaim, artifacts: Iterable[ArtifactLineage]) -> GateDecision:
    """Evaluate whether available artifacts allow reporting ``claim``.

    The evaluator is intentionally claim-specific and conservative: negative
    frequencies remain signed evidence of dynamical instability, not values to
    absolutize away.
    """

    artifact_list = list(artifacts)
    frequencies = _collect_frequencies(artifact_list)
    negative_frequencies = [frequency for frequency in frequencies if frequency.frequency_cm1 < 0.0]
    epc_values = _collect_epc_evidence(artifact_list)
    supporting_ids = _supporting_artifact_ids(frequencies, epc_values)

    if claim.claim_type == ClaimType.NEGATIVE_RESULT and negative_frequencies:
        return GateDecision(
            claim_id=claim.id,
            maturity=EvidenceMaturity.PHYSICALLY_USABLE,
            verdict=GateVerdict.PASS,
            blocking_reasons=[_soft_mode_reason(negative_frequencies)],
            supporting_artifacts=supporting_ids,
            forbidden_conclusions=[
                "Do not report a stable-phase Tc or EPC conclusion from a structure with a soft mode."
            ],
            recommended_next_actions=[
                "Report the instability as a physically usable negative result and keep Tc/EPC out of conclusions."
            ],
        )

    if claim.claim_type in {ClaimType.EPC_MECHANISM, ClaimType.TC_ROBUSTNESS}:
        if negative_frequencies:
            return GateDecision(
                claim_id=claim.id,
                maturity=EvidenceMaturity.PHYSICALLY_USABLE,
                verdict=GateVerdict.BLOCKED,
                blocking_reasons=[_soft_mode_reason(negative_frequencies)],
                supporting_artifacts=supporting_ids,
                forbidden_conclusions=["Do not report Tc until dynamical stability passes."],
                recommended_next_actions=[
                    "Run mode-following for the soft mode and re-evaluate EPC/Tc only after stability passes."
                ],
            )

        if any(epc.has_nan_epc_value for epc in epc_values):
            return GateDecision(
                claim_id=claim.id,
                maturity=EvidenceMaturity.RUN_FINISHED,
                verdict=GateVerdict.BLOCKED,
                blocking_reasons=["lambda.x output contains NaN EPC/Tc values without a soft-mode explanation."],
                supporting_artifacts=supporting_ids,
                forbidden_conclusions=["Do not report Tc or EPC mechanism from NaN lambda.x outputs."],
                recommended_next_actions=[
                    "Inspect lambda.x inputs and phonon stability evidence before re-running EPC/Tc post-processing."
                ],
            )

    if claim.claim_type == ClaimType.STABILITY:
        if negative_frequencies:
            return GateDecision(
                claim_id=claim.id,
                maturity=EvidenceMaturity.PHYSICALLY_USABLE,
                verdict=GateVerdict.FAIL,
                blocking_reasons=[_soft_mode_reason(negative_frequencies)],
                supporting_artifacts=supporting_ids,
                forbidden_conclusions=["Do not claim dynamical stability while any signed frequency is negative."],
                recommended_next_actions=["Follow or converge the soft mode before making a stability claim."],
            )

        if frequencies:
            return GateDecision(
                claim_id=claim.id,
                maturity=EvidenceMaturity.NUMERICALLY_CONVERGED,
                verdict=GateVerdict.PASS,
                supporting_artifacts=supporting_ids,
                recommended_next_actions=["Keep the signed frequency evidence with the stability claim."],
            )

    return GateDecision(
        claim_id=claim.id,
        maturity=EvidenceMaturity.RUN_FINISHED,
        verdict=GateVerdict.WARNING,
        supporting_artifacts=supporting_ids,
        missing_artifacts=["claim-specific evidence policy"],
        recommended_next_actions=["Add evidence or a deterministic gate policy for this claim type."],
    )


def _collect_frequencies(artifacts: list[ArtifactLineage]) -> list[FrequencyEvidence]:
    frequencies: list[FrequencyEvidence] = []
    for artifact in artifacts:
        if artifact.artifact_type not in {ArtifactType.DYN, ArtifactType.OUTPUT, ArtifactType.REPORT}:
            continue
        path = Path(artifact.path)
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".freq":
            frequencies.extend(_parse_matdyn_freq(artifact.artifact_id, text))
        else:
            frequencies.extend(_parse_output_frequencies(artifact.artifact_id, text))
    return frequencies


def _parse_matdyn_freq(artifact_id: str, text: str) -> list[FrequencyEvidence]:
    nbnd = _parse_matdyn_nbnd(text)
    if nbnd is not None:
        return _parse_matdyn_freq_with_nbnd(artifact_id, text, nbnd)

    frequencies: list[FrequencyEvidence] = []
    current_q: tuple[float, float, float] | None = None
    for line in text.splitlines():
        numbers = _float_values(line)
        if len(numbers) == 3:
            current_q = (numbers[0], numbers[1], numbers[2])
            continue
        if current_q is None:
            continue
        frequencies.extend(
            FrequencyEvidence(artifact_id=artifact_id, frequency_cm1=value, q_point=current_q)
            for value in numbers
        )
    return frequencies


def _parse_matdyn_nbnd(text: str) -> int | None:
    match = re.search(r"\bnbnd\s*=\s*(\d+)", text, re.IGNORECASE)
    if match is None:
        return None
    return int(match.group(1))


def _parse_matdyn_freq_with_nbnd(artifact_id: str, text: str, nbnd: int) -> list[FrequencyEvidence]:
    frequencies: list[FrequencyEvidence] = []
    current_q: tuple[float, float, float] | None = None
    current_values: list[float] = []

    for line in text.splitlines():
        numbers = _float_values(line)
        if not numbers:
            continue

        if current_q is None:
            if len(numbers) >= 3:
                current_q = (numbers[0], numbers[1], numbers[2])
                current_values = []
            continue

        current_values.extend(numbers)
        if len(current_values) >= nbnd:
            frequencies.extend(
                FrequencyEvidence(artifact_id=artifact_id, frequency_cm1=value, q_point=current_q)
                for value in current_values[:nbnd]
            )
            current_q = None
            current_values = []

    return frequencies


def _parse_output_frequencies(artifact_id: str, text: str) -> list[FrequencyEvidence]:
    q_point = _parse_q_point(text)
    frequencies: list[FrequencyEvidence] = []
    for line in text.splitlines():
        match = re.search(
            r"freq\s*\(\s*\d+\s*\)\s*=\s*"
            r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)"
            r"(?:\s*\[[^\]]+\])?"
            r"(?:\s*=\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)\s*\[cm-?1\])?",
            line,
            re.IGNORECASE,
        )
        if match is None:
            continue
        frequency_cm1 = match.group(2) if match.group(2) is not None else match.group(1)
        frequencies.append(
            FrequencyEvidence(
                artifact_id=artifact_id,
                frequency_cm1=float(frequency_cm1),
                q_point=q_point,
            )
        )
    return frequencies


def _parse_q_point(text: str) -> tuple[float, float, float] | None:
    match = re.search(
        r"(?:q\s*=|Dynamical matrices for)\s*\(?\s*"
        r"([-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?)\s+"
        r"([-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?)\s+"
        r"([-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?)",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return (float(match.group(1)), float(match.group(2)), float(match.group(3)))


def _collect_epc_evidence(artifacts: list[ArtifactLineage]) -> list[EpcEvidence]:
    epc_values: list[EpcEvidence] = []
    for artifact in artifacts:
        if artifact.artifact_type != ArtifactType.LAMBDAX:
            continue
        path = Path(artifact.path)
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        epc_values.append(EpcEvidence(artifact.artifact_id, bool(re.search(r"\bnan\b", text, re.IGNORECASE))))
    return epc_values


def _supporting_artifact_ids(
    frequencies: Iterable[FrequencyEvidence],
    epc_values: Iterable[EpcEvidence],
) -> list[str]:
    ids: list[str] = []
    for item in [*frequencies, *epc_values]:
        if item.artifact_id not in ids:
            ids.append(item.artifact_id)
    return ids


def _soft_mode_reason(negative_frequencies: list[FrequencyEvidence]) -> str:
    most_negative = min(negative_frequencies, key=lambda item: item.frequency_cm1)
    q_text = _q_point_text(most_negative.q_point)
    finite_q = "finite-q " if most_negative.is_finite_q else ""
    return f"{finite_q}soft mode detected: {most_negative.frequency_cm1:.6f} cm-1 at {q_text}."


def _q_point_text(q_point: tuple[float, float, float] | None) -> str:
    if q_point is None:
        return "unknown q"
    return f"q=({q_point[0]:.9g}, {q_point[1]:.9g}, {q_point[2]:.9g})"


def _float_values(text: str) -> list[float]:
    return [
        float(match)
        for match in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?", text)
    ]
