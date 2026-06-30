"""Batch convergence review: scan → extract → analyze → artifacts → HTML.

Entry point: ``run_convergence_analysis(root_dir, output_html)``
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from vibedft.convergence.scanner import scan_batch_root, CaseSnapshot
from vibedft.convergence.parameter_extractor import extract_parameters
from vibedft.convergence.metrics import extract_metrics
from vibedft.convergence.analyzer import analyze_convergence, ConvergenceReport
from vibedft.convergence.report import (
    build_convergence_table,
    build_convergence_trend_plot,
    build_convergence_status_table,
)
from vibedft.postprocess.artifacts import Artifact


def run_convergence_analysis(
    root_dir: Path | str,
    *,
    title: str = "VibeDFT Convergence Report",
    output: Path | str | None = None,
) -> tuple[ConvergenceReport, list[Artifact]]:
    """Run full batch convergence analysis.

    Returns (ConvergenceReport, list of Artifacts).
    If *output* is given, also writes an HTML report.
    """
    r = Path(root_dir).resolve()

    # ── 1. Scan ──
    snapshots = scan_batch_root(r)

    # ── 2. Extract params & metrics ──
    all_params = [extract_parameters(s) for s in snapshots]
    all_metrics = [extract_metrics(s) for s in snapshots]

    # ── 3. Analyze convergence ──
    report = analyze_convergence(snapshots, all_params, all_metrics)

    # ── 4. Build artifacts ──
    artifacts: list[Artifact] = []

    tbl = build_convergence_table(report)
    if tbl:
        artifacts.append(tbl)

    status = build_convergence_status_table(report)
    if status:
        artifacts.append(status)

    trend = build_convergence_trend_plot(report)
    if trend:
        artifacts.append(trend)

    # ── 5. HTML ──
    if output:
        html = _render_convergence_html(title, report, artifacts)
        Path(output).write_text(html, encoding="utf-8")

    return report, artifacts


def _render_convergence_html(
    title: str,
    report: ConvergenceReport,
    artifacts: list[Artifact],
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()

    # ── Summary bar ──
    conf_color = {"high": "#3fb950", "medium": "#d2991d", "low": "#f85149"}
    color = conf_color.get(report.overall_confidence, "#8b949e")

    # ── Table rows ──
    if report.rows:
        headers = ["Case", "k-grid", "q-grid", "ecut", "degauss",
                   "λ_max", "Tc (K)", "ωlog (K)", "DOS@EF", "min_freq", "Imag", "Conf"]
        th = "".join(f"<th>{h}</th>" for h in headers)
        trs = ""
        for r in report.rows:
            vals = [
                r.case_name, r.k_grid, r.q_grid,
                f"{r.ecutwfc:.0f}" if r.ecutwfc else "—",
                f"{r.degauss:.4f}" if r.degauss else "—",
                f"{r.lambda_max:.4f}" if r.lambda_max is not None else "—",
                f"{r.tc_max_K:.2f}" if r.tc_max_K is not None else "—",
                f"{r.omega_log_K:.1f}" if r.omega_log_K is not None else "—",
                f"{r.dos_at_ef:.3f}" if r.dos_at_ef is not None else "—",
                f"{r.min_phonon_freq_cm1:.1f}" if r.min_phonon_freq_cm1 is not None else "—",
                str(r.n_imaginary_modes) if r.n_imaginary_modes is not None else "—",
                f'<span style="color:{conf_color.get(r.confidence, "#8b949e")}">{r.confidence.upper()}</span>',
            ]
            trs += "<tr>" + "".join(f"<td>{v}</td>" for v in vals) + "</tr>"

        table_html = f"""
<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"""
    else:
        table_html = '<p style="color:var(--muted)">No cases found.</p>'

    # ── Convergence status ──
    conv_rows = ""
    for param in ["lambda", "tc", "omega_log", "dos_at_ef", "phonon_min"]:
        if param in report.converged_params:
            status = "✅ Converged"
            sc = "#3fb950"
        elif param in report.unconverged_params:
            status = "❌ Not converged"
            sc = "#f85149"
        else:
            status = "— No data"
            sc = "#8b949e"
        label = {"lambda": "λ (EPC constant)", "tc": "Tc (K)",
                 "omega_log": "ωlog (K)", "dos_at_ef": "DOS@EF",
                 "phonon_min": "Phonon stability"}.get(param, param)
        conv_rows += f'<tr><td>{label}</td><td style="color:{sc}">{status}</td></tr>'

    # ── Figures ──
    figures_html = ""
    for art in artifacts:
        if art.kind == "figure":
            b64 = art.data.get("png_base64", "")
            figures_html += f"""
<div style="margin:12px 0;border:1px solid var(--border);border-radius:6px;overflow:hidden">
  <img src="data:image/png;base64,{b64}" alt="{escape(art.title)}" style="max-width:100%">
  <div style="padding:8px 12px;font-size:11px;color:var(--muted)">{escape(art.title)}</div>
</div>"""

    # ── Warnings ──
    warn_html = ""
    if report.warnings:
        warn_html = "<div style='margin:8px 0'>" + "".join(
            f'<div style="color:#d2991d;font-size:12px;margin:4px 0">⚠ {escape(w)}</div>'
            for w in report.warnings
        ) + "</div>"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
:root{{--bg:#0d1117;--panel:#161b22;--border:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--pass:#3fb950;--warn:#d2991d;--fail:#f85149}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);padding:20px 28px;max-width:1200px;margin:0 auto}}
h1{{font-size:18px;margin-bottom:4px}}
.meta{{font-size:11px;color:var(--muted);margin-bottom:20px}}
.bar{{display:flex;align-items:center;gap:12px;margin:16px 0;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--panel)}}
.badge{{display:inline-block;padding:2px 10px;border-radius:4px;font-weight:600;font-size:12px;color:#000;background:{color}}}
section{{margin-bottom:24px;background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:16px}}
section h2{{font-size:14px;margin-bottom:10px;color:var(--muted)}}
table{{border-collapse:collapse;width:100%;font-size:11px;margin:8px 0}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--border)}}
th{{color:var(--muted);font-weight:600;text-transform:uppercase;font-size:10px}}
</style>
</head>
<body>
<h1>{escape(title)}</h1>
<div class="meta">Root: {escape(report.root_dir)} · Generated: {generated_at} · {len(report.rows)} cases</div>

<div class="bar">
  <span class="badge">{report.overall_confidence.upper()}</span>
  <span style="font-size:13px">
    Converged: {', '.join(report.converged_params) if report.converged_params else 'none'}
    {f' · Not converged: {", ".join(report.unconverged_params)}' if report.unconverged_params else ''}
    {f' · Varying: {", ".join(report.varying_params)}' if report.varying_params else ''}
  </span>
</div>
{warn_html}

<section><h2>Convergence Table</h2>{table_html}</section>

<section><h2>Convergence Status</h2>
<table><thead><tr><th>Metric</th><th>Status</th></tr></thead><tbody>{conv_rows}</tbody></table>
</section>

<section><h2>Trends</h2>{figures_html}</section>

<section><h2>Convergence Criteria</h2>
<div style="font-size:11px;color:var(--muted)">
  Δλ &lt; 0.05 · ΔTc &lt; 0.5 K (or &lt; 5%) · Δωlog &lt; 5% ·
  DOS@EF stable (&lt; 10% change) · No new imaginary phonon modes
</div>
</section>
</body>
</html>"""
