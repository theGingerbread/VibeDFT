"""Parse Quantum ESPRESSO PWscf SCF stdout."""

from __future__ import annotations

import math
from statistics import median
import re
from dataclasses import dataclass, field
from pathlib import Path

from vibedft.calculator.qe.common import QEOutputEvent, parse_qe_output_events


RY_TO_EV = 13.605703976


@dataclass(frozen=True)
class SCFState:
    """Canonical per-iteration state used by the observability state machine."""

    iteration: int
    energy: float | None
    energy_diff: float | None
    scf_error: float | None
    mixing_beta: float | None
    fermi_energy: float | None
    eigen_warning: bool
    is_converged_step: bool
    warnings: list[str]

    def to_schema(self) -> dict[str, object]:
        """Return the canonical state payload."""

        return {
            "iteration": self.iteration,
            "energy": self.energy,
            "energy_diff": self.energy_diff,
            "scf_error": self.scf_error,
            "mixing_beta": self.mixing_beta,
            "fermi_energy": self.fermi_energy,
            "eigen_warning": self.eigen_warning,
            "is_converged_step": self.is_converged_step,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ScfIteration:
    """Backward-compatible per-iteration SCF step with machine-compatible aliases."""

    number: int
    total_energy_ry: float | None = None
    scf_accuracy_ry: float | None = None
    energy_difference_ry: float | None = field(default=None, compare=False)
    mixing_beta: float | None = field(default=None, compare=False)
    fermi_energy: float | None = field(default=None, compare=False)
    eigenvalue_warning: bool = field(default=False, compare=False)
    warnings: list[str] = field(default_factory=list, compare=False)
    converged: bool = field(default=False, compare=False)

    @property
    def iteration(self) -> int:
        return self.number

    @property
    def energy(self) -> float | None:
        return self.total_energy_ry

    @property
    def energy_diff(self) -> float | None:
        return self.energy_difference_ry

    @property
    def scf_error(self) -> float | None:
        return self.scf_accuracy_ry

    @property
    def is_converged_step(self) -> bool:
        return self.converged

    @property
    def total_energy_ev(self) -> float | None:
        """Total energy converted to eV when the Ry value is available."""

        return _ry_to_ev(self.total_energy_ry)

    @property
    def energy_difference_ev(self) -> float | None:
        """SCF energy change converted to eV when the Ry value is available."""

        return _ry_to_ev(self.energy_difference_ry)

    def to_schema(self) -> dict[str, object]:
        """Return the legacy JSON-like trajectory entry for this iteration."""

        return {
            "iteration": self.number,
            "total_energy_ry": self.total_energy_ry,
            "total_energy_ev": self.total_energy_ev,
            "energy_difference_ry": self.energy_difference_ry,
            "energy_difference_ev": self.energy_difference_ev,
            "scf_accuracy_ry": self.scf_accuracy_ry,
            "mixing_beta": self.mixing_beta,
            "eigenvalue_warning": self.eigenvalue_warning,
            "warnings": list(self.warnings),
            "converged": self.converged,
        }

    def to_state_schema(self) -> dict[str, object]:
        """Return the canonical state view of this iteration."""

        return {
            "iteration": self.number,
            "energy": self.total_energy_ry,
            "energy_diff": self.energy_difference_ry,
            "scf_error": self.scf_accuracy_ry,
            "mixing_beta": self.mixing_beta,
            "fermi_energy": self.fermi_energy,
            "eigen_warning": self.eigenvalue_warning,
            "is_converged_step": self.converged,
            "warnings": list(self.warnings),
        }

    def to_state(self) -> SCFState:
        """Convert to the canonical SCFState model."""

        return SCFState(
            iteration=self.number,
            energy=self.total_energy_ry,
            energy_diff=self.energy_difference_ry,
            scf_error=self.scf_accuracy_ry,
            mixing_beta=self.mixing_beta,
            fermi_energy=self.fermi_energy,
            eigen_warning=self.eigenvalue_warning,
            is_converged_step=self.converged,
            warnings=list(self.warnings),
        )


@dataclass(frozen=True)
class ConvergenceDynamics:
    """Derived SCF convergence behaviour."""

    convergence_rate: float | None
    energy_decay_type: str
    estimated_asymptotic_error: float | None
    convergence_half_life: int | None

    def to_schema(self) -> dict[str, object]:
        return {
            "convergence_rate": self.convergence_rate,
            "energy_decay_type": self.energy_decay_type,
            "estimated_asymptotic_error": self.estimated_asymptotic_error,
            "convergence_half_life": self.convergence_half_life,
        }


@dataclass(frozen=True)
class WorkflowReadiness:
    """Downstream workflow eligibility derived from SCF quality signals."""

    dos: bool
    bands: bool
    phonon: bool
    dielectric: bool
    reason: str

    def to_schema(self) -> dict[str, object]:
        return {
            "dos": self.dos,
            "bands": self.bands,
            "phonon": self.phonon,
            "dielectric": self.dielectric,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class NumericalStabilityReport:
    """Conservative stability assessment for parsed SCF output."""

    severity: str
    suitable_for_followup: bool
    likely_root_cause: str | None = None
    impact_on_observables: str | None = None
    symptoms: list[str] = field(default_factory=list, compare=False)
    likely_causes: list[str] = field(default_factory=list, compare=False)
    causal_chain: list[str] = field(default_factory=list, compare=False)
    recommendations: list[str] = field(default_factory=list, compare=False)

    def to_schema(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "likely_root_cause": self.likely_root_cause,
            "impact_on_observables": self.impact_on_observables,
            "suitable_for_followup": self.suitable_for_followup,
            "symptoms": list(self.symptoms),
            "likely_causes": list(self.likely_causes),
            "causal_chain": list(self.causal_chain),
            "recommendations": list(self.recommendations),
        }


@dataclass(frozen=True)
class ScfOutput:
    """Structured SCF stdout summary."""

    program: str | None
    version: str | None
    iterations: list[ScfIteration]
    final_total_energy_ry: float | None
    final_scf_accuracy_ry: float | None
    fermi_energy_ev: float | None
    converged: bool
    convergence_iterations: int | None
    job_done: bool
    cpu_seconds: float | None
    wall_seconds: float | None
    issues: list[QEOutputEvent]
    source: str
    number_of_electrons: float | None = None
    number_of_bands: int | None = None
    ecutwfc_ry: float | None = None
    ecutrho_ry: float | None = None
    k_point_count: int | None = None
    k_point_mesh: list[int] | None = None
    fft_grids: dict[str, list[int]] = field(default_factory=dict)
    input_parameters: dict[str, dict[str, object]] = field(default_factory=dict)
    convergence_threshold_ry: float | None = None
    diagnostics: dict[str, object] = field(default_factory=dict)
    stability_assessment: NumericalStabilityReport | None = None
    convergence_dynamics: ConvergenceDynamics | None = None
    workflow_readiness: WorkflowReadiness | None = None

    @property
    def final_total_energy_ev(self) -> float | None:
        """Final total energy converted to eV when available."""

        return _ry_to_ev(self.final_total_energy_ry)

    @property
    def suitable_for_followup(self) -> bool:
        """True only for clean, converged, completed SCF outputs."""

        if self.stability_assessment is None:
            return False
        return self.stability_assessment.suitable_for_followup

    def to_schema(self) -> dict[str, object]:
        """Return the required seven-layer SCF schema."""

        stability = self.stability_assessment or _assess_stability(
            iterations=self.iterations,
            converged=self.converged,
            job_done=self.job_done,
            issues=self.issues,
            diagnostics=self.diagnostics,
        )
        suitable_for_followup = stability.suitable_for_followup
        dynamics = self.convergence_dynamics
        readiness = self.workflow_readiness
        numerical_setup = {
            "ecutwfc_ry": self.ecutwfc_ry,
            "ecutwfc_ev": _ry_to_ev(self.ecutwfc_ry),
            "ecutrho_ry": self.ecutrho_ry,
            "ecutrho_ev": _ry_to_ev(self.ecutrho_ry),
            "k_points": {
                "count": self.k_point_count,
                "mesh": list(self.k_point_mesh) if self.k_point_mesh is not None else None,
            },
            "fft_grids": {key: list(value) for key, value in self.fft_grids.items()},
            "basis": {
                "number_of_bands": self.number_of_bands,
            },
        }

        return {
            "system": {
                "program": self.program,
                "version": self.version,
                "source": self.source,
                "number_of_electrons": self.number_of_electrons,
                "number_of_bands": self.number_of_bands,
            },
            "input_parameters": _schema_input_parameters(self.input_parameters),
            "numerical_setup": numerical_setup,
            "scf_trajectory": [iteration.to_schema() for iteration in self.iterations],
            "convergence": {
                "converged": self.converged,
                "iterations": self.convergence_iterations,
                "threshold_ry": self.convergence_threshold_ry,
                "final_scf_accuracy_ry": self.final_scf_accuracy_ry,
                "job_done": self.job_done,
                "state_sequence": [iteration.to_state_schema() for iteration in self.iterations],
                "dynamics": dynamics.to_schema() if dynamics is not None else None,
                "workflow_readiness": readiness.to_schema() if readiness is not None else None,
                "suitable_for_followup": suitable_for_followup,
            },
            "final_observables": {
                "total_energy_ry": self.final_total_energy_ry,
                "total_energy_ev": self.final_total_energy_ev,
                "fermi_energy_ev": self.fermi_energy_ev,
                "number_of_electrons": self.number_of_electrons,
                "number_of_bands": self.number_of_bands,
            },
            "diagnostics": _schema_diagnostics(self.diagnostics, self.issues),
            "stability_assessment": stability.to_schema(),
        }


_FLOAT_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_PROGRAM_RE = re.compile(
    r"\bProgram\s+([A-Za-z0-9_.-]+)(?:\s+v\.?\s*([A-Za-z0-9_.-]+))?",
    re.IGNORECASE,
)
_ITERATION_RE = re.compile(r"\biteration\s*#\s*(\d+)", re.IGNORECASE)
_TOTAL_ENERGY_RE = re.compile(
    rf"!?\s*\btotal\s+energy\s*=\s*({_FLOAT_RE})\s*Ry\b",
    re.IGNORECASE,
)
_ACCURACY_RE = re.compile(
    rf"\bestimated\s+scf\s+accuracy\s*<\s*({_FLOAT_RE})\s*Ry\b",
    re.IGNORECASE,
)
_MIXING_BETA_RE = re.compile(rf"\bbeta\s*=\s*({_FLOAT_RE})\b", re.IGNORECASE)
_INPUT_KEY_VALUE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*,?\s*$")
_FERMI_RE = re.compile(rf"\bFermi\s+energy\s+is\s+({_FLOAT_RE})\s*eV\b", re.IGNORECASE)
_ELECTRONS_RE = re.compile(
    rf"\bnumber\s+of\s+electrons\s*=\s*({_FLOAT_RE})\b",
    re.IGNORECASE,
)
_BANDS_RE = re.compile(
    r"\bnumber\s+of\s+Kohn-Sham\s+states\s*=\s*(\d+)\b",
    re.IGNORECASE,
)
_ECUTWFC_RE = re.compile(
    rf"\bkinetic-energy\s+cutoff\s*=\s*({_FLOAT_RE})\s*Ry\b",
    re.IGNORECASE,
)
_ECUTRHO_RE = re.compile(
    rf"\bcharge\s+density\s+cutoff\s*=\s*({_FLOAT_RE})\s*Ry\b",
    re.IGNORECASE,
)
_K_POINTS_COUNT_RE = re.compile(r"\bnumber\s+of\s+k\s+points\s*=\s*(\d+)\b", re.IGNORECASE)
_K_POINTS_AUTOMATIC_RE = re.compile(r"^\s*K_POINTS\s+automatic\b", re.IGNORECASE)
_INTEGER_LINE_RE = re.compile(r"^\s*([+-]?\d+)(?:\s+([+-]?\d+)){2,5}\s*$")
_FFT_GRID_RE = re.compile(
    r"\b(Dense|Smooth)\s+grid:.*?\bFFT\s+dimensions:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)",
    re.IGNORECASE,
)
_EIGENVALUE_WARNING_RE = re.compile(
    r"\bc_bands\b.*\beigenvalues?\s+not\s+converged\b|\beigenvalues?\s+not\s+converged\b",
    re.IGNORECASE,
)
_MIXING_INSTABILITY_RE = re.compile(
    r"\bmixing\b.*\b(?:failed|unstable|reduced|too\s+large|diverg)",
    re.IGNORECASE,
)
_FFT_OR_CUTOFF_ISSUE_RE = re.compile(
    r"\b(?:fft|cutoff|ecutwfc|ecutrho|g-vector|g-vectors)\b.*\b(?:warning|too\s+small|insufficient|error)\b",
    re.IGNORECASE,
)
_CONVERGENCE_RE = re.compile(
    r"\bconvergence\s+has\s+been\s+achieved(?:\s+in\s+(\d+)\s+iterations?)?",
    re.IGNORECASE,
)
_JOB_DONE_RE = re.compile(r"\bJOB\s+DONE\b", re.IGNORECASE)
_TIMING_RE = re.compile(
    rf"\bPWSCF\b.*?:\s*({_FLOAT_RE})s\s+CPU\s+({_FLOAT_RE})s\s+WALL\b",
    re.IGNORECASE,
)
_FATAL_ISSUE_CATEGORIES = {
    "error",
    "file_not_found",
    "mpi_abort",
    "out_of_memory",
    "segmentation_fault",
    "time_limit",
    "traceback",
}


def parse_scf_output(text_or_path: str | Path, *, source: str | Path | None = None) -> ScfOutput:
    """Parse SCF output text or a path into a structured PWscf summary."""

    text, source_label = _load_text_and_source(text_or_path, source)
    scan = parse_qe_output_events(text, source=source_label)

    program: str | None = None
    version: str | None = None
    iterations: list[ScfIteration] = []
    current_iteration: ScfIteration | None = None
    final_total_energy_ry: float | None = None
    final_scf_accuracy_ry: float | None = None
    fermi_energy_ev: float | None = None
    number_of_electrons: float | None = None
    number_of_bands: int | None = None
    ecutwfc_ry: float | None = None
    ecutrho_ry: float | None = None
    k_point_count: int | None = None
    k_point_mesh: list[int] | None = None
    fft_grids: dict[str, list[int]] = {}
    input_parameters: dict[str, dict[str, object]] = {
        "control": {},
        "system": {},
        "electrons": {},
    }
    current_namelist: str | None = None
    expect_k_points_mesh = False
    converged = False
    convergence_iterations: int | None = None
    job_done = False
    cpu_seconds: float | None = None
    wall_seconds: float | None = None
    eigenvalue_warnings: list[str] = []
    mixing_instability_signals: list[str] = []
    fft_or_cutoff_issues: list[str] = []
    current_fermi_energy: float | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        namelist_match = re.match(r"^&([A-Za-z]+)\b", line)
        if namelist_match:
            candidate = namelist_match.group(1).lower()
            current_namelist = candidate if candidate in input_parameters else None
            continue
        if line == "/":
            current_namelist = None
            continue
        if current_namelist is not None:
            key_value = _INPUT_KEY_VALUE_RE.match(line)
            if key_value:
                key = key_value.group(1).lower()
                value = _parse_input_value(key_value.group(2))
                input_parameters[current_namelist][key] = value
                if key == "ecutwfc" and isinstance(value, (int, float)):
                    ecutwfc_ry = float(value)
                elif key == "ecutrho" and isinstance(value, (int, float)):
                    ecutrho_ry = float(value)
                elif key == "nbnd" and isinstance(value, (int, float)):
                    number_of_bands = int(value)
                elif key == "conv_thr" and isinstance(value, (int, float)):
                    pass
            continue

        if program is None:
            program_match = _PROGRAM_RE.search(line)
            if program_match:
                program = program_match.group(1)
                version = program_match.group(2)

        if expect_k_points_mesh:
            k_mesh = _parse_k_points_mesh(line)
            if k_mesh is not None:
                k_point_mesh = k_mesh
                expect_k_points_mesh = False
            elif not line.upper().startswith("K_POINTS"):
                expect_k_points_mesh = False

        if _K_POINTS_AUTOMATIC_RE.search(line):
            expect_k_points_mesh = True

        iteration_match = _ITERATION_RE.search(line)
        if iteration_match:
            current_iteration = _rebind_iteration(
                ScfIteration(
                    number=int(iteration_match.group(1)),
                    mixing_beta=_parse_optional_float(_MIXING_BETA_RE.search(line)),
                ),
                fermi_energy=current_fermi_energy,
            )
            iterations.append(current_iteration)

        energy_match = _TOTAL_ENERGY_RE.search(line)
        if energy_match:
            energy_ry = _parse_float(energy_match.group(1))
            final_total_energy_ry = energy_ry
            if current_iteration is not None:
                previous_energy_ry = _previous_iteration_energy(iterations)
                current_iteration = _rebind_iteration(
                    current_iteration,
                    total_energy_ry=energy_ry,
                    energy_difference_ry=_energy_difference(energy_ry, previous_energy_ry),
                )
                iterations[-1] = current_iteration

        accuracy_match = _ACCURACY_RE.search(line)
        if accuracy_match:
            accuracy_ry = _parse_float(accuracy_match.group(1))
            final_scf_accuracy_ry = accuracy_ry
            if current_iteration is not None:
                current_iteration = _rebind_iteration(
                    current_iteration,
                    scf_accuracy_ry=accuracy_ry,
                )
                iterations[-1] = current_iteration

        electrons_match = _ELECTRONS_RE.search(line)
        if electrons_match:
            number_of_electrons = _parse_float(electrons_match.group(1))

        bands_match = _BANDS_RE.search(line)
        if bands_match:
            number_of_bands = int(bands_match.group(1))

        ecutwfc_match = _ECUTWFC_RE.search(line)
        if ecutwfc_match:
            ecutwfc_ry = _parse_float(ecutwfc_match.group(1))

        ecutrho_match = _ECUTRHO_RE.search(line)
        if ecutrho_match:
            ecutrho_ry = _parse_float(ecutrho_match.group(1))

        k_points_count_match = _K_POINTS_COUNT_RE.search(line)
        if k_points_count_match:
            k_point_count = int(k_points_count_match.group(1))

        fft_grid_match = _FFT_GRID_RE.search(line)
        if fft_grid_match:
            fft_grids[fft_grid_match.group(1).lower()] = [
                int(fft_grid_match.group(2)),
                int(fft_grid_match.group(3)),
                int(fft_grid_match.group(4)),
            ]

        if _EIGENVALUE_WARNING_RE.search(line):
            eigenvalue_warnings.append(line)
            if current_iteration is not None:
                current_iteration = _rebind_iteration(
                    current_iteration,
                    eigenvalue_warning=True,
                    warnings=[*current_iteration.warnings, line],
                )
                iterations[-1] = current_iteration

        if _MIXING_INSTABILITY_RE.search(line):
            mixing_instability_signals.append(line)

        if _FFT_OR_CUTOFF_ISSUE_RE.search(line):
            fft_or_cutoff_issues.append(line)

        fermi_match = _FERMI_RE.search(line)
        if fermi_match:
            fermi_energy_ev = _parse_float(fermi_match.group(1))
            current_fermi_energy = fermi_energy_ev
            if current_iteration is not None:
                current_iteration = _rebind_iteration(current_iteration, fermi_energy=fermi_energy_ev)
                iterations[-1] = current_iteration

        convergence_match = _CONVERGENCE_RE.search(line)
        if convergence_match:
            converged = True
            if convergence_match.group(1) is not None:
                convergence_iterations = int(convergence_match.group(1))
            if iterations:
                converged_index = _find_iteration_index(
                    iterations,
                    convergence_iterations if convergence_iterations is not None else iterations[-1].number,
                )
                if converged_index is not None:
                    converged_step = _rebind_iteration(
                        iterations[converged_index],
                        converged=True,
                    )
                    iterations[converged_index] = converged_step
                    if current_iteration is not None and current_iteration.number == converged_step.number:
                        current_iteration = converged_step

        if _JOB_DONE_RE.search(line):
            job_done = True

        timing_match = _TIMING_RE.search(line)
        if timing_match:
            cpu_seconds = _parse_float(timing_match.group(1))
            wall_seconds = _parse_float(timing_match.group(2))

    input_parameters = _normalized_input_parameters(input_parameters)
    convergence_threshold_ry = _first_numeric_input(input_parameters, "electrons", "conv_thr")
    if ecutwfc_ry is None:
        ecutwfc_ry = _first_numeric_input(input_parameters, "system", "ecutwfc")
    if ecutrho_ry is None:
        ecutrho_ry = _first_numeric_input(input_parameters, "system", "ecutrho")
    if number_of_bands is None:
        nbnd = _first_numeric_input(input_parameters, "system", "nbnd")
        number_of_bands = int(nbnd) if nbnd is not None else None

    accuracy_values = [
        iteration.scf_accuracy_ry
        for iteration in iterations
        if iteration.scf_accuracy_ry is not None
    ]
    oscillatory_accuracy = _has_oscillatory_accuracy(accuracy_values)
    slow_convergence = _is_slow_convergence(iterations, convergence_iterations, converged)
    mixing_beta_values = [
        iteration.mixing_beta for iteration in iterations if iteration.mixing_beta is not None
    ]
    if len(set(mixing_beta_values)) > 1:
        mixing_instability_signals.append("mixing beta changed during SCF trajectory")
    diagnostics: dict[str, object] = {
        "eigenvalue_warnings": eigenvalue_warnings,
        "oscillatory_accuracy": oscillatory_accuracy,
        "slow_convergence": slow_convergence,
        "mixing_instability_signals": mixing_instability_signals,
        "fft_or_cutoff_issues": fft_or_cutoff_issues,
    }
    stability_assessment = _assess_stability(
        iterations=iterations,
        converged=converged,
        job_done=job_done,
        issues=scan.issues,
        diagnostics=diagnostics,
    )
    convergence_dynamics = _assess_convergence_dynamics(iterations)
    workflow_readiness = _assess_workflow_readiness(
        converged=converged,
        job_done=job_done,
        stability=stability_assessment,
        convergence_dynamics=convergence_dynamics,
    )

    return ScfOutput(
        program=program,
        version=version,
        iterations=iterations,
        final_total_energy_ry=final_total_energy_ry,
        final_scf_accuracy_ry=final_scf_accuracy_ry,
        fermi_energy_ev=fermi_energy_ev,
        converged=converged,
        convergence_iterations=convergence_iterations,
        job_done=job_done,
        cpu_seconds=cpu_seconds,
        wall_seconds=wall_seconds,
        issues=scan.issues,
        source=scan.source,
        number_of_electrons=number_of_electrons,
        number_of_bands=number_of_bands,
        ecutwfc_ry=ecutwfc_ry,
        ecutrho_ry=ecutrho_ry,
        k_point_count=k_point_count,
        k_point_mesh=k_point_mesh,
        fft_grids=fft_grids,
        input_parameters=input_parameters,
        convergence_threshold_ry=convergence_threshold_ry,
        diagnostics=diagnostics,
        stability_assessment=stability_assessment,
        convergence_dynamics=convergence_dynamics,
        workflow_readiness=workflow_readiness,
    )


def _load_text_and_source(text_or_path: str | Path, source: str | Path | None) -> tuple[str, str]:
    if isinstance(text_or_path, Path):
        return (
            text_or_path.read_text(encoding="utf-8", errors="replace"),
            _source_label(source if source is not None else text_or_path),
        )
    candidate_path = Path(text_or_path)
    if "\n" not in text_or_path and candidate_path.is_file():
        return (
            candidate_path.read_text(encoding="utf-8", errors="replace"),
            _source_label(source if source is not None else candidate_path),
        )
    return text_or_path, _source_label(source if source is not None else "text")


def _source_label(source: str | Path) -> str:
    if isinstance(source, Path):
        return source.name
    source_text = str(source)
    if "/" in source_text or "\\" in source_text:
        normalized = source_text.replace("\\", "/")
        return normalized.rsplit("/", 1)[-1]
    return source_text


def _parse_float(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "E"))


def _parse_optional_float(match: re.Match[str] | None) -> float | None:
    if match is None:
        return None
    return _parse_float(match.group(1))


def _parse_input_value(raw_value: str) -> object:
    value = raw_value.strip().rstrip(",")
    lower = value.lower()
    if (value.startswith("'") and value.endswith("'")) or (
        value.startswith('"') and value.endswith('"')
    ):
        return value[1:-1]
    if lower in {".true.", "true"}:
        return True
    if lower in {".false.", "false"}:
        return False
    if re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    if re.fullmatch(_FLOAT_RE, value):
        return _parse_float(value)
    return value


def _parse_k_points_mesh(line: str) -> list[int] | None:
    if _INTEGER_LINE_RE.match(line) is None:
        return None
    values = [int(value) for value in re.findall(r"[+-]?\d+", line)]
    if len(values) < 3:
        return None
    return values[:3]


def _previous_iteration_energy(iterations: list[ScfIteration]) -> float | None:
    for iteration in reversed(iterations[:-1]):
        if iteration.total_energy_ry is not None:
            return iteration.total_energy_ry
    return None


def _rebind_iteration(
    iteration: ScfIteration,
    *,
    total_energy_ry: float | None = None,
    scf_accuracy_ry: float | None = None,
    energy_difference_ry: float | None = None,
    mixing_beta: float | None = None,
    fermi_energy: float | None = None,
    eigenvalue_warning: bool | None = None,
    warnings: list[str] | None = None,
    converged: bool | None = None,
) -> ScfIteration:
    return ScfIteration(
        number=iteration.number,
        total_energy_ry=(
            total_energy_ry if total_energy_ry is not None else iteration.total_energy_ry
        ),
        scf_accuracy_ry=(
            scf_accuracy_ry if scf_accuracy_ry is not None else iteration.scf_accuracy_ry
        ),
        energy_difference_ry=(
            energy_difference_ry
            if energy_difference_ry is not None
            else iteration.energy_difference_ry
        ),
        mixing_beta=mixing_beta if mixing_beta is not None else iteration.mixing_beta,
        fermi_energy=fermi_energy if fermi_energy is not None else iteration.fermi_energy,
        eigenvalue_warning=(
            eigenvalue_warning if eigenvalue_warning is not None else iteration.eigenvalue_warning
        ),
        warnings=list(warnings) if warnings is not None else list(iteration.warnings),
        converged=converged if converged is not None else iteration.converged,
    )


def _energy_difference(energy_ry: float, previous_energy_ry: float | None) -> float | None:
    if previous_energy_ry is None:
        return None
    return round(energy_ry - previous_energy_ry, 12)


def _ry_to_ev(value_ry: float | None) -> float | None:
    if value_ry is None:
        return None
    return value_ry * RY_TO_EV


def _find_iteration_index(iterations: list[ScfIteration], number: int) -> int | None:
    for index, iteration in enumerate(iterations):
        if iteration.number == number:
            return index
    return None


def _sign_changes(values: list[float]) -> bool:
    previous = 0.0
    saw_non_zero = False
    for value in values:
        if value == 0.0:
            continue
        sign = math.copysign(1.0, value)
        if not saw_non_zero:
            previous = sign
            saw_non_zero = True
            continue
        if sign != previous:
            return True
        previous = sign
    return False


def _convergence_ratio_errors(errors: list[float]) -> list[float]:
    ratios: list[float] = []
    for previous, current in zip(errors, errors[1:]):
        if previous <= 0 or current < 0:
            continue
        if previous == 0:
            continue
        ratios.append(current / previous)
    return ratios


def _normalized_input_parameters(
    input_parameters: dict[str, dict[str, object]]
) -> dict[str, dict[str, object]]:
    normalized = {
        "control": dict(input_parameters.get("control", {})),
        "system": dict(input_parameters.get("system", {})),
        "electrons": dict(input_parameters.get("electrons", {})),
    }
    system = normalized["system"]
    if "ecutwfc" in system:
        system["ecutwfc_ry"] = float(system["ecutwfc"])  # type: ignore[arg-type]
    if "ecutrho" in system:
        system["ecutrho_ry"] = float(system["ecutrho"])  # type: ignore[arg-type]
    return normalized


def _schema_input_parameters(
    input_parameters: dict[str, dict[str, object]]
) -> dict[str, dict[str, object]]:
    return {
        "control": dict(input_parameters.get("control", {})),
        "system": dict(input_parameters.get("system", {})),
        "electrons": dict(input_parameters.get("electrons", {})),
    }


def _schema_diagnostics(
    diagnostics: dict[str, object],
    issues: list[QEOutputEvent],
) -> dict[str, object]:
    return {
        "eigenvalue_warnings": list(diagnostics.get("eigenvalue_warnings", [])),
        "oscillatory_accuracy": bool(diagnostics.get("oscillatory_accuracy", False)),
        "slow_convergence": bool(diagnostics.get("slow_convergence", False)),
        "mixing_instability_signals": list(
            diagnostics.get("mixing_instability_signals", [])
        ),
        "fft_or_cutoff_issues": list(diagnostics.get("fft_or_cutoff_issues", [])),
        "qe_issues": [
            {
                "line_number": issue.line_number,
                "category": issue.category,
                "severity": issue.severity,
                "message": issue.message,
                "source": issue.source,
            }
            for issue in issues
        ],
    }


def _first_numeric_input(
    input_parameters: dict[str, dict[str, object]], section: str, key: str
) -> float | None:
    value = input_parameters.get(section, {}).get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _has_oscillatory_accuracy(accuracy_values: list[float]) -> bool:
    if len(accuracy_values) < 2:
        return False
    for previous, current in zip(accuracy_values, accuracy_values[1:]):
        if current > previous:
            return True
    return False


def _assess_convergence_dynamics(iterations: list[ScfIteration]) -> ConvergenceDynamics:
    """Estimate SCF trajectory quality and extrapolation behaviour."""

    energies = [iteration.total_energy_ry for iteration in iterations if iteration.total_energy_ry is not None]
    errors = [iteration.scf_accuracy_ry for iteration in iterations if iteration.scf_accuracy_ry is not None and iteration.scf_accuracy_ry > 0]
    energy_differences = [
        iteration.energy_difference_ry
        for iteration in iterations
        if iteration.energy_difference_ry is not None
    ]

    if not errors or len(errors) < 2:
        return ConvergenceDynamics(
            convergence_rate=None,
            energy_decay_type="insufficient_data",
            estimated_asymptotic_error=None,
            convergence_half_life=None,
        )

    energy_decay_type = "monotonic"
    if _sign_changes(energy_differences) or _has_oscillatory_accuracy(errors):
        energy_decay_type = "oscillatory"

    ratios = _convergence_ratio_errors(errors)
    if not ratios:
        convergence_rate = None
    else:
        convergence_rate = float(median(ratios))

    if len(errors) >= 3 and max(errors[1:]) > errors[0]:
        energy_decay_type = "unstable"

    if convergence_rate is not None and 0 < convergence_rate < 1:
        estimated_asymptotic_error = float(errors[-1]) * convergence_rate
        convergence_half_life = max(1, int(math.ceil(math.log(0.5) / math.log(convergence_rate))))
    else:
        estimated_asymptotic_error = None
        convergence_half_life = None
        if energy_decay_type == "monotonic" and len(errors) >= 2 and any(
            ratio > 1 for ratio in ratios
        ):
            energy_decay_type = "unstable"

    if len(energies) >= 2 and len({energy for energy in energies}) <= 1:
        energy_decay_type = "stalled"

    return ConvergenceDynamics(
        convergence_rate=convergence_rate,
        energy_decay_type=energy_decay_type,
        estimated_asymptotic_error=estimated_asymptotic_error,
        convergence_half_life=convergence_half_life,
    )


def _assess_workflow_readiness(
    *,
    converged: bool,
    job_done: bool,
    stability: NumericalStabilityReport,
    convergence_dynamics: ConvergenceDynamics,
) -> WorkflowReadiness:
    if not job_done:
        return WorkflowReadiness(
            dos=False,
            bands=False,
            phonon=False,
            dielectric=False,
            reason="SCF job has not completed (no JOB DONE).",
        )
    if not converged:
        return WorkflowReadiness(
            dos=False,
            bands=False,
            phonon=False,
            dielectric=False,
            reason="SCF did not report convergence.",
        )
    if stability.severity == "high":
        return WorkflowReadiness(
            dos=False,
            bands=False,
            phonon=False,
            dielectric=False,
            reason=(
                stability.likely_root_cause
                or "fatal numerical issue detected in SCF trajectory."
            ),
        )

    unstable_decay = convergence_dynamics.energy_decay_type in {"oscillatory", "unstable"}
    if stability.severity == "medium" or unstable_decay:
        reasons: list[str] = []
        if unstable_decay:
            reasons.append("SCF decay pattern is not robust.")
        if stability.symptoms:
            reasons.extend(stability.symptoms[:2])
        return WorkflowReadiness(
            dos=False,
            bands=False,
            phonon=False,
            dielectric=False,
            reason="; ".join(dict.fromkeys(reasons)) or (
                "Convergence has medium-severity issues."
            ),
        )

    return WorkflowReadiness(
        dos=True,
        bands=True,
        phonon=True,
        dielectric=True,
        reason="Converged stable SCF with low-severity signals.",
    )


def _is_slow_convergence(
    iterations: list[ScfIteration],
    convergence_iterations: int | None,
    converged: bool,
) -> bool:
    iteration_count = convergence_iterations if convergence_iterations is not None else len(iterations)
    if iteration_count >= 50:
        return True
    return not converged and iteration_count >= 20


def _assess_stability(
    *,
    iterations: list[ScfIteration],
    converged: bool,
    job_done: bool,
    issues: list[QEOutputEvent],
    diagnostics: dict[str, object],
) -> NumericalStabilityReport:
    fatal_categories = {
        issue.category for issue in issues if issue.category in _FATAL_ISSUE_CATEGORIES
    }
    suitable_for_followup = False
    if fatal_categories:
        symptoms = [f"fatal event: {sorted(fatal_categories)[0]}"]
        likely_causes = [f"fatal QE category: {category}" for category in sorted(fatal_categories)]
        causal_chain = [
            "fatal runtime/output event detected -> trust of SCF observables is compromised"
        ]
        recommendations = [
            "Fix the fatal event in QE input/runtime before reusing this trajectory."
        ]
        return NumericalStabilityReport(
            severity="high",
            likely_root_cause=f"fatal QE output issue: {', '.join(sorted(fatal_categories))}",
            impact_on_observables=(
                "Final observables should not be trusted until the fatal output issue is resolved."
            ),
            suitable_for_followup=False,
            symptoms=symptoms,
            likely_causes=likely_causes,
            causal_chain=causal_chain,
            recommendations=recommendations,
        )

    medium_causes: list[str] = []
    if diagnostics.get("eigenvalue_warnings"):
        medium_causes.append("eigenvalue convergence warning")
    if diagnostics.get("slow_convergence"):
        medium_causes.append("slow SCF convergence")
    if diagnostics.get("oscillatory_accuracy"):
        medium_causes.append("non-monotonic SCF accuracy")
    if diagnostics.get("mixing_instability_signals"):
        medium_causes.append("changing mixing beta")
    if diagnostics.get("fft_or_cutoff_issues"):
        medium_causes.append("FFT or cutoff numerical issue")

    if medium_causes:
        recommendations = []
        if diagnostics.get("eigenvalue_warnings"):
            recommendations.append("Increase ecutwfc by ~10-20% and tighten smearing settings if metallic.")
        if diagnostics.get("slow_convergence") or diagnostics.get("oscillatory_accuracy"):
            recommendations.append("Tighten conv_thr and reduce mixing_beta to stabilise SCF.")
        if diagnostics.get("mixing_instability_signals"):
            recommendations.append("Lock or adapt mixing beta and restart with a cleaner previous wavefunction.")
        if diagnostics.get("fft_or_cutoff_issues"):
            recommendations.append("Increase ecutwfc/ecutrho and verify FFT grid line-up.")
        if not recommendations:
            recommendations.append("Re-run SCF with tuned convergence parameters.")
        return NumericalStabilityReport(
            severity="medium",
            likely_root_cause="; ".join(medium_causes),
            impact_on_observables=(
                "Final values are parsed but follow-up use should wait for a cleaner low-severity SCF run."
            ),
            suitable_for_followup=False,
            symptoms=[str(cause) for cause in medium_causes],
            likely_causes=[str(cause) for cause in medium_causes],
            causal_chain=_build_causal_chain(medium_causes),
            recommendations=recommendations,
        )

    stable_accuracy = not _has_oscillatory_accuracy(
        [
            iteration.scf_accuracy_ry
            for iteration in iterations
            if iteration.scf_accuracy_ry is not None
        ]
    )
    suitable_for_followup = converged and job_done and stable_accuracy
    severity = "low" if suitable_for_followup else "medium"
    likely_root_cause = "no important numerical stability signals detected"
    impact_on_observables = (
        "Converged JOB DONE output with stable SCF trajectory; parsed observables are suitable for follow-up."
        if suitable_for_followup
        else "SCF output lacks a clean converged JOB DONE state; follow-up use is not recommended."
    )
    stability = NumericalStabilityReport(
        severity=severity,
        likely_root_cause=likely_root_cause,
        impact_on_observables=impact_on_observables,
        suitable_for_followup=suitable_for_followup,
    )
    return stability


def _build_causal_chain(causes: list[str]) -> list[str]:
    chain: list[str] = []
    if "eigenvalue convergence warning" in causes:
        chain.append("diagonalization noise -> eigenvalue_warning -> weak SCF stability")
    if "non-monotonic SCF accuracy" in causes:
        chain.append("SCF residual oscillates -> mixed-step acceptance -> delayed convergence")
    if "slow SCF convergence" in causes:
        chain.append("residual decrease too slow -> preemptive stop or stale charge density")
    if "changing mixing beta" in causes:
        chain.append("variable mixer settings -> trajectory non-stationary")
    if "FFT or cutoff numerical issue" in causes:
        chain.append("basis/grid insufficiency -> inaccurate matrix updates")
    if not chain:
        chain.append("no explicit high-confidence causal chain extracted")
    return chain


__all__ = [
    "RY_TO_EV",
    "SCFState",
    "ConvergenceDynamics",
    "WorkflowReadiness",
    "NumericalStabilityReport",
    "ScfIteration",
    "ScfOutput",
    "parse_scf_output",
]
