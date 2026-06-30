"""Named gate decision engine for VibeDFT physics workflows.

Replaces counting-based verdict logic in ``orchestrator.py`` with
hard gates, each mapping to a specific DFT/DFPT workflow checkpoint.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class GateStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    MISSING = "missing"


@dataclass
class GateResult:
    gate_name: str
    status: GateStatus
    reason: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass
class Decision:
    gates: list[GateResult]
    blocked_by: str = ""
    verdict: str = ""
    recommendation: str = ""


GATES_ORDERED = [
    "G0_INPUT",
    "G1_RELAX",
    "G2_ELECTRONIC",
    "G3_PH_GAMMA",
    "G4_PH_FULLQ",
    "G5_EPC",
    "G6_TC_OVERLAP",
    "G7_MECHANISM",
]

VERDICT_BLOCKED = "BLOCKED"
VERDICT_READY_PH_GAMMA = "READY_FOR_PH_GAMMA"
VERDICT_READY_FULL_PH = "READY_FOR_FULL_PH"
VERDICT_READY_EPC = "READY_FOR_EPC"
VERDICT_TC_PRELIMINARY = "TC_PRELIMINARY_ONLY"
VERDICT_READY_REPORT = "READY_FOR_REPORT"
VERDICT_TC_UNRELIABLE = "TC_UNRELIABLE"


def evaluate_gates(
    *,
    n_critical_errors: int = 0,
    n_errors: int = 0,
    has_la2f_violation: bool = False,
    relax_converged: bool | None = None,
    has_scf: bool = False,
    has_dos: bool = False,
    has_bands: bool = False,
    is_metallic: bool | None = None,
    has_ph_gamma: bool = False,
    has_imaginary_gamma_non_acoustic: bool = False,
    has_ph_fullq: bool = False,
    has_imaginary_non_gamma: bool = False,
    has_epc_complete: bool = False,
    has_lambda: bool = False,
    has_tc_overlap_pass: bool | None = None,
    has_tc_point: bool = False,
    tc_nan_or_infinity: bool = False,
    has_mechanism_evidence: bool = False,
) -> Decision:
    """Evaluate all workflow gates and return the first blocking failure.

    Gates are evaluated in priority order (G0 → G7).  The first FAIL
    gate blocks downstream and determines the verdict.
    """
    gates: list[GateResult] = []

    # ── G0: Input validity ──
    if has_la2f_violation:
        gates.append(GateResult("G0_INPUT", GateStatus.FAIL,
                                "la2F in q2r.x will crash the calculation"))
    elif n_critical_errors >= 1:
        gates.append(GateResult("G0_INPUT", GateStatus.FAIL,
                                f"{n_critical_errors} critical input errors"))
    elif n_errors >= 10:
        gates.append(GateResult("G0_INPUT", GateStatus.WARN,
                                f"{n_errors} input errors"))
    elif n_errors > 0:
        gates.append(GateResult("G0_INPUT", GateStatus.PASS,
                                f"{n_errors} non-critical issues"))
    else:
        gates.append(GateResult("G0_INPUT", GateStatus.PASS))

    # ── G1: Relax convergence ──
    if relax_converged is False:
        gates.append(GateResult("G1_RELAX", GateStatus.FAIL,
                                "relax did not converge; redo with stricter thresholds"))
    elif relax_converged is None:
        gates.append(GateResult("G1_RELAX", GateStatus.MISSING,
                                "no relax output found"))
    else:
        gates.append(GateResult("G1_RELAX", GateStatus.PASS))

    # ── G2: Electronic data ──
    if has_scf and has_dos and has_bands:
        met_label = " (metallic)" if is_metallic else (" (insulator)" if is_metallic is False else "")
        gates.append(GateResult("G2_ELECTRONIC", GateStatus.PASS,
                                f"SCF+DOS+bands present{met_label}"))
    elif has_scf:
        gates.append(GateResult("G2_ELECTRONIC", GateStatus.WARN,
                                "SCF present, DOS or bands missing"))
    else:
        gates.append(GateResult("G2_ELECTRONIC", GateStatus.MISSING))

    # ── G3: Gamma PH ──
    if has_ph_gamma and not has_imaginary_gamma_non_acoustic:
        gates.append(GateResult("G3_PH_GAMMA", GateStatus.PASS))
    elif has_imaginary_gamma_non_acoustic:
        gates.append(GateResult("G3_PH_GAMMA", GateStatus.FAIL,
                                "Gamma optical imaginary modes; run mode-following"))
    else:
        gates.append(GateResult("G3_PH_GAMMA", GateStatus.MISSING))

    # ── G4: Full-q PH stability ──
    if has_ph_fullq and not has_imaginary_non_gamma:
        gates.append(GateResult("G4_PH_FULLQ", GateStatus.PASS))
    elif has_imaginary_non_gamma:
        gates.append(GateResult("G4_PH_FULLQ", GateStatus.FAIL,
                                "non-Gamma imaginary modes; dynamically unstable"))
    elif has_ph_gamma:
        gates.append(GateResult("G4_PH_FULLQ", GateStatus.MISSING,
                                "Gamma available, full BZ PH not computed"))
    else:
        gates.append(GateResult("G4_PH_FULLQ", GateStatus.MISSING))

    # ── G5: EPC chain complete ──
    if has_epc_complete and has_lambda:
        gates.append(GateResult("G5_EPC", GateStatus.PASS))
    elif has_epc_complete:
        gates.append(GateResult("G5_EPC", GateStatus.WARN,
                                "EPC chain exists but lambda missing"))
    else:
        gates.append(GateResult("G5_EPC", GateStatus.MISSING))

    # ── G6: Tc convergence ──
    if tc_nan_or_infinity:
        gates.append(GateResult("G6_TC_OVERLAP", GateStatus.FAIL,
                                "Tc is NaN or infinity; EPC data unreliable"))
    elif has_tc_overlap_pass is True and has_tc_point:
        gates.append(GateResult("G6_TC_OVERLAP", GateStatus.PASS, "two-grid overlap passed"))
    elif has_tc_overlap_pass is False:
        gates.append(GateResult("G6_TC_OVERLAP", GateStatus.FAIL,
                                "Tc overlap failed between k-grids"))
    elif has_epc_complete:
        gates.append(GateResult("G6_TC_OVERLAP", GateStatus.WARN,
                                "single-grid Tc only; not reportable"))
    else:
        gates.append(GateResult("G6_TC_OVERLAP", GateStatus.MISSING))

    # ── G7: Mechanism evidence ──
    if has_mechanism_evidence:
        gates.append(GateResult("G7_MECHANISM", GateStatus.PASS))
    else:
        gates.append(GateResult("G7_MECHANISM", GateStatus.MISSING,
                                "not collected yet"))

    return _build_decision(gates)


def _build_decision(gates: list[GateResult]) -> Decision:
    blocked_by = ""
    verdict = ""
    recommendation = ""

    gate_map = {g.gate_name: g for g in gates}

    for name in GATES_ORDERED:
        g = gate_map.get(name)
        if g is None:
            continue
        if g.status == GateStatus.FAIL:
            blocked_by = name
            break

    if blocked_by:
        verdict = VERDICT_BLOCKED
        recommendation = "needs_review"
    else:
        last_reached = GATES_ORDERED[0]
        for name in GATES_ORDERED:
            g = gate_map.get(name)
            if g is None or g.status == GateStatus.MISSING:
                break
            last_reached = name

        verdict_map = {
            "G0_INPUT": VERDICT_BLOCKED,
            "G1_RELAX": VERDICT_BLOCKED,
            "G2_ELECTRONIC": VERDICT_READY_PH_GAMMA,
            "G3_PH_GAMMA": VERDICT_READY_FULL_PH,
            "G4_PH_FULLQ": VERDICT_READY_EPC,
            "G5_EPC": VERDICT_TC_PRELIMINARY,
            "G6_TC_OVERLAP": VERDICT_READY_REPORT,
            "G7_MECHANISM": VERDICT_READY_REPORT,
        }
        verdict = verdict_map.get(last_reached, "")

        if "READY" in verdict:
            recommendation = "continue"
        elif "PRELIMINARY" in verdict:
            recommendation = "convergence_test"
        elif verdict:
            recommendation = "needs_review"

    return Decision(
        gates=gates,
        blocked_by=blocked_by,
        verdict=verdict,
        recommendation=recommendation,
    )
