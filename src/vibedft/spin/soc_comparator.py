"""SOC vs scalar comparison — DOS@EF, band crossings, gap changes."""

from __future__ import annotations

from pathlib import Path


def compare_soc_vs_scalar(case_dir: Path | str) -> dict:
    """Compare scalar-relativistic results with SOC results if both are present.

    Looks for scf.out (scalar) and a SOC subdirectory for comparison.
    Returns a dict with comparison metrics.
    """
    d = Path(case_dir)
    result: dict = {
        "status": "no_soc_data",
        "dos_ef_scalar": None,
        "dos_ef_soc": None,
        "dos_ef_change_pct": None,
        "fermi_shift_ev": None,
        "soc_gap_change": None,
        "summary": "",
    }

    # Find scalar SCF output
    scalar_scf = _find_scf(d)
    soc_dir = d / "soc_scf" if (d / "soc_scf").is_dir() else None
    if not soc_dir:
        # Check common SOC subdirectory names
        for name in ("12_soc_scf", "soc", "SOC"):
            if (d / name).is_dir():
                soc_dir = d / name
                break
    if not soc_dir:
        return result

    soc_scf = _find_scf(soc_dir)
    if not scalar_scf or not soc_scf:
        return result

    # Extract DOS@EF and Fermi energy from both
    try:
        from vibedft.core.analysis import parse_qe_output, parse_dos_output

        scalar_qe = parse_qe_output(scalar_scf)
        soc_qe = parse_qe_output(soc_scf)

        # Fermi energy comparison
        if scalar_qe.fermi_energy_ev and soc_qe.fermi_energy_ev:
            result["fermi_shift_ev"] = round(soc_qe.fermi_energy_ev - scalar_qe.fermi_energy_ev, 4)

        # Total energy difference
        if scalar_qe.total_energy_ry and soc_qe.total_energy_ry:
            de_ry = soc_qe.total_energy_ry - scalar_qe.total_energy_ry
            de_mev = de_ry * 13605.7  # Ry → meV
            result["total_energy_shift_mev"] = round(de_mev, 1)

        # DOS files
        scalar_dos_files = list(d.rglob("*.dos"))
        soc_dos_files = list(soc_dir.rglob("*.dos"))
        if scalar_dos_files and soc_dos_files:
            scalar_dos = parse_dos_output(scalar_dos_files[0])
            soc_dos = parse_dos_output(soc_dos_files[0])
            ef_scalar = scalar_dos.e_fermi_ev or 0
            ef_soc = soc_dos.e_fermi_ev or 0
            closest_scalar = min(scalar_dos.dos_data, key=lambda r: abs(r["energy_ev"] - ef_scalar), default=None)
            closest_soc = min(soc_dos.dos_data, key=lambda r: abs(r["energy_ev"] - ef_soc), default=None)
            if closest_scalar and closest_soc:
                dos_scalar = closest_scalar["dos"]
                dos_soc = closest_soc["dos"]
                result["dos_ef_scalar"] = round(dos_scalar, 4)
                result["dos_ef_soc"] = round(dos_soc, 4)
                if dos_scalar > 0.01:
                    result["dos_ef_change_pct"] = round(abs(dos_soc - dos_scalar) / dos_scalar * 100, 1)

        result["status"] = "compared"

        # Summary
        if result["dos_ef_change_pct"] is not None:
            pct = result["dos_ef_change_pct"]
            if pct < 5:
                result["summary"] = f"SOC effect on DOS@EF is negligible ({pct:.1f}% change)."
            elif pct < 20:
                result["summary"] = f"SOC causes moderate DOS@EF change ({pct:.1f}%). Include SOC for quantitative accuracy."
            else:
                result["summary"] = f"SOC causes large DOS@EF change ({pct:.1f}%). SOC is ESSENTIAL for this system."

        if result["fermi_shift_ev"] and abs(result["fermi_shift_ev"]) > 0.05:
            result["summary"] += f" EF shifts by {result['fermi_shift_ev']:.3f} eV with SOC."

    except Exception:
        result["status"] = "error"

    return result


def _find_scf(d: Path) -> Path | None:
    """Find scf.out in a directory."""
    candidates = list(d.rglob("scf.out"))
    return candidates[0] if candidates else None
