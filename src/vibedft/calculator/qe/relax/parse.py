"""Parse Quantum ESPRESSO PWSCF relax / vc-relax output trajectories."""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Any

from vibedft.calculator.qe.common import QEOutputEvent, parse_qe_output_events

from vibedft.calculator.qe.scf.parse import ScfOutput, parse_scf_output


RY_TO_EV = 13.605703976
_FLOAT_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"


@dataclass(frozen=True)
class RelaxScfStep:
    """Single SCF iteration record nested under one ionic step."""

    iteration: int
    total_energy: float | None
    energy_change: float | None
    scf_accuracy: float | None
    mixing_info: dict[str, object]
    convergence_flag: bool
    scf_job_done: bool = False

    def to_schema(self) -> dict[str, object]:
        return {
            "iteration": self.iteration,
            "total_energy": self.total_energy,
            "energy_change": self.energy_change,
            "scf_accuracy": self.scf_accuracy,
            "mixing_info": dict(self.mixing_info),
            "convergence_flag": bool(self.convergence_flag),
            "scf_job_done": self.scf_job_done,
        }


@dataclass(frozen=True)
class RelaxGeometry:
    """Geometry snapshot for one ionic step."""

    atomic_positions: list[dict[str, object]]
    cell_parameters: list[list[float]]
    volume: float | None
    lattice_vectors: list[list[float]]

    def to_schema(self) -> dict[str, object]:
        return {
            "atomic_positions": [dict(atom) for atom in self.atomic_positions],
            "cell_parameters": [list(row) for row in self.cell_parameters],
            "volume": self.volume,
            "lattice_vectors": [list(row) for row in self.lattice_vectors],
        }


@dataclass(frozen=True)
class RelaxForces:
    """Forces extracted from a relax ionic step."""

    forces_per_atom: list[dict[str, object]]
    max_force: float | None
    force_threshold: float | None
    rms_force: float | None = None

    def to_schema(self) -> dict[str, object]:
        return {
            "forces_per_atom": [dict(force) for force in self.forces_per_atom],
            "max_force": self.max_force,
            "force_threshold": self.force_threshold,
            "rms_force": self.rms_force,
        }


@dataclass(frozen=True)
class RelaxStress:
    """Stress tensor and pressure for one step."""

    stress_tensor: list[list[float]]
    pressure: float | None
    pressure_unit: str = "kbar"

    def to_schema(self) -> dict[str, object]:
        return {
            "stress_tensor": [list(row) for row in self.stress_tensor],
            "pressure": self.pressure,
        }


@dataclass(frozen=True)
class RelaxStep:
    """Single ionic step in a relaxation trajectory."""

    step_index: int
    scf_trajectory: list[RelaxScfStep]
    geometry: RelaxGeometry
    forces: RelaxForces
    stress: RelaxStress
    step_convergence: dict[str, bool]

    def to_schema(self) -> dict[str, object]:
        return {
            "step_index": self.step_index,
            "scf_trajectory": [entry.to_schema() for entry in self.scf_trajectory],
            "geometry": self.geometry.to_schema(),
            "forces": self.forces.to_schema(),
            "stress": self.stress.to_schema(),
            "step_convergence": dict(self.step_convergence),
        }


@dataclass(frozen=True)
class RelaxOutput:
    """Structured QE relax output result."""

    system: dict[str, object]
    input_parameters: dict[str, dict[str, object]]
    numerical_setup: dict[str, object]
    relaxation_trajectory: list[RelaxStep]
    job_done: bool
    global_convergence: dict[str, bool]
    final_structure: dict[str, object]
    final_observables: dict[str, float | None]
    diagnostics: dict[str, object]
    issues: list[QEOutputEvent]
    events: list[QEOutputEvent]
    source: str
    source_summary: str
    variable_cell: bool

    def to_schema(self) -> dict[str, object]:
        return {
            "system": dict(self.system),
            "input_parameters": {key: dict(values) for key, values in self.input_parameters.items()},
            "numerical_setup": dict(self.numerical_setup),
            "relaxation_trajectory": [step.to_schema() for step in self.relaxation_trajectory],
            "global_convergence": dict(self.global_convergence),
            "final_structure": dict(self.final_structure),
            "final_observables": dict(self.final_observables),
            "diagnostics": {"stability_report": dict(self.diagnostics["stability_report"])},
        }


_PROGRAM_RE = re.compile(
    r"\bProgram\s+([A-Za-z0-9_.-]+)\s+v\.?\s*([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_INPUT_KEY_VALUE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*,?\s*$")
_ITERATION_RE = re.compile(r"^\s*iteration\s*#\s*(\d+)", re.IGNORECASE)
_SELF_CONSISTENT_START_RE = re.compile(r"^\s*Self-consistent Calculation", re.IGNORECASE)
_SELF_CONSISTENT_END_RE = re.compile(r"^\s*End of self-consistent calculation", re.IGNORECASE)
_ATOMIC_POSITIONS_RE = re.compile(r"^\s*ATOMIC_POSITIONS\b", re.IGNORECASE)
_CELL_PARAMETERS_RE = re.compile(r"^\s*CELL_PARAMETERS\b", re.IGNORECASE)
_FORCES_HEADER_RE = re.compile(r"^\s*Forces\s+acting\s+on\s+atoms", re.IGNORECASE)
_FORCE_LINE_RE = re.compile(
    rf"^\s*atom\s+(\d+)\s+type\s+(-?\d+)\s+force\s*=\s*({_FLOAT_RE})\s+({_FLOAT_RE})\s+({_FLOAT_RE})",
    re.IGNORECASE,
)
_FORCE_ALT_LINE_RE = re.compile(
    rf"^\s*(\d+)\s+([A-Za-z][A-Za-z0-9_]*)\s+({_FLOAT_RE})\s+({_FLOAT_RE})\s+({_FLOAT_RE})",
    re.IGNORECASE,
)
_TOTAL_FORCE_RE = re.compile(rf"^\s*total\s+force\s*=\s*({_FLOAT_RE})", re.IGNORECASE)
_STRESS_HEADER_RE = re.compile(r"^\s*total\s+stress", re.IGNORECASE)
_PRESSURE_RE = re.compile(rf"\bP\s*=\s*({_FLOAT_RE})", re.IGNORECASE)
_NUMBER_OF_KPOINTS_RE = re.compile(r"^\s*number of k points\s*=\s*(\d+)", re.IGNORECASE)
_BFGS_CONVERGED_RE = re.compile(r"\bbfgs\s+converged\b", re.IGNORECASE)
_BFGS_NOT_CONVERGED_RE = re.compile(
    r"\b(?:convergence\s+NOT\s+achieved|not\s+converged|stopping|no convergence)\b",
    re.IGNORECASE,
)
_BEGIN_FINAL_RE = re.compile(r"^\s*Begin\s+final\s+coordinates", re.IGNORECASE)
_END_FINAL_RE = re.compile(r"^\s*End\s+final\s+coordinates", re.IGNORECASE)
_FINAL_ENERGY_RE = re.compile(rf"\bFinal\s+energy\s*=\s*({_FLOAT_RE})")
_FINAL_ENTHALPY_RE = re.compile(rf"\bFinal\s+enthalpy\s*=\s*({_FLOAT_RE})")
_END_BFGS_RE = re.compile(r"^\s*End of BFGS Geometry Optimization", re.IGNORECASE)
_BFGS_GEOM_RE = re.compile(r"^\s*BFGS\s+Geometry\s+Optimization", re.IGNORECASE)
_CELL_DOFREE_RE = re.compile(r"cell_dofree|calculation\s*=\s*['\"]vc-relax['\"]|calculation\s*=\s*vc-relax", re.IGNORECASE)
_VOLUME_RE = re.compile(rf"unit-cell\s+volume\s*=\s*({_FLOAT_RE})", re.IGNORECASE)
_WARNING_RE = re.compile(r"\bc_bands:|failed|warning|oscillat|not\s+converged|aborting", re.IGNORECASE)


def parse_relax_output(
    text_or_path: str | Path,
    *,
    source: str | Path | None = None,
    variable_cell: bool | None = None,
) -> RelaxOutput:
    """Parse a QE relax / vc-relax output log into a nested trajectory schema."""

    text, source_label = _load_text_and_source(text_or_path, source)
    lines = text.splitlines()
    scan = parse_qe_output_events(text, source=source_label)

    program, version = _parse_program(lines)
    input_parameters = _parse_input_parameters(lines)
    numerical_setup = _parse_numerical_setup(lines, input_parameters)
    variable_cell_detected = bool(
        variable_cell if variable_cell is not None else _detect_variable_cell(lines, input_parameters)
    )

    steps, final_coordinates = _parse_relax_steps(lines, source=source_label)

    final_geometry = final_coordinates
    if final_geometry is None and steps:
        final_geometry = steps[-1].geometry
    if final_geometry is None:
        final_geometry = _empty_geometry()

    final_trajectory_energy = _last_value(
        [entry.total_energy for step in steps for entry in step.scf_trajectory if entry.total_energy is not None]
    )
    final_pressure = _last_value([step.stress.pressure for step in steps])
    final_volume = final_geometry.volume
    final_enthalpy = _extract_last_scalar(lines, _FINAL_ENTHALPY_RE)
    if final_enthalpy is None:
        final_enthalpy = _computed_enthalpy(
            final_trajectory_energy,
            final_pressure,
            final_volume,
        )

    global_convergence = _compute_global_convergence(steps)
    diagnostics = _build_diagnostics(steps, scan.issues, text)

    final_structure = final_geometry.to_schema()
    final_observables = {
        "total_energy": final_trajectory_energy,
        "enthalpy": final_enthalpy,
        "pressure": final_pressure,
        "volume": final_volume,
    }

    return RelaxOutput(
        system={
            "program": program,
            "version": version,
            "source": source_label,
            "number_of_bands": _first_number(
                input_parameters,
                ["system", "nbnd"],
            ),
            "number_of_electrons": _first_number(
                input_parameters,
                ["system", "number_of_electrons"],
            ),
        },
        input_parameters=input_parameters,
        numerical_setup=numerical_setup,
        relaxation_trajectory=steps,
        job_done=any(event.category == "job_done" for event in scan.events),
        global_convergence=global_convergence,
        final_structure=final_structure,
        final_observables=final_observables,
        diagnostics=diagnostics,
        issues=scan.issues,
        events=scan.events,
        source=source_label,
        source_summary=_build_source_summary(text, source_label, len(steps)),
        variable_cell=variable_cell_detected,
    )


def parse_relax_outputs(
    outputs: list[str | Path],
    *,
    variable_cell: bool | None = None,
) -> list[RelaxOutput]:
    """Parse one or more QE relax outputs."""

    return [parse_relax_output(output, variable_cell=variable_cell) for output in outputs]


def _parse_relax_steps(
    lines: list[str],
    *,
    source: str,
) -> tuple[list[RelaxStep], RelaxGeometry | None]:
    """Parse ion-relax steps with nested SCF blocks."""

    scf_starts = [idx for idx, line in enumerate(lines) if _SELF_CONSISTENT_START_RE.search(line)]
    if not scf_starts:
        return [], _parse_final_coordinates(lines)

    force_threshold = _detect_force_threshold(lines)
    final_coordinates: RelaxGeometry | None = None
    pending_geometry = _empty_geometry()
    steps: list[RelaxStep] = []

    scan_head = 0
    for step_index, scf_start in enumerate(scf_starts):
        # Parse any geometry update in the gap before SCF. This catches the
        # ATOMIC_POSITIONS / CELL_PARAMETERS lines that are printed before the
        # next SCF cycle block.
        pending_geometry = _consume_geometry_updates(
            lines,
            start=scan_head,
            end=scf_start,
            geometry=pending_geometry,
        )

        next_scf_start = scf_starts[step_index + 1] if step_index + 1 < len(scf_starts) else None
        scf_end = _find_scf_end(lines, scf_start, next_scf_start)
        step_scf_text = "\n".join(lines[scf_start : scf_end + 1])
        scf_output = parse_scf_output(step_scf_text, source=source)

        scf_trajectory: list[RelaxScfStep] = [
            RelaxScfStep(
                iteration=iteration.number,
                total_energy=iteration.total_energy_ry,
                energy_change=iteration.energy_difference_ry,
                scf_accuracy=iteration.scf_accuracy_ry,
                mixing_info={
                    "beta": iteration.mixing_beta,
                    "eigenvalue_warning": iteration.eigenvalue_warning,
                },
                convergence_flag=bool(iteration.converged),
                scf_job_done=scf_output.job_done,
            )
            for iteration in scf_output.iterations
        ]

        step_geometry = pending_geometry
        step_forces: list[dict[str, object]] = []
        max_force: float | None = None
        rms_force: float | None = None
        step_pressure: float | None = None
        step_stress: list[list[float]] = []
        ionic_converged = False
        step_converged = False

        head = scf_start
        tail_end = scf_starts[step_index + 1] if step_index + 1 < len(scf_starts) else len(lines)

        j = head
        while j < tail_end:
            tail_line = lines[j].strip()

            if _BEGIN_FINAL_RE.search(tail_line):
                parsed_final = _parse_final_coordinates(lines[j:])
                if parsed_final is not None:
                    final_coordinates = parsed_final
                pending_geometry = _consume_geometry_updates(
                    lines,
                    start=j,
                    end=tail_end,
                    geometry=pending_geometry,
                )
                step_geometry = pending_geometry
                j = _find_next_marker(lines, j + 1, tail_end)
                continue

            if _CELL_PARAMETERS_RE.match(tail_line):
                parsed_cell = _parse_cell_block(lines, j)
                if parsed_cell is not None:
                    pending_geometry = _replace_cell(pending_geometry, parsed_cell)
                    step_geometry = pending_geometry
                    j = parsed_cell["_next_index"]
                    continue

            if _ATOMIC_POSITIONS_RE.match(tail_line):
                parsed_atomic = _parse_atomic_block(lines, j)
                if parsed_atomic is not None:
                    pending_geometry = _replace_atomic_positions(pending_geometry, parsed_atomic)
                    step_geometry = pending_geometry
                    j = parsed_atomic["_next_index"]
                    continue

            if _FORCES_HEADER_RE.search(tail_line):
                step_forces, max_force, rms_force, j = _parse_forces_block(lines, j)
                continue

            if _STRESS_HEADER_RE.search(tail_line):
                step_stress, step_pressure, j = _parse_stress_block(lines, j)
                continue

            if _VOLUME_RE.search(tail_line):
                volume_match = _VOLUME_RE.search(tail_line)
                if volume_match is not None:
                    pending_geometry = _update_volume(pending_geometry, volume_match.group(1))
                    step_geometry = pending_geometry
                    j += 1
                    continue

            if _BFGS_CONVERGED_RE.search(tail_line):
                ionic_converged = True

            if _BFGS_NOT_CONVERGED_RE.search(tail_line):
                ionic_converged = False
            j += 1

        segment = _find_line_range(lines, scf_start, tail_end)
        if not step_converged:
            step_converged = bool(
                (
                    "convergence has been achieved" in segment
                    or "convergence achieved" in segment
                    or "bfgs converged" in segment
                )
                and "convergence not achieved" not in segment
            )

        if not scf_trajectory:
            # Robustness for non-standard blocks: still create one step with the raw SCF outcome.
            scf_trajectory = [
                RelaxScfStep(
                    iteration=1,
                    total_energy=scf_output.final_total_energy_ry,
                    energy_change=None,
                    scf_accuracy=scf_output.final_scf_accuracy_ry,
                    mixing_info={},
                    convergence_flag=scf_output.converged,
                    scf_job_done=scf_output.job_done,
                )
            ]

        if step_converged is False:
            step_converged = bool(scf_output.converged and "convergence not achieved" not in segment)

        steps.append(
            RelaxStep(
                step_index=step_index,
                scf_trajectory=scf_trajectory,
                geometry=step_geometry,
                forces=RelaxForces(
                    forces_per_atom=step_forces,
                    max_force=max_force,
                    force_threshold=force_threshold,
                    rms_force=rms_force,
                ),
                stress=RelaxStress(stress_tensor=step_stress, pressure=step_pressure),
                step_convergence={
                    "scf_converged": bool(scf_output.converged),
                    "ionic_converged": bool(ionic_converged or step_converged),
                },
            )
        )

        scan_head = tail_end

    # Parse any trailing updates (rarely, final coordinates appear after loop end).
    final_coordinates_candidate = _parse_final_coordinates(lines)
    if final_coordinates_candidate is not None:
        if steps:
            fallback_geometry = steps[-1].geometry
            if (
                (final_coordinates_candidate.volume is None)
                and fallback_geometry.volume is not None
            ):
                final_coordinates = RelaxGeometry(
                    atomic_positions=(
                        final_coordinates_candidate.atomic_positions
                        if final_coordinates_candidate.atomic_positions
                        else [dict(atom) for atom in fallback_geometry.atomic_positions]
                    ),
                    cell_parameters=(
                        final_coordinates_candidate.cell_parameters
                        if final_coordinates_candidate.cell_parameters
                        else [list(row) for row in fallback_geometry.cell_parameters]
                    ),
                    volume=fallback_geometry.volume,
                    lattice_vectors=(
                        final_coordinates_candidate.lattice_vectors
                        if final_coordinates_candidate.lattice_vectors
                        else [list(row) for row in fallback_geometry.lattice_vectors]
                    ),
                )
            else:
                final_coordinates = final_coordinates_candidate
        else:
            final_coordinates = final_coordinates_candidate

    return steps, final_coordinates


def _consume_geometry_updates(
    lines: list[str],
    *,
    start: int,
    end: int,
    geometry: RelaxGeometry,
) -> RelaxGeometry:
    """Parse geometry updates in a specific line range."""

    i = start
    current = geometry
    while i < end:
        raw = lines[i].strip()
        if _CELL_PARAMETERS_RE.match(raw):
            parsed_cell = _parse_cell_block(lines, i)
            if parsed_cell is not None:
                current = _replace_cell(current, parsed_cell)
                i = parsed_cell["_next_index"]
                continue

        if _VOLUME_RE.search(raw):
            volume_match = _VOLUME_RE.search(raw)
            if volume_match is not None:
                current = _update_volume(current, volume_match.group(1))
                i += 1
                continue

        if _ATOMIC_POSITIONS_RE.match(raw):
            parsed_atomic = _parse_atomic_block(lines, i)
            if parsed_atomic is not None:
                current = _replace_atomic_positions(current, parsed_atomic)
                i = parsed_atomic["_next_index"]
                continue

        i += 1
    return current


def _find_next_marker(lines: list[str], start: int, end: int) -> int:
    i = start
    while i < end:
        line = lines[i].strip()
        if _END_FINAL_RE.search(line):
            return i + 1
        i += 1
    return end


def _find_case_insensitive(lines: list[str], pattern: str) -> bool:
    target = pattern.lower()
    return any(target in line.lower() for line in lines)


def _find_line_range(lines: list[str], start: int, end: int) -> str:
    return "\n".join(lines[start:end]).lower()


def _parse_cell_block(lines: list[str], start: int) -> dict[str, Any] | None:
    i = start + 1
    vectors: list[list[float]] = []
    while i < len(lines) and len(vectors) < 3:
        raw = lines[i].strip()
        if not raw:
            i += 1
            continue
        if _marker_line(raw):
            break
        parts = raw.split()
        if len(parts) < 3:
            break
        if not all(_is_float_like(part) for part in parts[:3]):
            break
        vectors.append([_to_float(parts[0]), _to_float(parts[1]), _to_float(parts[2])])
        i += 1

    if len(vectors) != 3:
        return None
    return {
        "cell_parameters": vectors,
        "volume": _compute_volume(vectors),
        "lattice_vectors": vectors,
        "_next_index": i,
    }


def _parse_atomic_block(lines: list[str], start: int) -> dict[str, Any] | None:
    line = lines[start]
    match = re.search(r"\(([^)]+)\)", line)
    coordinate_system = match.group(1).strip() if match else None

    i = start + 1
    atoms: list[dict[str, object]] = []
    while i < len(lines):
        raw = lines[i].strip()
        if not raw:
            if atoms:
                i += 1
                break
            i += 1
            continue
        if _marker_line(raw):
            break
        parts = raw.split()
        if len(parts) < 4:
            break
        if not _is_float_like(parts[1]) or not _is_float_like(parts[2]) or not _is_float_like(parts[3]):
            break
        atom = {
            "element": parts[0],
            "x": _to_float(parts[1]),
            "y": _to_float(parts[2]),
            "z": _to_float(parts[3]),
            "coordinate_system": coordinate_system,
        }
        if len(parts) >= 5:
            atom["occupancy"] = parts[4]
        atoms.append(atom)
        i += 1

    if not atoms:
        return None
    return {
        "atomic_positions": atoms,
        "coordinate_system": coordinate_system,
        "_next_index": i,
    }


def _parse_program(lines: list[str]) -> tuple[str | None, str | None]:
    for line in lines:
        match = _PROGRAM_RE.search(line)
        if match:
            return match.group(1), match.group(2)
    return None, None


def _parse_input_parameters(lines: list[str]) -> dict[str, dict[str, object]]:
    input_parameters = {
        "control": {},
        "system": {},
        "electrons": {},
        "ions": {},
    }
    current_namelist: str | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        namelist_match = re.match(r"^&([A-Za-z]+)\b", line)
        if namelist_match:
            name = namelist_match.group(1).lower()
            current_namelist = name if name in input_parameters else None
            continue

        if line == "/":
            current_namelist = None
            continue

        if current_namelist is None:
            continue

        key_value = _INPUT_KEY_VALUE_RE.match(line)
        if key_value:
            key = key_value.group(1).lower()
            input_parameters[current_namelist][key] = _parse_input_value(key_value.group(2))

    number_of_k_points = _extract_number_after_keyword(lines, _NUMBER_OF_KPOINTS_RE)
    if number_of_k_points is not None:
        input_parameters.setdefault("kpoints", {})["count"] = number_of_k_points
    return input_parameters


def _parse_numerical_setup(lines: list[str], input_parameters: dict[str, dict[str, object]]) -> dict[str, object]:
    ecutwfc_ry = _numeric_for_keys(input_parameters, ["system", "ecutwfc"], ["system", "ecutwfc_ry"])
    ecutrho_ry = _numeric_for_keys(input_parameters, ["system", "ecutrho"], ["system", "ecutrho_ry"])
    k_points_count = _extract_number_after_keyword(lines, _NUMBER_OF_KPOINTS_RE)
    k_mesh = _extract_k_mesh(lines)
    force_threshold = _numeric_for_keys(input_parameters, ["ions", "forc_conv_thr"], ["control", "forc_conv_thr"])

    return {
        "ecutwfc_ry": ecutwfc_ry,
        "ecutwfc_ev": _to_ev(ecutwfc_ry),
        "ecutrho_ry": ecutrho_ry,
        "ecutrho_ev": _to_ev(ecutrho_ry),
        "k_points": {
            "count": k_points_count,
            "mesh": k_mesh,
        },
        "forces": {
            "convergence_threshold": force_threshold,
        },
    }


def _find_scf_end(lines: list[str], start: int, next_scf_start: int | None = None) -> int:
    idx = start
    limit = len(lines) if next_scf_start is None else next_scf_start
    while idx < len(lines):
        if _SELF_CONSISTENT_END_RE.search(lines[idx]):
            return idx
        idx += 1
        if next_scf_start is not None and idx >= limit:
            break
    return (next_scf_start - 1) if next_scf_start is not None else len(lines) - 1


def _parse_forces_block(
    lines: list[str],
    start: int,
) -> tuple[list[dict[str, object]], float | None, float | None, int]:
    forces: list[dict[str, object]] = []
    max_force: float | None = None
    values_for_rms: list[float] = []

    i = start + 1
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            if forces:
                i += 1
                break
            i += 1
            continue

        if (
            _STRESS_HEADER_RE.search(line)
            or _BFGS_GEOM_RE.search(line)
            or _END_BFGS_RE.search(line)
            or _ATOMIC_POSITIONS_RE.search(line)
            or _CELL_PARAMETERS_RE.search(line)
        ):
            break

        if any(breaker in line for breaker in ["The non-local contrib", "The local contrib", "The Harris-Foulkes"]) :
            break

        if _FORCE_LINE_RE.match(line):
            force_match = _FORCE_LINE_RE.match(line)
            atom_index = int(force_match.group(1))
            fx = _to_float(force_match.group(3))
            fy = _to_float(force_match.group(4))
            fz = _to_float(force_match.group(5))
            norm = sqrt(fx * fx + fy * fy + fz * fz)
            forces.append(
                {
                    "atom": atom_index,
                    "force_x": fx,
                    "force_y": fy,
                    "force_z": fz,
                    "norm": norm,
                }
            )
            max_force = norm if max_force is None else max(max_force, norm)
            values_for_rms.append(norm)
            i += 1
            continue

        if _FORCE_ALT_LINE_RE.match(line):
            force_match = _FORCE_ALT_LINE_RE.match(line)
            atom_index = int(force_match.group(1))
            fx = _to_float(force_match.group(3))
            fy = _to_float(force_match.group(4))
            fz = _to_float(force_match.group(5))
            norm = sqrt(fx * fx + fy * fy + fz * fz)
            forces.append(
                {
                    "atom": atom_index,
                    "force_x": fx,
                    "force_y": fy,
                    "force_z": fz,
                    "norm": norm,
                }
            )
            max_force = norm if max_force is None else max(max_force, norm)
            values_for_rms.append(norm)
            i += 1
            continue

        if _TOTAL_FORCE_RE.search(line):
            max_force_match = _TOTAL_FORCE_RE.search(line)
            if max_force_match:
                max_force = _to_float(max_force_match.group(1))
            i += 1
            continue

        if _marker_line(line):
            break

        i += 1

    rms_force = (
        sqrt(sum(value * value for value in values_for_rms) / len(values_for_rms))
        if values_for_rms
        else None
    )
    return forces, max_force, rms_force, i


def _parse_stress_block(
    lines: list[str],
    start: int,
) -> tuple[list[list[float]], float | None, int]:
    tensor: list[list[float]] = []
    pressure: float | None = None

    i = start + 1
    header_pressure_match = _PRESSURE_RE.search(lines[start])
    if header_pressure_match:
        pressure = _to_float(header_pressure_match.group(1))

    while i < len(lines) and len(tensor) < 3:
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        if _marker_line(line) and not tensor:
            break
        if _marker_line(line) and tensor:
            break

        pressure_match = _PRESSURE_RE.search(line)
        if pressure_match:
            pressure = _to_float(pressure_match.group(1))

        row = _extract_numbers(line)
        if len(row) >= 3:
            tensor.append(row[:3])

        i += 1

    # Some QE builds print a few non-numeric header lines between stress rows.
    # Keep scanning until exactly 3 rows are read or a non-marker terminator appears.
    j = i
    while len(tensor) < 3 and j < len(lines):
        line = lines[j].strip()
        if not line:
            j += 1
            continue
        if _marker_line(line) and not tensor:
            break
        row = _extract_numbers(line)
        if len(row) >= 3:
            tensor.append(row[:3])
            j += 1
            continue
        if _marker_line(line) or _WARNING_RE.search(line):
            break
        j += 1

    if len(tensor) > 3:
        tensor = tensor[:3]

    return tensor, pressure, max(i, j)


def _parse_final_coordinates(lines: list[str]) -> RelaxGeometry | None:
    if isinstance(lines, list):
        source_lines = lines
    else:
        source_lines = lines.splitlines()

    if not source_lines:
        return None

    has_block = False
    final_geometry = _empty_geometry()
    i = 0
    while i < len(source_lines):
        line = source_lines[i].strip()
        if _BEGIN_FINAL_RE.search(line):
            has_block = True
            i += 1
            continue
        if _END_FINAL_RE.search(line):
            break
        if not has_block:
            i += 1
            continue

        if _CELL_PARAMETERS_RE.match(line):
            cell_block = _parse_cell_block(source_lines, i)
            if cell_block is not None:
                final_geometry = _replace_cell(final_geometry, cell_block)
                i = cell_block["_next_index"]
                continue

        if _VOLUME_RE.search(line):
            volume_match = _VOLUME_RE.search(line)
            if volume_match is not None:
                final_geometry = _update_volume(final_geometry, volume_match.group(1))
                i += 1
                continue

        if _ATOMIC_POSITIONS_RE.match(line):
            atomic_block = _parse_atomic_block(source_lines, i)
            if atomic_block is not None:
                final_geometry = _replace_atomic_positions(final_geometry, atomic_block)
                i = atomic_block["_next_index"]
                continue

        i += 1

    if final_geometry.atomic_positions or final_geometry.cell_parameters:
        return final_geometry if has_block else None
    return None


def _build_source_summary(text: str, source: str, step_count: int) -> str:
    has_scf = _SELF_CONSISTENT_START_RE.search(text) is not None
    return (
        f"{source}: {'has' if has_scf else 'no'} scf markers, "
        f"scf steps={step_count}"
    )


def _compute_global_convergence(steps: list[RelaxStep]) -> dict[str, bool]:
    if not steps:
        return {
            "ionic_converged": False,
            "scf_converged_all_steps": False,
            "geometry_converged": False,
        }

    scf_converged_all = all(step.step_convergence.get("scf_converged") for step in steps)
    last_step = steps[-1]
    ionic_last = bool(last_step.step_convergence.get("ionic_converged"))
    force_threshold = last_step.forces.force_threshold
    max_force = last_step.forces.max_force

    geometry_converged = bool(
        force_threshold is not None
        and max_force is not None
        and max_force <= force_threshold
    )

    return {
        "ionic_converged": bool(ionic_last),
        "scf_converged_all_steps": bool(scf_converged_all),
        "geometry_converged": geometry_converged,
    }


def _build_diagnostics(steps: list[RelaxStep], issues: list[QEOutputEvent], text: str) -> dict[str, object]:
    step_energies: list[float] = []
    step_forces: list[float] = []
    step_volumes: list[float] = []
    atom_series: list[list[dict[str, object]]] = []

    for step in steps:
        if step.scf_trajectory:
            energy = _last_value([entry.total_energy for entry in step.scf_trajectory])
            if energy is not None:
                step_energies.append(energy)

        if step.forces.max_force is not None:
            step_forces.append(step.forces.max_force)

        if step.geometry.volume is not None:
            step_volumes.append(step.geometry.volume)

        atom_series.append(step.geometry.atomic_positions)

    issue_messages = " ".join(issue.message.lower() for issue in issues)
    issue_categories = {issue.category for issue in issues}

    electronic_modes: list[str] = []
    if "eigenvalue" in issue_messages:
        electronic_modes.append("eigenvalue_warning")
    if _oscillatory_signal(step_energies):
        electronic_modes.append("oscillatory_energy")

    ionic_modes: list[str] = []
    if len(step_forces) >= 3 and all(curr > prev for prev, curr in zip(step_forces, step_forces[1:])):
        ionic_modes.append("forces_increasing")
    if len(step_forces) >= 2 and _stagnating_tail(step_forces):
        ionic_modes.append("insufficient_force_reduction")

    structural_modes: list[str] = []
    if len(step_volumes) >= 2 and any(abs(cur - prev) > 1.0 for prev, cur in zip(step_volumes, step_volumes[1:])):
        structural_modes.append("volume_drift")
    if _composition_changed(atom_series):
        structural_modes.append("composition_change")

    symmetry_modes: list[str] = []
    if _symmetry_changed(atom_series):
        symmetry_modes.append("symmetry_change")

    overall_risk = "low"
    if issue_categories & {"error", "mpi_abort", "segmentation_fault", "out_of_memory", "time_limit", "traceback", "file_not_found"}:
        overall_risk = "high"
    elif electronic_modes or ionic_modes or structural_modes or symmetry_modes:
        overall_risk = "medium"

    likely_failure_modes = sorted(
        {mode for mode in (*electronic_modes, *ionic_modes, *structural_modes, *symmetry_modes)}
    )

    return {
        "stability_report": {
            "electronic_stability": {
                "modes": electronic_modes,
                "risk": "high" if "eigenvalue_warning" in electronic_modes else "medium" if electronic_modes else "low",
            },
            "ionic_stability": {
                "modes": ionic_modes,
                "risk": "high" if "forces_increasing" in ionic_modes else "medium" if ionic_modes else "low",
            },
            "structural_stability": {
                "modes": structural_modes,
                "risk": "high" if "volume_drift" in structural_modes else "medium" if structural_modes else "low",
            },
            "symmetry_stability": {
                "modes": symmetry_modes,
                "risk": "high" if symmetry_modes else "low",
            },
            "overall_risk_level": overall_risk,
            "likely_failure_modes": likely_failure_modes,
        }
    }


def _stagnating_tail(values: list[float], *, window: int = 3) -> bool:
    if len(values) < window + 1:
        return False
    tail = values[-window:]
    start = tail[0]
    return all(abs(val - start) <= 0.1 * max(abs(start), 1e-12) for val in tail[1:])


def _oscillatory_signal(values: list[float]) -> bool:
    if len(values) < 3:
        return False
    diffs = [cur - prev for prev, cur in zip(values, values[1:])]
    return any(prev * curr < 0 for prev, curr in zip(diffs, diffs[1:]))


def _compute_volume(vectors: list[list[float]]) -> float | None:
    if len(vectors) != 3 or any(len(v) != 3 for v in vectors):
        return None
    a1, a2, a3 = vectors
    return abs(
        a1[0] * (a2[1] * a3[2] - a2[2] * a3[1])
        - a1[1] * (a2[0] * a3[2] - a2[2] * a3[0])
        + a1[2] * (a2[0] * a3[1] - a2[1] * a3[0])
    )


def _detect_variable_cell(lines: list[str], input_parameters: dict[str, dict[str, object]]) -> bool:
    if _CELL_DOFREE_RE.search("\n".join(lines)):
        return True
    control_text = str(input_parameters.get("control", {})).lower()
    if "vc-relax" in control_text or "cell_dofree" in control_text:
        return True
    return any("variable-cell" in line.lower() for line in lines)


def _detect_force_threshold(lines: list[str]) -> float | None:
    for line in lines:
        if "force convergence thresh." in line.lower() or "forc_conv_thr" in line.lower():
            candidate = _extract_last_scalar([line], re.compile(rf"({_FLOAT_RE})"))
            if candidate is not None:
                return candidate
    return None


def _extract_k_mesh(lines: list[str]) -> list[int] | None:
    for i, line in enumerate(lines[:-1]):
        if line.strip().startswith("K_POINTS") and "automatic" in line:
            values = re.findall(r"-?\d+", lines[i + 1])
            if len(values) >= 3:
                return [int(values[0]), int(values[1]), int(values[2])]
    return None


def _extract_number_after_keyword(lines: list[str], pattern: re.Pattern[str]) -> int | None:
    for line in lines:
        match = pattern.search(line)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def _extract_last_scalar(lines: list[str], pattern: re.Pattern[str]) -> float | None:
    last_match: str | None = None
    for line in lines:
        match = pattern.search(line)
        if match:
            last_match = match.group(1)
    if last_match is None:
        return None
    return _to_float(last_match)


def _numeric_for_keys(input_parameters: dict[str, dict[str, object]], *keys: list[str]) -> float | None:
    for key_path in keys:
        if len(key_path) != 2:
            continue
        section = input_parameters.get(key_path[0], {})
        value = section.get(key_path[1]) if isinstance(section, dict) else None
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _first_number(input_parameters: dict[str, dict[str, object]], *paths: list[str]) -> float | None:
    for path in paths:
        section = input_parameters.get(path[0], {})
        value = section.get(path[1]) if isinstance(section, dict) else None
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _to_ev(value: float | None) -> float | None:
    if value is None:
        return None
    return value * RY_TO_EV


def _to_float(raw: str) -> float:
    return float(raw.replace("D", "E").replace("d", "E"))


def _is_float_like(value: str) -> bool:
    return bool(re.fullmatch(_FLOAT_RE, value.replace("D", "E").replace("d", "E")))


def _extract_numbers(text: str) -> list[float]:
    values = re.findall(_FLOAT_RE, text)
    return [_to_float(value) for value in values]


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
        try:
            return int(value)
        except ValueError:
            return value
    if re.fullmatch(_FLOAT_RE, value):
        try:
            return _to_float(value)
        except ValueError:
            return value
    return value


def _composition_changed(atomic_series: list[list[dict[str, object]]]) -> bool:
    if len(atomic_series) < 2:
        return False
    signatures = [
        tuple(sorted(atom.get("element") for atom in atoms if "element" in atom))
        for atoms in atomic_series
        if atoms
    ]
    return len({s for s in signatures}) > 1


def _symmetry_changed(atomic_series: list[list[dict[str, object]]]) -> bool:
    if len(atomic_series) < 2:
        return False
    signatures: list[tuple[Any, ...]] = []
    for atoms in atomic_series:
        if not atoms:
            continue
        sig: list[tuple[Any, Any, Any, Any]] = []
        for atom in atoms:
            try:
                sig.append(
                    (
                        atom.get("element"),
                        round(float(atom.get("x", 0.0)), 6),
                        round(float(atom.get("y", 0.0)), 6),
                        round(float(atom.get("z", 0.0)), 6),
                    )
                )
            except (TypeError, ValueError):
                continue
        signatures.append(tuple(sorted(sig)))

    if len(signatures) < 2:
        return False
    return any(signature != signatures[0] for signature in signatures[1:])


def _replace_cell(geometry: RelaxGeometry, block: dict[str, Any]) -> RelaxGeometry:
    block_volume = block.get("volume")
    next_volume = block_volume if geometry.volume is None else geometry.volume
    return RelaxGeometry(
        atomic_positions=[dict(atom) for atom in geometry.atomic_positions],
        cell_parameters=[list(row) for row in block["cell_parameters"]],
        volume=next_volume,
        lattice_vectors=[list(row) for row in block.get("lattice_vectors", block["cell_parameters"])],
    )


def _replace_atomic_positions(geometry: RelaxGeometry, block: dict[str, Any]) -> RelaxGeometry:
    coordinate_system = block.get("coordinate_system")
    atomic_positions: list[dict[str, object]] = []
    for atom in block.get("atomic_positions", []):
        atom_copy = dict(atom)
        atom_copy["coordinate_system"] = coordinate_system
        atomic_positions.append(atom_copy)

    return RelaxGeometry(
        atomic_positions=atomic_positions,
        cell_parameters=[list(row) for row in geometry.cell_parameters],
        volume=geometry.volume,
        lattice_vectors=[list(row) for row in geometry.lattice_vectors],
    )


def _update_volume(geometry: RelaxGeometry, raw_volume: str) -> RelaxGeometry:
    return RelaxGeometry(
        atomic_positions=[dict(atom) for atom in geometry.atomic_positions],
        cell_parameters=[list(row) for row in geometry.cell_parameters],
        lattice_vectors=[list(row) for row in geometry.lattice_vectors],
        volume=_to_float(raw_volume),
    )


def _empty_geometry() -> RelaxGeometry:
    return RelaxGeometry([], [], None, [])


def _computed_enthalpy(total_energy: float | None, pressure_kbar: float | None, volume_bohr3: float | None) -> float | None:
    if total_energy is None or pressure_kbar is None or volume_bohr3 is None:
        return None
    # 1 Ry / a0^3 = 14710.507846843304 GPa
    pressure_ry_per_bohr3 = pressure_kbar / 14710.507846843304
    return total_energy + pressure_ry_per_bohr3 * volume_bohr3


def _last_value(values: list[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None:
            return value
    return None


def _marker_line(line: str) -> bool:
    return bool(
        _SELF_CONSISTENT_START_RE.search(line)
        or _SELF_CONSISTENT_END_RE.search(line)
        or _FORCES_HEADER_RE.search(line)
        or _ATOMIC_POSITIONS_RE.search(line)
        or _CELL_PARAMETERS_RE.search(line)
        or _STRESS_HEADER_RE.search(line)
        or _BEGIN_FINAL_RE.search(line)
        or _END_FINAL_RE.search(line)
        or _BFGS_GEOM_RE.search(line)
        or _END_BFGS_RE.search(line)
    )


def _load_text_and_source(text_or_path: str | Path, source: str | Path | None) -> tuple[str, str]:
    if isinstance(text_or_path, Path):
        return text_or_path.read_text(encoding="utf-8", errors="replace"), _source_label(
            source if source is not None else text_or_path
        )

    candidate_path = Path(text_or_path)
    if "\n" not in text_or_path and candidate_path.is_file():
        return candidate_path.read_text(encoding="utf-8", errors="replace"), _source_label(
            source if source is not None else candidate_path
        )

    return text_or_path, _source_label(source if source is not None else "text")


def _source_label(source: str | Path | None) -> str:
    if source is None:
        return "text"
    if isinstance(source, Path):
        return source.name
    source_text = str(source)
    if "/" in source_text or "\\" in source_text:
        normalized = source_text.replace("\\", "/")
        return normalized.rsplit("/", 1)[-1]
    return source_text


__all__ = [
    "RelaxOutput",
    "RelaxStep",
    "RelaxScfStep",
    "RelaxGeometry",
    "RelaxForces",
    "RelaxStress",
    "parse_relax_output",
    "parse_relax_outputs",
]
