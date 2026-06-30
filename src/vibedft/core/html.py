"""Build an interactive HTML analysis workbench for VibeDFT results.

The generated HTML is a single self-contained file with all data embedded as JSON
and all rendering done client-side using Chart.js (loaded from CDN).
No server or build step required — just open the file in a browser.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vibedft.core.analysis import (
    parse_qe_output,
    parse_dos_output,
    parse_bands_output,
    compute_k_distances,
    parse_pdos_bundle,
    discover_pdos_files,
)
from vibedft.core.kpath import detect_high_symmetry as _detect_high_symmetry
from vibedft.core.physics import analyze_bands_physics


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_workbench(
    output: Path | str,
    *,
    cases_dir: str | None = None,
    bands_file: Path | str | None = None,
    dos_file: Path | str | None = None,
    scf_output: Path | str | None = None,
    title: str = "VibeDFT Analysis",
    extra_json: dict[str, Any] | None = None,
) -> Path:
    """Build a self-contained interactive HTML analysis workbench.

    *cases_dir* accepts comma-separated directories for multi-case comparison.
    Each case directory should follow the ``cases/<case-id>/`` layout.
    """
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {"title": title, "cases": []}

    # --- Resolve cases ---
    case_dirs: list[Path] = []
    if cases_dir:
        for part in cases_dir.split(","):
            p = Path(part.strip())
            if p.is_dir():
                case_dirs.append(p)

    # If explicit file paths given and no case_dirs, treat as single-case
    if not case_dirs and (bands_file or dos_file or scf_output):
        case_dirs = [Path(".")]  # sentinel

    for cd in case_dirs:
        case_data: dict[str, Any] = {"dir": str(cd), "label": cd.name}

        _bands = _resolve_bands(cd, bands_file)
        _bands_ga = _resolve_bands_ga(cd)  # Γ-A out-of-plane path
        _dos = _resolve_dos(cd, dos_file)
        _scf = _resolve_scf(cd, scf_output)

        if _scf:
            scf = parse_qe_output(_scf)
            case_data["scf"] = {
                "program": scf.program, "version": scf.version,
                "total_energy_ry": scf.total_energy_ry,
                "total_energy_ev": scf.total_energy_ev,
                "fermi_energy_ev": scf.fermi_energy_ev,
                "scf_converged": scf.scf_converged,
                "scf_iterations": scf.scf_iterations,
                "wall_time_sec": scf.wall_time_sec,
            }
            case_data.setdefault("fermi_energy", scf.fermi_energy_ev or 0.0)

        if _dos:
            dos = parse_dos_output(_dos)
            # Build array of DOS datasets: [{"label":"TDOS","data":[...]}, ...]
            dos_sets: list[dict[str, Any]] = [
                {"label": "TDOS", "data": dos.dos_data}
            ]
            # Auto-detect PDOS files from the same directory
            pdos_dir = _dos.parent if _dos.parent.exists() else cd / "output"
            try:
                pdos_results = parse_pdos_bundle(pdos_dir)
                import re as _re

                # First pass: detect which (elem, orb) combos have duplicates
                # so we can append wfc index only when needed
                parsed_labels = []
                for p in pdos_results:
                    lbl = p.label
                    atm_m = _re.search(r"atm#(\d+)\((\w+)\)", lbl)
                    wfc_m = _re.search(r"_wfc#(\d+)\((\w)\)", lbl)
                    elem = atm_m.group(2) if atm_m else "?"
                    atm_idx = atm_m.group(1) if atm_m else ""
                    orb = wfc_m.group(2) if wfc_m else ""
                    wfc_idx = wfc_m.group(1) if wfc_m else ""
                    parsed_labels.append({
                        "elem": elem, "atm_idx": atm_idx,
                        "orb": orb, "wfc_idx": wfc_idx,
                        "data": p.data,
                    })

                # Count occurrences of each (elem, atm_idx, orb) key
                from collections import Counter
                key_counts = Counter(
                    f"{pl['elem']}[{pl['atm_idx']}]-{pl['orb']}" if pl['atm_idx'] else f"{pl['elem']}-{pl['orb']}"
                    for pl in parsed_labels
                )

                for pl in parsed_labels:
                    base = f"{pl['elem']}[{pl['atm_idx']}]-{pl['orb']}" if pl['atm_idx'] else f"{pl['elem']}-{pl['orb']}"
                    # If multiple wfc share the same label, append wfc index
                    if key_counts.get(base, 1) > 1 and pl['wfc_idx']:
                        short = f"{base}(wfc{pl['wfc_idx']})"
                    else:
                        short = base
                    dos_sets.append({"label": f"PDOS({short})", "data": pl["data"]})
            except Exception:
                pass  # No PDOS files found or parse error — OK

            case_data["dos"] = {
                "e_fermi_ev": dos.e_fermi_ev,
                "n_points": dos.n_points,
                "e_min": dos.e_min,
                "e_max": dos.e_max,
                "datasets": dos_sets,
            }
            case_data.setdefault("fermi_energy", dos.e_fermi_ev or 0.0)

        if _bands:
            bands = parse_bands_output(_bands)
            k_dists = compute_k_distances(bands.k_points)
            hs = _detect_high_symmetry(bands.k_points, k_dists)
            case_data["bands"] = {
                "nbnd": bands.nbnd, "nks": bands.nks,
                "k_distances": k_dists,
                "bands": bands.bands,
                "high_symmetry": hs,
                "path_label": "Γ-M-K-Γ",
            }

        if _bands_ga:
            bands_ga = parse_bands_output(_bands_ga)
            k_dists_ga = compute_k_distances(bands_ga.k_points)
            case_data["bands_ga"] = {
                "nbnd": bands_ga.nbnd, "nks": bands_ga.nks,
                "k_distances": k_dists_ga,
                "bands": bands_ga.bands,
                "high_symmetry": [{"label": "Γ", "distance": 0.0},
                                  {"label": "A", "distance": k_dists_ga[-1]}],
                "path_label": "Γ-A",
            }

        # Run comprehensive physics analysis on main bands
        ef = case_data.get("fermi_energy", 0.0)
        dos_for_physics = case_data.get("dos") if "dos" in case_data else None
        bands_ga_for_physics = case_data.get("bands_ga") if "bands_ga" in case_data else None
        if "bands" in case_data:
            physics = analyze_bands_physics(
                case_data["bands"],
                dos_for_physics,
                ef,
                bands_ga_data=bands_ga_for_physics,
                run_transport=True,
                run_jdos=True,
                run_advanced=True,
            )
            case_data["physics"] = physics

        # Only include case if it has data
        if any(k in case_data for k in ("scf", "dos", "bands")):
            payload["cases"].append(case_data)

    if extra_json:
        payload.update(extra_json)

    data_json = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    html = _WORKBENCH_TEMPLATE.replace("__DATA_PAYLOAD__", data_json)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def _resolve_bands(case_dir: Path, explicit: Path | str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    out = case_dir / "output"
    candidates = sorted(out.glob("HfBr2.bands*")) if out.exists() else []
    # Prefer the main bands file (Γ-M-K-Γ path). Exclude GA (out-of-plane).
    main = [c for c in candidates if "GA" not in c.name.upper() and "bands_ga" not in c.name.lower()]
    return main[0] if main else (candidates[0] if candidates else None)


def _resolve_bands_ga(case_dir: Path) -> Path | None:
    out = case_dir / "output"
    candidates = sorted(out.glob("HfBr2.bands_GA*")) if out.exists() else []
    return candidates[0] if candidates else None


def _resolve_dos(case_dir: Path, explicit: Path | str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    p = case_dir / "output" / "HfBr2.dos"
    return p if p.exists() else None


def _resolve_scf(case_dir: Path, explicit: Path | str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    p = case_dir / "output" / "scf.out"
    return p if p.exists() else None

# ---------------------------------------------------------------------------
# HTML Template
# ---------------------------------------------------------------------------

_WORKBENCH_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VibeDFT Analysis Workbench</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.1.0/dist/chartjs-plugin-annotation.min.js"></script>
<style>
:root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--green:#3fb950;--red:#f85149;--orange:#d2991d;--fermi:#ffd700}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
header{background:var(--panel);border-bottom:1px solid var(--border);padding:10px 20px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;position:sticky;top:0;z-index:10}
header h1{font-size:16px;font-weight:600}
.meta{font-size:11px;color:var(--muted)}
main{padding:12px 20px;max-width:1600px;margin:0 auto}
.case-tabs{display:flex;gap:4px;margin-bottom:12px;flex-wrap:wrap}
.case-tab{padding:6px 14px;border:1px solid var(--border);border-radius:6px 6px 0 0;background:var(--panel);color:var(--muted);cursor:pointer;font-size:12px;border-bottom:none}
.case-tab.active{color:var(--text);background:var(--accent);color:#000;font-weight:600}
.case-grid{display:grid;grid-template-columns:4fr 3fr;gap:12px;align-items:stretch}
@media(max-width:1000px){.case-grid{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:14px}
.panel h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--border);color:var(--muted);display:flex;align-items:center;gap:6px}
.panel.full{grid-column:1/-1}
.chart-wrap{position:relative;width:100%;height:420px;display:flex;align-items:stretch}
.chart-wrap canvas{width:100%!important;height:100%!important}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin-bottom:10px}
.stat{padding:8px 12px;border:1px solid var(--border);border-radius:6px;background:rgba(255,255,255,.02)}
.stat .label{font-size:10px;color:var(--muted);text-transform:uppercase;margin-bottom:2px}
.stat .value{font-size:16px;font-weight:600}
.stat .value.ok{color:var(--green)}.stat .value.warn{color:var(--orange)}.stat .value.err{color:var(--red)}
.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:6px 0 10px}
.controls label{font-size:11px;color:var(--muted);display:flex;align-items:center;gap:4px;white-space:nowrap}
.controls select,.controls input[type=number]{background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:3px 6px;font-size:11px}
.controls input[type=range]{width:80px;accent-color:var(--accent)}
.controls input[type=checkbox]{accent-color:var(--accent)}
button{background:var(--accent);color:#000;border:none;border-radius:4px;padding:4px 10px;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap}
button:hover{opacity:.85}
button.small{padding:2px 8px;font-size:10px}
.empty{color:var(--muted);font-style:italic;padding:20px;text-align:center}
.fermi-line{stroke:var(--fermi);stroke-dasharray:6,4;stroke-width:1.5}
.fermi-label{fill:var(--fermi);font-size:10px}
.dos-toggle{display:flex;gap:4px;flex-wrap:wrap;margin:4px 0}
.dos-toggle label{font-size:10px;padding:2px 6px;border:1px solid var(--border);border-radius:3px;cursor:pointer;color:var(--muted)}
.dos-toggle input:checked+span{color:var(--accent)}
.analysis-panel{font-size:12px;line-height:1.6;color:var(--muted)}
.analysis-panel .insight{border-left:3px solid var(--accent);padding:4px 8px;margin:6px 0;background:rgba(88,166,255,.05);border-radius:0 4px 4px 0}
</style>
</head>
<body>
<header>
  <h1>⚛ VibeDFT Analysis Workbench</h1>
  <span class="meta" id="headerMeta"></span>
  <span style="flex:1"></span>
  <div class="controls" style="margin:0">
    <label>Bands E <input id="bandsEmin" type="number" value="-8" step="0.5" style="width:55px"> – <input id="bandsEmax" type="number" value="8" step="0.5" style="width:55px"></label>
    <input id="bandsEminR" type="range" min="-20" max="20" value="-8" step="0.5" style="width:80px">
    <input id="bandsEmaxR" type="range" min="-20" max="20" value="8" step="0.5" style="width:80px">
    <label>Dos E <input id="dosEmin" type="number" value="-8" step="0.5" style="width:55px"> – <input id="dosEmax" type="number" value="8" step="0.5" style="width:55px"></label>
    <input id="dosEminR" type="range" min="-20" max="20" value="-8" step="0.5" style="width:80px">
    <input id="dosEmaxR" type="range" min="-20" max="20" value="8" step="0.5" style="width:80px">
    <label><input id="syncERange" type="checkbox" checked> Sync E</label>
    <label><input id="bandsFermiShift" type="checkbox" checked> Bands E−E<sub>F</sub></label>
    <label><input id="dosFermiShift" type="checkbox" checked> Dos E−E<sub>F</sub></label>
    <span style="border-left:1px solid var(--border);height:20px;margin:0 4px"></span>
    <label>Path <select id="bandsPathSel" style="font-size:11px"><option value="main">Γ-M-K-Γ</option></select></label>
    <span style="border-left:1px solid var(--border);height:20px;margin:0 4px"></span>
    <label>Orient <select id="dosOrient"><option value="vertical">V</option><option value="horizontal" selected>H</option></select></label>
    <label>DOS rng <input id="dosXmin" type="number" value="0" step="1" style="width:50px"> – <input id="dosXmax" type="number" value="auto" step="1" style="width:55px" placeholder="auto"></label>
    <label><input id="dosSmooth" type="checkbox"> Smooth <input id="dosSmoothWin" type="number" value="15" min="3" max="101" step="2" style="width:42px"></label>
    <span id="pdosToggles" style="display:flex;gap:3px;flex-wrap:wrap;align-items:center"></span>
  </div>
</header>
<main>
  <div id="caseTabs" class="case-tabs"></div>
  <div id="caseContent"></div>
  <div class="panel full analysis-panel" id="analysisPanel">
    <h2>📋 Quick Analysis</h2>
    <div id="analysisContent"><span class="empty">Load data to see automated analysis.</span></div>
  </div>
</main>

<script>
const DATA = __DATA_PAYLOAD__;
const el = id => document.getElementById(id);
const fmt = (v,d) => (v!=null?Number(v).toFixed(d):'N/A');

let allCharts = [];
let activeCaseIdx = 0;

// ---- Global E-range sync ----
// ---- Per-panel E-range state ----
function getBandsERange() {
  return { min: parseFloat(el('bandsEmin').value), max: parseFloat(el('bandsEmax').value) };
}
function getDosERange() {
  return { min: parseFloat(el('dosEmin').value), max: parseFloat(el('dosEmax').value) };
}
function setERangeDefaults(min,max) {
  ['bands','dos'].forEach(which => {
    el(which+'Emin').value = min; el(which+'EminR').value = min;
    el(which+'Emax').value = max; el(which+'EmaxR').value = max;
  });
}
function applyBandsERange() {
  const r = getBandsERange();
  el('bandsEminR').value=r.min; el('bandsEmaxR').value=r.max;
  if (el('syncERange').checked) {
    el('dosEmin').value=r.min; el('dosEminR').value=r.min;
    el('dosEmax').value=r.max; el('dosEmaxR').value=r.max;
  }
  for (const c of allCharts) {
    if (c._isBands) { c.options.scales.y.min=r.min; c.options.scales.y.max=r.max; c.update(); }
    else if (c._isDos) {
      const er = el('syncERange').checked ? r : getDosERange();
      if (c._orientation==='vertical') { c.options.scales.y.min=er.min; c.options.scales.y.max=er.max; }
      else { c.options.scales.x.min=er.min; c.options.scales.x.max=er.max; }
      c.update();
    }
  }
}
function applyDosERange() {
  const r = getDosERange();
  el('dosEminR').value=r.min; el('dosEmaxR').value=r.max;
  if (el('syncERange').checked) {
    el('bandsEmin').value=r.min; el('bandsEminR').value=r.min;
    el('bandsEmax').value=r.max; el('bandsEmaxR').value=r.max;
  }
  for (const c of allCharts) {
    if (c._isDos) {
      const er = el('syncERange').checked ? r : getDosERange();
      if (c._orientation==='vertical') { c.options.scales.y.min=er.min; c.options.scales.y.max=er.max; }
      else { c.options.scales.x.min=er.min; c.options.scales.x.max=er.max; }
      c.update();
    } else if (c._isBands && el('syncERange').checked) {
      c.options.scales.y.min=r.min; c.options.scales.y.max=r.max; c.update();
    }
  }
}
// Wire up: number inputs + range sliders for bands
['bands','dos'].forEach(which => {
  const applyFn = which==='bands' ? applyBandsERange : applyDosERange;
  el(which+'Emin').addEventListener('change', () => { el(which+'EminR').value=el(which+'Emin').value; applyFn(); });
  el(which+'Emax').addEventListener('change', () => { el(which+'EmaxR').value=el(which+'Emax').value; applyFn(); });
  el(which+'EminR').addEventListener('input', () => { el(which+'Emin').value=el(which+'EminR').value; applyFn(); });
  el(which+'EmaxR').addEventListener('input', () => { el(which+'Emax').value=el(which+'EmaxR').value; applyFn(); });
});
el('syncERange').addEventListener('change', () => {
  if (el('syncERange').checked) {
    // On re-enable sync, copy bands range to dos
    const br = getBandsERange();
    el('dosEmin').value=br.min; el('dosEminR').value=br.min;
    el('dosEmax').value=br.max; el('dosEmaxR').value=br.max;
    applyBandsERange();
  }
});
el('bandsFermiShift').addEventListener('change', () => { rebuildActiveCase(); });
el('dosFermiShift').addEventListener('change', () => { rebuildActiveCase(); });


// ---- Tab switching ----
function switchCase(idx) {
  activeCaseIdx = idx;
  document.querySelectorAll('.case-tab').forEach((t,i) => t.classList.toggle('active', i===idx));
  renderCase(DATA.cases[idx], idx);
}
function renderTabs() {
  const tabs = DATA.cases.map((c,i) =>
    `<span class="case-tab${i===0?' active':''}" onclick="switchCase(${i})">${esc(c.label||'Case '+(i+1))}</span>`
  ).join('');
  el('caseTabs').innerHTML = tabs;
  if (DATA.cases.length) renderCase(DATA.cases[0], 0);
}

// ---- Main render ----
function rebuildActiveCase() { if (DATA.cases.length) renderCase(DATA.cases[activeCaseIdx], activeCaseIdx); }

function renderCase(caseData, idx) {
  allCharts = [];
  const bandsShift = el('bandsFermiShift').checked ? (caseData.fermi_energy ?? 0) : 0;
  const bandsEr = getBandsERange();
  const dosEr = getDosERange();
  const prefix = 'c'+idx+'_';

  let html = '';
  // SCF
  if (caseData.scf) {
    const s = caseData.scf;
    const items = [
      ['Program', s.program+' v'+s.version], ['Total Energy', fmt(s.total_energy_ry,6)+' Ry'],
      ['Fermi Energy', fmt(s.fermi_energy_ev,4)+' eV'],
      ['SCF', s.scf_converged?'✅ Converged':'❌ Not converged', s.scf_converged?'ok':'err'],
      ['Iterations', s.scf_iterations], ['Wall Time', fmt(s.wall_time_sec,1)+' s']
    ];
    html += `<div class="panel full"><h2>📊 SCF Summary — ${esc(caseData.label)}</h2><div class="stats">`+
      items.map(([l,v,c])=>`<div class="stat"><div class="label">${l}</div><div class="value ${c||''}">${v}</div></div>`).join('')+
      `</div></div>`;
  }
  html += '<div class="case-grid">';

  // Bands
  let hasGa = !!(caseData.bands_ga);
  html += `<div class="panel"><h2>🎵 Band Structure</h2>`;
  html += `<div class="chart-wrap bands-wrap"><canvas id="${prefix}bandsChart"></canvas></div></div>`;
  // DOS
  html += `<div class="panel"><h2>📈 Density of States</h2><div class="chart-wrap dos-wrap"><canvas id="${prefix}dosChart"></canvas></div></div>`;

  html += '</div>';
  el('caseContent').innerHTML = html;

  // Populate global PDOS toggles in header
  if (caseData.dos && caseData.dos.datasets && caseData.dos.datasets.length > 1) {
    let tags = '';
    caseData.dos.datasets.forEach((ds, i) => {
      const checked = i === 0 ? ' checked' : '';
      const color = ['#f85149','#58a6ff','#3fb950','#d2991d','#bc8cff'][i%5];
      tags += `<label class="pdos-tag" data-idx="${i}" style="display:inline-flex;align-items:center;gap:3px;font-size:10px;padding:2px 6px;border:1px solid var(--border);border-radius:3px;cursor:pointer;margin:0 1px;background:${checked?'rgba(88,166,255,.15)':'transparent'}">
        <span style="display:inline-block;width:7px;height:7px;border-radius:2px;background:${color}"></span>
        <input type="checkbox"${checked} style="display:none"> ${ds.label}</label>`;
    });
    el('pdosToggles').innerHTML = tags;
  } else {
    el('pdosToggles').innerHTML = '';
  }

  // Populate header band-path selector
  const pathSel = el('bandsPathSel');
  if (pathSel) {
    let pathOpts = '<option value="main">Γ-M-K-Γ (in-plane)</option>';
    if (hasGa) pathOpts += '<option value="ga">Γ-A (out-of-plane)</option>';
    pathSel.innerHTML = pathOpts;
    pathSel.value = 'main';
  }
  // ---- Bands chart ----
  if (caseData.bands) {
    const b = caseData.bands;
    const datasets = b.bands.map((energies, ib) => ({
      label: `Band ${ib+1}`,
      data: energies.map((e,ik) => ({x: b.k_distances[ik], y: e - bandsShift})),
      borderColor: `hsl(${(ib*360/b.nbnd)%360},70%,60%)`,
      borderWidth: 0.8, pointRadius: 0
    }));
    const annotations = {};
    if (b.high_symmetry) {
      b.high_symmetry.forEach((hs,i) => {
        annotations[`hs${i}`] = {
          type:'line', mode:'vertical', scaleID:'x', value:hs.distance,
          borderColor:'#8b949e', borderWidth:1, borderDash:[4,4],
          label:{content:hs.label,display:true,position:'start',backgroundColor:'rgba(0,0,0,.7)',color:'#e6edf3',font:{size:12}}
        };
      });
    }
    // Fermi level annotation
    annotations['fermi'] = {
      type:'line', mode:'horizontal', scaleID:'y', value:0,
      borderColor:'#ffd700', borderWidth:1.5, borderDash:[6,4],
      label:{content:'EF',display:true,position:'end',backgroundColor:'rgba(0,0,0,.7)',color:'#ffd700',font:{size:11,weight:'bold'}}
    };

    function buildBandsData(bdata, sft) {
      const ds = bdata.bands.map((energies, ib) => ({
        label: `Band ${ib+1}`,
        data: energies.map((e,ik) => ({x: bdata.k_distances[ik], y: e - sft})),
        borderColor: `hsl(${(ib*360/bdata.nbnd)%360},70%,60%)`,
        borderWidth: 0.8, pointRadius: 0
      }));
      const ann = {};
      if (bdata.high_symmetry) {
        bdata.high_symmetry.forEach((hs,i) => {
          ann[`hs${i}`] = {
            type:'line', mode:'vertical', scaleID:'x', value:hs.distance,
            borderColor:'#8b949e', borderWidth:1, borderDash:[4,4],
            label:{content:hs.label,display:true,position:'start',backgroundColor:'rgba(0,0,0,.7)',color:'#e6edf3',font:{size:12}}
          };
        });
      }
      ann['fermi'] = {
        type:'line', mode:'horizontal', scaleID:'y', value:0,
        borderColor:'#ffd700', borderWidth:1.5, borderDash:[6,4],
        label:{content:'EF',display:true,position:'end',backgroundColor:'rgba(0,0,0,.7)',color:'#ffd700',font:{size:11,weight:'bold'}}
      };
      return {datasets: ds, annotations: ann, nks: bdata.nks, nbnd: bdata.nbnd, hs: bdata.high_symmetry};
    }

    let currentBandsData = buildBandsData(b, bandsShift);
    const bc = new Chart(el(prefix+'bandsChart'), {
      type:'line', data:{datasets: currentBandsData.datasets},
      options:{
        responsive:true, maintainAspectRatio:false, animation:false,
        scales:{
          x:{type:'linear',title:{display:true,text:currentBandsData.hs?'k-path distance':'k index'},ticks:{maxTicksLimit:12}},
          y:{title:{display:true,text:bandsShift?'E − EF (eV)':'Energy (eV)'},min:bandsEr.min,max:bandsEr.max}
        },
        plugins:{legend:{display:false}, annotation:{annotations: currentBandsData.annotations}}
      }
    });
    bc._isBands = true; bc._caseData = caseData;
    // Store pre-built bands data for path switching
    bc._bandsMain = currentBandsData;
    if (caseData.bands_ga) {
      const bga = caseData.bands_ga;
      bc._bandsGa = {
        datasets: bga.bands.map((energies, ib) => ({
          label: `Band ${ib+1}`,
          data: energies.map((e,ik) => ({x: bga.k_distances[ik], y: e - bandsShift})),
          borderColor: `hsl(${(ib*360/bga.nbnd)%360},70%,60%)`,
          borderWidth: 0.8, pointRadius: 0
        })),
        annotations: (() => {
          const ann = {};
          (bga.high_symmetry||[{label:'Γ',distance:0},{label:'A',distance:bga.k_distances[bga.k_distances.length-1]}]).forEach((hs,i) => {
            ann[`hs${i}`] = {type:'line',mode:'vertical',scaleID:'x',value:hs.distance,borderColor:'#8b949e',borderWidth:1,borderDash:[4,4],label:{content:hs.label,display:true,position:'start',backgroundColor:'rgba(0,0,0,.7)',color:'#e6edf3',font:{size:12}}};
          });
          ann['fermi'] = {type:'line',mode:'horizontal',scaleID:'y',value:0,borderColor:'#ffd700',borderWidth:1.5,borderDash:[6,4],label:{content:'EF',display:true,position:'end',backgroundColor:'rgba(0,0,0,.7)',color:'#ffd700',font:{size:11,weight:'bold'}}};
          return ann;
        })(),
        nks: bga.nks, nbnd: bga.nbnd,
        hs: bga.high_symmetry||[{label:'Γ',distance:0},{label:'A',distance:bga.k_distances[bga.k_distances.length-1]}],
      };
    }
    allCharts.push(bc);
  }

  // Wire header path selector globally (once)
  if (!window._pathSelWired) {
    window._pathSelWired = true;
    el('bandsPathSel').addEventListener('change', () => {
      const isGa = el('bandsPathSel').value === 'ga';
      const bc = allCharts.find(c => c._isBands);
      if (!bc) return;
      const nd = isGa ? bc._bandsGa : bc._bandsMain;
      if (!nd) return;
      bc.data.datasets = nd.datasets;
      bc.options.plugins.annotation.annotations = nd.annotations;
      bc.options.scales.x.title.text = isGa ? 'k-path (Γ→A)' : 'k-path (Γ-M-K-Γ)';
      bc.update();
    });
  }

  // ---- DOS chart ----
  if (caseData.dos) {
    const d = caseData.dos;
    const isVert = el('dosOrient').value === 'vertical';
    const dosShift = el('dosFermiShift').checked ? (caseData.fermi_energy ?? 0) : 0;
    const dsets = (d.datasets||[{label:'TDOS',data:d.data||[]}]).map((ds,i) => {
      const color = ['#f85149','#58a6ff','#3fb950','#d2991d','#bc8cff'][i%5];
      const pts = isVert
        ? ds.data.map(r=>({x:r.dos, y:r.energy_ev-dosShift}))
        : ds.data.map(r=>({x:r.energy_ev-dosShift, y:r.dos}));
      return {label:ds.label,data:pts,borderColor:color,backgroundColor:color+'22',borderWidth:1.2,pointRadius:0,fill:i===0,hidden:i>0};
    });
    const dosAnnotations = {
      fermi:{type:'line',mode:isVert?'horizontal':'vertical',scaleID:isVert?'y':'x',value:isVert?0:0,
             borderColor:'#ffd700',borderWidth:1.5,borderDash:[6,4],
             label:{content:'EF',display:true,position:'end',backgroundColor:'rgba(0,0,0,.7)',color:'#ffd700',font:{size:11,weight:'bold'}}}
    };

    const dc = new Chart(el(prefix+'dosChart'), {
      type:'line', data:{datasets:dsets},
      options:{
        responsive:true, maintainAspectRatio:false, animation:false,
        scales:{
          x:{type:'linear',title:{display:true,text:isVert?'DOS (states/eV)':(dosShift?'E − EF (eV)':'Energy (eV)')},
             min:isVert?undefined:dosEr.min, max:isVert?undefined:dosEr.max},
          y:{title:{display:true,text:isVert?(dosShift?'E − EF (eV)':'Energy (eV)'):'DOS (states/eV)'},
             min:isVert?dosEr.min:undefined, max:isVert?dosEr.max:undefined}
        },
        plugins:{legend:{display:false},
                 annotation:{annotations:dosAnnotations}}
      }
    });
    dc._isDos = true; dc._orientation = isVert?'vertical':'horizontal'; allCharts.push(dc);

    // Sync chart heights (bands and dos already share same CSS height: 420px)
    // No JS sync needed — CSS grid with align-items:stretch handles alignment

    // Store original data for smooth toggle
    dc._dosOriginal = (d.datasets||[{label:'TDOS',data:d.data||[]}]).map(ds => ({
      label: ds.label,
      data: ds.data.map(r => ({energy_ev: r.energy_ev, dos: r.dos, int_dos: r.int_dos}))
    }));

    // Smooth toggle
    function applyDosSmooth() {
      const win = parseInt(el('dosSmoothWin').value) || 15;
      const enabled = el('dosSmooth').checked;
      const orig = dc._dosOriginal;
      const v = dc._orientation === 'vertical';
      const shiftVal = el('dosFermiShift').checked ? (caseData.fermi_energy??0) : 0;
      orig.forEach((ods, i) => {
        const ds = dc.data.datasets[i];
        if (!ds) return;
        const src = enabled ? smoothDOS(ods.data, win) : ods.data;
        ds.data = v
          ? src.map(r => ({x: r.dos, y: r.energy_ev - shiftVal}))
          : src.map(r => ({x: r.energy_ev - shiftVal, y: r.dos}));
      });
      dc.update();
    }
    el('dosSmooth').addEventListener('change', applyDosSmooth);
    el('dosSmoothWin').addEventListener('change', applyDosSmooth);

    // DOS-X range controls (states/eV axis)
    function applyDosXRange() {
      const v = dc._orientation === 'vertical';
      const rawMin = (el('dosXmin')||{}).value||'';
      const rawMax = (el('dosXmax')||{}).value||'';
      let minV = undefined, maxV = undefined;
      const vMin = parseFloat(rawMin), vMax = parseFloat(rawMax);
      if (rawMin !== '' && rawMin !== 'auto' && !isNaN(vMin)) minV = vMin;
      if (rawMax !== '' && rawMax !== 'auto' && !isNaN(vMax)) maxV = vMax;
      if (v) { dc.options.scales.x.min = minV; dc.options.scales.x.max = maxV; }
      else   { dc.options.scales.y.min = minV; dc.options.scales.y.max = maxV; }
      dc.update();
    }
    el('dosXmin').addEventListener('change', applyDosXRange);
    el('dosXmax').addEventListener('change', applyDosXRange);

    el('dosOrient').addEventListener('change', () => {
      const v = el('dosOrient').value === 'vertical';
      const d = caseData.dos;
      const shift2 = el('dosFermiShift').checked ? (caseData.fermi_energy??0) : 0;
      const dosEr2 = getDosERange();
      (d.datasets||[{label:'TDOS',data:d.data||[]}]).forEach((ds, i) => {
        const existing = dc.data.datasets[i];
        if (!existing) return;
        existing.data = v
          ? ds.data.map(r2=>({x:r2.dos, y:r2.energy_ev-shift2}))
          : ds.data.map(r2=>({x:r2.energy_ev-shift2, y:r2.dos}));
      });
      const sx = dc.options.scales.x, sy = dc.options.scales.y;
      sx.title.text = v ? 'DOS (states/eV)' : (shift2 ? 'E − EF (eV)' : 'Energy (eV)');
      sy.title.text = v ? (shift2 ? 'E − EF (eV)' : 'Energy (eV)') : 'DOS (states/eV)';
      if (!v) { sx.min = dosEr2.min; sx.max = dosEr2.max; sx.type = 'linear'; }
      else     { sx.min = undefined; sx.max = undefined; }
      if (v)  { sy.min = dosEr2.min; sy.max = dosEr2.max; }
      else    { sy.min = undefined; sy.max = undefined; }
      // Swap EF annotation mode
      const fa = dc.options.plugins.annotation.annotations.fermi;
      if (fa) { fa.mode = v ? 'horizontal' : 'vertical'; fa.scaleID = v ? 'y' : 'x'; }
      dc._orientation = v ? 'vertical' : 'horizontal';
      // Re-apply DOS-X range after orientation change
      applyDosXRange();
    });
  }

  // ---- Analysis ----
  renderAnalysis(caseData);
}

function renderAnalysis(caseData) {
  let lines = [];
  const p = caseData.physics || {};
  const ef = caseData.fermi_energy ?? 0;

  // --- SCF ---
  if (caseData.scf) {
    const s = caseData.scf;
    lines.push('<div class="insight">🔬 <b>SCF:</b> Total energy = '+fmt(s.total_energy_ry,6)+' Ry, '+(s.scf_converged?'converged':'<span style=color:var(--red)>NOT converged</span>')+' in '+s.scf_iterations+' iterations.</div>');
  }

  // --- Band gap (enhanced) ---
  if (p.band_gap) {
    const bg = p.band_gap;
    const typeIcon = bg.type==='direct'?'☀ Direct':'↗ Indirect';
    const typeColor = bg.type==='direct'?'var(--green)':'var(--orange)';
    if (bg.gap_ev != null && bg.gap_ev > 0.01) {
      lines.push('<div class="insight">📐 <b>Band gap:</b> <span style="color:'+typeColor+'">'+typeIcon+'</span> — VBM='+fmt(bg.vbm_ev,4)+' eV, CBM='+fmt(bg.cbm_ev,4)+' eV → gap = '+fmt(bg.gap_ev,4)+' eV'+(bg.optical_gap_ev!=null?' · Optical gap = '+fmt(bg.optical_gap_ev,4)+' eV':'')+'</div>');
    } else {
      lines.push('<div class="insight">📐 <b>Band gap:</b> <span style="color:var(--green)">Metallic</span> (zero or negative gap)</div>');
    }
    if (bg.stokes_shift_ev != null && bg.stokes_shift_ev > 0.01) {
      lines.push('<div class="insight">💡 <b>Stokes shift:</b> '+fmt(bg.stokes_shift_ev,4)+' eV (optical gap − electronic gap) → indirect-gap fingerprint</div>');
    }
  }

  // --- Directional Effective Mass Tensor ---
  if (p.effective_mass) {
    const em = p.effective_mass;
    let emRows = '';
    const allDirs = [...(em.cbm||[]), ...(em.vbm||[])];
    if (allDirs.length > 0) {
      allDirs.forEach(r => {
        const q = r.r_squared != null && r.r_squared > 0.9 ? '✅' : r.r_squared != null && r.r_squared > 0.7 ? '⚠' : '❌';
        emRows += '<tr><td>'+(r.m_eff_me!=null?(r.m_eff_me>0?'e⁻':'h⁺'):'?')+'</td><td>'+r.direction_label+'</td><td>'+fmt(r.m_eff_me,3)+'</td><td>'+q+' R²='+fmt(r.r_squared,3)+'</td><td>n='+r.n_points+'</td></tr>';
      });
      lines.push('<div class="insight">⚡ <b>Directional Effective Masses (m*/mₑ):</b><table style="margin-top:4px;font-size:11px"><thead><tr><th>Type</th><th>Direction</th><th>m*/mₑ</th><th>Quality</th><th>Pts</th></tr></thead><tbody>'+emRows+'</tbody></table></div>');
    }
    // Backward-compatible scalar CBM effective mass
    if (p.effective_mass_cbm && p.effective_mass_cbm.m_eff_me != null) {
      const sc = p.effective_mass_cbm;
      lines.push('<div class="insight">⚡ <b>Effective mass (CBM, scalar):</b> m*/mₑ = '+fmt(sc.m_eff_me,3)+' R²='+fmt(sc.r_squared,3)+'</div>');
    }
  }

  // --- Fermi velocity ---
  if (p.fermi_velocity && p.fermi_velocity.n_crossings > 0) {
    const fv = p.fermi_velocity;
    lines.push('<div class="insight">🏃 <b>Fermi velocity:</b> '+fv.n_crossings+' EF crossings, avg vF = '+fmt(fv.avg_v_fermi_A_per_fs,2)+' Å/fs'+(fv.crossings.length>0?' · max vF = '+fmt(Math.max(...fv.crossings.map(function(c){return c.v_fermi_A_per_fs})),2)+' Å/fs':'')+'</div>');
  }

  // --- Van Hove singularities ---
  if (p.van_hove && p.van_hove.length > 0) {
    const vhs = p.van_hove.slice(0, 5).map(function(v){return 'E='+fmt(v.energy_vs_ef,3)+' eV (vs EF), DOS='+v.dos_value.toExponential(1)}).join('; ');
    lines.push('<div class="insight">📈 <b>Van Hove singularities (top 5):</b> '+vhs+'</div>');
  }

  // --- JDOS (Optical absorption) ---
  if (p.jdos && p.jdos.peaks && p.jdos.peaks.length > 0) {
    const j = p.jdos;
    const onsetInfo = j.optical_onset_ev != null ? ' · Optical onset: '+fmt(j.optical_onset_ev,3)+' eV' : '';
    lines.push('<div class="insight">🌈 <b>Joint DOS (optical absorption):</b> '+j.n_valence+' v-bands × '+j.n_conduction+' c-bands'+onsetInfo+'</div>');
    let jdosPeaks = j.peaks.slice(0,5).map(function(pk){return fmt(pk.energy_ev,3)+' eV (intensity '+fmt(pk.relative_intensity,2)+')'}).join('; ');
    lines.push('<div class="insight">🌈 <b>JDOS peaks:</b> '+jdosPeaks+'</div>');
    if (j.top_transitions && j.top_transitions.length > 0) {
      let trRows = j.top_transitions.slice(0,5).map(function(t){return '<tr><td>VB'+t.valence_band+' → CB'+t.conduction_band+'</td><td>'+fmt(t.min_transition_ev,3)+'</td><td>'+fmt(t.avg_transition_ev,3)+'</td></tr>'}).join('');
      lines.push('<details style="margin-top:4px"><summary style="cursor:pointer;color:var(--accent);font-size:11px">Top optical transitions</summary><table style="margin-top:4px;font-size:11px"><thead><tr><th>Transition</th><th>Min (eV)</th><th>Avg (eV)</th></tr></thead><tbody>'+trRows+'</tbody></table></details>');
    }
  }

  // --- CRTA Transport Coefficients ---
  if (p.transport && p.transport.sigma_over_tau_au != null) {
    const tr = p.transport;
    lines.push('<div class="insight">🔌 <b>CRTA Transport</b> (T='+tr.temperature_k+' K, approximate 1D-path):</div>');
    let trInfo = [];
    trInfo.push('σ/τ = '+tr.sigma_over_tau_au.toExponential(2)+' a.u.');
    if (tr.seebeck_uv_per_k != null) trInfo.push('S = '+fmt(tr.seebeck_uv_per_k,1)+' μV/K');
    if (tr.power_factor_over_tau_au != null) trInfo.push('PF/τ = '+tr.power_factor_over_tau_au.toExponential(2)+' a.u.');
    if (tr.kappa_e_over_tau_au != null) trInfo.push('κₑ/τ = '+tr.kappa_e_over_tau_au.toExponential(2)+' a.u.');
    if (tr.dln_tdf_dE_at_ef != null) trInfo.push('dlnΞ/dE|EF = '+fmt(tr.dln_tdf_dE_at_ef,3)+' eV⁻¹');
    lines.push('<div class="insight">'+trInfo.join(' · ')+'</div>');
    if (tr.caveat) lines.push('<div class="insight" style="font-size:10px;color:var(--orange)">⚠ '+tr.caveat+'</div>');
  }

  // --- Plasma Frequency ---
  if (p.plasma_frequency && p.plasma_frequency.omega_p_ev_estimate != null) {
    const pl = p.plasma_frequency;
    lines.push('<div class="insight">⚡ <b>Plasma frequency (intraband estimate):</b> ħω_p ≈ '+fmt(pl.omega_p_ev_estimate,3)+' eV (⟨v²⟩_EF = '+pl.velocity_squared_at_ef.toExponential(2)+' Å²/fs²)</div>');
  }

  // --- Band Degeneracy & Crystal Field ---
  if (p.degeneracy && p.degeneracy.gamma_point && p.degeneracy.gamma_point.degenerate_groups) {
    const dg = p.degeneracy;
    const grps = dg.gamma_point.degenerate_groups;
    let degenSummary = grps.map(function(g){return g.degeneracy+'× (E='+fmt(g.energy_vs_ef_ev,3)+' eV vs EF)'}).join(', ');
    lines.push('<div class="insight">🔷 <b>Γ-point degeneracy:</b> '+degenSummary+'</div>');
    if (dg.gamma_point.crystal_field_splittings && dg.gamma_point.crystal_field_splittings.length > 0) {
      let cfRows = dg.gamma_point.crystal_field_splittings.map(function(cf){
        return '<tr><td>'+cf.from_bands.join(',')+' → '+cf.to_bands.join(',')+'</td><td>'+fmt(cf.splitting_ev,4)+' eV</td><td style="font-size:10px;color:var(--muted)">'+cf.possible_origin+'</td></tr>';
      }).join('');
      lines.push('<details style="margin-top:4px"><summary style="cursor:pointer;color:var(--accent);font-size:11px">Crystal-field splittings</summary><table style="margin-top:4px;font-size:11px"><thead><tr><th>Transition</th><th>ΔE (eV)</th><th>Possible origin</th></tr></thead><tbody>'+cfRows+'</tbody></table></details>');
    }
  }

  // --- Avoided Crossings ---
  if (p.avoided_crossings && p.avoided_crossings.n_avoided_crossings > 0) {
    const ac = p.avoided_crossings;
    lines.push('<div class="insight">⚠ <b>Avoided crossings:</b> '+ac.n_avoided_crossings+' detected'+(ac.is_physically_interesting?' — potentially physically interesting!':'')+'</div>');
    let acRows = ac.avoided_crossings.slice(0,10).map(function(c){
      return '<tr><td>Band '+c.band_a+' ↔ Band '+c.band_b+'</td><td>ΔE<sub>min</sub>='+fmt(c.min_gap_ev,4)+' eV</td><td>@ k-idx '+c.k_index+'</td></tr>';
    }).join('');
    lines.push('<details style="margin-top:4px"><summary style="cursor:pointer;color:var(--accent);font-size:11px">Avoided crossing details</summary><table style="margin-top:4px;font-size:11px"><thead><tr><th>Band pair</th><th>Min gap</th><th>Location</th></tr></thead><tbody>'+acRows+'</tbody></table></details>');
  }

  // --- Fermi Surface ---
  if (p.fermi_surface) {
    const fs = p.fermi_surface;
    if (fs.n_bands_crossing_ef > 0) {
      lines.push('<div class="insight">🔄 <b>Fermi surface:</b> '+(fs.is_metallic?'Metallic':'')+' — '+fs.n_bands_crossing_ef+' bands cross EF · '+fs.n_electron_pockets+' e⁻ pockets + '+fs.n_hole_pockets+' h⁺ pockets · '+fs.n_pockets+' total</div>');
      if (fs.estimated_n_2d_per_unit_cell != null) {
        lines.push('<div class="insight">📐 <b>Est. 2D carrier density:</b> n₂D ≈ '+fs.estimated_n_2d_per_unit_cell.toExponential(2)+' per unit cell (from 1D path Fermi wavevectors)</div>');
      }
      if (fs.pockets && fs.pockets.length > 0) {
        let pkRows = fs.pockets.map(function(pk){
          return '<tr><td>Band '+pk.band_indices.join(',')+'</td><td>'+pk.carrier_type+'</td><td>Δk_F='+fmt(pk.kf_range,4)+'</td><td>'+pk.n_crossings+' crossings</td></tr>';
        }).join('');
        lines.push('<details style="margin-top:4px"><summary style="cursor:pointer;color:var(--accent);font-size:11px">Fermi surface pockets</summary><table style="margin-top:4px;font-size:11px"><thead><tr><th>Bands</th><th>Type</th><th>Δk_F</th><th>Crossings</th></tr></thead><tbody>'+pkRows+'</tbody></table></details>');
      }
    } else {
      lines.push('<div class="insight">🔄 <b>Fermi surface:</b> Insulating — no bands cross EF</div>');
    }
  }

  // --- Dimensionality ---
  if (p.dimensionality) {
    const dim = p.dimensionality;
    lines.push('<div class="insight">📏 <b>Dimensionality:</b> In-plane bandwidth = '+fmt(dim.avg_in_plane_bandwidth_ev,3)+' eV (max '+fmt(dim.max_in_plane_bandwidth_ev,3)+' eV)');
    if (dim.dimensionality_ratio != null) {
      const dimColor = dim.dimensionality_ratio < 0.1 ? 'var(--green)' : dim.dimensionality_ratio < 0.3 ? 'var(--accent)' : 'var(--orange)';
      lines.push(' · <span style="color:'+dimColor+'">'+dim.dimensionality_class+'</span> (oop/ip ratio = '+fmt(dim.dimensionality_ratio,4)+')</div>');
    } else {
      lines.push('</div>');
    }
  }

  // --- Velocity Statistics ---
  if (p.velocity_stats && p.velocity_stats.per_band) {
    const vs = p.velocity_stats;
    lines.push('<div class="insight">💨 <b>Velocity statistics:</b> v_max='+fmt(vs.v_max_all_A_per_fs,2)+' Å/fs · v_avg='+fmt(vs.v_avg_all_A_per_fs,2)+' Å/fs · v_avg@EF='+fmt(vs.v_avg_near_ef_A_per_fs,2)+' Å/fs</div>');
    if (vs.fastest_band && vs.slowest_band) {
      lines.push('<div class="insight">💨 Fastest: band '+vs.fastest_band.band_index+' (v_max='+fmt(vs.fastest_band.v_max_A_per_fs,2)+') · Slowest: band '+vs.slowest_band.band_index+' (v_max='+fmt(vs.slowest_band.v_max_A_per_fs,2)+')</div>');
    }
    // Per-band velocity table
    let velRows = vs.per_band.slice(0,15).map(function(b){
      return '<tr><td>'+b.band_index+'</td><td>'+fmt(b.v_max_A_per_fs,3)+'</td><td>'+fmt(b.v_avg_A_per_fs,3)+'</td><td>'+fmt(b.v_avg_near_ef_A_per_fs,3)+'</td><td>'+b.n_points_near_ef+'</td></tr>';
    }).join('');
    lines.push('<details style="margin-top:4px"><summary style="cursor:pointer;color:var(--accent);font-size:11px">Per-band velocities (Å/fs)</summary><table style="margin-top:4px;font-size:11px"><thead><tr><th>Band</th><th>v_max</th><th>v_avg</th><th>v_avg@EF</th><th>Pts@EF</th></tr></thead><tbody>'+velRows+'</tbody></table></details>');
  }

  // --- Band statistics ---
  if (p.band_stats && p.band_stats.per_band) {
    const bs = p.band_stats.per_band;
    const bandsCrossingEF = bs.filter(function(b){return b.crosses_ef});
    const widest = bs.reduce(function(a,b){return b.bandwidth > a.bandwidth ? b : a}, bs[0]);
    const narrowest = bs.reduce(function(a,b){return b.bandwidth < a.bandwidth ? b : a}, bs[0]);
    const avgBw = bs.reduce(function(s,b){return s + b.bandwidth}, 0) / bs.length;

    lines.push('<div class="insight">🎵 <b>Band stats:</b> '+bs.length+' bands · avg bandwidth '+fmt(avgBw,2)+' eV · widest: band '+widest.band_index+' ('+fmt(widest.bandwidth,2)+' eV) · narrowest: band '+narrowest.band_index+' ('+fmt(narrowest.bandwidth,3)+' eV) · '+bandsCrossingEF.length+' bands cross EF</div>');

    let detailRows = bs.map(function(b){
      const efTag = b.crosses_ef ? '<span style="color:var(--green)">✓EF</span>' : '';
      const bwStyle = b.bandwidth < 0.5 ? 'color:var(--orange)' : '';
      return '<tr><td>'+b.band_index+'</td><td>'+fmt(b.e_min,3)+'</td><td>'+fmt(b.e_max,3)+'</td><td style="'+bwStyle+'">'+fmt(b.bandwidth,3)+'</td><td>'+fmt(b.rms_dispersion,2)+'</td><td>'+efTag+'</td></tr>';
    }).join('');
    lines.push('<details style="margin-top:6px"><summary style="cursor:pointer;color:var(--accent);font-size:11px">Per-band table</summary><table style="margin-top:4px;font-size:11px"><thead><tr><th>Band</th><th>Min(eV)</th><th>Max(eV)</th><th>BW(eV)</th><th>⟨|∂E/∂k|⟩</th><th>EF</th></tr></thead><tbody>'+detailRows+'</tbody></table></details>');
  }

  // --- DOS at EF ---
  if (caseData.dos) {
    const d = caseData.dos;
    const dosEf = d.e_fermi_ev ?? ef;
    let dosAtEf = 0;
    const tdOS = (d.datasets && d.datasets[0]) ? d.datasets[0].data : (d.data || []);
    if (tdOS.length) {
      let best = null;
      for (var ii=0; ii<tdOS.length; ii++) {
        const pt = tdOS[ii];
        if (best===null || Math.abs(pt.energy_ev-dosEf)<Math.abs(best.energy_ev-dosEf)) best = pt;
      }
      if (best) dosAtEf = best.dos;
    }
    const isMetal = dosAtEf > 0.05;
    lines.push('<div class="insight">📊 <b>DOS(E<sub>F</sub>):</b> '+dosAtEf.toExponential(2)+' states/eV · EF='+fmt(dosEf,4)+' eV · '+(isMetal?'<span style="color:var(--green)">Metallic (N(EF)>0)</span>':'<span style="color:var(--orange)">Insulating / low DOS</span>')+'</div>');
  }

  el('analysisContent').innerHTML = lines.length ? lines.join('') : '<span class="empty">Load bands/DOS data for automated analysis.</span>';
}

function esc(s) {
  const d = document.createElement('div'); d.textContent = s; return d.innerHTML;
}


// ---- PDOS toggle ----
document.addEventListener('click', function(e) {
  const tag = e.target.closest('.pdos-tag');
  if (!tag) return;
  const idx = parseInt(tag.dataset.idx);
  const cb = tag.querySelector('input[type=checkbox]');
  cb.checked = !cb.checked;
  tag.style.background = cb.checked ? 'rgba(88,166,255,.15)' : 'transparent';
  const chartObj = allCharts.find(c => c._isDos);
  if (chartObj && chartObj.data.datasets[idx]) {
    chartObj.setDatasetVisibility(idx, cb.checked);
    chartObj.update();
  }
});

// ---- DOS smoothing (moving average) ----
function smoothDOS(data, window) {
  if (window < 3 || data.length < window) return data;
  const half = Math.floor(window / 2);
  const result = new Array(data.length);
  for (let i = 0; i < data.length; i++) {
    let sum = 0, count = 0;
    for (let j = Math.max(0, i - half); j < Math.min(data.length, i + half + 1); j++) {
      sum += data[j].dos;
      count++;
    }
    result[i] = { energy_ev: data[i].energy_ev, dos: sum / count, int_dos: data[i].int_dos };
  }
  return result;
}

// ---- Init ----
try { Chart.register(ChartAnnotation); } catch(e) { console.warn('Annotation plugin unavailable:', e); }
Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#30363d';
(function(){
  if (!DATA.cases || !DATA.cases.length) { el('caseContent').innerHTML='<div class="empty">No case data. Use --cases-dir to load results.</div>'; return; }
  let meta = [];
  const c0 = DATA.cases[0];
  if (c0.scf) meta.push(`SCF: ${fmt(c0.scf.total_energy_ry,6)} Ry`);
  if (c0.dos) meta.push(`DOS: ${c0.dos.n_points} pts`);
  if (c0.bands) meta.push(`Bands: ${c0.bands.nbnd}×${c0.bands.nks}`);
  if (DATA.cases.length>1) meta.push(`${DATA.cases.length} cases`);
  el('headerMeta').textContent = meta.join(' · ');
  // Set initial E range from data
  if (c0.dos&&c0.dos.e_min!=null) setERangeDefaults(Math.max(c0.dos&&c0.dos.e_min!=null?c0.dos.e_min:-10,-10), Math.min(c0.dos&&c0.dos.e_max!=null?c0.dos.e_max:10,10));
  renderTabs();
})();
</script>
</body>
</html>
"""
