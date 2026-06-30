"""Advanced bands analysis: projected DOS joint panel, overlay bands.

P0: Bands + Projected DOS Joint Panel
  - Side-by-side bands + element/orbital PDOS with shared energy axis
  - Near-EF dominant orbital insight
  - Does NOT do per-k-point fat bands (PDOS is on uniform DOS mesh, not band path)

P1: Overlay Bands (future)
P2: Fat / Unfolded Bands (data-dependent, future)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibedft.core.analysis import parse_bands_output, parse_dos_output, parse_qe_output
from vibedft.core.kpath import detect_high_symmetry, compute_k_distances


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProjectedDosPanel:
    """Element/orbital-resolved PDOS for joint rendering with bands."""
    tdos: list[dict[str, float]] = field(default_factory=list)
    pdos_groups: dict[str, list[dict[str, float]]] = field(default_factory=dict)
    dominant_near_ef: dict[str, Any] = field(default_factory=dict)
    e_fermi_ev: float = 0.0

    @property
    def group_labels(self) -> list[str]:
        return sorted(self.pdos_groups.keys())


@dataclass
class BandPanelData:
    """Normalised band structure with k-path labels."""
    nbnd: int
    nks: int
    k_distances: list[float]
    bands: list[list[float]]
    k_labels: list[dict[str, Any]]
    gap_ev: float | None = None
    gap_type: str = "unknown"


@dataclass
class OverlayCase:
    """One case participating in an overlay band comparison."""
    label: str
    case_dir: str
    source_file: str
    nbnd: int
    nks: int
    k_points: list[list[float]]
    k_distances: list[float]
    k_labels: list[dict[str, Any]]
    bands: list[list[float]]
    bands_aligned_ev: list[list[float]]
    fermi_energy_ev: float
    fermi_source: str


@dataclass
class OverlayBands:
    """Normalised overlay bands for same-k-path case comparison."""
    cases: list[OverlayCase] = field(default_factory=list)
    k_path_compatible: bool = False
    warnings: list[str] = field(default_factory=list)
    delta_e_ev: list[list[float]] | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# P0: Joint Panel Builder
# ═══════════════════════════════════════════════════════════════════════════════


def build_joint_bands_pdos_panel(
    bands_file: Path | str,
    dos_file: Path | str | None = None,
    pdos_dir: Path | str | None = None,
    e_fermi_ev: float | None = None,
) -> dict[str, Any]:
    """Build a joint bands + projected DOS panel data structure.

    Returns a dict with keys: bands, pdos, k_labels, fermi_energy_ev,
    fermi_source, errors.  All energy values are aligned to a single
    Fermi energy (scf > user-supplied > dos fallback > 0.0).
    """
    errors: list[str] = []
    result: dict[str, Any] = {
        "bands": None, "pdos": None, "k_labels": None,
        "fermi_energy_ev": 0.0, "fermi_source": "none", "errors": errors,
    }

    # ── PDOS first (to resolve EF before gap analysis) ──
    pdos = ProjectedDosPanel()
    dos_ef = None
    if dos_file and Path(dos_file).is_file():
        try:
            d = parse_dos_output(dos_file)
            pdos.tdos = d.dos_data
            dos_ef = d.e_fermi_ev
        except Exception as exc:
            errors.append(f"dos parse error ({Path(dos_file).name}): {exc}")

    # ── Resolve Fermi energy (unified, before gap analysis) ──
    # Priority: explicit scf-ef > DOS header > fallback 0
    if e_fermi_ev is not None:
        ef = e_fermi_ev
        fermi_source = "scf" if e_fermi_ev != 0.0 else "scf_zero"
    elif dos_ef is not None:
        ef = dos_ef
        fermi_source = "dos_header"
    else:
        ef = 0.0
        fermi_source = "fallback_zero"
    pdos.e_fermi_ev = ef
    result["fermi_energy_ev"] = ef
    result["fermi_source"] = fermi_source
    if dos_ef is not None and abs(dos_ef - ef) > 0.05:
        result["dos_fermi_ev_note"] = (
            f"DOS header EF={dos_ef:.4f} eV differs from used EF={ef:.4f} eV "
            f"(source: {fermi_source})"
        )

    # ── Bands (with resolved EF) ──
    try:
        parsed = parse_bands_output(bands_file)
        k_dists = compute_k_distances(parsed.k_points)
        hs = detect_high_symmetry(parsed.k_points, k_dists)

        from vibedft.core.physics import band_gap_analysis
        gap_info = band_gap_analysis(parsed.bands, k_dists, ef)

        result["bands"] = BandPanelData(
            nbnd=parsed.nbnd, nks=parsed.nks,
            k_distances=k_dists, bands=parsed.bands,
            k_labels=hs,
            gap_ev=gap_info.get("gap_ev"),
            gap_type=gap_info.get("type", "unknown"),
        )
        result["k_labels"] = hs
    except Exception as exc:
        errors.append(f"bands parse error ({Path(bands_file).name}): {exc}")

    # ── PDOS groups with grid validation ──
    if pdos_dir and Path(pdos_dir).is_dir():
        from vibedft.core.analysis import discover_pdos_files, parse_pdos_file
        import re

        pdos_results = []
        for pdos_file in discover_pdos_files(Path(pdos_dir)):
            try:
                pdos_results.append(parse_pdos_file(pdos_file))
            except Exception as exc:
                errors.append(f"PDOS parse error ({pdos_file.name}): {exc}")

        groups: dict[str, list[dict[str, float]]] = {}
        grids: dict[str, list[float]] = {}  # group key → energy grid for validation
        base_entries: dict[str, list[dict[str, str]]] = {}

        def _rename_group(old_key: str, new_key: str) -> None:
            if old_key == new_key or old_key not in groups:
                return
            groups[new_key] = groups.pop(old_key)
            grids[new_key] = grids.pop(old_key)
            for entries in base_entries.values():
                for entry in entries:
                    if entry["key"] == old_key:
                        entry["key"] = new_key

        for p in pdos_results:
            lbl = p.label
            atm_m = re.search(r"atm#(\d+)\((\w+)\)", lbl)
            wfc_m = re.search(r"_wfc#(\d+)\((\w)\)", lbl)
            elem = atm_m.group(2) if atm_m else "?"
            orb = wfc_m.group(2) if wfc_m else "?"
            wfc_idx = wfc_m.group(1) if wfc_m else "?"
            base_key = f"{elem}-{orb}"
            indexed_key = f"{base_key}_wfc{wfc_idx}"
            new_grid = [d["energy_ev"] for d in p.data]

            entries = base_entries.setdefault(base_key, [])
            matching = next((entry for entry in entries if _energy_grids_match(grids[entry["key"]], new_grid)), None)
            if matching:
                key = matching["key"]
                for i, d in enumerate(p.data):
                    groups[key][i]["dos"] += d["dos"]
                continue

            if entries:
                # A new grid for the same element/orbital would make a merged
                # label misleading. Split all groups in that family by wfc index.
                for entry in list(entries):
                    if not entry["key"].endswith(f"_wfc{entry['wfc_idx']}"):
                        _rename_group(entry["key"], f"{base_key}_wfc{entry['wfc_idx']}")
                errors.append(
                    f"PDOS grid mismatch for {base_key}: "
                    f"{len(grids[entries[0]['key']])} vs {len(new_grid)} points — split by wfc index"
                )
                key = indexed_key
            else:
                key = base_key

            grids[key] = new_grid
            groups[key] = [{"energy_ev": d["energy_ev"], "dos": d["dos"]} for d in p.data]
            entries.append({"key": key, "wfc_idx": wfc_idx})
        pdos.pdos_groups = groups

    # Near-EF dominant orbital
    if pdos.tdos and pdos.pdos_groups:
        ef_val = ef
        contributions = {}
        for label, data in pdos.pdos_groups.items():
            closest = min(data, key=lambda d: abs(d["energy_ev"] - ef_val))
            contributions[label] = max(closest["dos"], 0.0)
        total = sum(contributions.values()) or 1.0
        dominant = max(contributions, key=contributions.get)
        pdos.dominant_near_ef = {
            "element_orbital": dominant,
            "fraction": max(contributions[dominant] / total, 0.0) if total > 0 else 0.0,
            "ef_used_ev": ef_val,
            "all_contributions": {k: v / total for k, v in sorted(contributions.items(), key=lambda x: -x[1])[:5]},
        }

    result["pdos"] = pdos
    return result


def build_overlay_bands(
    main_case_dir: Path | str,
    compare_dirs: list[Path | str] | tuple[Path | str, ...],
    *,
    k_tolerance: float = 1e-4,
) -> OverlayBands:
    """Build same-k-path overlay bands for a main case plus compare cases.

    Energies are aligned per case as ``E - EF``. Delta-E is computed for the
    first compare case only: ``compare_aligned - main_aligned``. No k-path
    resampling, multi-material alignment, or unfolding is attempted.
    """
    warnings: list[str] = []
    case_dirs = [Path(main_case_dir)] + [Path(p) for p in compare_dirs]
    cases: list[OverlayCase] = []

    for idx, case_dir in enumerate(case_dirs):
        loaded = _load_overlay_case(case_dir, label=case_dir.name or f"case-{idx}")
        if loaded is None:
            warnings.append(f"{case_dir}: no bands file found")
            continue
        cases.append(loaded)

    if len(cases) < 2:
        return OverlayBands(cases=cases, k_path_compatible=False, warnings=warnings)

    main = cases[0]
    k_path_compatible = True
    for other in cases[1:]:
        if main.nks != other.nks:
            warnings.append(
                f"{other.label}: n_kpoints mismatch ({main.nks} vs {other.nks})"
            )
            k_path_compatible = False
            continue
        for ik, (ka, kb) in enumerate(zip(main.k_points, other.k_points)):
            delta = max(abs(ka[i] - kb[i]) for i in range(3))
            if delta >= k_tolerance:
                warnings.append(
                    f"{other.label}: k coordinate mismatch at index {ik} "
                    f"({delta:.2e} >= {k_tolerance:.1e})"
                )
                k_path_compatible = False
                break
        if not _labels_compatible(main.k_labels, other.k_labels, tolerance=k_tolerance):
            warnings.append(f"{other.label}: high-symmetry labels are not compatible")
            k_path_compatible = False
        if main.nbnd != other.nbnd:
            warnings.append(
                f"{other.label}: n_bands mismatch ({main.nbnd} vs {other.nbnd}); "
                "partial comparison uses the shared band count"
            )

    delta_e = None
    if k_path_compatible and len(cases) >= 2:
        delta_e = _compute_delta_e(cases[0], cases[1])

    return OverlayBands(
        cases=cases,
        k_path_compatible=k_path_compatible,
        warnings=warnings,
        delta_e_ev=delta_e,
    )


def _energy_grids_match(a: list[float], b: list[float], *, tol: float = 1e-6) -> bool:
    """Return True when two PDOS energy grids are identical within tolerance."""
    if len(a) != len(b):
        return False
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _load_overlay_case(case_dir: Path, *, label: str) -> OverlayCase | None:
    bands_file = _find_overlay_bands_file(case_dir)
    if bands_file is None:
        return None
    parsed = parse_bands_output(bands_file)
    k_dists = compute_k_distances(parsed.k_points)
    k_labels = detect_high_symmetry(parsed.k_points, k_dists)
    ef, source = _resolve_overlay_fermi(case_dir)
    aligned = [
        [round(e - ef, 10) for e in band]
        for band in parsed.bands
    ]
    try:
        source_file = str(bands_file.relative_to(case_dir))
    except ValueError:
        source_file = bands_file.name
    return OverlayCase(
        label=label,
        case_dir=label,
        source_file=source_file,
        nbnd=parsed.nbnd,
        nks=parsed.nks,
        k_points=parsed.k_points,
        k_distances=k_dists,
        k_labels=k_labels,
        bands=parsed.bands,
        bands_aligned_ev=aligned,
        fermi_energy_ev=ef,
        fermi_source=source,
    )


def _find_overlay_bands_file(case_dir: Path) -> Path | None:
    out = case_dir / "output"
    search_root = out if out.is_dir() else case_dir
    candidates = [
        p for p in sorted(search_root.rglob("*bands*"))
        if p.is_file() and "GA" not in p.name.upper()
    ]
    preferred = [
        p for p in candidates
        if ".gnu" in p.name or ".bands.dat" in p.name
    ]
    return preferred[0] if preferred else (candidates[0] if candidates else None)


def _resolve_overlay_fermi(case_dir: Path) -> tuple[float, str]:
    out = case_dir / "output"
    scf = out / "scf.out"
    if scf.is_file():
        try:
            ef = parse_qe_output(scf).fermi_energy_ev
            if ef is not None:
                return ef, "scf"
        except Exception:
            pass
    dos_files = sorted(out.rglob("*.dos")) if out.is_dir() else []
    for dos_file in dos_files:
        try:
            ef = parse_dos_output(dos_file).e_fermi_ev
            if ef is not None:
                return ef, "dos_header"
        except Exception:
            continue
    return 0.0, "fallback_zero"


def _labels_compatible(
    a: list[dict[str, Any]],
    b: list[dict[str, Any]],
    *,
    tolerance: float,
) -> bool:
    if len(a) != len(b):
        return False
    for la, lb in zip(a, b):
        if la.get("label") != lb.get("label"):
            return False
        if abs(float(la.get("distance", 0.0)) - float(lb.get("distance", 0.0))) >= tolerance:
            return False
    return True


def _compute_delta_e(main: OverlayCase, compare: OverlayCase) -> list[list[float]]:
    n_bands = min(main.nbnd, compare.nbnd, len(main.bands_aligned_ev), len(compare.bands_aligned_ev))
    n_k = min(main.nks, compare.nks)
    delta: list[list[float]] = []
    for ib in range(n_bands):
        row = [
            round(compare.bands_aligned_ev[ib][ik] - main.bands_aligned_ev[ib][ik], 10)
            for ik in range(n_k)
        ]
        delta.append(row)
    return delta
