"""Parameter intelligence — classify parameter values as template placeholders, runtime values, or anomalies."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParameterInsight:
    parameter: str
    value: Any
    context: str = ""          # "template_placeholder" | "ultra_strict" | "runtime" | "anomaly"
    severity: str = "info"     # "info" | "warning" | "error"
    message: str = ""
    file: str = ""


@dataclass
class ParameterIntelligenceReport:
    insights: list[ParameterInsight] = field(default_factory=list)
    is_template: bool = False
    n_placeholders: int = 0


def analyze_parameters(case_dir: Path | str) -> ParameterIntelligenceReport:
    """Classify parameter values across all input files in a case directory."""
    d = Path(case_dir)
    report = ParameterIntelligenceReport()

    in_files = list(d.rglob("*.in"))
    report.is_template = len(in_files) > 20  # heuristic

    from vibedft.parsers.qe_input_parser import parse_qe_input

    for in_file in in_files:
        try:
            qe = parse_qe_input(in_file)
        except Exception:
            continue

        rel = str(in_file.relative_to(d)) if in_file.is_relative_to(d) else in_file.name

        # ── tr2_ph ──
        tr2 = qe.get_param("inputph", "tr2_ph", None)
        if tr2 is not None:
            try:
                val = float(tr2)
                if val < 1e-13:
                    report.insights.append(ParameterInsight(
                        parameter="tr2_ph", value=val, context="ultra_strict",
                        severity="info",
                        message=f"tr2_ph={val:.0e} — ultra-tight phonon convergence threshold. "
                                "This ensures high-quality dynamical matrices for EPC.",
                        file=rel,
                    ))
                elif val > 1e-8:
                    report.insights.append(ParameterInsight(
                        parameter="tr2_ph", value=val, context="anomaly",
                        severity="warning",
                        message=f"tr2_ph={val:.0e} — unusually loose for EPC. "
                                "Standard is 1e-14 or tighter.",
                        file=rel,
                    ))
            except (ValueError, TypeError):
                pass

        # ── forc_conv_thr ──
        fct = qe.get_param("control", "forc_conv_thr", None)
        if fct is not None:
            try:
                val = float(fct)
                if val < 5e-5:
                    report.insights.append(ParameterInsight(
                        parameter="forc_conv_thr", value=val, context="ultra_strict",
                        severity="info",
                        message=f"forc_conv_thr={val:.0e} — unusually strict force convergence. "
                                "Structure is optimized to very high precision.",
                        file=rel,
                    ))
            except (ValueError, TypeError):
                pass

        # ── mustar ──
        mu = qe.get_param("input", "mustar", None)
        if mu is not None:
            try:
                val = float(mu)
                if val > 1.0:
                    context = "template_placeholder" if report.is_template else "anomaly"
                    sev = "warning" if report.is_template else "error"
                    msg = (
                        f"mustar={val} — appears to be a template placeholder. "
                        "Replace with a physical value (0.08–0.15) before running."
                    ) if report.is_template else (
                        f"mustar={val} — outside physical range (0.0–0.5). "
                        "Tc results will be meaningless."
                    )
                    report.insights.append(ParameterInsight(
                        parameter="mustar", value=val, context=context,
                        severity=sev, message=msg, file=rel,
                    ))
                    if report.is_template:
                        report.n_placeholders += 1
            except (ValueError, TypeError):
                pass

    return report
