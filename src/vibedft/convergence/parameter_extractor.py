"""Extract convergence-critical parameters from each case snapshot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibedft.convergence.scanner import CaseSnapshot
from vibedft.parsers.qe_input_parser import parse_qe_input


def extract_parameters(snapshot: CaseSnapshot) -> dict[str, Any]:
    """Extract k-grid, q-grid, ecut, degauss, sigma from input files.

    Returns a flat dict with keys like k_nk1, k_nk2, q_nq1, q_nq2, ecutwfc, etc.
    """
    params: dict[str, Any] = {}
    d = Path(snapshot.path)

    # Search for .in files
    for in_file in d.rglob("*.in"):
        try:
            qe = parse_qe_input(in_file)
        except Exception:
            continue

        # ── pw.x params ──
        params.setdefault("ecutwfc", qe.get_param("system", "ecutwfc", None))
        params.setdefault("ecutrho", qe.get_param("system", "ecutrho", None))
        params.setdefault("degauss", qe.get_param("system", "degauss", None))
        params.setdefault("occupations", qe.get_param("system", "occupations", None))

        # K-points from card
        kp = qe.cards.get("K_POINTS")
        if kp and kp.rows and kp.rows[0]:
            row = kp.rows[0]
            if len(row) >= 3 and "k_nk1" not in params:
                try:
                    params["k_nk1"] = int(row[0])
                    params["k_nk2"] = int(row[1])
                    params["k_nk3"] = int(row[2])
                except (ValueError, IndexError):
                    pass

        # ── ph.x params ──
        if "q_nq1" not in params:
            nq1 = qe.get_param("inputph", "nq1", None)
            nq2 = qe.get_param("inputph", "nq2", None)
            nq3 = qe.get_param("inputph", "nq3", None)
            if nq1 is not None:
                try:
                    params["q_nq1"] = int(nq1)
                    params["q_nq2"] = int(nq2) if nq2 is not None else 0
                    params["q_nq3"] = int(nq3) if nq3 is not None else 1
                except (ValueError, TypeError):
                    pass

        # EPC sigma
        if "el_ph_sigma" not in params:
            sigma = qe.get_param("inputph", "el_ph_sigma", None)
            if sigma is not None:
                try:
                    params["el_ph_sigma"] = float(sigma)
                except (ValueError, TypeError):
                    pass

        # ── lambda.x params ──
        if "mustar" not in params:
            mu = qe.get_param("input", "mustar", None)
            if mu is not None:
                try:
                    params["mustar"] = float(mu)
                except (ValueError, TypeError):
                    pass

    # Fill defaults for missing params
    defaults = {
        "k_nk1": 0, "k_nk2": 0, "k_nk3": 0,
        "q_nq1": 0, "q_nq2": 0, "q_nq3": 0,
        "ecutwfc": 0, "ecutrho": 0, "degauss": 0.0,
        "el_ph_sigma": 0.0, "mustar": 0.1,
    }
    for k, v in defaults.items():
        if k not in params or params[k] is None:
            params[k] = v

    return params


def format_grid(params: dict[str, Any], prefix: str) -> str:
    """Format a grid as 'N1×N2×N3' string."""
    n1 = params.get(f"{prefix}_n1", 0) or params.get(f"{prefix}_nk1", 0)
    n2 = params.get(f"{prefix}_n2", 0) or params.get(f"{prefix}_nk2", 0)
    n3 = params.get(f"{prefix}_n3", 0) or params.get(f"{prefix}_nk3", 0)
    return f"{n1}×{n2}×{n3}"


def format_k_grid(params: dict[str, Any]) -> str:
    return format_grid(params, "k")


def format_q_grid(params: dict[str, Any]) -> str:
    return format_grid(params, "q")
