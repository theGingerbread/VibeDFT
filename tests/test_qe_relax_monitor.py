from __future__ import annotations

from dataclasses import is_dataclass

from vibedft.calculator.qe.relax import monitor_relax_output


def _make_relax_steps(energies: list[float], *, converged_messages: list[bool] | None = None) -> str:
    if converged_messages is None:
        converged_messages = [True] * len(energies)

    chunks: list[str] = ["Program PWSCF v.7.3 starts on 30Jun2026", ""]
    for step_index, energy in enumerate(energies):
        converged = "convergence has been achieved" if converged_messages[step_index] else "convergence NOT achieved after 100 iterations"
        chunks.append("Self-consistent Calculation")
        chunks.append(f"iteration #  1     total energy              =    {energy: .8f} Ry")
        chunks.append("estimated scf accuracy    <       1.0E-03 Ry")
        chunks.append(converged)
        chunks.append("Forces acting on atoms (cartesian axes, Ry/au):")
        chunks.append(" atom    1 type  1   force =     0.0010   0.0000   0.0000")
        chunks.append(" atom    2 type  1   force =    -0.0010   0.0000  -0.0000")
        chunks.append(" total force   1.0E-03")
        chunks.append("     total   stress  (Ry/bohr**3)                   (kbar)     P=      5.0")
        chunks.append("  0.10  0.00  0.00   1.00  2.00  3.00")
        chunks.append("  0.00  0.10  0.00   4.00  5.00  6.00")
        chunks.append("  0.00  0.00  0.10   7.00  8.00  9.00")
        chunks.append("BFGS Geometry Optimization")
        chunks.append("  number of scf cycles    =   2")
        chunks.append("  number of bfgs steps    =   0")
        chunks.append(f"ATOMIC_POSITIONS (crystal)")
        chunks.append("Na  0.000000  0.000000  0.000000")
        chunks.append("Cl  0.500000  0.500000  0.500000")
        chunks.append("End of BFGS Geometry Optimization")
        chunks.append("End of self-consistent calculation")
    return "\n".join(chunks)


def test_relax_monitor_completed_after_job_done_and_convergence() -> None:
    text = "\n".join(
        [
            _make_relax_steps([-10.0]),
            "JOB DONE.",
            "",
        ]
    )

    snapshot = monitor_relax_output(text, source="relax.out")

    assert is_dataclass(snapshot)
    assert snapshot.status == "completed"
    assert snapshot.job_done is True
    assert snapshot.ionic_converged is True
    assert snapshot.scf_converged is True
    assert snapshot.last_step == 0
    assert snapshot.last_total_energy_ry == -10.0
    assert snapshot.suggested_actions == []


def test_relax_monitor_detects_fatal_failure() -> None:
    text = """Program PWSCF v.7.3 starts on 30Jun2026
Self-consistent Calculation
iteration #  1     total energy              =    -10.10000000 Ry
estimated scf accuracy    <       1.0E-03 Ry
convergence has been achieved in   1 iterations
JOB DONE.
MPI_ABORT was invoked on rank 0
"""

    snapshot = monitor_relax_output(text, source="relax.out")

    assert snapshot.status == "failed"
    assert snapshot.job_done is True
    assert snapshot.ionic_converged is True
    assert snapshot.scf_converged is False
    assert snapshot.last_step == 0
    assert snapshot.summary.startswith("relax failed with severity markers")


def test_relax_monitor_no_data() -> None:
    snapshot = monitor_relax_output("Submitted batch job 123456\n", source="relax.out")

    assert snapshot.status == "no_data"
    assert snapshot.job_done is False
    assert snapshot.last_step is None
    assert snapshot.last_total_energy_ry is None
    assert snapshot.issues == []


def test_relax_monitor_flags_oscillation() -> None:
    text = _make_relax_steps([-10.0, -9.0, -10.0])

    snapshot = monitor_relax_output(text, source="relax.out")

    assert snapshot.status == "oscillating"
    assert snapshot.ionic_converged is True
    assert snapshot.scf_converged is True
    assert snapshot.last_step == 2
    assert snapshot.oscillating is True
    assert snapshot.summary.startswith("Relaxation trajectory shows non-monotonic energy/force behavior")
