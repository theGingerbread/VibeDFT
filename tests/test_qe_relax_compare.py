from __future__ import annotations

from pathlib import Path

from vibedft.calculator.qe.relax import compare_relax_outputs


def _make_relax_output(
    *,
    label: str,
    energies: list[float],
    converged: list[bool],
    forces: list[float],
    job_done: bool,
) -> str:
    assert len(energies) == len(converged) == len(forces)

    lines = [
        f"Program PWSCF v.7.3 starts on 30Jun2026 ({label})",
        "",
        "&CONTROL",
        f"  calculation = '{label}'",
        "/",
    ]

    for step_index, (energy, is_converged, force) in enumerate(
        zip(energies, converged, forces),
        start=1,
    ):
        lines.append(" Self-consistent Calculation")
        lines.append(f"iteration #  1     total energy              =    {energy:.8f} Ry")
        lines.append("estimated scf accuracy    <       1.0E-03 Ry")
        if is_converged:
            lines.append("convergence has been achieved in   1 iterations")
        else:
            lines.append("convergence NOT achieved after 100 iterations")
        lines.append("Forces acting on atoms (cartesian axes, Ry/au):")
        lines.append(f" atom    1 type  1   force =  {force: .6f}  0.000000  0.000000")
        lines.append(f" atom    2 type  1   force = {-force: .6f}  0.000000  0.000000")
        lines.append(f" total force   {force:.6E}")
        lines.append("     total   stress  (Ry/bohr**3)                   (kbar)     P=      5.0")
        lines.append("  0.10  0.00  0.00   1.00  2.00  3.00")
        lines.append("  0.00  0.10  0.00   4.00  5.00  6.00")
        lines.append("  0.00  0.00  0.10   7.00  8.00  9.00")
        lines.append(f"BFGS Geometry Optimization")
        lines.append("  number of scf cycles    =   1")
        lines.append("  number of bfgs steps    =   0")
        lines.append("End of BFGS Geometry Optimization")
        lines.append("End of self-consistent calculation")
        if step_index < len(energies):
            lines.append("ATOMIC_POSITIONS (crystal)")
            lines.append("Na  0.000100  0.000200  0.000300")

    if job_done:
        lines.append("JOB DONE.")
    return "\n".join(lines)


def test_compare_relax_outputs_prefers_completed_over_blocked_energy() -> None:
    completed = _make_relax_output(
        label="relax",
        energies=[-10.0, -10.1],
        converged=[True, True],
        forces=[0.20, 0.02],
        job_done=True,
    )
    blocked = _make_relax_output(
        label="relax",
        energies=[-11.0, -11.1],
        converged=[True, False],
        forces=[0.40, 0.35],
        job_done=False,
    )

    comparison = compare_relax_outputs([completed, blocked])

    assert comparison.best_source == "text:0"
    assert comparison.runs[0].source == "text:0"
    assert comparison.runs[0].rank == 1
    assert comparison.runs[0].status == "completed"
    assert comparison.runs[1].status == "blocked"
    assert comparison.runs[0].delta_to_best_energy_ry == 0.0
    assert comparison.runs[1].delta_to_best_energy_ry == -1.0
    assert comparison.runs[1].delta_to_best_energy_ry is not None


def test_compare_relax_outputs_ranks_energy_within_completed() -> None:
    high = _make_relax_output(
        label="relax",
        energies=[-8.0],
        converged=[True],
        forces=[0.01],
        job_done=True,
    )
    low = _make_relax_output(
        label="relax",
        energies=[-10.0],
        converged=[True],
        forces=[0.02],
        job_done=True,
    )

    comparison = compare_relax_outputs([high, low])

    assert comparison.runs[0].source == "text:1"
    assert comparison.runs[0].final_energy_ry == -10.0
    assert comparison.runs[0].status == "completed"
    assert comparison.runs[1].final_energy_ry == -8.0


def test_compare_relax_outputs_file_input_uses_file_names(tmp_path: Path) -> None:
    out_a = tmp_path / "a_relax.out"
    out_b = tmp_path / "b_relax.out"

    out_a.write_text(
        _make_relax_output(label="relax", energies=[-1.0], converged=[True], forces=[0.01], job_done=True),
        encoding="utf-8",
    )
    out_b.write_text(
        _make_relax_output(label="relax", energies=[-2.0], converged=[False], forces=[0.20], job_done=True),
        encoding="utf-8",
    )

    comparison = compare_relax_outputs([out_a, out_b])

    assert comparison.runs[0].source == "a_relax.out"
    assert comparison.runs[1].source == "b_relax.out"


def test_compare_relax_outputs_status_counts_and_best_gap(
    tmp_path: Path,
) -> None:
    out_a = tmp_path / "a_relax.out"
    out_b = tmp_path / "b_relax.out"
    out_c = tmp_path / "c_relax.out"

    out_a.write_text(
        _make_relax_output(label="relax", energies=[-1.0], converged=[True], forces=[0.01], job_done=True),
        encoding="utf-8",
    )
    out_b.write_text(
        _make_relax_output(label="relax", energies=[-2.0], converged=[True], forces=[0.02], job_done=True),
        encoding="utf-8",
    )
    out_c.write_text(
        _make_relax_output(label="relax", energies=[-1.5], converged=[False], forces=[0.03], job_done=False),
        encoding="utf-8",
    )

    comparison = compare_relax_outputs([out_a, out_b, out_c])

    assert comparison.best_source == "b_relax.out"
    assert comparison.best_energy_gap_ry == 0.0
    assert comparison.status_counts == {
        "completed": 2,
        "running": 1,
        "oscillating": 0,
        "blocked": 0,
        "failed": 0,
        "no_data": 0,
    }
