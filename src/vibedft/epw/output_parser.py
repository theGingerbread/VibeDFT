"""EPW output parser — extract λ, ωlog, Tc, fine mesh info, Wannier quality."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EpwResult:
    """Structured EPW output results."""
    source_file: str = ""
    has_data: bool = False
    # EPC
    lambda_max: float | None = None
    lambda_values: list[float] = field(default_factory=list)
    omega_log_K: float | None = None
    tc_max_K: float | None = None
    tc_values: list[float] = field(default_factory=list)
    # Fine mesh
    fine_k_mesh: str = ""
    fine_q_mesh: str = ""
    # Wannier quality
    wannier_spreads: list[float] = field(default_factory=list)
    wannier_max_spread: float | None = None
    wannier_total_spread: float | None = None
    wannier_num_bands: int = 0
    # Convergence
    degauss_values: list[float] = field(default_factory=list)
    # Warnings
    warnings: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)


def parse_epw_output(filepath: Path | str) -> EpwResult | None:
    """Parse an EPW output file (epw.out or epw.in output)."""
    path = Path(filepath)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    result = EpwResult(source_file=str(path))

    # Check for EPW signature
    if "EPW" not in text and "Wannier" not in text and "electron-phonon" not in text.lower():
        return result

    result.has_data = True

    # ── Fine mesh ──
    m_fine = re.search(r"fine\s+(?:k|q).*?mesh\s*[:=]\s*(\d+)\s*[x×]\s*(\d+)\s*[x×]\s*(\d+)", text, re.IGNORECASE)
    if not m_fine:
        m_fine = re.search(r"nk(?:fine)?\s*=\s*(\d+)\s*,\s*nq\w*\s*=\s*(\d+)", text, re.IGNORECASE)
    if m_fine:
        result.fine_k_mesh = f"{m_fine.group(1)}×{m_fine.group(2)}×{m_fine.group(3)}" if m_fine.lastindex and m_fine.lastindex >= 3 else ""

    # ── λ ──
    lam_vals = re.findall(r"(?:el-ph|eph|total)\s+(?:coupling|lambda)\s*[=:]\s*([\d.]+)", text, re.IGNORECASE)
    if not lam_vals:
        # EPW format: "lambda [    1] =   1.3500"
        lam_vals = re.findall(r"lambda\s*\[[^\]]*\]\s*=\s*([\d.]+)", text, re.IGNORECASE)
    if not lam_vals:
        # Generic: "lambda = X.XX" or "lambda  =  X.XX"
        lam_vals = re.findall(r"lambda\s*[=:]\s*([\d.]+)", text, re.IGNORECASE)
    if lam_vals:
        result.lambda_values = [float(v) for v in lam_vals if float(v) > 0]
        result.lambda_max = max(result.lambda_values)

    # ── ωlog ──
    m_wlog = re.search(r"(?:omega_log|ωlog|<log\s*w>)\s*[=:]\s*([\d.]+)\s*(?:K|meV)?", text, re.IGNORECASE)
    if m_wlog:
        val = float(m_wlog.group(1))
        if val < 10:  # probably in meV
            val *= 11.604  # meV → K (approximate)
        result.omega_log_K = val

    # ── Tc ──
    tc_vals = re.findall(r"Tc\s*[=:]\s*([\d.]+)\s*K", text, re.IGNORECASE)
    if not tc_vals:
        # EPW format: "Tc (McMillan-Allen-Dynes) =    8.500 K"
        tc_vals = re.findall(r"Tc\s*\([^)]*\)\s*=\s*([\d.]+)\s*K", text, re.IGNORECASE)
    if tc_vals:
        result.tc_values = [float(v) for v in tc_vals]
        result.tc_max_K = max(float(v) for v in tc_vals if float(v) > 0)

    # ── Degauss ──
    dg_vals = re.findall(r"degauss\w*\s*[=:]\s*([\d.]+)", text, re.IGNORECASE)
    if dg_vals:
        result.degauss_values = [float(v) for v in dg_vals]

    # ── Wannier spreads ──
    spread_vals: list[str] = []
    # EPW format: "WF centre and spread    1  (  0.0000,  0.0000,  0.0000 )    1.2345"
    for line in text.splitlines():
        if "spread" in line.lower() and any(c.isdigit() for c in line):
            parts = line.split()
            for p in reversed(parts):
                try:
                    val = float(p)
                    if 0.01 < val < 100:
                        spread_vals.append(p)
                        break
                except ValueError:
                    continue
    if not spread_vals:
        spread_vals = re.findall(r"(?:WF\s*centre.*?spread|spread\s*\[.*?\])\s*[=:]\s*([\d.]+)", text, re.IGNORECASE)
    # Also try the Wannier90-style output within EPW
    if not spread_vals:
        spread_vals = re.findall(r"Spread\s*\[.*?\]\s*=\s*([\d.]+)", text)
    if not spread_vals:
        spread_vals = re.findall(r"Final\s+Spread\s*[=:]\s*([\d.]+)", text, re.IGNORECASE)
    # Generic spread lines
    if not spread_vals:
        for line in text.splitlines():
            m_sp = re.search(r"spread\s*[=:]\s*([\d.]+)", line, re.IGNORECASE)
            if m_sp:
                spread_vals.append(m_sp.group(1))
    if spread_vals:
        result.wannier_spreads = [float(v) for v in spread_vals if float(v) < 1000]
        if result.wannier_spreads:
            result.wannier_max_spread = max(result.wannier_spreads)
            result.wannier_total_spread = sum(result.wannier_spreads)
            result.wannier_num_bands = len(result.wannier_spreads)

    # ── Warnings ──
    warning_patterns = [
        (r"(?i)warning.*?(?:not.*?converge|disentangle|interpolat)", "EPW warning detected"),
        (r"(?i)negative.*?(?:frequency|phonon)", "Negative phonon frequency in EPW"),
        (r"(?i)wannier.*?(?:spread.*?(?:large|high)|not.*?localiz)", "Wannier spread concern"),
    ]
    for pat, msg in warning_patterns:
        if re.search(pat, text):
            result.warnings.append(msg)

    return result
