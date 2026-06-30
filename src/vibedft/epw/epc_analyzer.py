"""QE vs EPW comparison — λ, ωlog, Tc side-by-side."""

from __future__ import annotations

from typing import Any


def compare_qe_vs_epw(
    qe_lambda: float | None = None,
    qe_tc_K: float | None = None,
    qe_omega_log_K: float | None = None,
    epw_result: Any = None,
) -> dict:
    """Compare QE native lambda.x results with EPW interpolation.

    Returns a dict with comparison metrics and agreement status.
    """
    epw = epw_result
    comp: dict = {
        "status": "no_epw_data",
        "lambda_qe": qe_lambda,
        "lambda_epw": None,
        "tc_qe_K": qe_tc_K,
        "tc_epw_K": None,
        "omega_qe_K": qe_omega_log_K,
        "omega_epw_K": None,
        "lambda_diff_pct": None,
        "tc_diff_K": None,
        "agreement": "unknown",
    }

    if epw is None or not getattr(epw, "has_data", False):
        return comp

    comp["status"] = "compared"
    comp["lambda_epw"] = getattr(epw, "lambda_max", None)
    comp["tc_epw_K"] = getattr(epw, "tc_max_K", None)
    comp["omega_epw_K"] = getattr(epw, "omega_log_K", None)

    # λ comparison
    if qe_lambda and comp["lambda_epw"] and qe_lambda > 0:
        diff_pct = abs(comp["lambda_epw"] - qe_lambda) / qe_lambda * 100.0
        comp["lambda_diff_pct"] = round(diff_pct, 1)

    # Tc comparison
    if qe_tc_K and comp["tc_epw_K"] and qe_tc_K > 0:
        comp["tc_diff_K"] = round(abs(comp["tc_epw_K"] - qe_tc_K), 2)

    # Agreement
    lam_diff = comp["lambda_diff_pct"]
    tc_diff = comp["tc_diff_K"]
    if lam_diff is not None and tc_diff is not None:
        if lam_diff < 10 and tc_diff < 2.0:
            comp["agreement"] = "good"
        elif lam_diff < 20 and tc_diff < 5.0:
            comp["agreement"] = "acceptable"
        else:
            comp["agreement"] = "disagree"
    elif lam_diff is not None:
        comp["agreement"] = "good" if lam_diff < 10 else ("acceptable" if lam_diff < 20 else "disagree")

    return comp
