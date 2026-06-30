"""Batch-4 post-processing analyzers wrapping the dos.x / projwfc.x /
bands.x / dynmat.x / pp.x / average.x / pw.x-MD / spin-polarized parsers.

Each subclass wraps a single ``parse_*_output`` function from
``vibedft.core.analysis`` / ``vibedft.core.phonon`` and exposes the
unified ``Analyzer`` pipeline (ROADMAP §3.1).
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from vibedft.analyzers.base import (
    Analyzer,
    _match_files,
    register_analyzer,
)
from vibedft.analyzers.physics_models import (
    EvidenceLink,
    InsightLevel,
    PhysicsInsight,
)
from vibedft.core.analysis import (
    AverageOutput,
    BandsxOutput,
    DosxOutput,
    MagnetismOutput,
    MdOutput,
    PpOutput,
    ProjwfcOutput,
    parse_average_output,
    parse_bandsx_output,
    parse_dosx_output,
    parse_magnetism_output,
    parse_md_output,
    parse_pp_output,
    parse_projwfc_output,
)
from vibedft.core.phonon import DynmatOutput, parse_dynmat_output


# ═══════════════════════════════════════════════════════════════════════════════
# dos.x stdout
# ═══════════════════════════════════════════════════════════════════════════════


@register_analyzer
class DosAnalyzer(Analyzer):
    """Analyzer wrapping ``parse_dosx_output`` (dos.x broadening metadata)."""

    id = "dos"
    label = "DOS (dos.x broadening)"
    required_patterns = ["**/dos.out", "**/dos*.out"]
    optional_patterns: list[str] = []

    def __init__(self) -> None:
        self.case_dir: Path | None = None
        self.matched_files: list[Path] = []
        self.score: float = 0.0
        self._data: DosxOutput | None = None

    def discover(self, files: list[Path]) -> list[Path]:
        return _match_files(files, self.required_patterns)

    def parse(self) -> dict[str, Any]:
        if not self.matched_files:
            return {}
        self._data = parse_dosx_output(self.matched_files[0])
        if self._data is None:
            return {}
        return {
            "ngauss": self._data.ngauss,
            "degauss": self._data.degauss,
            "emin": self._data.emin,
            "emax": self._data.emax,
            "delta_e": self._data.delta_e,
            "job_done": self._data.job_done,
            "source_file": self._data.source_file,
        }

    def summarize(self) -> dict[str, Any]:
        if self._data is None:
            return {"status": "missing"}
        return {
            "status": "pass",
            "ngauss": self._data.ngauss,
            "degauss": self._data.degauss,
            "delta_e": self._data.delta_e,
            "job_done": self._data.job_done,
        }

    def insights(self) -> list[PhysicsInsight]:
        if self._data is None:
            self.score = 0.0
            return [
                PhysicsInsight(
                    id="dos.no_data", category="electronic",
                    level=InsightLevel.NEUTRAL,
                    message="No dos.x stdout found — DOS broadening metadata unavailable.",
                )
            ]
        ins: list[PhysicsInsight] = [
            PhysicsInsight(
                id="dos.metadata", category="electronic",
                level=InsightLevel.NEUTRAL,
                message=(
                    f"dos.x: ngauss={self._data.ngauss}, degauss={self._data.degauss:.6f} Ry, "
                    f"E ∈ [{self._data.emin:.4f}, {self._data.emax:.4f}] eV "
                    f"(ΔE={self._data.delta_e:.4f} eV)."
                ),
                evidence=[
                    EvidenceLink(key="degauss", value=self._data.degauss,
                                 parser="parse_dosx_output"),
                    EvidenceLink(key="delta_e", value=self._data.delta_e,
                                 parser="parse_dosx_output"),
                ],
            )
        ]
        if not self._data.job_done:
            ins.append(PhysicsInsight(
                id="dos.incomplete", category="workflow_health",
                level=InsightLevel.WARNING,
                message="dos.x output has no JOB DONE marker — run may be incomplete.",
            ))
            self.score = 5.0
        else:
            self.score = 7.0
        return ins

    def plots(self) -> list[dict[str, Any]]:
        return []

    def provenance(self) -> dict[str, Any]:
        return {
            "parser": "vibedft.core.analysis.parse_dosx_output",
            "source_files": [str(f) for f in self.matched_files],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# projwfc.x stdout
# ═══════════════════════════════════════════════════════════════════════════════


@register_analyzer
class ProjwfcAnalyzer(Analyzer):
    """Analyzer wrapping ``parse_projwfc_output`` (Lowdin charges + spilling)."""

    id = "projwfc"
    label = "PDOS (projwfc.x Lowdin + spilling)"
    required_patterns = ["**/pdos.out", "**/projwfc*.out"]
    optional_patterns: list[str] = []

    def __init__(self) -> None:
        self.case_dir: Path | None = None
        self.matched_files: list[Path] = []
        self.score: float = 0.0
        self._data: ProjwfcOutput | None = None

    def discover(self, files: list[Path]) -> list[Path]:
        return _match_files(files, self.required_patterns)

    def parse(self) -> dict[str, Any]:
        if not self.matched_files:
            return {}
        self._data = parse_projwfc_output(self.matched_files[0])
        if self._data is None:
            return {}
        return {
            "n_atoms": len(self._data.lowdin_charges),
            "spilling_parameter": self._data.spilling_parameter,
            "job_done": self._data.job_done,
            "source_file": self._data.source_file,
        }

    def summarize(self) -> dict[str, Any]:
        if self._data is None:
            return {"status": "missing"}
        return {
            "status": "pass",
            "n_atoms": len(self._data.lowdin_charges),
            "spilling_parameter": self._data.spilling_parameter,
            "job_done": self._data.job_done,
        }

    def insights(self) -> list[PhysicsInsight]:
        if self._data is None:
            self.score = 0.0
            return [
                PhysicsInsight(
                    id="projwfc.no_data", category="electronic",
                    level=InsightLevel.NEUTRAL,
                    message="No projwfc.x stdout found — Lowdin/spilling unavailable.",
                )
            ]
        ins: list[PhysicsInsight] = [
            PhysicsInsight(
                id="projwfc.lowdin", category="electronic",
                level=InsightLevel.NEUTRAL,
                message=(
                    f"projwfc.x: {len(self._data.lowdin_charges)} Lowdin atoms, "
                    f"spilling parameter = {self._data.spilling_parameter:.6f}."
                ),
                evidence=[
                    EvidenceLink(key="n_atoms", value=len(self._data.lowdin_charges),
                                 parser="parse_projwfc_output"),
                    EvidenceLink(key="spilling_parameter", value=self._data.spilling_parameter,
                                 parser="parse_projwfc_output"),
                ],
            )
        ]
        spilling = self._data.spilling_parameter
        if spilling > 0.1:
            ins.append(PhysicsInsight(
                id="projwfc.high_spilling", category="electronic",
                level=InsightLevel.WARNING,
                message=(
                    f"Spilling parameter {spilling:.4f} is high (> 0.1) — "
                    "the minimal truncated basis poorly represents the occupied subspace."
                ),
                evidence=[EvidenceLink(key="spilling_parameter", value=spilling,
                                      parser="parse_projwfc_output")],
            ))
            self.score = 4.5
        elif spilling > 0.02:
            ins.append(PhysicsInsight(
                id="projwfc.moderate_spilling", category="electronic",
                level=InsightLevel.WARNING,
                message=(
                    f"Spilling parameter {spilling:.4f} is moderate (> 0.02) — "
                    "consider increasingecutwfc to reduce basis truncation."
                ),
                evidence=[EvidenceLink(key="spilling_parameter", value=spilling,
                                      parser="parse_projwfc_output")],
            ))
            self.score = 6.0
        else:
            self.score = 7.0
        return ins

    def plots(self) -> list[dict[str, Any]]:
        return []

    def provenance(self) -> dict[str, Any]:
        return {
            "parser": "vibedft.core.analysis.parse_projwfc_output",
            "source_files": [str(f) for f in self.matched_files],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# bands.x stdout
# ═══════════════════════════════════════════════════════════════════════════════


@register_analyzer
class BandsxAnalyzer(Analyzer):
    """Analyzer wrapping ``parse_bandsx_output`` (bands.x minimal metadata)."""

    id = "bandsx"
    label = "Bands (bands.x stdout)"
    required_patterns = ["**/bandsx.out", "**/bands.x.out"]
    optional_patterns: list[str] = []

    def __init__(self) -> None:
        self.case_dir: Path | None = None
        self.matched_files: list[Path] = []
        self.score: float = 0.0
        self._data: BandsxOutput | None = None

    def discover(self, files: list[Path]) -> list[Path]:
        return _match_files(files, self.required_patterns)

    def parse(self) -> dict[str, Any]:
        if not self.matched_files:
            return {}
        self._data = parse_bandsx_output(self.matched_files[0])
        if self._data is None:
            return {}
        return {
            "n_bands": self._data.n_bands,
            "n_kpoints": self._data.n_kpoints,
            "job_done": self._data.job_done,
            "source_file": self._data.source_file,
        }

    def summarize(self) -> dict[str, Any]:
        if self._data is None:
            return {"status": "missing"}
        return {
            "status": "pass",
            "n_bands": self._data.n_bands,
            "n_kpoints": self._data.n_kpoints,
            "job_done": self._data.job_done,
        }

    def insights(self) -> list[PhysicsInsight]:
        if self._data is None:
            self.score = 0.0
            return [
                PhysicsInsight(
                    id="bandsx.no_data", category="electronic",
                    level=InsightLevel.NEUTRAL,
                    message="No bands.x stdout found — band-count metadata unavailable.",
                )
            ]
        nb = self._data.n_bands
        nk = self._data.n_kpoints
        ins: list[PhysicsInsight] = [
            PhysicsInsight(
                id="bandsx.count", category="electronic",
                level=InsightLevel.NEUTRAL,
                message=(
                    f"bands.x: {nb} bands × {nk} k-points "
                    f"(job_done={self._data.job_done})."
                ),
                evidence=[
                    EvidenceLink(key="n_bands", value=nb, parser="parse_bandsx_output"),
                    EvidenceLink(key="n_kpoints", value=nk, parser="parse_bandsx_output"),
                ],
            )
        ]
        if not self._data.job_done:
            ins.append(PhysicsInsight(
                id="bandsx.incomplete", category="workflow_health",
                level=InsightLevel.WARNING,
                message="bands.x output has no JOB DONE marker — run may be incomplete.",
            ))
            self.score = 5.0
        else:
            self.score = 7.0
        return ins

    def plots(self) -> list[dict[str, Any]]:
        return []

    def provenance(self) -> dict[str, Any]:
        return {
            "parser": "vibedft.core.analysis.parse_bandsx_output",
            "source_files": [str(f) for f in self.matched_files],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# dynmat.x output
# ═══════════════════════════════════════════════════════════════════════════════


@register_analyzer
class DynmatAnalyzer(Analyzer):
    """Analyzer wrapping ``parse_dynmat_output`` (Γ-mode freqs + IR)."""

    id = "dynmat"
    label = "Dynmat (Γ-mode frequencies)"
    required_patterns = ["**/dynmat*.out"]
    optional_patterns: list[str] = []

    def __init__(self) -> None:
        self.case_dir: Path | None = None
        self.matched_files: list[Path] = []
        self.score: float = 0.0
        self._data: DynmatOutput | None = None

    def discover(self, files: list[Path]) -> list[Path]:
        return _match_files(files, self.required_patterns)

    def parse(self) -> dict[str, Any]:
        if not self.matched_files:
            return {}
        self._data = parse_dynmat_output(self.matched_files[0])
        if self._data is None:
            return {}
        freqs = self._data.frequencies_cm1
        min_f = min(freqs) if freqs else 0.0
        max_f = max(freqs) if freqs else 0.0
        return {
            "q_point": list(self._data.q_point),
            "n_modes": self._data.n_modes,
            "has_imaginary": self._data.has_imaginary,
            "min_freq_cm1": min_f,
            "max_freq_cm1": max_f,
            "n_ir_activities": len(self._data.ir_activities),
            "source_file": self._data.source_file,
        }

    def summarize(self) -> dict[str, Any]:
        if self._data is None:
            return {"status": "missing"}
        return {
            "status": "pass",
            "n_modes": self._data.n_modes,
            "has_imaginary": self._data.has_imaginary,
            "q_point": list(self._data.q_point),
        }

    def insights(self) -> list[PhysicsInsight]:
        if self._data is None:
            self.score = 0.0
            return [
                PhysicsInsight(
                    id="dynmat.no_data", category="stability",
                    level=InsightLevel.NEUTRAL,
                    message="No dynmat.x output found — Γ-mode frequencies unavailable.",
                )
            ]
        freqs = self._data.frequencies_cm1
        min_f = min(freqs) if freqs else 0.0
        max_f = max(freqs) if freqs else 0.0
        ins: list[PhysicsInsight] = [
            PhysicsInsight(
                id="dynmat.gfreq", category="stability",
                level=InsightLevel.NEUTRAL,
                message=(
                    f"dynmat.x: {self._data.n_modes} Γ-point modes, "
                    f"freq range {min_f:.2f} – {max_f:.2f} cm⁻¹."
                ),
                evidence=[
                    EvidenceLink(key="n_modes", value=self._data.n_modes,
                                 parser="parse_dynmat_output"),
                    EvidenceLink(key="min_freq_cm1", value=min_f,
                                 parser="parse_dynmat_output"),
                ],
            )
        ]
        if self._data.has_imaginary:
            n_imag = sum(1 for f in freqs if f < 0)
            worst = min(f for f in freqs if f < 0)
            ins.append(PhysicsInsight(
                id="dynmat.imaginary", category="stability",
                level=InsightLevel.WARNING,
                message=(
                    f"{n_imag} imaginary Γ-point mode(s) (most negative {worst:.2f} cm⁻¹) "
                    "— structural instability or acoustic-sum-rule artifact."
                ),
                evidence=[EvidenceLink(key="has_imaginary", value=worst,
                                      parser="parse_dynmat_output")],
            ))
            self.score = 4.0
        else:
            self.score = 7.0
        return ins

    def plots(self) -> list[dict[str, Any]]:
        return []

    def provenance(self) -> dict[str, Any]:
        return {
            "parser": "vibedft.core.phonon.parse_dynmat_output",
            "source_files": [str(f) for f in self.matched_files],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# pp.x stdout
# ═══════════════════════════════════════════════════════════════════════════════


@register_analyzer
class PpAnalyzer(Analyzer):
    """Analyzer wrapping ``parse_pp_output`` (pp.x plot metadata + ELF flag)."""

    id = "pp"
    label = "Post-proc (pp.x plot metadata)"
    required_patterns = ["**/pp.out", "**/post-proc*.out"]
    optional_patterns: list[str] = []

    def __init__(self) -> None:
        self.case_dir: Path | None = None
        self.matched_files: list[Path] = []
        self.score: float = 0.0
        self._data: PpOutput | None = None

    def discover(self, files: list[Path]) -> list[Path]:
        return _match_files(files, self.required_patterns)

    def parse(self) -> dict[str, Any]:
        if not self.matched_files:
            return {}
        self._data = parse_pp_output(self.matched_files[0])
        if self._data is None:
            return {}
        return {
            "plot_num": self._data.plot_num,
            "filplot": self._data.filplot,
            "output_format": self._data.output_format,
            "iflag": self._data.iflag,
            "fileout": self._data.fileout,
            "integrated_charge": self._data.integrated_charge,
            "is_elf": self._data.is_elf,
            "job_done": self._data.job_done,
            "source_file": self._data.source_file,
        }

    def summarize(self) -> dict[str, Any]:
        if self._data is None:
            return {"status": "missing"}
        return {
            "status": "pass",
            "plot_num": self._data.plot_num,
            "is_elf": self._data.is_elf,
            "filplot": self._data.filplot,
            "job_done": self._data.job_done,
        }

    def insights(self) -> list[PhysicsInsight]:
        if self._data is None:
            self.score = 0.0
            return [
                PhysicsInsight(
                    id="pp.no_data", category="material",
                    level=InsightLevel.NEUTRAL,
                    message="No pp.x stdout found — plot metadata unavailable.",
                )
            ]
        ins: list[PhysicsInsight] = [
            PhysicsInsight(
                id="pp.plot_num", category="material",
                level=InsightLevel.NEUTRAL,
                message=(
                    f"pp.x: plot_num={self._data.plot_num}, filplot='{self._data.filplot}', "
                    f"is_elf={self._data.is_elf}."
                ),
                evidence=[
                    EvidenceLink(key="plot_num", value=self._data.plot_num,
                                 parser="parse_pp_output"),
                    EvidenceLink(key="is_elf", value=self._data.is_elf,
                                 parser="parse_pp_output"),
                ],
            )
        ]
        if self._data.is_elf:
            ins.append(PhysicsInsight(
                id="pp.elf", category="material",
                level=InsightLevel.NEUTRAL,
                message="plot_num=9 — Electron Localization Function (ELF) post-processing.",
                evidence=[EvidenceLink(key="is_elf", value=True,
                                       parser="parse_pp_output")],
            ))
        if not self._data.job_done:
            ins.append(PhysicsInsight(
                id="pp.incomplete", category="workflow_health",
                level=InsightLevel.WARNING,
                message="pp.x output has no JOB DONE marker — run may be incomplete.",
            ))
            self.score = 5.0
        else:
            self.score = 7.0
        return ins

    def plots(self) -> list[dict[str, Any]]:
        return []

    def provenance(self) -> dict[str, Any]:
        return {
            "parser": "vibedft.core.analysis.parse_pp_output",
            "source_files": [str(f) for f in self.matched_files],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# average.x stdout
# ═══════════════════════════════════════════════════════════════════════════════


@register_analyzer
class AverageAnalyzer(Analyzer):
    """Analyzer wrapping ``parse_average_output`` (planar-average table)."""

    id = "average"
    label = "Planar average (average.x)"
    required_patterns = ["**/avg.out", "**/average*.out"]
    optional_patterns: list[str] = []

    def __init__(self) -> None:
        self.case_dir: Path | None = None
        self.matched_files: list[Path] = []
        self.score: float = 0.0
        self._data: AverageOutput | None = None

    def discover(self, files: list[Path]) -> list[Path]:
        return _match_files(files, self.required_patterns)

    def parse(self) -> dict[str, Any]:
        if not self.matched_files:
            return {}
        self._data = parse_average_output(self.matched_files[0])
        if self._data is None:
            return {}
        z = self._data.z_values
        a = self._data.averages
        return {
            "n_points": self._data.n_points,
            "z_min": z[0] if z else 0.0,
            "z_max": z[-1] if z else 0.0,
            "avg_min": min(a) if a else 0.0,
            "avg_max": max(a) if a else 0.0,
            "job_done": self._data.job_done,
            "source_file": self._data.source_file,
        }

    def summarize(self) -> dict[str, Any]:
        if self._data is None:
            return {"status": "missing"}
        z = self._data.z_values
        a = self._data.averages
        return {
            "status": "pass",
            "n_points": self._data.n_points,
            "z_range": [z[0], z[-1]] if z else [],
            "avg_range": [min(a), max(a)] if a else [],
            "job_done": self._data.job_done,
        }

    def insights(self) -> list[PhysicsInsight]:
        if self._data is None or not self._data.z_values:
            self.score = 0.0
            return [
                PhysicsInsight(
                    id="average.no_data", category="material",
                    level=InsightLevel.NEUTRAL,
                    message="No average.x stdout found — planar average unavailable.",
                )
            ]
        z = self._data.z_values
        a = self._data.averages
        ins: list[PhysicsInsight] = [
            PhysicsInsight(
                id="average.range", category="material",
                level=InsightLevel.NEUTRAL,
                message=(
                    f"average.x: {self._data.n_points} points, "
                    f"z ∈ [{z[0]:.4f}, {z[-1]:.4f}], "
                    f"avg ∈ [{min(a):.6f}, {max(a):.6f}]."
                ),
                evidence=[
                    EvidenceLink(key="n_points", value=self._data.n_points,
                                 parser="parse_average_output"),
                    EvidenceLink(key="z_range", value=[z[0], z[-1]],
                                 parser="parse_average_output"),
                ],
            )
        ]
        if not self._data.job_done:
            ins.append(PhysicsInsight(
                id="average.incomplete", category="workflow_health",
                level=InsightLevel.WARNING,
                message="average.x output has no JOB DONE marker — run may be incomplete.",
            ))
            self.score = 5.0
        else:
            self.score = 7.0
        return ins

    def plots(self) -> list[dict[str, Any]]:
        return []

    def provenance(self) -> dict[str, Any]:
        return {
            "parser": "vibedft.core.analysis.parse_average_output",
            "source_files": [str(f) for f in self.matched_files],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# pw.x MD output
# ═══════════════════════════════════════════════════════════════════════════════


@register_analyzer
class AimdAnalyzer(Analyzer):
    """Analyzer wrapping ``parse_md_output`` (pw.x MD trajectory metadata)."""

    id = "aimd"
    label = "AIMD (pw.x md trajectory)"
    required_patterns = ["**/md.out", "**/md*.out"]
    optional_patterns: list[str] = []

    def __init__(self) -> None:
        self.case_dir: Path | None = None
        self.matched_files: list[Path] = []
        self.score: float = 0.0
        self._data: MdOutput | None = None

    def discover(self, files: list[Path]) -> list[Path]:
        return _match_files(files, self.required_patterns)

    def parse(self) -> dict[str, Any]:
        if not self.matched_files:
            return {}
        self._data = parse_md_output(self.matched_files[0])
        if self._data is None:
            return {}
        temps = self._data.temperatures
        return {
            "n_steps": self._data.n_steps,
            "n_temperatures": len(temps),
            "last_temperature": temps[-1] if temps else None,
            "n_energies": len(self._data.energies),
            "last_energy_ry": self._data.energies[-1] if self._data.energies else None,
            "job_done": self._data.job_done,
        }

    def summarize(self) -> dict[str, Any]:
        if self._data is None:
            return {"status": "missing"}
        return {
            "status": "pass",
            "n_steps": self._data.n_steps,
            "n_temperatures": len(self._data.temperatures),
            "job_done": self._data.job_done,
        }

    def insights(self) -> list[PhysicsInsight]:
        if self._data is None:
            self.score = 0.0
            return [
                PhysicsInsight(
                    id="aimd.no_data", category="stability",
                    level=InsightLevel.NEUTRAL,
                    message="No pw.x MD output found — AIMD trajectory unavailable.",
                )
            ]
        temps = self._data.temperatures
        if temps:
            temp_msg = (
                f"AIMD: {self._data.n_steps} steps, "
                f"{len(self._data.energies)} energy samples, "
                f"{len(temps)} temperature samples (last={temps[-1]:.2f} K)."
            )
        else:
            temp_msg = (
                f"AIMD: {self._data.n_steps} steps, "
                f"{len(self._data.energies)} energy samples, no temperature data."
            )
        ins: list[PhysicsInsight] = [
            PhysicsInsight(
                id="aimd.steps", category="stability",
                level=InsightLevel.NEUTRAL,
                message=temp_msg,
                evidence=[
                    EvidenceLink(key="n_steps", value=self._data.n_steps,
                                 parser="parse_md_output"),
                    EvidenceLink(key="last_temperature", value=temps[-1] if temps else None,
                                 parser="parse_md_output"),
                ],
            )
        ]
        score = 7.0
        if len(temps) >= 2:
            spread = max(temps) - min(temps)
            mean_t = statistics.fmean(temps)
            ins.append(PhysicsInsight(
                id="aimd.temp_stability", category="stability",
                level=InsightLevel.WARNING if spread > max(50.0, 0.2 * mean_t) else InsightLevel.NEUTRAL,
                message=(
                    f"Temperature span {spread:.1f} K around mean {mean_t:.1f} K "
                    f"({len(temps)} samples)."
                ),
                evidence=[EvidenceLink(key="temperature_span", value=spread,
                                       parser="parse_md_output")],
            ))
            if spread > max(50.0, 0.2 * mean_t):
                score = 5.0
        if not self._data.job_done:
            ins.append(PhysicsInsight(
                id="aimd.incomplete", category="workflow_health",
                level=InsightLevel.WARNING,
                message="MD output has no JOB DONE marker — trajectory may be truncated.",
            ))
            score = min(score, 5.0)
        self.score = score
        return ins

    def plots(self) -> list[dict[str, Any]]:
        return []

    def provenance(self) -> dict[str, Any]:
        return {
            "parser": "vibedft.core.analysis.parse_md_output",
            "source_files": [str(f) for f in self.matched_files],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# pw.x spin-polarized output  (magnetism)
# ═══════════════════════════════════════════════════════════════════════════════


@register_analyzer
class MagnetismAnalyzer(Analyzer):
    """Analyzer wrapping ``parse_magnetism_output`` (nspin=2 magnetization)."""

    id = "magnetism"
    label = "Magnetism (spin-polarized pw.x)"
    required_patterns = ["**/*sp.out", "**/magnetism*.out"]
    optional_patterns: list[str] = []

    def __init__(self) -> None:
        self.case_dir: Path | None = None
        self.matched_files: list[Path] = []
        self.score: float = 0.0
        self._data: MagnetismOutput | None = None

    def discover(self, files: list[Path]) -> list[Path]:
        return _match_files(files, self.required_patterns)

    def parse(self) -> dict[str, Any]:
        if not self.matched_files:
            return {}
        self._data = parse_magnetism_output(self.matched_files[0])
        if self._data is None:
            return {}
        return {
            "total_magnetization": self._data.total_magnetization,
            "absolute_magnetization": self._data.absolute_magnetization,
            "total_energy_ry": self._data.total_energy_ry,
            "nspin": self._data.nspin,
            "job_done": self._data.job_done,
            "source_file": self._data.source_file,
        }

    def summarize(self) -> dict[str, Any]:
        if self._data is None:
            return {"status": "missing"}
        return {
            "status": "pass",
            "total_magnetization": self._data.total_magnetization,
            "absolute_magnetization": self._data.absolute_magnetization,
            "nspin": self._data.nspin,
            "job_done": self._data.job_done,
        }

    def insights(self) -> list[PhysicsInsight]:
        if self._data is None:
            self.score = 0.0
            return [
                PhysicsInsight(
                    id="mag.no_data", category="electronic",
                    level=InsightLevel.NEUTRAL,
                    message="No spin-polarized pw.x output found — magnetization unavailable.",
                )
            ]
        tm = self._data.total_magnetization
        am = self._data.absolute_magnetization
        ins: list[PhysicsInsight] = [
            PhysicsInsight(
                id="mag.values", category="electronic",
                level=InsightLevel.NEUTRAL,
                message=(
                    f"Magnetization: total={tm:.6f}, absolute={am:.6f} Bohr mag/cell "
                    f"(nspin={self._data.nspin})."
                ),
                evidence=[
                    EvidenceLink(key="total_magnetization", value=tm,
                                 parser="parse_magnetism_output"),
                    EvidenceLink(key="absolute_magnetization", value=am,
                                 parser="parse_magnetism_output"),
                ],
            )
        ]
        if abs(tm) < 1e-3 and am < 1e-3:
            ins.append(PhysicsInsight(
                id="mag.nonmagnetic", category="electronic",
                level=InsightLevel.NEUTRAL,
                message="Near-zero magnetization — system is non-magnetic.",
                evidence=[EvidenceLink(key="total_magnetization", value=tm,
                                      parser="parse_magnetism_output")],
            ))
            self.score = 7.0
        elif abs(tm) > 0.1:
            ins.append(PhysicsInsight(
                id="mag.magnetic", category="electronic",
                level=InsightLevel.NEUTRAL,
                message=f"Finite total magnetization ({tm:.4f} Bohr mag/cell) — magnetic state.",
                evidence=[EvidenceLink(key="total_magnetization", value=tm,
                                      parser="parse_magnetism_output")],
            ))
            self.score = 7.0
        if not self._data.job_done:
            ins.append(PhysicsInsight(
                id="mag.incomplete", category="workflow_health",
                level=InsightLevel.WARNING,
                message="Spin-polarized output has no JOB DONE marker — SCF may be incomplete.",
            ))
            self.score = min(self.score, 5.0)
        return ins

    def plots(self) -> list[dict[str, Any]]:
        return []

    def provenance(self) -> dict[str, Any]:
        return {
            "parser": "vibedft.core.analysis.parse_magnetism_output",
            "source_files": [str(f) for f in self.matched_files],
        }