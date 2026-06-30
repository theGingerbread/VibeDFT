"""Evidence-backed 2D validity analyzer for QE inputs."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from vibedft.parsers.qe_input_parser import parse_qe_input
from vibedft.research.models import (
    AnalysisResult,
    ArtifactType,
    EvidenceRef,
    PhysicsDescriptor,
    ReliabilityLevel,
    ResultStatus,
)


_HEAVY_ELEMENTS = {
    "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi",
    "I", "Te", "Sb", "Sn", "In", "Cd", "Ag", "Pd", "Rh", "Ru", "Tc", "Mo", "Nb", "Zr", "Y",
}

_STRICT_CLAIMS = {"epc_tc", "phonon_epc", "superconductivity", "band_alignment", "type3"}


def analyze_2d_validity(
    *,
    pw_input_path: Path | str,
    ph_input_path: Path | str | None = None,
    claim_type: str = "screening",
    is_heterostructure: bool = False,
) -> AnalysisResult:
    """Analyze whether a QE case has enough 2D setup evidence for a claim.

    This validator aggregates structure, k/q mesh, electrostatics, SOC, and vdW
    policy checks into one evidence-backed descriptor.  Strict claim types such
    as EPC/Tc and band alignment turn missing 2D electrostatics into blockers;
    screening keeps more items as warnings.
    """

    pw_path = Path(pw_input_path)
    claim = claim_type.lower()
    strict = claim in _STRICT_CLAIMS
    blockers: list[str] = []
    warnings: list[str] = []
    recommendations: list[str] = []
    evidence: list[EvidenceRef] = []
    checks: dict[str, dict[str, Any]] = {}

    pw = parse_qe_input(pw_path)
    evidence.append(
        EvidenceRef(
            artifact_path=str(pw_path),
            artifact_type=ArtifactType.INPUT,
            parser_name="vibedft.parsers.qe_input_parser.parse_qe_input",
            parsed_quantity="pw_2d_input_parameters",
            raw_value={
                "program": pw.program.value if hasattr(pw.program, "value") else str(pw.program),
                "parse_errors": pw.parse_errors,
                "system": dict(pw.namelists.get("system").params) if pw.namelists.get("system") else {},
            },
            summary="pw.x input parameters used for 2D validity checks.",
            blockers=list(pw.parse_errors),
            reliability=ReliabilityLevel.MEDIUM if not pw.parse_errors else ReliabilityLevel.LOW,
        )
    )
    if pw.parse_errors:
        blockers.append(f"pw.x input missing or unreadable: {'; '.join(pw.parse_errors)}")

    ph = None
    if ph_input_path is not None:
        ph_path = Path(ph_input_path)
        ph = parse_qe_input(ph_path)
        evidence.append(
            EvidenceRef(
                artifact_path=str(ph_path),
                artifact_type=ArtifactType.INPUT,
                parser_name="vibedft.parsers.qe_input_parser.parse_qe_input",
                parsed_quantity="ph_2d_input_parameters",
                raw_value={
                    "program": ph.program.value if hasattr(ph.program, "value") else str(ph.program),
                    "parse_errors": ph.parse_errors,
                    "inputph": dict(ph.namelists.get("inputph").params) if ph.namelists.get("inputph") else {},
                },
                summary="ph.x input parameters used for nq3 2D validity checks.",
                blockers=list(ph.parse_errors),
                reliability=ReliabilityLevel.MEDIUM if not ph.parse_errors else ReliabilityLevel.LOW,
            )
        )
        if ph.parse_errors:
            blockers.append(f"ph.x input missing or unreadable: {'; '.join(ph.parse_errors)}")

    if not pw.parse_errors:
        _check_vacuum(pw, checks, blockers, warnings, strict)
        _check_kz_mesh(pw, checks, blockers, warnings)
        _check_assume_isolated(pw, checks, blockers, warnings, strict)
        _check_charged_slab(pw, checks, blockers, warnings, strict)
        _check_slab_asymmetry_and_dipole(pw, checks, warnings, recommendations, is_heterostructure)
        _check_soc_policy(pw, checks, blockers, warnings, claim)
        _check_vdw_policy(pw, checks, blockers, warnings, recommendations, is_heterostructure, claim)
    if ph is not None and not ph.parse_errors:
        _check_ph_nq3(ph, checks, blockers, warnings, claim)

    score = _validity_score(checks)
    descriptors = [
        PhysicsDescriptor(
            name="two_d_validity_score",
            value=score,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if not pw.parse_errors else ReliabilityLevel.LOW,
            metadata={"claim_type": claim, "is_heterostructure": is_heterostructure},
        ),
        PhysicsDescriptor(
            name="two_d_checks",
            value=checks,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if checks else ReliabilityLevel.LOW,
        ),
    ]

    if pw.parse_errors:
        status = ResultStatus.INSUFFICIENT_EVIDENCE
    elif blockers:
        status = ResultStatus.BLOCKED
    elif warnings:
        status = ResultStatus.WARNING
    else:
        status = ResultStatus.PASS

    return AnalysisResult(
        id="analysis.two_d_validity",
        parser_name="vibedft.validators.two_d.analyze_2d_validity",
        status=status,
        parsed_quantity="two_d_validity",
        evidence=evidence,
        descriptors=descriptors,
        raw_value={
            "score": score,
            "checks": checks,
            "claim_type": claim,
            "is_heterostructure": is_heterostructure,
        },
        summary="Evidence-backed 2D setup validity analysis.",
        warnings=warnings,
        blockers=blockers,
        reliability=ReliabilityLevel.MEDIUM if not pw.parse_errors else ReliabilityLevel.LOW,
        metadata={
            "recommendations": recommendations,
            "paper_grade_allowed": not blockers and score >= 85,
        },
    )


def _check_vacuum(qe, checks, blockers, warnings, strict: bool) -> None:
    c_length = _cell_c_length(qe)
    if c_length is None:
        checks["vacuum_thickness"] = _check("warn", None, "CELL_PARAMETERS missing; vacuum cannot be assessed")
        warnings.append("CELL_PARAMETERS missing; vacuum thickness cannot be assessed")
        return
    if c_length < 15.0:
        message = f"vacuum/c-axis is too small for a 2D slab: c={c_length:.2f} Å"
        status = "block" if strict else "warn"
        checks["vacuum_thickness"] = _check(status, c_length, message, unit="angstrom")
        (blockers if strict else warnings).append(message)
    else:
        checks["vacuum_thickness"] = _check("pass", c_length, f"c-axis/vacuum proxy is {c_length:.2f} Å", unit="angstrom")


def _check_kz_mesh(qe, checks, blockers, warnings) -> None:
    nk3 = _kpoints_nk3(qe)
    if nk3 is None:
        checks["kz_mesh"] = _check("warn", None, "K_POINTS automatic mesh missing or not parseable")
        warnings.append("K_POINTS automatic mesh missing or not parseable")
    elif nk3 != 1:
        message = f"kz mesh must be 1 for 2D calculations; got nk3={nk3}"
        checks["kz_mesh"] = _check("block", nk3, message)
        blockers.append(message)
    else:
        checks["kz_mesh"] = _check("pass", nk3, "kz mesh is 1")


def _check_assume_isolated(qe, checks, blockers, warnings, strict: bool) -> None:
    value = str(qe.get_param("system", "assume_isolated", "")).strip().strip("'\"")
    if value.lower() == "2d":
        checks["assume_isolated_2d"] = _check("pass", value, "assume_isolated='2D' is set")
        return
    message = "assume_isolated='2D' is missing for slab electrostatics"
    status = "block" if strict else "warn"
    checks["assume_isolated_2d"] = _check(status, value or None, message)
    (blockers if strict else warnings).append(message)


def _check_charged_slab(qe, checks, blockers, warnings, strict: bool) -> None:
    charge = _system_float(qe, "tot_charge", 0.0)
    assume = str(qe.get_param("system", "assume_isolated", "")).strip().strip("'\"").lower()
    tefield = qe.get_param("system", "tefield", False) is True
    dipfield = qe.get_param("system", "dipfield", False) is True
    if abs(charge) <= 1e-12:
        checks["charged_slab_consistency"] = _check("pass", charge, "neutral slab")
        return
    if assume != "2d":
        message = f"charged slab tot_charge={charge:g} lacks assume_isolated='2D'"
        status = "block" if strict else "warn"
        checks["charged_slab_consistency"] = _check(status, charge, message)
        (blockers if strict else warnings).append(message)
    else:
        message = "charged 2D slab uses Coulomb cutoff; record vacuum/gating sensitivity"
        checks["charged_slab_consistency"] = _check("warn", charge, message)
        warnings.append(message)
    if not (tefield and dipfield):
        warnings.append("charged slab has no explicit tefield/dipfield dipole model recorded")


def _check_slab_asymmetry_and_dipole(qe, checks, warnings, recommendations, is_heterostructure: bool) -> None:
    asymmetry = _slab_asymmetry(qe)
    tefield = qe.get_param("system", "tefield", False) is True
    dipfield = qe.get_param("system", "dipfield", False) is True
    if asymmetry is None:
        checks["slab_asymmetry_dipole"] = _check("warn", None, "ATOMIC_POSITIONS missing; slab asymmetry cannot be assessed")
        warnings.append("ATOMIC_POSITIONS missing; slab asymmetry cannot be assessed")
        return
    if asymmetry > 0.08 or is_heterostructure:
        if tefield and dipfield:
            checks["slab_asymmetry_dipole"] = _check("pass", asymmetry, "asymmetric/heterostructure slab records dipole correction")
        else:
            message = "asymmetric or heterostructure slab should record dipole-correction policy"
            checks["slab_asymmetry_dipole"] = _check("warn", asymmetry, message)
            warnings.append(message)
            recommendations.append("Record tefield/dipfield or equivalent dipole-correction rationale for asymmetric 2D slabs.")
    else:
        checks["slab_asymmetry_dipole"] = _check("pass", asymmetry, "slab z distribution is approximately centered")


def _check_soc_policy(qe, checks, blockers, warnings, claim: str) -> None:
    heavy = _heavy_species(qe)
    has_soc = qe.get_param("system", "noncolin", False) is True and qe.get_param("system", "lspinorb", False) is True
    if not heavy:
        checks["soc_policy"] = _check("pass", [], "no heavy elements detected")
        return
    if has_soc:
        checks["soc_policy"] = _check("pass", heavy, "SOC is enabled for heavy elements")
        return
    message = f"heavy elements detected without SOC policy: {', '.join(heavy)}"
    if claim in {"band_alignment", "type3"}:
        checks["soc_policy"] = _check("block", heavy, message)
        blockers.append(message)
    else:
        checks["soc_policy"] = _check("warn", heavy, message)
        warnings.append(message)


def _check_vdw_policy(qe, checks, blockers, warnings, recommendations, is_heterostructure: bool, claim: str) -> None:
    vdw = qe.get_param("system", "vdw_corr", None)
    input_dft = str(qe.get_param("system", "input_dft", "")).lower()
    has_vdw = bool(vdw) or "vdw" in input_dft or "d3" in input_dft
    if not is_heterostructure:
        checks["vdw_policy"] = _check("pass", vdw or input_dft or None, "vdW policy not required for non-heterostructure context")
        return
    if has_vdw:
        checks["vdw_policy"] = _check("pass", vdw or input_dft, "vdW policy is recorded for heterostructure")
        return
    message = "vdW policy is missing for heterostructure geometry and band-alignment claims"
    checks["vdw_policy"] = _check("warn", None, message)
    warnings.append(message)
    recommendations.append("Record vdW functional/correction policy for heterostructure comparisons.")


def _check_ph_nq3(ph, checks, blockers, warnings, claim: str) -> None:
    nq3 = ph.get_param("inputph", "nq3", None)
    if nq3 is None:
        checks["phonon_nq3"] = _check("warn", None, "ph.x nq3 is missing")
        warnings.append("ph.x nq3 is missing")
        return
    nq3_int = int(_to_float(nq3, 0.0))
    if nq3_int != 1:
        message = f"phonon nq3 must be 1 for 2D claims; got nq3={nq3_int}"
        checks["phonon_nq3"] = _check("block", nq3_int, message)
        blockers.append(message)
    else:
        checks["phonon_nq3"] = _check("pass", nq3_int, "phonon nq3 is 1")


def _cell_c_length(qe) -> float | None:
    card = qe.cards.get("CELL_PARAMETERS")
    if not card or len(card.rows) < 3:
        return None
    try:
        row = [float(value) for value in card.rows[2][:3]]
    except (ValueError, IndexError):
        return None
    return math.sqrt(sum(value * value for value in row))


def _kpoints_nk3(qe) -> int | None:
    card = qe.cards.get("K_POINTS")
    if not card or not card.rows:
        return None
    if card.option and card.option.lower() != "automatic":
        return None
    try:
        return int(card.rows[0][2])
    except (ValueError, IndexError):
        return None


def _slab_asymmetry(qe) -> float | None:
    card = qe.cards.get("ATOMIC_POSITIONS")
    if not card or not card.rows:
        return None
    z_values: list[float] = []
    for row in card.rows:
        if len(row) < 4:
            continue
        try:
            z_values.append(float(row[3]))
        except ValueError:
            continue
    if not z_values:
        return None
    center = (min(z_values) + max(z_values)) / 2.0
    return abs(center - 0.5)


def _heavy_species(qe) -> list[str]:
    card = qe.cards.get("ATOMIC_SPECIES")
    if not card:
        return []
    species: list[str] = []
    for row in card.rows:
        if row and row[0] in _HEAVY_ELEMENTS and row[0] not in species:
            species.append(row[0])
    return species


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _system_float(qe, key: str, default: float) -> float:
    value = qe.get_param("system", key, None)
    if value is not None:
        return _to_float(value, default)
    pattern = rf"\b{re.escape(key)}\s*=\s*([+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[dDeE][+\-]?\d+)?)"
    match = re.search(pattern, qe.raw_text, re.IGNORECASE)
    if not match:
        return default
    raw = match.group(1).replace("D", "e").replace("d", "e")
    return _to_float(raw, default)


def _check(status: str, raw_value: Any, message: str, *, unit: str = "") -> dict[str, Any]:
    return {
        "status": status,
        "raw_value": raw_value,
        "message": message,
        "unit": unit,
    }


def _validity_score(checks: dict[str, dict[str, Any]]) -> int:
    score = 100
    for check in checks.values():
        if check["status"] == "block":
            score -= 25
        elif check["status"] == "warn":
            score -= 10
    return max(score, 0)
