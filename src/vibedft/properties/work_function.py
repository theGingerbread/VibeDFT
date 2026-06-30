"""Work function analyzer — from pp.x planar average potential output."""

from __future__ import annotations

from pathlib import Path

from vibedft.properties.base import PropertyResult


def analyze_work_function(case_dir: Path) -> PropertyResult:
    """Extract work function from pp.x avg.dat or potential average files.

    Expected files:
      - avg.dat (planar average potential along z)
    """
    result = PropertyResult(property_name="work_function")

    # Find potential average files
    candidates = list(case_dir.rglob("avg.dat")) + list(case_dir.rglob("*avg*"))
    if not candidates:
        result.status = "missing"
        result.insights.append("No planar average potential file (avg.dat) found — run pp.x first.")
        return result

    for fp in candidates[:1]:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        z_vals: list[float] = []
        pot_vals: list[float] = []
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                try:
                    z_vals.append(float(parts[0]))
                    pot_vals.append(float(parts[1]))
                except ValueError:
                    continue

        if len(z_vals) < 10:
            continue

        # Vacuum level: average of potential in the flat vacuum region
        # Heuristic: use top 20% and bottom 20% of z-range as vacuum
        n = len(z_vals)
        vac_top = pot_vals[-n // 5:] if n > 5 else pot_vals[-2:]
        vac_bot = pot_vals[:n // 5] if n > 5 else pot_vals[:2]
        vacuum_level = (sum(vac_top) / len(vac_top) + sum(vac_bot) / len(vac_bot)) / 2.0

        # Fermi energy from SCF output (fallback: 0)
        ef = _get_fermi_energy(case_dir)

        wf = vacuum_level - ef

        # Vacuum flatness check
        vac_std_top = _std(vac_top)
        vac_std_bot = _std(vac_bot)
        vacuum_flat = vac_std_top < 0.1 and vac_std_bot < 0.1

        result.status = "ok"
        result.data = {
            "vacuum_level_ev": round(vacuum_level, 4),
            "fermi_energy_ev": round(ef, 4),
            "work_function_ev": round(wf, 4),
            "vacuum_flat": vacuum_flat,
            "n_points": len(z_vals),
        }
        result.source_files.append(str(fp))
        result.insights.append(
            f"Work function: Φ = {wf:.3f} eV (E_vac = {vacuum_level:.3f}, EF = {ef:.3f})."
        )
        if not vacuum_flat:
            result.insights.append(
                "Vacuum potential is not flat — dipole correction may be needed."
            )

    return result


def _get_fermi_energy(case_dir: Path) -> float:
    """Extract Fermi energy from SCF output in the case."""
    scf_files = list(case_dir.rglob("scf.out"))
    if scf_files:
        try:
            from vibedft.core.analysis import parse_qe_output
            qe = parse_qe_output(scf_files[0])
            return qe.fermi_energy_ev or 0.0
        except Exception:
            pass
    return 0.0


def _std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    return (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
