"""Electronic structure physics analyzer: DOS@EF, van Hove, orbital character, gap."""

from __future__ import annotations

from pathlib import Path

from vibedft.analyzers.physics_models import (
    ElectronicData,
    EvidenceLink,
    InsightLevel,
    PhysicsInsight,
)
from vibedft.core.analysis import parse_dos_output, parse_bands_output, parse_qe_output, compute_k_distances
from vibedft.core.physics import band_gap_analysis


def extract_electronic_data(case_dir: Path | str) -> ElectronicData | None:
    """Extract electronic structure metrics from SCF/DOS/bands outputs."""
    d = Path(case_dir)
    out = d / "output"

    scf_files = sorted(out.rglob("scf.out"))
    dos_files = sorted(out.rglob("*.dos"))
    bands_files = sorted(out.rglob("*bands*"))

    has_any = scf_files or dos_files
    if not has_any:
        return None

    data = ElectronicData()

    # SCF
    if scf_files:
        try:
            qe = parse_qe_output(scf_files[0])
            data.fermi_energy_ev = qe.fermi_energy_ev or 0.0
            data.source_files.append(str(scf_files[0]))
        except Exception:
            pass

    # DOS
    if dos_files:
        try:
            dos = parse_dos_output(dos_files[0])
            if dos.e_fermi_ev is not None:
                data.fermi_energy_ev = dos.e_fermi_ev
            data.source_files.append(str(dos_files[0]))
            # DOS at EF
            ef = data.fermi_energy_ev
            closest = min(dos.dos_data, key=lambda d: abs(d["energy_ev"] - ef), default=None)
            if closest:
                data.dos_at_ef = closest["dos"]
                data.is_metallic = closest["dos"] > 0.05
        except Exception:
            pass

    # Bands — gap analysis
    if bands_files:
        main = [f for f in bands_files if "GA" not in f.name.upper()]
        best = main[0] if main else bands_files[0]
        try:
            parsed = parse_bands_output(best)
            k_dists = compute_k_distances(parsed.k_points)
            gap = band_gap_analysis(parsed.bands, k_dists, data.fermi_energy_ev)
            data.band_gap_ev = gap.get("gap_ev")
            data.gap_type = gap.get("type", "unknown")
            data.source_files.append(str(best))
        except Exception:
            pass

    # Van Hove from physics module
    if dos_files:
        try:
            from vibedft.core.physics import van_hove_singularities
            dos = parse_dos_output(dos_files[0])
            vhs = van_hove_singularities(dos.dos_data, data.fermi_energy_ev)
            data.van_hove_near_ef = [
                v for v in vhs if abs(v.get("energy_vs_ef", 100)) < 2.0
            ][:5]
        except Exception:
            pass

    # PDOS dominant orbital
    try:
        from vibedft.core.analysis import parse_pdos_bundle
        pdos_results = parse_pdos_bundle(out)
        if pdos_results:
            ef = data.fermi_energy_ev
            contributions: dict[str, float] = {}
            for p in pdos_results:
                if not p.data:
                    continue
                closest = min(p.data, key=lambda d: abs(d["energy_ev"] - ef), default=None)
                if closest:
                    import re
                    m_atm = re.search(r"\((\w+)\)", p.label)
                    m_orb = re.search(r"\((\w)\)", p.label)
                    elem = m_atm.group(1) if m_atm else "?"
                    orb = m_orb.group(1) if m_orb else "?"
                    contributions[f"{elem}-{orb}"] = max(closest["dos"], 0.0)
            if contributions:
                total = sum(contributions.values()) or 1.0
                dominant = max(contributions, key=contributions.get)
                data.dominant_orbital_near_ef = dominant
                data.dominant_orbital_fraction = contributions[dominant] / total
    except Exception:
        pass

    return data


def analyze_electronic_structure(data: ElectronicData | None) -> tuple[list[PhysicsInsight], float]:
    """Produce physics insights and score (0–10) from electronic data."""
    if data is None:
        return [
            PhysicsInsight(
                id="elec.no_data", category="electronic",
                level=InsightLevel.NEUTRAL,
                message="No electronic structure data found.",
            )
        ], 5.0

    insights: list[PhysicsInsight] = []
    score = 6.0

    # ── Metallic vs insulating ──
    if data.is_metallic:
        insights.append(PhysicsInsight(
            id="elec.metallic", category="electronic",
            level=InsightLevel.NEUTRAL,
            message=f"DOS(EF) = {data.dos_at_ef:.3f} states/eV — metallic.",
            detail="Non-zero DOS at EF is required for conventional superconductivity. "
                   "Higher DOS(EF) generally enhances λ.",
            evidence=[EvidenceLink(key="dos_at_ef", value=data.dos_at_ef, parser="parse_dos_output")],
        ))
        if data.dos_at_ef > 2.0:
            score += 1.5
            insights.append(PhysicsInsight(
                id="elec.high_dos", category="electronic",
                level=InsightLevel.POSITIVE,
                message=f"High DOS(EF) = {data.dos_at_ef:.1f} states/eV — favorable for SC.",
            ))
        elif data.dos_at_ef < 0.2:
            score -= 1.0
            insights.append(PhysicsInsight(
                id="elec.low_dos", category="electronic",
                level=InsightLevel.WARNING,
                message=f"Low DOS(EF) = {data.dos_at_ef:.3f} states/eV — may limit λ and Tc.",
            ))
    elif data.band_gap_ev is not None and data.band_gap_ev > 0.05:
        gap_icon = "☀" if data.gap_type == "direct" else "↗"
        insights.append(PhysicsInsight(
            id="elec.insulating", category="electronic",
            level=InsightLevel.NEUTRAL,
            message=f"{gap_icon} Band gap: {data.band_gap_ev:.3f} eV ({data.gap_type}).",
            detail="Insulating at the single-particle level. Doping is required for "
                   "metallicity and superconductivity.",
        ))
        if data.band_gap_ev < 1.0:
            score += 0.5  # small gap — easily doped
        else:
            score -= 1.0  # large gap — hard to dope

    # ── Orbital character ──
    if data.dominant_orbital_near_ef:
        frac_pct = data.dominant_orbital_fraction * 100
        insights.append(PhysicsInsight(
            id="elec.orbital_character", category="electronic",
            level=InsightLevel.NEUTRAL,
            message=f"Near EF: dominant character = {data.dominant_orbital_near_ef} "
                    f"({frac_pct:.0f}% of DOS@EF).",
            detail="Transition-metal d-orbitals near EF typically enhance EPC. "
                   "Main-group p-orbital character may indicate weaker coupling.",
            evidence=[EvidenceLink(key="dominant_orbital", value=data.dominant_orbital_near_ef)],
        ))
        if "d" in data.dominant_orbital_near_ef.split("-")[-1]:
            score += 0.5  # d-orbital → stronger EPC potential

    # ── Van Hove singularities near EF ──
    if data.van_hove_near_ef:
        vh = data.van_hove_near_ef[0]
        dist_ev = vh.get("energy_vs_ef", 0)
        insights.append(PhysicsInsight(
            id="elec.van_hove", category="electronic",
            level=InsightLevel.POSITIVE if abs(dist_ev) < 0.2 else InsightLevel.NEUTRAL,
            message=f"Van Hove singularity at E−EF = {dist_ev:.3f} eV "
                    f"(DOS peak = {vh.get('dos_value', 0):.1f}).",
            detail="Van Hove singularities near EF can strongly enhance DOS and λ. "
                   "Strain or doping can tune the VHS to EF.",
            evidence=[EvidenceLink(key="van_hove_energy", value=dist_ev)],
        ))
        if abs(dist_ev) < 0.1:
            score += 1.5
            insights.append(PhysicsInsight(
                id="elec.vhs_near_ef", category="electronic",
                level=InsightLevel.POSITIVE,
                message=f"VHS is very close to EF ({dist_ev:.3f} eV) — strong enhancement possible.",
            ))
        elif abs(dist_ev) < 0.5:
            score += 0.5

    return insights, max(0.0, min(10.0, score))
