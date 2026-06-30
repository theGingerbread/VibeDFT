"""Extract key physical metrics from each case for convergence tracking."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibedft.convergence.scanner import CaseSnapshot


def extract_metrics(snapshot: CaseSnapshot) -> dict[str, Any]:
    """Extract λ, Tc, ωlog, DOS@EF, min phonon freq from a case.

    Returns a dict; missing values are None.
    """
    d = Path(snapshot.path)
    metrics: dict[str, Any] = {
        "lambda_max": None, "tc_max_K": None, "omega_log_K": None,
        "dos_at_ef": None, "fermi_energy_ev": None,
        "min_phonon_freq_cm1": None, "max_phonon_freq_cm1": None,
        "n_imaginary_modes": None, "n_imaginary_non_gamma": None,
        "scf_converged": None,
    }

    # ── λ / Tc from lambdax.out ──
    lambdax_files = list(d.rglob("lambdax.out"))
    if lambdax_files:
        try:
            from vibedft.core.tc import parse_lambdax_output
            all_lambda: list[float] = []
            all_tc: list[float] = []
            all_omega: list[float] = []
            for lf in lambdax_files:
                lam = parse_lambdax_output(lf)
                if lam.has_data:
                    all_lambda.extend(v for v in lam.lambda_values if v > 0)
                    all_tc.extend(v for v in lam.tc_values if v > 0)
                    all_omega.extend(v for v in lam.omega_log_values if v > 0)
            if all_lambda:
                metrics["lambda_max"] = max(all_lambda)
            if all_tc:
                metrics["tc_max_K"] = max(all_tc)
            if all_omega:
                metrics["omega_log_K"] = max(all_omega)
        except Exception:
            pass

    # ── DOS@EF from .dos files ──
    dos_files = list(d.rglob("*.dos"))
    if dos_files:
        try:
            from vibedft.core.analysis import parse_dos_output
            dos = parse_dos_output(dos_files[0])
            if dos.e_fermi_ev is not None:
                metrics["fermi_energy_ev"] = dos.e_fermi_ev
            if dos.dos_data:
                ef = dos.e_fermi_ev or 0.0
                closest = min(dos.dos_data, key=lambda r: abs(r["energy_ev"] - ef))
                metrics["dos_at_ef"] = closest["dos"]
        except Exception:
            pass

    # ── Phonon from freq.gp ──
    freq_files = list(d.rglob("*.freq.gp"))
    if freq_files:
        try:
            from vibedft.core.phonon import parse_freq_gp
            disp = parse_freq_gp(freq_files[0])
            if disp.has_data:
                metrics["min_phonon_freq_cm1"] = disp.min_frequency_cm1
                metrics["max_phonon_freq_cm1"] = disp.max_frequency_cm1
                metrics["n_imaginary_modes"] = disp.n_imaginary
                metrics["n_imaginary_non_gamma"] = disp.n_imaginary_non_gamma
        except Exception:
            pass

    # ── SCF convergence from scf.out ──
    scf_files = list(d.rglob("scf.out"))
    if scf_files:
        try:
            from vibedft.core.analysis import parse_qe_output
            qe = parse_qe_output(scf_files[0])
            metrics["scf_converged"] = qe.scf_converged
            if metrics["fermi_energy_ev"] is None:
                metrics["fermi_energy_ev"] = qe.fermi_energy_ev
        except Exception:
            pass

    return metrics
