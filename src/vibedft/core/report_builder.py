"""Report builder: review + postprocess → self-contained static HTML.

Entry point: ``build_static_report(case_dir, output_html)``
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from html import escape
from typing import Any

from vibedft.core.review import review_case
from vibedft.postprocess.dispatcher import dispatch_postprocess
from vibedft.postprocess.artifacts import Artifact
from vibedft.analyzers.orchestrator import run_physics_analysis


def build_static_report(
    case_dir: Path | str,
    *,
    title: str = "VibeDFT Materials Report",
    output: Path | str | None = None,
) -> str:
    """Build a self-contained static HTML report for a case directory.

    Pipeline: review_case → dispatch_postprocess → HTML.

    Returns the HTML string.  If *output* is given, writes it to disk.
    """
    d = Path(case_dir).resolve()

    # ── 1. Review ──
    review = review_case(d)

    # ── 2. Physics Analysis ──
    physics_report = run_physics_analysis(d, review_result=review)

    # ── 3. Postprocess ──
    artifacts = dispatch_postprocess(d, review_result=review)

    # ── 4. Render HTML ──
    html = _render_html(
        case_dir=str(d),
        title=title,
        review=review,
        artifacts=artifacts,
        physics=physics_report,
    )

    if output:
        Path(output).write_text(html, encoding="utf-8")

    return html


def _render_html(
    case_dir: str,
    title: str,
    review: Any,
    artifacts: list[Artifact],
    physics: Any = None,
) -> str:
    """Render the complete HTML report."""
    generated_at = datetime.now(timezone.utc).isoformat()

    # ── Sections ──
    sections_html: list[str] = []

    # 1. Overview
    sections_html.append(_section("overview", "1. Case Overview",
        _overview_block(review) + _scf_quick_stats(review)))

    # 2. Workflow
    sections_html.append(_section("workflow", "2. Workflow Completeness",
        _workflow_block(review)))

    # 3. Issues
    sections_html.append(_section("issues", "3. Issues",
        _issues_block(review)))

    # 4. Physics Insights
    sections_html.append(_section("physics", "4. Physics Insights",
        _physics_block(physics)))

    # 5. Figures & Tables (from artifacts)
    sections_html.append(_section("results", "5. Results",
        _artifacts_block(artifacts)))

    # 6. Missing Steps
    sections_html.append(_section("next", "6. Missing Steps & Next Actions",
        _next_steps_block(review)))

    # 7. Provenance
    sections_html.append(_section("provenance", "7. Provenance",
        _provenance_block(artifacts)))

    # ── Nav ──
    nav_items = [
        ("overview", "Overview"),
        ("workflow", "Workflow"),
        ("issues", "Issues"),
        ("physics", "Physics"),
        ("results", "Results"),
        ("next", "Next Steps"),
        ("provenance", "Provenance"),
    ]
    nav_html = "\n".join(
        f'<a href="#{sec_id}">{label}</a>'
        for sec_id, label in nav_items
    )

    # ── Issue summary bar ──
    n_errors = review.n_errors
    n_warnings = review.n_warnings
    status_color = "#f85149" if n_errors > 0 else ("#d2991d" if n_warnings > 0 else "#3fb950")
    status_text = "FAIL" if n_errors > 0 else ("WARN" if n_warnings > 0 else "PASS")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
:root{{--bg:#0d1117;--panel:#161b22;--border:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--pass:#3fb950;--warn:#d2991d;--fail:#f85149}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);display:flex;min-height:100vh}}
nav{{width:200px;min-width:200px;background:var(--panel);border-right:1px solid var(--border);padding:16px 12px;position:sticky;top:0;height:100vh;overflow-y:auto}}
nav h1{{font-size:14px;margin-bottom:12px}}
nav a{{display:block;padding:6px 10px;color:var(--muted);text-decoration:none;border-radius:4px;font-size:12px;margin-bottom:2px}}
nav a:hover{{background:rgba(88,166,255,.08);color:var(--text)}}
main{{flex:1;padding:20px 28px;max-width:1000px}}
.bar{{display:flex;align-items:center;gap:12px;margin-bottom:20px;padding-bottom:12px;border-bottom:1px solid var(--border)}}
.badge{{display:inline-block;padding:2px 10px;border-radius:4px;font-weight:600;font-size:12px;color:#000;background:{status_color}}}
.meta{{font-size:11px;color:var(--muted)}}
section{{margin-bottom:24px;background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:16px}}
section h2{{font-size:14px;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--border)}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin:8px 0}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--border)}}
th{{color:var(--muted);font-weight:600;text-transform:uppercase;font-size:10px}}
.sev-error{{color:var(--fail);font-weight:600}}
.sev-warn{{color:var(--warn)}}
.sev-info{{color:var(--muted)}}
.figure-card{{margin:12px 0;border:1px solid var(--border);border-radius:6px;overflow:hidden}}
.figure-card img{{max-width:100%;display:block}}
.figure-card .fig-caption{{padding:8px 12px;font-size:11px;color:var(--muted);background:rgba(255,255,255,.02)}}
.source-tag{{font-size:10px;padding:1px 6px;background:rgba(88,166,255,.08);border:1px solid var(--border);border-radius:3px;color:var(--muted);font-family:monospace;margin:2px}}
.missing-step{{padding:6px 10px;border-left:3px solid var(--warn);margin:4px 0;font-size:12px;background:rgba(210,153,29,.05)}}
.prov-row{{font-size:11px;color:var(--muted);margin:2px 0}}
</style>
</head>
<body>
<nav>
  <h1>{escape(title)}</h1>
  <div class="badge">{status_text}</div>
  <div style="margin:8px 0;font-size:10px;color:var(--muted)">
    {n_errors} errors · {n_warnings} warnings
  </div>
  {nav_html}
</nav>
<main>
  <div class="bar">
    <h2 style="border:0;margin:0;padding:0">{escape(title)}</h2>
    <span class="meta">Generated: {generated_at}</span>
  </div>
  {"".join(sections_html)}
</main>
</body>
</html>"""


def _section(sec_id: str, title: str, body: str) -> str:
    return f'<section id="{sec_id}"><h2>{escape(title)}</h2>{body}</section>'


def _overview_block(review: Any) -> str:
    return f"""
<p style="font-size:13px;color:var(--muted)">
  Case: <code>{escape(review.case_dir)}</code><br>
  Files scanned: {review.files_scanned} · Inspected: {review.files_inspected}<br>
  Tasks identified: {len(review.inspection.tasks)}<br>
  {escape(review.summary)}
</p>"""


def _scf_quick_stats(review: Any) -> str:
    """Extract SCF quick stats from inspection data."""
    lines: list[str] = []
    for f in review.inspection.files:
        if f.type == "output" and f.parse_status == "ok":
            lines.append(f'<tr><td>{escape(f.path)}</td><td>{escape(f.program.value)}</td><td>{escape(f.summary)}</td></tr>')
    if not lines:
        return ""
    return f"""
<h3 style="font-size:12px;margin-top:12px;color:var(--muted)">Output Files</h3>
<table><thead><tr><th>File</th><th>Program</th><th>Summary</th></tr></thead>
<tbody>{"".join(lines)}</tbody></table>"""


def _workflow_block(review: Any) -> str:
    if not review.best_match:
        return '<p style="color:var(--muted)">No workflow matched.</p>'
    bm = review.best_match
    rows = ""
    for m in review.workflow_matches[:5]:
        pct = f"{m.completeness:.0%}"
        missing = ", ".join(s.label for s in m.missing_steps) if m.missing_steps else "—"
        is_best = "font-weight:600" if m is bm else ""
        rows += f'<tr style="{is_best}"><td>{escape(m.workflow.workflow_id)}</td><td>{escape(m.workflow.label)}</td><td>{pct}</td><td style="font-size:11px">{escape(missing)}</td></tr>'
    next_step = escape(review.next_step)
    return f"""
<table><thead><tr><th>Workflow</th><th>Label</th><th>Complete</th><th>Missing</th></tr></thead>
<tbody>{rows}</tbody></table>
<p style="margin-top:8px;font-size:12px"><strong>Next step:</strong> {next_step}</p>"""


def _issues_block(review: Any) -> str:
    all_issues = review.all_issues
    if not all_issues:
        return '<p style="color:var(--pass)">✅ No issues found.</p>'
    rows = ""
    for iss in all_issues[:80]:
        sev_class = f"sev-{iss.severity.value}" if hasattr(iss.severity, 'value') else "sev-info"
        src_short = iss.source_file
        if src_short and len(src_short) > 60:
            src_short = "..." + src_short[-57:]
        rows += f'<tr><td class="{sev_class}">{iss.severity.value.upper() if hasattr(iss.severity, "value") else str(iss.severity)}</td><td><code>{escape(iss.id)}</code></td><td>{escape(iss.message)}</td><td style="font-size:10px;color:var(--muted)">{escape(src_short or "")}</td></tr>'
    return f"""
<table><thead><tr><th>Severity</th><th>Check</th><th>Message</th><th>Source</th></tr></thead>
<tbody>{rows}</tbody></table>"""


def _physics_block(physics: Any) -> str:
    """Render the Physics Insights section with scores and findings."""
    if physics is None:
        return '<p style="color:var(--muted)">Physics analysis not available.</p>'

    # Score cards
    scores = [
        ("Stability", physics.stability_score, "Phonon stability & structure"),
        ("Electronic", physics.electronic_score, "DOS, band gap, orbital character"),
        ("Superconductivity", physics.superconductivity_score, "λ, Tc, α²F"),
        ("Workflow Confidence", physics.workflow_confidence, "Convergence quality & completeness"),
    ]

    score_cards = ""
    for label, val, desc in scores:
        color = "#3fb950" if val >= 7 else ("#d2991d" if val >= 4 else "#f85149")
        score_cards += f"""
<div style="display:inline-block;text-align:center;margin:8px 16px 8px 0;padding:10px 16px;border:1px solid var(--border);border-radius:6px">
  <div style="font-size:24px;font-weight:700;color:{color}">{val:.1f}</div>
  <div style="font-size:11px;color:var(--muted);margin-top:2px">{label}</div>
  <div style="font-size:9px;color:var(--muted)">{desc}</div>
</div>"""

    # Verdict
    verdict_color = "#3fb950" if physics.recommendation == "continue" else (
        "#d2991d" if physics.recommendation in ("convergence_test", "needs_review") else "#f85149"
    )
    rec_label = {"continue": "✅ Continue", "convergence_test": "⚠ Convergence Test",
                 "needs_review": "🔍 Needs Review", "abandon": "❌ Abandon"}.get(
                     physics.recommendation, physics.recommendation)

    # Insights by category
    insights_by_cat: dict[str, list] = {}
    for ins in physics.insights:
        insights_by_cat.setdefault(ins.category, []).append(ins)

    cat_labels = {
        "material": "Material & Structure",
        "electronic": "Electronic Structure",
        "stability": "Phonon Stability",
        "superconductivity": "Superconductivity",
        "workflow_health": "Workflow Health",
    }

    insight_html = ""
    for cat, cat_insights in insights_by_cat.items():
        cat_label = cat_labels.get(cat, cat)
        rows = ""
        for ins in cat_insights:
            level_color = {"positive": "#3fb950", "negative": "#f85149",
                          "warning": "#d2991d", "neutral": "#8b949e"}.get(ins.level.value, "#8b949e")
            rows += f"""
<div style="padding:6px 10px;margin:4px 0;border-left:3px solid {level_color};background:rgba(255,255,255,.01);border-radius:0 4px 4px 0">
  <div style="font-size:12px">{escape(ins.message)}</div>
  {f'<div style="font-size:10px;color:var(--muted);margin-top:2px">{escape(ins.detail)}</div>' if ins.detail else ''}
</div>"""
        insight_html += f"""
<div style="margin-bottom:12px">
  <h3 style="font-size:12px;color:var(--muted);margin-bottom:6px">{escape(cat_label)}</h3>
  {rows}
</div>"""

    return f"""
<div style="margin-bottom:16px;padding:12px;border:1px solid var(--border);border-radius:8px;background:rgba(255,255,255,.01)">
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
    {score_cards}
  </div>
  <div style="margin-top:10px;padding:8px 12px;border-left:3px solid {verdict_color};background:rgba(255,255,255,.02);border-radius:0 4px 4px 0">
    <strong style="font-size:13px">{rec_label}</strong>
    <span style="font-size:12px;color:var(--muted);margin-left:8px">{escape(physics.overall_verdict)}</span>
  </div>
</div>
{insight_html}"""


def _artifacts_block(artifacts: list[Artifact]) -> str:
    if not artifacts:
        return '<p style="color:var(--muted)">No results to display. Run calculations to populate figures and tables.</p>'
    parts: list[str] = []
    for art in artifacts:
        if art.kind == "figure":
            b64 = art.data.get("png_base64", "")
            src_tags = " ".join(f'<span class="source-tag">{escape(s)}</span>' for s in art.source_files[:5])
            parts.append(f"""
<div class="figure-card">
  <img src="data:image/png;base64,{b64}" alt="{escape(art.title)}">
  <div class="fig-caption">
    <strong>{escape(art.title)}</strong>{f' — {escape(art.caption)}' if art.caption else ''}
    <div style="margin-top:4px">{src_tags}</div>
  </div>
</div>""")
        elif art.kind == "table":
            headers = art.data.get("headers", [])
            rows = art.data.get("rows", [])
            th = "".join(f"<th>{escape(str(h))}</th>" for h in headers)
            tr = "".join(
                "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>"
                for row in rows
            )
            src_tags = " ".join(f'<span class="source-tag">{escape(s)}</span>' for s in art.source_files[:5])
            parts.append(f"""
<div class="figure-card">
  <div style="padding:12px">
    <strong style="font-size:13px">{escape(art.title)}</strong>
    {f'<div style="font-size:11px;color:var(--muted);margin:4px 0">{escape(art.caption)}</div>' if art.caption else ''}
    <table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>
    <div style="margin-top:4px">{src_tags}</div>
  </div>
</div>""")
        elif art.kind == "text":
            parts.append(f"""
<div class="figure-card">
  <div style="padding:12px">
    <strong style="font-size:13px">{escape(art.title)}</strong>
    <p style="font-size:12px;margin-top:4px">{escape(art.data.get('body', ''))}</p>
  </div>
</div>""")
    return "\n".join(parts)


def _next_steps_block(review: Any) -> str:
    parts: list[str] = [f'<p style="font-size:13px"><strong>Recommended next action:</strong> {escape(review.next_step)}</p>']
    if review.best_match and review.best_match.missing_steps:
        parts.append('<div style="margin-top:8px">')
        for ms in review.best_match.missing_steps:
            parts.append(f'<div class="missing-step"><strong>{escape(ms.label)}</strong> — {escape(ms.description)}</div>')
        parts.append('</div>')
    if not (review.best_match and review.best_match.missing_steps):
        parts.append('<p style="color:var(--pass);font-size:12px;margin-top:8px">✅ All workflow steps are present.</p>')
    return "\n".join(parts)


def _provenance_block(artifacts: list[Artifact]) -> str:
    # Collect unique source files across all artifacts
    seen: set[str] = set()
    for art in artifacts:
        for sf in art.source_files:
            seen.add(sf)
    rows = "\n".join(f'<div class="prov-row">📄 {escape(s)}</div>' for s in sorted(seen))
    return f"""
<p style="font-size:12px;color:var(--muted)">All results traceable to source files:</p>
{rows if rows else '<p style="color:var(--muted)">No artifacts generated.</p>'}
<p style="font-size:11px;color:var(--muted);margin-top:8px">
  <strong>Parsers used:</strong> parse_qe_output, parse_dos_output, parse_bands_output,
  parse_freq_gp, parse_lambdax_output, compute_tc_overlap<br>
  <strong>Validators:</strong> pw_rules, ph_rules, q2r_rules, matdyn_rules, lambda_rules<br>
  <strong>Report generated at:</strong> {datetime.now(timezone.utc).isoformat()}
</p>"""
