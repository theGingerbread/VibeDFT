"""Interactive 2D materials report: data models, file discovery, section builders.

Architecture:
  case_dir -> CaseFileDiscovery -> SectionBuilders -> ReportPayload -> JSON -> HTML

Every section follows: source files -> parser -> normalized data -> insights.
"""

from __future__ import annotations

import fnmatch
import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

from vibedft.core.analysis import (
    parse_qe_output,
    parse_dos_output,
    parse_bands_output,
    parse_pdos_bundle,
    compute_k_distances,
)
from vibedft.core.phonon import parse_freq_gp, qa_phonon_frequencies
from vibedft.core.structure import (
    parse_structure_from_qe_input,
    parse_structure_from_qe_output,
    parse_structure_from_poscar,
    compute_2d_metrics,
    compute_symmetry,
    Structure,
    TwoDMetrics,
)
from vibedft.core.fs import parse_bxsf
from vibedft.core.bands_advanced import build_joint_bands_pdos_panel, build_overlay_bands
from vibedft.core.tc import parse_lambdax_output, compute_tc_overlap


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EvidenceRef:
    """Pointer to a source file + parser that produced a value."""
    file: str          # relative path from case dir
    parser: str        # function name
    threshold: str = ""  # e.g. "< 1e-3 Ry/Bohr"


@dataclass
class Insight:
    """Auto-generated insight for a report section."""
    section_id: str
    status: str       # pass | warn | fail | missing
    message: str
    evidence: list[EvidenceRef] = field(default_factory=list)


@dataclass
class SectionData:
    """Normalized data for one report section."""
    section_id: str
    title: str
    status: str = "missing"   # pass | warn | fail | missing
    data: dict[str, Any] = field(default_factory=dict)
    insights: list[Insight] = field(default_factory=list)
    evidence_files: list[str] = field(default_factory=list)


@dataclass
class ReportPayload:
    """Complete report payload — serialisable to JSON, renderable to HTML."""
    title: str = "VibeDFT Materials Report"
    case_id: str = ""
    material: str = ""
    generated_at: str = ""
    sections: list[SectionData] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False, default=str)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════════════
# Case File Discovery
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CaseFileDiscovery:
    """Discovers lightweight result files in a VibeDFT case directory."""
    case_dir: Path
    files: dict[str, list[Path]] = field(default_factory=dict)

    def discover(self) -> dict[str, list[Path]]:
        """Recursively scan output/ for known file patterns. Returns {stage: [paths]}."""
        out = self.case_dir / "output"
        if not out.is_dir():
            return {}

        patterns = {
            "scf": ["scf.out"],
            "nscf": ["nscf.out", "nscf_dos.out"],
            "dos": ["*.dos"],
            "pdos": ["*pdos_tot", "*pdos_atm*"],
            "bands": ["*bands*", "*.gnu"],
            "ph_disp": ["*.freq.gp"],
            "ph_fc": ["*.fc"],
            "ph_dos_data": ["*.phdos*"],
            "epc_alpha2f": ["alpha2F.dat"],
            "epc_lambda": ["lambda.dat"],
            "tc_lambdax": ["lambdax.out"],
            "rx": ["rx.out"],
            "fs_bxsf": ["*.bxsf"],
        }

        discovered: dict[str, list[Path]] = {}
        all_files = list(out.rglob("*"))

        for stage, pats in patterns.items():
            matched = []
            for pat in pats:
                for f in all_files:
                    if f.is_file() and fnmatch.fnmatch(f.name, pat):
                        matched.append(f)
            if matched:
                discovered[stage] = sorted(set(matched), key=lambda p: str(p))

        self.files = discovered
        return discovered

    def has_stage(self, stage: str) -> bool:
        return stage in self.files and len(self.files[stage]) > 0

    def get_first(self, stage: str) -> Path | None:
        fs = self.files.get(stage, [])
        return fs[0] if fs else None

    def get_all(self, stage: str) -> list[Path]:
        return self.files.get(stage, [])


# ═══════════════════════════════════════════════════════════════════════════════
# Section Builders
# ═══════════════════════════════════════════════════════════════════════════════

def _make_insight(section_id: str, status: str, message: str, **evidence: str) -> Insight:
    refs = [EvidenceRef(file=v, parser="") for k, v in evidence.items() if v]
    return Insight(section_id=section_id, status=status, message=message, evidence=refs)


def build_overview_section(discovery: CaseFileDiscovery) -> SectionData:
    """Build Overview section: SCF summary, basic material metadata."""
    section = SectionData(section_id="overview", title="Overview", status="missing")
    scf_file = discovery.get_first("scf")
    rx_file = discovery.get_first("rx")

    overview: dict[str, Any] = {}
    if scf_file and scf_file.is_file():
        scf = parse_qe_output(scf_file)
        overview["scf"] = {
            "program": scf.program, "version": scf.version,
            "total_energy_ry": scf.total_energy_ry,
            "total_energy_ev": scf.total_energy_ev,
            "fermi_energy_ev": scf.fermi_energy_ev,
            "scf_converged": scf.scf_converged,
            "scf_iterations": scf.scf_iterations,
            "wall_time_sec": scf.wall_time_sec,
            "cpu_time_sec": scf.cpu_time_sec,
        }
        section.evidence_files.append(str(scf_file.relative_to(discovery.case_dir)))
        section.status = "pass" if scf.scf_converged else "fail"
        section.insights.append(_make_insight(
            "overview", "pass" if scf.scf_converged else "fail",
            f"SCF {'converged' if scf.scf_converged else 'NOT converged'} in {scf.scf_iterations} iterations, "
            f"E_tot = {scf.total_energy_ry:.6f} Ry, E_F = {scf.fermi_energy_ev:.4f} eV",
            scf_output=str(scf_file.relative_to(discovery.case_dir)),
        ))
    else:
        section.insights.append(_make_insight("overview", "missing", "No SCF output found"))

    if rx_file and rx_file.is_file():
        rx_text = rx_file.read_text(encoding="utf-8", errors="replace")
        overview["rx"] = {
            "job_done": "JOB DONE" in rx_text,
            "converged": "convergence has been achieved" in rx_text,
        }
        section.evidence_files.append(str(rx_file.relative_to(discovery.case_dir)))

    # Build a stage presence summary
    stages_present = {k: len(v) for k, v in discovery.files.items()}
    overview["stages_present"] = stages_present
    overview["total_files"] = sum(len(v) for v in discovery.files.values())

    section.data = overview
    return section


def build_bands_section(discovery: CaseFileDiscovery) -> SectionData:
    """Build Bands section: band structure, gap, high-symmetry path."""
    section = SectionData(section_id="bands", title="Band Structure", status="missing")
    bands_files = discovery.get_all("bands")
    bands_data: dict[str, Any] = {}

    # Pick the best bands file: prefer .gnu format (has k-path in first column)
    best = None
    for f in bands_files:
        if f.suffix == ".gnu" or ".bands.dat.gnu" in f.name:
            best = f
            break
    if not best and bands_files:
        best = bands_files[0]

    if best and best.is_file():
        try:
            parsed = parse_bands_output(best)
            k_dists = compute_k_distances(parsed.k_points)

            # Get Fermi energy from SCF or DOS for proper gap alignment
            ef = 0.0
            scf_file = discovery.get_first("scf")
            if scf_file and scf_file.is_file():
                ef = parse_qe_output(scf_file).fermi_energy_ev or 0.0
            elif discovery.get_first("dos"):
                dos_file = discovery.get_first("dos")
                if dos_file and dos_file.is_file():
                    ef = parse_dos_output(dos_file).e_fermi_ev or 0.0

            # Band gap from physics module
            from vibedft.core.physics import band_gap_analysis
            gap_info = band_gap_analysis(parsed.bands, k_dists, ef)
            section.status = "pass"

            bands_data = {
                "nbnd": parsed.nbnd, "nks": parsed.nks,
                "k_distances": k_dists,
                "bands": parsed.bands,
                "k_points": parsed.k_points,
                "band_gap": gap_info,
            }
            section.evidence_files.append(str(best.relative_to(discovery.case_dir)))

            if gap_info.get("gap_ev") is not None and gap_info["gap_ev"] > 0.01:
                section.insights.append(_make_insight(
                    "bands", "pass",
                    f"Band gap: {gap_info['type']}, E_g = {gap_info['gap_ev']:.4f} eV, "
                    f"optical gap = {gap_info.get('optical_gap_ev', 'N/A')}",
                    bands_file=str(best.relative_to(discovery.case_dir)),
                ))
            elif gap_info.get("gap_ev") is not None:
                section.insights.append(_make_insight(
                    "bands", "warn",
                    f"Metallic or near-zero gap ({gap_info['gap_ev']:.4f} eV)",
                    bands_file=str(best.relative_to(discovery.case_dir)),
                ))
        except Exception as exc:
            section.insights.append(_make_insight(
                "bands", "fail", f"Failed to parse bands: {exc}",
                bands_file=str(best),
            ))
    else:
        section.insights.append(_make_insight("bands", "missing", "No bands data found"))

    section.data = bands_data
    return section


def build_dos_pdos_section(discovery: CaseFileDiscovery) -> SectionData:
    """Build DOS/PDOS section: total DOS + element/orbital-resolved PDOS."""
    section = SectionData(section_id="dos_pdos", title="DOS / PDOS", status="missing")
    dos_file = discovery.get_first("dos")
    pdos_files = discovery.get_all("pdos")

    dos_data: dict[str, Any] = {}
    if dos_file and dos_file.is_file():
        dos = parse_dos_output(dos_file)
        dos_data["tdos"] = {
            "e_fermi_ev": dos.e_fermi_ev, "n_points": dos.n_points,
            "e_min": dos.e_min, "e_max": dos.e_max,
            "data": dos.dos_data,
        }
        section.evidence_files.append(str(dos_file.relative_to(discovery.case_dir)))
        section.status = "pass"

    # PDOS — group by atom and orbital
    if pdos_files:
        pdos_results = parse_pdos_bundle(pdos_files[0].parent if pdos_files else Path("."))
        pdos_grouped: dict[str, list[dict[str, Any]]] = {}
        for p in pdos_results:
            # Parse label: "HfBr2.pdos.pdos_atm#2(Br)_wfc#1(s)" → elem=Br, atom_idx=2, orb=s
            import re
            lbl = p.label
            atm_m = re.search(r"atm#(\d+)\((\w+)\)", lbl)
            wfc_m = re.search(r"_wfc#(\d+)\((\w)\)", lbl)
            elem = atm_m.group(2) if atm_m else "?"
            atom_idx = atm_m.group(1) if atm_m else "?"
            orb = wfc_m.group(2) if wfc_m else "?"
            key = f"{elem}[{atom_idx}]-{orb}"
            pdos_grouped[key] = p.data[:200] if len(p.data) > 200 else p.data  # downsample if needed

        dos_data["pdos"] = {
            "groups": {k: v for k, v in pdos_grouped.items()},
            "n_atoms": len(set(k.split("[")[1].split("]")[0] for k in pdos_grouped if "[" in k)),
        }
        section.evidence_files.extend(
            str(f.relative_to(discovery.case_dir)) for f in pdos_files[:8]
        )
        section.status = "pass"

        # Insight: DOS at EF
        if dos_file and dos_data.get("tdos"):
            tdos = dos_data["tdos"]["data"]
            ef = dos_data["tdos"]["e_fermi_ev"] or 0.0
            closest = min(tdos, key=lambda d: abs(d["energy_ev"] - ef))
            is_metal = closest["dos"] > 0.05
            section.insights.append(_make_insight(
                "dos_pdos", "pass" if not is_metal else "warn",
                f"DOS(E_F) = {closest['dos']:.4f} states/eV, "
                f"{'metallic' if is_metal else 'insulating/semiconducting'}",
                dos_file=str(dos_file.relative_to(discovery.case_dir)),
            ))

    section.data = dos_data
    return section


def build_phonon_section(discovery: CaseFileDiscovery) -> SectionData:
    """Build Phonon section: dispersion, QA, multi-grid comparison."""
    section = SectionData(section_id="phonon", title="Phonon Dispersion", status="missing")
    freq_files = discovery.get_all("ph_disp")
    if not freq_files:
        section.insights.append(_make_insight("phonon", "missing", "No freq.gp files found"))
        return section

    grids_data: dict[str, Any] = {}
    all_pass = True
    for f in freq_files:
        grid_label = _grid_label_from_path(f)
        disp = parse_freq_gp(f)
        qa = qa_phonon_frequencies(disp)
        grids_data[grid_label] = {
            "n_qpoints": disp.n_qpoints, "n_branches": disp.n_branches,
            "min_freq_cm1": disp.min_frequency_cm1,
            "max_freq_cm1": disp.max_frequency_cm1,
            "n_imaginary": disp.n_imaginary,
            "imaginary_modes": disp.imaginary_modes[:10],
            "qa_status": qa.status,
            "frequencies": disp.frequencies,
            "q_distances": disp.q_distances,
        }
        section.evidence_files.append(str(f.relative_to(discovery.case_dir)))
        if qa.status != "pass":
            all_pass = False

    section.status = "pass" if all_pass else "warn"
    section.data = {"grids": grids_data}

    # Insight: imaginary mode summary
    for label, gd in grids_data.items():
        n_im = gd["n_imaginary"]
        if n_im > 0:
            worst = min(m["freq_cm1"] for m in gd["imaginary_modes"]) if gd["imaginary_modes"] else 0
            section.insights.append(_make_insight(
                "phonon", "warn" if abs(worst) < 5 else "fail",
                f"{label}: {n_im} imaginary mode(s), worst = {worst:.3f} cm⁻¹",
                freq_file=section.evidence_files[-1] if section.evidence_files else "",
            ))
        else:
            section.insights.append(_make_insight(
                "phonon", "pass", f"{label}: No imaginary modes",
                freq_file=section.evidence_files[-1] if section.evidence_files else "",
            ))

    return section


def build_epc_section(discovery: CaseFileDiscovery) -> SectionData:
    """Build EPC section: alpha2F and lambda data from multiple grids."""
    section = SectionData(section_id="epc", title="Electron-Phonon Coupling", status="missing")
    alpha2f_files = discovery.get_all("epc_alpha2f")
    lambda_files = discovery.get_all("epc_lambda")

    epc_data: dict[str, Any] = {}
    for f in alpha2f_files:
        grid_label = _grid_label_from_path(f)
        a2f = _parse_alpha2f(f)
        if a2f:
            epc_data.setdefault(grid_label, {})["alpha2F"] = a2f
            section.evidence_files.append(str(f.relative_to(discovery.case_dir)))

    for f in lambda_files:
        grid_label = _grid_label_from_path(f)
        lam = _parse_lambda_dat(f)
        if lam:
            epc_data.setdefault(grid_label, {})["lambda"] = lam
            if str(f.relative_to(discovery.case_dir)) not in section.evidence_files:
                section.evidence_files.append(str(f.relative_to(discovery.case_dir)))

    if epc_data:
        section.status = "pass"
        for label, gd in epc_data.items():
            lam_vals = [r["lambda"] for r in gd.get("lambda", [])]
            lam_max = max(lam_vals) if lam_vals else 0
            section.insights.append(_make_insight(
                "epc", "pass" if lam_max > 0 else "warn",
                f"{label}: λ_max = {lam_max:.3f}" + (f" ({len(lam_vals)} degauss points)" if lam_vals else ""),
            ))

    section.data = epc_data
    return section


def build_superconductivity_section(discovery: CaseFileDiscovery) -> SectionData:
    """Build Superconductivity section: Tc overlap from multiple PH grids."""
    section = SectionData(section_id="superconductivity", title="Superconductivity", status="missing")
    lambdax_files = discovery.get_all("tc_lambdax")
    if len(lambdax_files) < 2:
        section.insights.append(_make_insight(
            "superconductivity", "missing",
            f"Need ≥2 lambdax.out files for Tc overlap, found {len(lambdax_files)}",
        ))
        section.data = {"n_grids": len(lambdax_files)}
        return section

    # Compute Tc overlap for first two grids
    f_a, f_b = lambdax_files[0], lambdax_files[1]
    label_a = _grid_label_from_path(f_a)
    label_b = _grid_label_from_path(f_b)

    result = compute_tc_overlap(f_a, f_b, label_a=label_a, label_b=label_b)
    section.evidence_files.extend([
        str(f_a.relative_to(discovery.case_dir)),
        str(f_b.relative_to(discovery.case_dir)),
    ])

    section.status = "pass" if result.overlap_status == "pass" else "warn"
    section.data = {
        "grid_a": {"label": label_a, "data": _parse_lambdax_compact(f_a)},
        "grid_b": {"label": label_b, "data": _parse_lambdax_compact(f_b)},
        "tc_overlap": {
            "tc_point_k": result.tc_point_k,
            "degauss_ry": result.degauss_ry,
            "overlap_status": result.overlap_status,
            "relative_deviation_pct": result.relative_deviation_pct,
        },
    }

    section.insights.append(_make_insight(
        "superconductivity", section.status,
        f"Tc({label_a} vs {label_b}): {result.overlap_status.upper()}, "
        f"Tc_Point = {result.tc_point_k:.2f} K" if result.tc_point_k else f"Tc overlap: {result.overlap_status}",
        lambdax_a=str(f_a.relative_to(discovery.case_dir)),
        lambdax_b=str(f_b.relative_to(discovery.case_dir)),
    ))

    return section


# ═══════════════════════════════════════════════════════════════════════════════
# Report assembly
# ═══════════════════════════════════════════════════════════════════════════════

def build_fermi_surface_section(discovery: CaseFileDiscovery) -> SectionData:
    """Build Fermi Surface section: BXSF parsing, near-EF topology, pocket analysis."""
    section = SectionData(section_id="fermi_surface", title="Fermi Surface", status="missing")

    bxsf_files = discovery.get_all("fs_bxsf")
    fs_data: dict[str, Any] = {}

    if bxsf_files:
        # Parse BXSF files for 3D Fermi surface data
        bxsf_results = []
        for f in bxsf_files:
            data = parse_bxsf(f)
            if data.has_data:
                bxsf_results.append({
                    "file": str(f.relative_to(discovery.case_dir)),
                    "n_bands": data.n_bands,
                    "grid": f"{data.n_k1}×{data.n_k2}×{data.n_k3}",
                    "n_kpoints": data.n_kpoints,
                    "fermi_energy_ev": data.fermi_energy_ev,
                    "bands_crossing_ef": data.bands_crossing_ef,
                    "has_fermi_surface": data.has_fermi_surface,
                    "band_min": data.band_min,
                    "band_max": data.band_max,
                })
                section.evidence_files.append(str(f.relative_to(discovery.case_dir)))

        if bxsf_results:
            fs_data["bxsf"] = bxsf_results
            section.status = "pass"

            # Insights
            for br in bxsf_results:
                n_cross = len(br["bands_crossing_ef"])
                if n_cross > 0:
                    section.insights.append(_make_insight(
                        "fermi_surface", "pass",
                        f"{br['file']}: {n_cross} bands cross EF on {br['grid']} grid, "
                        f"EF = {br['fermi_energy_ev']:.4f} eV"
                    ))
                else:
                    section.insights.append(_make_insight(
                        "fermi_surface", "warn",
                        f"{br['file']}: No bands cross EF — insulating or insufficient smearing"
                    ))
    else:
        # Fallback: near-EF analysis from band structure
        bands_files = discovery.get_all("bands")
        if bands_files and discovery.has_stage("scf"):
            from vibedft.core.analysis import parse_bands_output, compute_k_distances
            from vibedft.core.physics import fermi_surface_analysis

            best = bands_files[0]
            for f in bands_files:
                if ".gnu" in f.name:
                    best = f; break
            parsed = parse_bands_output(best)
            k_dists = compute_k_distances(parsed.k_points)

            # Get EF from SCF
            ef = 0.0
            scf_f = discovery.get_first("scf")
            if scf_f:
                from vibedft.core.analysis import parse_qe_output
                ef = parse_qe_output(scf_f).fermi_energy_ev or 0.0

            bands_data = {
                "k_distances": k_dists, "k_points": parsed.k_points,
                "bands": parsed.bands, "nbnd": parsed.nbnd, "nks": parsed.nks,
            }
            fs_info = fermi_surface_analysis(bands_data, ef)
            fs_data["bands_derived"] = {
                "n_bands_crossing_ef": fs_info["n_bands_crossing_ef"],
                "n_electron_pockets": fs_info["n_electron_pockets"],
                "n_hole_pockets": fs_info["n_hole_pockets"],
                "n_pockets": fs_info["n_pockets"],
                "pockets": fs_info["pockets"],
                "estimated_n_2d": fs_info.get("estimated_n_2d_per_unit_cell"),
                "is_metallic": fs_info["is_metallic"],
                "caveat": fs_info.get("caveat", ""),
            }
            section.status = "pass" if fs_info["is_metallic"] else "warn"
            section.evidence_files.append(str(best.relative_to(discovery.case_dir)))

            n_pockets = fs_info["n_pockets"]
            if n_pockets > 0:
                types = f"{fs_info['n_electron_pockets']} e⁻ + {fs_info['n_hole_pockets']} h⁺"
                section.insights.append(_make_insight(
                    "fermi_surface", "pass",
                    f"{fs_info['n_bands_crossing_ef']} bands cross EF, "
                    f"{n_pockets} pockets ({types})"
                ))
            else:
                section.insights.append(_make_insight(
                    "fermi_surface", "warn",
                    "No bands cross EF — insulating state (1D path assessment)"
                ))

    if not fs_data:
        section.insights.append(_make_insight("fermi_surface", "missing", "No BXSF or bands data available"))

    section.data = fs_data
    return section


def build_joint_bands_section(discovery: CaseFileDiscovery) -> SectionData:
    """Build Bands + Projected DOS joint panel section (P0 — side-by-side, not fat bands)."""
    section = SectionData(section_id="bands_advanced", title="Bands + Projected DOS", status="missing")

    bands_file = None
    for f in discovery.get_all("bands"):
        if ".bands.dat" in f.name and ".gnu" not in f.name:
            bands_file = f; break
    if not bands_file:
        for f in discovery.get_all("bands"):
            if ".gnu" not in f.name:
                bands_file = f; break
    if not bands_file:
        bands_file = discovery.get_first("bands")

    dos_file = discovery.get_first("dos")
    pdos_dir = None
    if discovery.get_all("pdos"):
        pdos_dir = discovery.get_all("pdos")[0].parent

    if not bands_file or not bands_file.is_file():
        section.insights.append(_make_insight("bands_advanced", "missing", "No bands data available"))
        return section

    # Get EF from SCF (pass None so builder falls back to DOS header if no SCF)
    ef_from_scf: float | None = None
    scf_file = discovery.get_first("scf")
    if scf_file and scf_file.is_file():
        from vibedft.core.analysis import parse_qe_output
        ef_from_scf = parse_qe_output(scf_file).fermi_energy_ev

    panel = build_joint_bands_pdos_panel(
        bands_file=bands_file, dos_file=dos_file,
        pdos_dir=pdos_dir, e_fermi_ev=ef_from_scf,
    )

    # Extract resolved EF from panel (may differ from scf_ef if DOS fallback)
    resolved_ef = panel.get("fermi_energy_ev", ef_from_scf or 0.0)

    bp = panel.get("bands")
    pp = panel.get("pdos")
    section.evidence_files.append(str(bands_file.relative_to(discovery.case_dir)))
    if dos_file:
        section.evidence_files.append(str(dos_file.relative_to(discovery.case_dir)))

    # Surface any parse errors from the panel builder
    panel_errors = panel.get("errors", [])
    if panel_errors:
        for err in panel_errors:
            section.insights.append(_make_insight("bands_advanced", "warn", f"Parse issue: {err}"))

    if bp:
        section.status = "pass"
        section.data = {
            "bands": {
                "nbnd": bp.nbnd, "nks": bp.nks,
                "k_distances": bp.k_distances, "bands": bp.bands,
                "k_labels": bp.k_labels,
                "gap_ev": bp.gap_ev, "gap_type": bp.gap_type,
            },
            "pdos": {
                "tdos": pp.tdos if pp else None,
                "groups": pp.pdos_groups if pp else {},
                "dominant_near_ef": pp.dominant_near_ef if pp else {},
                "e_fermi_ev": pp.e_fermi_ev if pp else ef,
            } if pp else None,
            "fermi_energy_ev": panel.get("fermi_energy_ev", resolved_ef),
            "fermi_source": panel.get("fermi_source", "unknown"),
            "dos_fermi_ev_note": panel.get("dos_fermi_ev_note"),
            "k_labels": panel.get("k_labels"),
        }

        # Surface any dos_fermi_ev_note from the panel
        dos_note = panel.get("dos_fermi_ev_note")
        if dos_note:
            evidence = []
            if scf_file:
                evidence.append(EvidenceRef(
                    file=str(scf_file.relative_to(discovery.case_dir)),
                    parser="parse_qe_output",
                    threshold="|EF_DOS - EF_SCF| <= 0.05 eV",
                ))
            if dos_file:
                evidence.append(EvidenceRef(
                    file=str(dos_file.relative_to(discovery.case_dir)),
                    parser="parse_dos_output",
                    threshold="|EF_DOS - EF_SCF| <= 0.05 eV",
                ))
            section.insights.append(Insight(
                section_id="bands_advanced",
                status="warn",
                message=dos_note,
                evidence=evidence,
            ))

        if bp.gap_ev and bp.gap_ev > 0.01:
            section.insights.append(_make_insight(
                "bands_advanced", "pass",
                f"Band gap: {bp.gap_type}, E_g = {bp.gap_ev:.4f} eV "
                f"(EF={resolved_ef:.4f} eV, source={panel.get('fermi_source', '?')})"
            ))

        if pp and pp.dominant_near_ef:
            dom = pp.dominant_near_ef
            section.insights.append(_make_insight(
                "bands_advanced", "pass",
                f"Near EF: dominant orbital = {dom['element_orbital']} "
                f"({dom['fraction']*100:.0f}% of DOS at EF)"
            ))
    else:
        section.status = "fail"

    return section


def build_structure_section(discovery: CaseFileDiscovery) -> SectionData:
    """Build Structure section: lattice, atoms, symmetry, 2D metrics."""
    section = SectionData(section_id="structure", title="Structure / Symmetry", status="missing")

    struct = None
    # Try to find structure from QE input, output, or POSCAR in the case
    case_dir = discovery.case_dir
    for pattern in ["**/scf.in", "**/relax.in", "**/*.in", "**/POSCAR", "**/CONTCAR"]:
        candidates = list(case_dir.glob(pattern))
        for f in candidates:
            if "scf.in" in f.name or "relax.in" in f.name:
                struct = parse_structure_from_qe_input(f)
            elif f.name in ("POSCAR", "CONTCAR"):
                struct = parse_structure_from_poscar(f)
            if struct and struct.atoms:
                break
        if struct and struct.atoms:
            break

    # Fallback: try QE output
    if not (struct and struct.atoms):
        rx_file = discovery.get_first("rx")
        if rx_file:
            struct = parse_structure_from_qe_output(rx_file)

    if not (struct and struct.atoms):
        section.insights.append(_make_insight("structure", "missing", "No structure data found"))
        return section

    # 2D metrics
    metrics = compute_2d_metrics(struct)
    # Symmetry
    sym = compute_symmetry(struct)

    section.status = "pass"
    section.data = {
        "formula": struct.formula or "",
        "n_atoms": struct.n_atoms,
        "elements": struct.elements,
        "n_species": struct.n_species,
        "lattice": {
            "a": struct.lattice.a if struct.lattice else 0,
            "b": struct.lattice.b if struct.lattice else 0,
            "c": struct.lattice.c if struct.lattice else 0,
            "alpha": struct.lattice.alpha if struct.lattice else 90,
            "beta": struct.lattice.beta if struct.lattice else 90,
            "gamma": struct.lattice.gamma if struct.lattice else 90,
            "volume": struct.lattice.volume if struct.lattice else 0,
        },
        "xyz_string": struct.to_xyz_string(),
        "metrics_2d": {
            "vacuum_thickness_ang": metrics.vacuum_thickness_ang,
            "layer_thickness_ang": metrics.layer_thickness_ang,
            "vacuum_sufficient": metrics.vacuum_sufficient,
            "n_layers": metrics.n_layers,
            "buckling_ang": metrics.buckling_ang,
        },
        "symmetry": sym,
    }

    # Insights
    lat = section.data["lattice"]
    section.insights.append(_make_insight(
        "structure", "pass",
        f"Lattice: a={lat['a']:.3f}, b={lat['b']:.3f}, c={lat['c']:.3f} Å, "
        f"α={lat['alpha']:.1f}° β={lat['beta']:.1f}° γ={lat['gamma']:.1f}°, "
        f"V={lat['volume']:.2f} Å³"
    ))
    m = section.data["metrics_2d"]
    if m["vacuum_sufficient"]:
        section.insights.append(_make_insight(
            "structure", "pass",
            f"Vacuum: {m['vacuum_thickness_ang']:.1f} Å — sufficient for 2D slab"
        ))
    elif m["vacuum_thickness_ang"] > 3:
        section.insights.append(_make_insight(
            "structure", "warn",
            f"Vacuum: {m['vacuum_thickness_ang']:.1f} Å — may be insufficient (< 10 Å)"
        ))
    if sym.get("space_group_symbol"):
        section.insights.append(_make_insight(
            "structure", "pass",
            f"Space group: {sym['space_group_symbol']} (#{sym['space_group_number']}), "
            f"{sym['n_operations']} symmetry operations"
        ))

    return section


def build_bands_overlay_section(
    case_dir: Path | str,
    compare_dirs: list[Path | str] | tuple[Path | str, ...],
) -> SectionData:
    """Build P1 Overlay Bands section for compatible same-k-path cases."""
    section = SectionData(section_id="bands_overlay", title="Overlay Bands", status="missing")
    overlay = build_overlay_bands(case_dir, compare_dirs)

    section.data = {
        "cases": [
            {
                "label": c.label,
                "case_dir": c.case_dir,
                "source_file": c.source_file,
                "nbnd": c.nbnd,
                "nks": c.nks,
                "k_distances": c.k_distances,
                "k_labels": c.k_labels,
                "bands_aligned_ev": c.bands_aligned_ev,
                "fermi_energy_ev": c.fermi_energy_ev,
                "fermi_source": c.fermi_source,
            }
            for c in overlay.cases
        ],
        "k_path_compatible": overlay.k_path_compatible,
        "warnings": overlay.warnings,
        "delta_e_ev": overlay.delta_e_ev,
    }
    section.evidence_files = [c.source_file for c in overlay.cases]

    evidence = [
        EvidenceRef(file=c.source_file, parser="parse_bands_output", threshold="k coordinate mismatch < 1e-4")
        for c in overlay.cases
    ]

    if len(overlay.cases) < 2:
        section.status = "missing"
        section.insights.append(Insight(
            section_id="bands_overlay",
            status="missing",
            message="Need main case plus at least one --compare-dir for overlay bands",
            evidence=evidence,
        ))
        return section

    if overlay.warnings:
        section.status = "warn"
        for warning in overlay.warnings:
            section.insights.append(Insight(
                section_id="bands_overlay",
                status="warn",
                message=warning,
                evidence=evidence,
            ))
    else:
        section.status = "pass"
        section.insights.append(Insight(
            section_id="bands_overlay",
            status="pass",
            message=f"Overlay bands: {len(overlay.cases)} compatible cases; Delta-E computed for first comparison",
            evidence=evidence,
        ))

    return section


SECTION_BUILDERS: list[tuple[str, str, Callable[[CaseFileDiscovery], SectionData]]] = [
    ("structure", "Structure / Symmetry", build_structure_section),
    ("overview", "Overview", build_overview_section),
    ("bands", "Band Structure", build_bands_section),
    ("bands_advanced", "Bands + Projected DOS", build_joint_bands_section),
    ("fermi_surface", "Fermi Surface", build_fermi_surface_section),
    ("dos_pdos", "DOS / PDOS", build_dos_pdos_section),
    ("phonon", "Phonon Dispersion", build_phonon_section),
    ("epc", "Electron-Phonon Coupling", build_epc_section),
    ("superconductivity", "Superconductivity", build_superconductivity_section),
]


def render_report_html(payload: ReportPayload, output: Path | str | None = None) -> str:
    """Render a ReportPayload into a self-contained interactive HTML report.

    Uses Plotly.js for scientific charts. Left-side navigation, collapsible
    sections, evidence panels, and auto-insight rendering.
    """
    sections_json = json.dumps([
        {
            "section_id": s.section_id, "title": s.title, "status": s.status,
            "data": s.data,
            "insights": [{"status": i.status, "message": i.message,
                          "evidence": [{"file": e.file, "parser": e.parser} for e in i.evidence]}
                         for i in s.insights],
            "evidence_files": s.evidence_files,
        }
        for s in payload.sections
    ], ensure_ascii=False, default=str)

    # Escape </script> sequences to prevent HTML injection via data content
    safe_json = sections_json.replace("</", "<\\/")
    html = _REPORT_HTML_TEMPLATE.replace("__REPORT_PAYLOAD__", safe_json)
    html = html.replace("__REPORT_TITLE__", payload.title)
    html = html.replace("__REPORT_CASE_ID__", payload.case_id)
    html = html.replace("__REPORT_MATERIAL__", payload.material)
    html = html.replace("__REPORT_GENERATED__", payload.generated_at)

    if output:
        Path(output).write_text(html, encoding="utf-8")
    return html


def build_report(
    case_dir: Path | str,
    *,
    title: str = "VibeDFT Materials Report",
    case_id: str | None = None,
    material: str = "",
    compare_dirs: list[Path | str] | tuple[Path | str, ...] | None = None,
) -> ReportPayload:
    """Build a complete report payload from a case directory."""
    d = Path(case_dir).resolve()
    cid = case_id or d.name

    discovery = CaseFileDiscovery(case_dir=d)
    discovery.discover()

    from datetime import datetime, timezone
    payload = ReportPayload(
        title=title,
        case_id=cid,
        material=material,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    for section_id, section_title, builder in SECTION_BUILDERS:
        try:
            section = builder(discovery)
            section.section_id = section_id
            section.title = section_title
            payload.sections.append(section)
            if section_id == "bands_advanced" and compare_dirs:
                payload.sections.append(build_bands_overlay_section(d, compare_dirs))
        except Exception as exc:
            payload.sections.append(SectionData(
                section_id=section_id, title=section_title, status="fail",
                insights=[_make_insight(section_id, "fail", f"Builder error: {exc}")],
            ))

    return payload


# ═══════════════════════════════════════════════════════════════════════════════
# Helper parsers for report-specific formats
# ═══════════════════════════════════════════════════════════════════════════════

def _grid_label_from_path(path: Path) -> str:
    """Extract grid label from path: .../ph64/file → 'ph64'."""
    parts = path.parts
    for p in reversed(parts):
        if p in ("ph64", "ph96", "ph48", "sc_ph48", "sc_ph64"):
            return p
    return path.parent.name


def _parse_alpha2f(filepath: Path) -> list[dict[str, float]] | None:
    """Parse QE alpha2F.dat Eliashberg spectral function.

    Format: two-column whitespace-separated:
        omega (cm⁻¹)   alpha²F(omega)
    Returns list of {omega_cm1, a2f}, truncated to 500 points for report size.
    """
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            rows.append({"omega_cm1": float(parts[0]), "a2f": float(parts[1])})
        except ValueError:
            continue
    return rows[:500] if rows else None


def _parse_lambda_dat(filepath: Path) -> list[dict[str, float]] | None:
    """Parse QE lambda.dat electron-phonon coupling scan.

    Format: whitespace-separated columns:
        degauss (Ry)   lambda   [omega_log (K)]   [Tc (K)]
    Returns list of {degauss_ry, lambda, omega_log_K?, tc_K?}.
    """
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            row = {"degauss_ry": float(parts[0]), "lambda": float(parts[1])}
            if len(parts) >= 3:
                row["omega_log_K"] = float(parts[2])
            if len(parts) >= 4:
                row["tc_K"] = float(parts[3])
            rows.append(row)
        except ValueError:
            continue
    return rows if rows else None


def _parse_lambdax_compact(filepath: Path) -> dict[str, Any] | None:
    """Parse lambdax.out into compact degauss→Tc mapping for report display."""
    data = parse_lambdax_output(filepath)
    if not data.has_data:
        return None
    return {
        "degauss_values": data.degauss_values,
        "lambda_values": data.lambda_values,
        "omega_log_values": data.omega_log_values,
        "tc_values": data.tc_values,
        "nef_values": data.nef_values,
        "n_rows": data.n_rows,
        "nan_rows": data.nan_rows,
        "mustar": data.mustar,
    }

# ═══════════════════════════════════════════════════════════════════════════════
# Interactive HTML Report Template (self-contained, Plotly.js CDN)
# ═══════════════════════════════════════════════════════════════════════════════

_REPORT_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__REPORT_TITLE__</title>
<script src="https://cdn.plot.ly/plotly-3.0.0.min.js"></script>
<script src="https://3Dmol.org/build/3Dmol-min.js"></script>
<style>
:root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--green:#3fb950;--red:#f85149;--orange:#d2991d;--pass:#3fb950;--warn:#d2991d;--fail:#f85149;--missing:#8b949e}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);display:flex;min-height:100vh}
nav{width:240px;min-width:240px;background:var(--panel);border-right:1px solid var(--border);padding:16px 12px;position:sticky;top:0;height:100vh;overflow-y:auto}
nav h1{font-size:14px;font-weight:600;margin-bottom:4px}
nav .meta{font-size:10px;color:var(--muted);margin-bottom:16px}
nav a{display:flex;align-items:center;gap:8px;padding:6px 10px;color:var(--muted);text-decoration:none;border-radius:5px;font-size:12px;margin-bottom:2px}
nav a:hover,nav a.active{background:rgba(88,166,255,.1);color:var(--text)}
nav a .dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.dot-pass{background:var(--pass)}.dot-warn{background:var(--warn)}.dot-fail{background:var(--fail)}.dot-missing{background:var(--missing)}
main{flex:1;padding:20px 28px;max-width:1200px}
.header-bar{margin-bottom:20px;padding-bottom:12px;border-bottom:1px solid var(--border)}
.header-bar h2{font-size:18px;font-weight:600}
.header-bar .gen{font-size:11px;color:var(--muted)}
section{margin-bottom:24px;background:var(--panel);border:1px solid var(--border);border-radius:10px;overflow:hidden}
section h3{padding:12px 16px;font-size:14px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:8px;user-select:none;border-bottom:1px solid transparent}
section h3:hover{background:rgba(255,255,255,.02)}
section.open h3{border-bottom-color:var(--border)}
section h3 .toggle{font-size:10px;transition:transform .2s}
section.open h3 .toggle{transform:rotate(90deg)}
.section-body{display:none;padding:16px}
section.open .section-body{display:block}
.chart-container{width:100%;min-height:300px;margin:8px 0}
.evidence-bar{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.evidence-tag{font-size:10px;padding:2px 8px;background:rgba(88,166,255,.08);border:1px solid var(--border);border-radius:4px;color:var(--muted);font-family:monospace}
.insight{font-size:12px;padding:8px 12px;margin:6px 0;border-radius:6px;border-left:3px solid var(--border);line-height:1.5}
.insight-pass{border-left-color:var(--pass);background:rgba(63,185,80,.05)}
.insight-warn{border-left-color:var(--warn);background:rgba(210,153,29,.05)}
.insight-fail{border-left-color:var(--fail);background:rgba(248,81,73,.05)}
.insight-missing{border-left-color:var(--missing);background:rgba(139,148,158,.05)}
.insight strong{margin-right:6px}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px;margin:8px 0}
.stat-card{padding:10px 12px;border:1px solid var(--border);border-radius:6px;background:rgba(255,255,255,.01)}
.stat-card .label{font-size:10px;color:var(--muted);text-transform:uppercase;margin-bottom:2px}
.stat-card .value{font-size:18px;font-weight:600}
</style>
</head>
<body>
<nav>
  <h1>__REPORT_TITLE__</h1>
  <div class="meta">__REPORT_CASE_ID__ · __REPORT_MATERIAL__<br>__REPORT_GENERATED__</div>
  <div id="navLinks"></div>
</nav>
<main>
  <div class="header-bar">
    <h2>__REPORT_TITLE__</h2>
    <div class="gen">Case: __REPORT_CASE_ID__ &nbsp;·&nbsp; Material: __REPORT_MATERIAL__ &nbsp;·&nbsp; Generated: __REPORT_GENERATED__</div>
  </div>
  <div id="sections"></div>
</main>
<script>
const SECTIONS = __REPORT_PAYLOAD__;
const ICONS = {pass:'✅',warn:'⚠️',fail:'❌',missing:'⏭️'};
const STATUS_DOT = {pass:'dot-pass',warn:'dot-warn',fail:'dot-fail',missing:'dot-missing'};

// -- Nav --
let navHtml = '';
SECTIONS.forEach((s,i) => {
  navHtml += '<a href="#s'+i+'" onclick="scrollToSection('+i+')"><span class="dot '+STATUS_DOT[s.status]+'"></span>'+esc(s.title)+'</a>';
});
document.getElementById('navLinks').innerHTML = navHtml;

// -- Sections --
let secHtml = '';
SECTIONS.forEach((s,i) => {
  secHtml += '<section class="open" id="s'+i+'">';
  secHtml += '<h3 onclick="this.parentElement.classList.toggle(\'open\')"><span class="toggle">▶</span>'+ICONS[s.status]+' '+esc(s.title)+'</h3>';
  secHtml += '<div class="section-body">';

  // Evidence bar
  if (s.evidence_files && s.evidence_files.length) {
    secHtml += '<div class="evidence-bar">';
    s.evidence_files.slice(0,6).forEach(f => { secHtml += '<span class="evidence-tag">'+esc(f)+'</span>'; });
    if (s.evidence_files.length > 6) secHtml += '<span class="evidence-tag">... +'+(s.evidence_files.length-6)+' more</span>';
    secHtml += '</div>';
  }

  // Insights
  if (s.insights && s.insights.length) {
    s.insights.forEach(ins => {
      secHtml += '<div class="insight insight-'+ins.status+'"><strong>'+ICONS[ins.status]+'</strong>'+esc(ins.message);
      if (ins.evidence && ins.evidence.length) {
        secHtml += '<div style="margin-top:4px;font-size:10px;color:var(--muted)">';
        ins.evidence.forEach(e => { secHtml += ' 📄 '+esc(e.file); });
        secHtml += '</div>';
      }
      secHtml += '</div>';
    });
  }

  // Chart + data rendering
  secHtml += '<div id="chart-'+i+'"></div>';

  secHtml += '</div></section>';
});
document.getElementById('sections').innerHTML = secHtml;

// -- Render charts per section --
function renderCharts() {
  SECTIONS.forEach((s,i) => {
    const el = document.getElementById('chart-'+i);
    if (!el) return;
    try {
      if (s.section_id === 'structure' && s.data.xyz_string) {
        renderStructureViewer(el, s.data);
      } else if (s.section_id === 'bands' && s.data.bands && s.data.bands.length) {
        renderBandsChart(el, s.data);
      } else if (s.section_id === 'dos_pdos' && s.data.tdos) {
        renderDosChart(el, s.data);
      } else if (s.section_id === 'phonon' && s.data.grids) {
        renderPhononChart(el, s.data);
      } else if (s.section_id === 'bands_advanced' && s.data.bands) {
        renderJointBandsPdos(el, s.data);
      } else if (s.section_id === 'bands_overlay' && s.data.cases) {
        renderOverlayBands(el, s.data);
      } else if (s.section_id === 'fermi_surface' && (s.data.bxsf || s.data.bands_derived)) {
        renderFermiSurface(el, s.data);
      } else if (s.section_id === 'superconductivity' && s.data.grid_a) {
        renderTcChart(el, s.data);
      } else if (s.section_id === 'overview' && s.data.scf) {
        renderOverviewStats(el, s.data);
      } else if (s.section_id === 'epc' && Object.keys(s.data).length) {
        renderEpcChart(el, s.data);
      }
    } catch(e) { console.error('Chart error for '+s.section_id, e); }
  });
}

function renderJointBandsPdos(el, data) {
  const bp = data.bands;
  const pp = data.pdos;
  if (!bp) return;
  const ef = pp ? (pp.e_fermi_ev||0) : 0;

  // Bands traces
  const bandTraces = bp.bands.map((energies, ib) => ({
    x: bp.k_distances, y: energies.map(e => e - ef),
    type: 'scatter', mode: 'lines',
    line: {color: 'hsl('+((ib*360/bp.nbnd)%360)+',70%,60%)', width: 0.8},
    name: 'Band '+(ib+1), showlegend: false,
    xaxis: 'x', yaxis: 'y',
    hovertemplate: 'k=%{x:.3f}<br>E−EF=%{y:.3f} eV<br>Band '+(ib+1)+'<extra></extra>'
  }));

  // PDOS traces
  const pdosTraces = [];
  const colors = ['#f85149','#58a6ff','#3fb950','#d2991d','#bc8cff','#ff7b72','#79c0ff','#a5d6ff'];
  if (pp && pp.tdos && pp.tdos.length) {
    pdosTraces.push({
      x: pp.tdos.map(d => d.dos), y: pp.tdos.map(d => d.energy_ev - ef),
      type: 'scatter', mode: 'lines', fill: 'tozerox',
      line: {color:'#f85149',width:1.5}, fillcolor: 'rgba(248,81,73,0.12)',
      name: 'TDOS', xaxis: 'x2', yaxis: 'y2',
      hovertemplate: 'DOS=%{x:.3f}<br>E−EF=%{y:.3f} eV<extra>TDOS</extra>'
    });
  }
  if (pp && pp.groups) {
    let ci = 0;
    Object.entries(pp.groups).forEach(([label, pts]) => {
      if (!pts || !pts.length) return;
      pdosTraces.push({
        x: pts.map(d => d.dos), y: pts.map(d => d.energy_ev - ef),
        type: 'scatter', mode: 'lines',
        line: {color: colors[ci%colors.length], width: 0.8},
        name: label, xaxis: 'x2', yaxis: 'y2', visible: 'legendonly',
        hovertemplate: label+'<br>DOS=%{x:.3f}<br>E−EF=%{y:.3f} eV<extra></extra>'
      });
      ci++;
    });
  }

  // High-symmetry lines
  const shapes = [];
  if (bp.k_labels) {
    bp.k_labels.forEach(hs => {
      shapes.push({type:'line',x0:hs.distance,x1:hs.distance,y0:0,y1:1,yref:'paper',line:{color:'#8b949e',width:1,dash:'dot'}});
    });
  }
  shapes.push({type:'line',x0:0,x1:1,xref:'paper',y0:0,y1:0,yref:'y',line:{color:'#ffd700',dash:'dash',width:1}});

  // k-path tick labels
  let tickVals = [], tickTexts = [];
  if (bp.k_labels) {
    bp.k_labels.forEach(h => { tickVals.push(h.distance); tickTexts.push(h.label); });
  }

  const allTraces = bandTraces.concat(pdosTraces);
  const layout = {
    title: 'Bands + Projected DOS', paper_bgcolor:'#161b22', plot_bgcolor:'#161b22',
    font: {color:'#8b949e',size:11},
    grid: {rows:1, columns:2, subplots:[['xy','x2y2']], roworder:'top to bottom'},
    xaxis: {title:'k-path', gridcolor:'#30363d', zeroline:false, tickvals:tickVals, ticktext:tickTexts},
    yaxis: {title:'E − EF (eV)', gridcolor:'#30363d', zeroline:true, zerolinecolor:'#ffd700'},
    xaxis2: {title:'DOS (states/eV)', gridcolor:'#30363d', zeroline:true, zerolinecolor:'#30363d'},
    yaxis2: {title:'', gridcolor:'#30363d', zeroline:true, zerolinecolor:'#ffd700', matches:'y'},
    shapes: shapes,
    legend: {x:1.02,y:1,font:{size:9}},
    margin: {l:55,r:20,t:30,b:50}, height: 420
  };
  Plotly.newPlot(el, allTraces, layout, {displayModeBar: false, responsive: true});
}

function renderOverlayBands(el, data) {
  const cases = data.cases || [];
  if (cases.length < 2) {
    el.innerHTML = '<div class="insight insight-missing"><strong>⏭️</strong>Need main case plus at least one compare case.</div>';
    return;
  }
  if (!data.k_path_compatible) {
    let msg = '<div class="insight insight-warn"><strong>⚠️</strong>Overlay chart disabled because k-paths are not compatible.';
    if (data.warnings && data.warnings.length) {
      msg += '<ul style="margin:6px 0 0 18px">';
      data.warnings.forEach(w => { msg += '<li>'+esc(w)+'</li>'; });
      msg += '</ul>';
    }
    msg += '</div>';
    el.innerHTML = msg;
    return;
  }

  const traces = [];
  const dashStyles = ['solid', 'dash', 'dot', 'dashdot'];
  cases.forEach((c, ci) => {
    (c.bands_aligned_ev || []).forEach((energies, ib) => {
      traces.push({
        x: c.k_distances, y: energies,
        type: 'scatter', mode: 'lines',
        line: {
          color: 'hsl('+((ib*360/Math.max(c.nbnd,1))%360)+',70%,60%)',
          width: ci === 0 ? 1.2 : 1,
          dash: dashStyles[ci % dashStyles.length]
        },
        name: c.label+' band '+(ib+1),
        legendgroup: c.label,
        showlegend: ib === 0,
        xaxis: 'x', yaxis: 'y',
        hovertemplate: esc(c.label)+'<br>band '+(ib+1)+'<br>k=%{x:.3f}<br>E−EF=%{y:.3f} eV<extra></extra>'
      });
    });
  });

  const delta = data.delta_e_ev || [];
  if (delta.length) {
    const main = cases[0];
    delta.forEach((row, ib) => {
      traces.push({
        x: main.k_distances.slice(0, row.length), y: row,
        type: 'scatter', mode: 'lines',
        line: {color: 'hsl('+((ib*360/Math.max(delta.length,1))%360)+',70%,60%)', width: 1},
        name: 'Delta-E band '+(ib+1),
        showlegend: false,
        xaxis: 'x2', yaxis: 'y2',
        hovertemplate: 'Delta-E band '+(ib+1)+'<br>k=%{x:.3f}<br>ΔE=%{y:.3f} eV<extra></extra>'
      });
    });
  }

  const labels = cases[0].k_labels || [];
  const tickVals = labels.map(h => h.distance);
  const tickTexts = labels.map(h => h.label);
  const shapes = [];
  labels.forEach(h => {
    shapes.push({type:'line',x0:h.distance,x1:h.distance,y0:0,y1:1,yref:'paper',line:{color:'#8b949e',width:1,dash:'dot'}});
  });
  shapes.push({type:'line',x0:0,x1:1,xref:'paper',y0:0,y1:0,yref:'y',line:{color:'#ffd700',dash:'dash',width:1}});
  shapes.push({type:'line',x0:0,x1:1,xref:'paper',y0:0,y1:0,yref:'y2',line:{color:'#30363d',width:1}});

  const layout = {
    title: 'Overlay Bands + Delta-E', paper_bgcolor:'#161b22', plot_bgcolor:'#161b22',
    font: {color:'#8b949e',size:11},
    grid: {rows:2, columns:1, subplots:[['xy'], ['x2y2']], roworder:'top to bottom'},
    xaxis: {title:'', gridcolor:'#30363d', zeroline:false, tickvals:tickVals, ticktext:tickTexts},
    yaxis: {title:'E − EF (eV)', gridcolor:'#30363d', zeroline:true, zerolinecolor:'#ffd700'},
    xaxis2: {title:'k-path', gridcolor:'#30363d', zeroline:false, tickvals:tickVals, ticktext:tickTexts},
    yaxis2: {title:'Delta-E (eV)', gridcolor:'#30363d', zeroline:true},
    legend: {x:1.02,y:1,font:{size:9}},
    shapes: shapes,
    margin: {l:60,r:20,t:34,b:44}, height: 560
  };
  Plotly.newPlot(el, traces, layout, {displayModeBar: false, responsive: true});
}

function renderFermiSurface(el, data) {
  let html = '';
  if (data.bxsf && data.bxsf.length) {
    data.bxsf.forEach(br => {
      html += '<div class="stats-grid" style="margin-bottom:8px">';
      html += '<div class="stat-card"><div class="label">File</div><div class="value" style="font-size:11px">'+esc(br.file)+'</div></div>';
      html += '<div class="stat-card"><div class="label">Grid</div><div class="value">'+esc(br.grid)+'</div></div>';
      html += '<div class="stat-card"><div class="label">Bands crossing EF</div><div class="value">'+(br.bands_crossing_ef||[]).length+' / '+br.n_bands+'</div></div>';
      html += '<div class="stat-card"><div class="label">EF (eV)</div><div class="value">'+fmt(br.fermi_energy_ev,4)+'</div></div>';
      html += '</div>';
      if (br.has_fermi_surface) {
        html += '<div style="font-size:12px;color:var(--green);margin:4px 0">✅ Fermi surface detected — bands '+br.bands_crossing_ef.join(', ')+' cross EF</div>';
      } else {
        html += '<div style="font-size:12px;color:var(--orange);margin:4px 0">⚠ No bands cross EF on this grid</div>';
      }
    });
  } else if (data.bands_derived) {
    const bd = data.bands_derived;
    html += '<div class="stats-grid">';
    html += '<div class="stat-card"><div class="label">Bands crossing EF</div><div class="value">'+bd.n_bands_crossing_ef+'</div></div>';
    html += '<div class="stat-card"><div class="label">Electron pockets</div><div class="value">'+bd.n_electron_pockets+'</div></div>';
    html += '<div class="stat-card"><div class="label">Hole pockets</div><div class="value">'+bd.n_hole_pockets+'</div></div>';
    html += '<div class="stat-card"><div class="label">Total pockets</div><div class="value">'+bd.n_pockets+'</div></div>';
    if (bd.estimated_n_2d != null) html += '<div class="stat-card"><div class="label">Est. n₂D (per cell)</div><div class="value">'+bd.estimated_n_2d.toExponential(1)+'</div></div>';
    html += '</div>';
    if (bd.pockets && bd.pockets.length) {
      html += '<div style="margin:8px 0;font-size:11px"><table style="width:100%;border-collapse:collapse">';
      html += '<tr style="color:var(--muted)"><th style="text-align:left;padding:4px">Bands</th><th>Type</th><th>Δk_F</th><th>Crossings</th></tr>';
      bd.pockets.forEach(p => {
        html += '<tr><td style="padding:4px">'+p.band_indices.join(',')+'</td><td>'+p.carrier_type+'</td><td>'+fmt(p.kf_range,4)+'</td><td>'+p.n_crossings+'</td></tr>';
      });
      html += '</table></div>';
    }
    if (bd.caveat) html += '<div style="font-size:10px;color:var(--muted);margin-top:4px">'+esc(bd.caveat)+'</div>';
  }
  el.innerHTML = html;
}

function renderOverviewStats(el, data) {
  const s = data.scf;
  if (!s) return;
  el.innerHTML = '<div class="stats-grid">'+
    '<div class="stat-card"><div class="label">Total Energy (Ry)</div><div class="value">'+fmt(s.total_energy_ry,6)+'</div></div>'+
    '<div class="stat-card"><div class="label">Fermi Energy (eV)</div><div class="value">'+fmt(s.fermi_energy_ev,4)+'</div></div>'+
    '<div class="stat-card"><div class="label">SCF Iterations</div><div class="value">'+s.scf_iterations+'</div></div>'+
    '<div class="stat-card"><div class="label">Wall Time (s)</div><div class="value">'+fmt(s.wall_time_sec,1)+'</div></div>'+
    '<div class="stat-card"><div class="label">Program</div><div class="value" style="font-size:12px">'+esc(s.program)+' v'+esc(s.version||'')+'</div></div>'+
    (data.stages_present ? '<div class="stat-card"><div class="label">Files Discovered</div><div class="value">'+data.total_files+'</div></div>' : '')+
    '</div>';
}

function renderStructureViewer(el, data) {
  // Lattice info card + 3Dmol.js viewer
  const lat = data.lattice || {};
  let html = '<div style="display:flex;gap:16px;flex-wrap:wrap">';
  html += '<div style="flex:1;min-width:300px">';
  html += '<div class="stats-grid">';
  html += '<div class="stat-card"><div class="label">a (Å)</div><div class="value">'+fmt(lat.a,3)+'</div></div>';
  html += '<div class="stat-card"><div class="label">b (Å)</div><div class="value">'+fmt(lat.b,3)+'</div></div>';
  html += '<div class="stat-card"><div class="label">c (Å)</div><div class="value">'+fmt(lat.c,3)+'</div></div>';
  html += '<div class="stat-card"><div class="label">α</div><div class="value">'+fmt(lat.alpha,1)+'°</div></div>';
  html += '<div class="stat-card"><div class="label">β</div><div class="value">'+fmt(lat.beta,1)+'°</div></div>';
  html += '<div class="stat-card"><div class="label">γ</div><div class="value">'+fmt(lat.gamma,1)+'°</div></div>';
  html += '<div class="stat-card"><div class="label">Volume</div><div class="value">'+fmt(lat.volume,1)+' Å³</div></div>';
  html += '</div>';
  if (data.metrics_2d) {
    const m = data.metrics_2d;
    html += '<div class="stats-grid" style="margin-top:8px">';
    html += '<div class="stat-card"><div class="label">Vacuum</div><div class="value">'+fmt(m.vacuum_thickness_ang,1)+' Å</div></div>';
    html += '<div class="stat-card"><div class="label">Layer thickness</div><div class="value">'+fmt(m.layer_thickness_ang,2)+' Å</div></div>';
    html += '<div class="stat-card"><div class="label">Layers</div><div class="value">'+m.n_layers+'</div></div>';
    if (m.buckling_ang > 0.01) html += '<div class="stat-card"><div class="label">Buckling</div><div class="value">'+fmt(m.buckling_ang,3)+' Å</div></div>';
    html += '</div>';
  }
  if (data.symmetry && data.symmetry.space_group_symbol) {
    html += '<div style="margin-top:8px;font-size:12px;color:var(--muted)">Space group: <strong>'+esc(data.symmetry.space_group_symbol)+'</strong> (#'+data.symmetry.space_group_number+'), '+data.symmetry.n_operations+' ops</div>';
  }
  html += '</div>';
  // 3Dmol viewer
  html += '<div id="mol-'+el.id+'" style="width:360px;height:300px;border:1px solid var(--border);border-radius:6px;position:relative"></div>';
  html += '</div>';
  el.innerHTML = html;

  // Init 3Dmol viewer
  try {
    let viewer = $3Dmol.createViewer('mol-'+el.id, {defaultcolors: $3Dmol.elementColors.Jmol});
    viewer.addModel(data.xyz_string, 'xyz');
    viewer.setStyle({}, {stick: {radius: 0.15}, sphere: {scale: 0.3}});
    viewer.addUnitCell();
    viewer.zoomTo();
    viewer.render();
  } catch(e) { console.log('3Dmol not loaded:', e); }
}

function renderBandsChart(el, data) {
  const traces = data.bands.map((energies, ib) => ({
    x: data.k_distances, y: energies,
    type: 'scatter', mode: 'lines',
    line: {color: 'hsl('+((ib*360/data.nbnd)%360)+',70%,60%)',width:1},
    name: 'Band '+(ib+1), showlegend: false
  }));
  const layout = {
    title: 'Band Structure', paper_bgcolor:'#161b22', plot_bgcolor:'#161b22',
    font: {color:'#8b949e',size:11},
    xaxis: {title:'k-path',gridcolor:'#30363d',zeroline:false},
    yaxis: {title:'Energy (eV)',gridcolor:'#30363d',zeroline:true,zerolinecolor:'#ffd700',zerolinewidth:1},
    margin: {l:50,r:20,t:30,b:40}, height: 380,
    shapes: [{type:'line',x0:0,x1:1,xref:'paper',y0:0,y1:0,yref:'y',line:{color:'#ffd700',dash:'dash',width:1}}]
  };
  if (data.band_gap && data.band_gap.gap_ev) {
    layout.title = 'Band Structure (gap='+fmt(data.band_gap.gap_ev,3)+' eV, '+data.band_gap.type+')';
  }
  Plotly.newPlot(el, traces, layout, {displayModeBar: false, responsive: true});
}

function renderDosChart(el, data) {
  const traces = [];
  if (data.tdos) {
    traces.push({
      x: data.tdos.data.map(d => d.dos), y: data.tdos.data.map(d => d.energy_ev),
      type: 'scatter', mode: 'lines', fill: 'tozerox',
      line: {color: '#f85149',width:1.5}, fillcolor: 'rgba(248,81,73,0.15)',
      name: 'TDOS', showlegend: true
    });
  }
  if (data.pdos && data.pdos.groups) {
    const colors = ['#58a6ff','#3fb950','#d2991d','#bc8cff','#ff7b72','#79c0ff'];
    let ci = 0;
    Object.entries(data.pdos.groups).forEach(([label, pts]) => {
      if (!pts || !pts.length) return;
      traces.push({
        x: pts.map(d => d.dos), y: pts.map(d => d.energy_ev),
        type: 'scatter', mode: 'lines',
        line: {color: colors[ci%colors.length],width:1},
        name: label, showlegend: true, visible: 'legendonly'
      });
      ci++;
    });
  }
  const layout = {
    title: 'DOS / PDOS', paper_bgcolor:'#161b22', plot_bgcolor:'#161b22',
    font: {color:'#8b949e',size:11},
    xaxis: {title:'DOS (states/eV)',gridcolor:'#30363d',zeroline:true,zerolinecolor:'#30363d'},
    yaxis: {title:'E − EF (eV)',gridcolor:'#30363d',zeroline:true,zerolinecolor:'#ffd700',zerolinewidth:1},
    legend: {x:0.85,y:1,font:{size:9}},
    margin: {l:50,r:20,t:30,b:40}, height: 380,
    shapes: [{type:'line',x0:0,x1:1,xref:'paper',y0:0,y1:0,yref:'y',line:{color:'#ffd700',dash:'dash',width:1}}]
  };
  Plotly.newPlot(el, traces, layout, {displayModeBar: false, responsive: true});
}

function renderPhononChart(el, data) {
  const traces = [];
  const gridLabels = Object.keys(data.grids||{});
  gridLabels.forEach((label, gi) => {
    const gd = data.grids[label];
    if (!gd.frequencies) return;
    gd.frequencies.forEach((freqs, ib) => {
      const colors = freqs.some(v => v < 0) ? '#f85149' : '#e6edf3';
      traces.push({
        x: gd.q_distances, y: freqs,
        type: 'scatter', mode: 'lines',
        line: {color: colors, width: 0.8},
        name: (gi===0?'':label+' ')+'b'+(ib+1),
        showlegend: false,
        xaxis: 'x'+(gi+1), yaxis: 'y'+(gi+1)
      });
    });
  });
  const layout = {
    title: 'Phonon Dispersion', paper_bgcolor:'#161b22', plot_bgcolor:'#161b22',
    font: {color:'#8b949e',size:11},
    xaxis: {title: gridLabels[0]||'','domain':[0,gridLabels.length>1?0.48:1],gridcolor:'#30363d',zeroline:false},
    yaxis: {title:'Frequency (cm⁻¹)',gridcolor:'#30363d',zeroline:true,zerolinecolor:'#30363d'},
    margin: {l:50,r:20,t:30,b:40}, height: 380,
    shapes: [{type:'line',x0:0,x1:1,xref:'paper',y0:0,y1:0,yref:'y',line:{color:'#30363d',width:1}}]
  };
  if (gridLabels.length > 1) {
    layout.xaxis2 = {title: gridLabels[1], domain: [0.52,1], gridcolor:'#30363d', zeroline:false, anchor:'y2'};
    layout.yaxis2 = {title:'', gridcolor:'#30363d', zerolinecolor:'#30363d', anchor:'x2', overlaying:'y'};
    layout.shapes.push({type:'line',x0:0.5,x1:0.5,xref:'paper',y0:0,y1:1,yref:'paper',line:{color:'var(--border)',width:1}});
  }
  Plotly.newPlot(el, traces, layout, {displayModeBar: false, responsive: true});
}

function renderEpcChart(el, data) {
  const traces = [];
  const gridLabels = Object.keys(data||{});
  gridLabels.forEach(label => {
    const gd = data[label];
    if (gd.alpha2F && gd.alpha2F.length) {
      traces.push({
        x: gd.alpha2F.map(d => d.omega_cm1), y: gd.alpha2F.map(d => d.a2f),
        type: 'scatter', mode: 'lines', fill: 'tozeroy',
        name: label+' a²F', line: {width:1.2}
      });
    }
    if (gd.lambda && gd.lambda.length) {
      const maxLam = Math.max(...gd.lambda.map(d => d.lambda));
      traces.push({
        x: gd.lambda.map(d => d.degauss_ry), y: gd.lambda.map(d => d.lambda),
        type: 'scatter', mode: 'lines+markers',
        name: label+' λ', yaxis: 'y2', line: {width:1.5}, marker: {size:4}
      });
    }
  });
  const layout = {
    title: 'Electron-Phonon Coupling', paper_bgcolor:'#161b22', plot_bgcolor:'#161b22',
    font: {color:'#8b949e',size:11},
    xaxis: {title: 'ω (cm⁻¹)',gridcolor:'#30363d'},
    yaxis: {title: 'α²F(ω)',gridcolor:'#30363d',zeroline:true},
    yaxis2: {title: 'λ',overlaying:'y',side:'right',gridcolor:'transparent'},
    legend: {x:0.8,y:1,font:{size:9}},
    margin: {l:50,r:50,t:30,b:40}, height: 380
  };
  if (traces.length) Plotly.newPlot(el, traces, layout, {displayModeBar: false, responsive: true});
}

function renderTcChart(el, data) {
  const traces = [];
  ['grid_a','grid_b'].forEach(key => {
    const gd = data[key];
    if (!gd || !gd.data) return;
    const d = gd.data;
    if (d.degauss_values && d.tc_values) {
      const valid = d.degauss_values.map((dg,i) => ({dg,tc:d.tc_values[i]})).filter(p => !isNaN(p.tc) && p.tc > 0);
      traces.push({
        x: valid.map(p => p.dg), y: valid.map(p => p.tc),
        type: 'scatter', mode: 'lines+markers',
        name: gd.label || key, line: {width:1.5}, marker: {size:5}
      });
    }
  });
  const layout = {
    title: 'Tc vs Degauss', paper_bgcolor:'#161b22', plot_bgcolor:'#161b22',
    font: {color:'#8b949e',size:11},
    xaxis: {title:'Degauss (Ry)',gridcolor:'#30363d',zeroline:false},
    yaxis: {title:'Tc (K)',gridcolor:'#30363d',zeroline:true},
    legend: {x:0.8,y:1,font:{size:9}},
    margin: {l:50,r:20,t:30,b:40}, height: 380
  };
  if (data.tc_overlap && data.tc_overlap.tc_point_k) {
    layout.shapes = [{
      type:'line',x0:data.tc_overlap.degauss_ry,x1:data.tc_overlap.degauss_ry,
      y0:0,y1:1,yref:'paper',line:{color:'#3fb950',dash:'dot',width:1.5}
    }];
    layout.annotations = [{
      x: data.tc_overlap.degauss_ry, y: 1, xref: 'x', yref: 'paper',
      text: 'Tc='+fmt(data.tc_overlap.tc_point_k,2)+' K', showarrow: false,
      font: {color:'#3fb950',size:10}, yanchor:'bottom'
    }];
  }
  if (traces.length) Plotly.newPlot(el, traces, layout, {displayModeBar: false, responsive: true});
}

function fmt(v,d) { return (v!=null ? Number(v).toFixed(d) : 'N/A'); }
function esc(s) { const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }
function scrollToSection(i) { document.getElementById('s'+i).scrollIntoView({behavior:'smooth'}); }

renderCharts();
</script>
</body>
</html>
"""
