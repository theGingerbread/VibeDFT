"""VC-relax review policy and pass/warn/block judgment."""

from __future__ import annotations

from vibedft._shared.contracts import Evidence, ReviewResult

from vibedft.calculator.qe.relax import review_relax_output
from vibedft.calculator.qe.relax.parse import RelaxOutput
from vibedft.calculator.qe.vc_relax.schemas import VC_RELAX_BASE_DOWNSTREAMS, VC_RELAX_DOWNSTREAMS


def review_vc_relax_output(output: RelaxOutput) -> ReviewResult:
    """Evaluate VC-relax parsed output using strict relax+vc constraints."""

    base_result = review_relax_output(output)
    if base_result.status == "BLOCK":
        return ReviewResult(
            status="BLOCK",
            reasons=list(base_result.reasons),
            evidence=_augment_vc_evidence(base_result.evidence, output),
            allowed_downstream=[],
            blocked_downstream=list(VC_RELAX_DOWNSTREAMS),
            recommendations=list(base_result.recommendations),
        )

    evidence = _augment_vc_evidence(base_result.evidence, output)
    reasons: list[str] = list(base_result.reasons)
    recommendations: list[str] = list(base_result.recommendations)

    if not output.variable_cell:
        reasons.append("Variable-cell intent was not active for this run.")
        reasons.append("VC-relax follow-up is blocked for fixed-cell trajectories.")
        return ReviewResult(
            status="BLOCK",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=evidence,
            allowed_downstream=[],
            blocked_downstream=list(VC_RELAX_DOWNSTREAMS),
            recommendations=list(
                dict.fromkeys(
                    recommendations
                    + [
                        "Rerun as vc-relax with variable-cell settings and fixed-cell-disabled mode turned off."
                    ]
                )
            ),
        )

    final_structure = output.final_structure or {}
    final_cell = final_structure.get("cell_parameters")
    final_vectors = final_structure.get("lattice_vectors")
    if not final_cell and not final_vectors:
        reasons.append("Final cell geometry was not recovered from output.")
        return ReviewResult(
            status="BLOCK",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=_append_vc_evidence(evidence, output, "final_cell", final_structure),
            allowed_downstream=[],
            blocked_downstream=list(VC_RELAX_DOWNSTREAMS),
            recommendations=list(
                dict.fromkeys(
                    recommendations + ["Capture final cell geometry in vc-relax output before reuse."]
                )
            ),
        )

    warn_reasons: list[str] = []
    final_volume = final_structure.get("volume")
    if final_volume is None:
        warn_reasons.append("Final cell volume is missing from final structure summary.")

    final_pressure = output.final_observables.get("pressure")
    if final_pressure is None:
        warn_reasons.append("Final pressure is missing from vc-relax observables.")

    if _is_volume_change_suspicious(output):
        warn_reasons.append("Volume evolution is suspicious for production reuse.")

    if warn_reasons:
        reasons.extend(warn_reasons)
        return ReviewResult(
            status="WARN",
            reasons=sorted(dict.fromkeys(reasons)),
            evidence=_append_vc_evidence(
                evidence,
                output,
                "vc_relax_quality",
                {
                    "final_volume": final_volume,
                    "final_pressure": final_pressure,
                    "volume_delta": _latest_volume_delta(output),
                },
            ),
            allowed_downstream=list(VC_RELAX_BASE_DOWNSTREAMS),
            blocked_downstream=[
                name for name in VC_RELAX_DOWNSTREAMS if name not in VC_RELAX_BASE_DOWNSTREAMS
            ],
            recommendations=list(
                dict.fromkeys(
                    recommendations
                    + [
                        "Review stress/pressure and cell-convergence evidence before lattice-sensitive follow-up."
                    ]
                )
            ),
        )

    return ReviewResult(
        status=base_result.status,
        reasons=reasons,
        evidence=evidence,
        allowed_downstream=list(VC_RELAX_BASE_DOWNSTREAMS),
        blocked_downstream=[
            name for name in VC_RELAX_DOWNSTREAMS if name not in VC_RELAX_BASE_DOWNSTREAMS
        ],
        recommendations=list(dict.fromkeys(recommendations)),
    )


def _append_vc_evidence(
    existing: list[Evidence],
    output: RelaxOutput,
    field: str,
    value: object,
) -> list[Evidence]:
    existing = list(existing)
    existing.append(
        Evidence(
            source=output.source,
            field=f"vc_relax.{field}",
            value=value,
            interpretation="VC-relax policy evidence.",
            line_number=None,
            artifact="relaxation_output",
            section="vc-relax",
        )
    )
    return existing


def _augment_vc_evidence(existing: list[Evidence], output: RelaxOutput) -> list[Evidence]:
    return _append_vc_evidence(existing, output, "variable_cell", output.variable_cell)


def _latest_volume_delta(output: RelaxOutput) -> float | None:
    volumes = [
        step.geometry.volume
        for step in output.relaxation_trajectory
        if step.geometry.volume is not None
    ]
    if len(volumes) < 2:
        return None
    return abs(volumes[-1] - volumes[0])


def _is_volume_change_suspicious(output: RelaxOutput) -> bool:
    if len(output.relaxation_trajectory) < 2:
        return False

    start_volume = output.relaxation_trajectory[0].geometry.volume
    end_volume = output.relaxation_trajectory[-1].geometry.volume
    if start_volume is None or end_volume is None or start_volume == 0:
        return False
    relative = abs(end_volume - start_volume) / abs(start_volume)
    return relative > 0.2


__all__ = ["review_vc_relax_output"]
