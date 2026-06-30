"""Deterministic claim templates for common VibeDFT research routes."""

from __future__ import annotations

import re

from vibedft.research.models import ClaimType, Route, ScientificClaim


def build_route_claims(
    route: Route,
    material_label: str,
    question_id: str | None = None,
) -> list[ScientificClaim]:
    """Build deterministic starter claims for a scientific workflow route."""

    material_slug = _slug(material_label)
    resolved_question_id = question_id or f"rq.{material_slug}.{route.value}"

    if route == Route.INTERCALATION:
        return [
            _claim(
                material_slug,
                resolved_question_id,
                ClaimType.NEGATIVE_RESULT,
                "negative_result",
                (
                    f"{material_label} can be reported as a negative result when signed phonon "
                    "evidence shows a dynamical instability."
                ),
            ),
            _claim(
                material_slug,
                resolved_question_id,
                ClaimType.EPC_MECHANISM,
                "epc",
                (
                    f"{material_label} has an EPC mechanism claim only if full-q dynamical "
                    "stability and EPC post-processing evidence pass deterministic gates."
                ),
            ),
        ]

    if route == Route.TYPE3_HETEROSTRUCTURE:
        return [
            _claim(
                material_slug,
                resolved_question_id,
                ClaimType.BAND_ALIGNMENT,
                "band_alignment",
                (
                    f"{material_label} has a Type-III band-alignment claim only under an "
                    "explicit SOC-consistent electronic structure comparison."
                ),
            )
        ]

    if route == Route.STATIC_DOPING:
        return [
            _claim(
                material_slug,
                resolved_question_id,
                ClaimType.STABILITY,
                "stability",
                (
                    f"{material_label} is dynamically stable under the static-doping protocol "
                    "only when signed phonon evidence passes the stability gate."
                ),
            ),
            _claim(
                material_slug,
                resolved_question_id,
                ClaimType.TC_ROBUSTNESS,
                "tc_robustness",
                (
                    f"{material_label} has a robust Tc trend only when stability, EPC, and "
                    "comparison controls are simultaneously satisfied."
                ),
            ),
        ]

    return []


def _claim(
    material_slug: str,
    question_id: str,
    claim_type: ClaimType,
    claim_slug: str,
    statement: str,
) -> ScientificClaim:
    return ScientificClaim(
        id=f"claim.{material_slug}.{claim_slug}",
        question_id=question_id,
        claim_type=claim_type,
        statement=statement,
        gate_policy_id=f"gate.{claim_type.value}",
    )


def _slug(label: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^0-9A-Za-z]+", "_", label).strip("_").lower())
