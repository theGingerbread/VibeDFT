from __future__ import annotations

from dataclasses import is_dataclass

from vibedft.calculator.qe.relax import parse_relax_output


_SYNTH_RELAX = """\
Program PWSCF v.7.4 starts

&CONTROL
  calculation = 'relax'
/
&SYSTEM
  ibrav = 0
  nat = 2
  ntyp = 1
  ecutwfc = 40
  ecutrho = 400
/
 Self-consistent Calculation
iteration #  1     total energy              =    -10.00000000 Ry
estimated scf accuracy    <       1.0E-03 Ry
iteration #  2     total energy              =    -10.10000000 Ry
estimated scf accuracy    <       1.0E-04 Ry
convergence has been achieved in   2 iterations
Forces acting on atoms (cartesian axes, Ry/au):
 atom    1 type  1   force =     0.0001   0.0000   0.0001
 atom    2 type  1   force =    -0.0001   0.0000  -0.0001
 total force   1.0E-04
     total   stress  (Ry/bohr**3)                   (kbar)     P=        5.0
  0.10  0.00  0.00   1.00  2.00  3.00
  0.00  0.10  0.00   4.00  5.00  6.00
  0.00  0.00  0.10   7.00  8.00  9.00
BFGS Geometry Optimization
  number of scf cycles    =   2
  number of bfgs steps    =   0
ATOMIC_POSITIONS (crystal)
Na  0.000000  0.000000  0.000000
Cl  0.500000  0.500000  0.500000
CELL_PARAMETERS (angstrom)
3.000000 0.000000 0.000000
0.000000 3.000000 0.000000
0.000000 0.000000 3.000000
Self-consistent Calculation
iteration #  1     total energy              =    -10.25000000 Ry
estimated scf accuracy    <       1.0E-02 Ry
convergence has been achieved
Forces acting on atoms (cartesian axes, Ry/au):
 atom    1 type  1   force =     0.0002   0.0000   0.0002
 atom    2 type  1   force =    -0.0002   0.0000  -0.0002
 total force   2.0E-04
     total   stress  (Ry/bohr**3)                   (kbar)     P=        6.0
  0.11  0.00  0.00   1.00  2.00  3.00
  0.00  0.11  0.00   4.00  5.00  6.00
  0.00  0.00  0.11   7.00  8.00  9.00
BFGS Geometry Optimization
 convergence NOT achieved after 100 iterations
End of BFGS Geometry Optimization
End of self-consistent calculation
Begin final coordinates
ATOMIC_POSITIONS (crystal)
Na  0.000100  0.000000  0.000000
Cl  0.500100  0.500000  0.500000
End final coordinates
"""

_SYNTH_RELAX_PREAMBLE_VOLUME = """\
Program PWSCF v.7.3 starts on 30Jun2026
     unit-cell volume          =    125.4321 (a.u.)^3

&CONTROL
  calculation = 'relax'
/
&SYSTEM
  ibrav = 0
  nat = 1
  ntyp = 1
/
 Self-consistent Calculation
iteration #  1     total energy              =    -5.00000000 Ry
estimated scf accuracy    <       1.0E-03 Ry
convergence has been achieved in   1 iterations
Forces acting on atoms (cartesian axes, Ry/au):
 atom    1 type  1   force =     0.0010   0.0000   0.0000
 total force   1.0E-03
     total   stress  (Ry/bohr**3)                   (kbar)     P=        5.0
  0.10  0.00  0.00   1.00  2.00  3.00
  0.00  0.10  0.00   4.00  5.00  6.00
  0.00  0.00  0.10   7.00  8.00  9.00
BFGS Geometry Optimization
 convergence NOT achieved after 100 iterations
End of self-consistent calculation
ATOMIC_POSITIONS (crystal)
Na  0.000100  0.000200  0.000300
"""


def test_parse_relax_output_builds_nested_trajectory_and_final_coordinates() -> None:
    output = parse_relax_output(_SYNTH_RELAX, source="relax.out")

    assert is_dataclass(output)
    assert output.source == "relax.out"
    assert len(output.relaxation_trajectory) == 2

    first = output.relaxation_trajectory[0]
    second = output.relaxation_trajectory[1]

    assert len(first.scf_trajectory) == 2
    assert first.scf_trajectory[0].iteration == 1
    assert first.scf_trajectory[-1].convergence_flag is True
    assert first.geometry.atomic_positions
    assert second.scf_trajectory
    assert second.geometry.atomic_positions

    assert first.step_convergence == {
        "scf_converged": True,
        "ionic_converged": True,
    }
    assert second.step_convergence == {
        "scf_converged": True,
        "ionic_converged": False,
    }

    assert output.final_structure["atomic_positions"] == second.geometry.atomic_positions
    assert output.final_observables["total_energy"] == -10.25
    assert output.final_observables["pressure"] == 6.0
    assert output.global_convergence == {
        "ionic_converged": False,
        "scf_converged_all_steps": True,
        "geometry_converged": False,
    }
    assert output.issues == []


def test_relax_schema_contains_required_keys() -> None:
    output = parse_relax_output(_SYNTH_RELAX, source="relax.out")
    schema = output.to_schema()

    assert list(schema.keys()) == [
        "system",
        "input_parameters",
        "numerical_setup",
        "relaxation_trajectory",
        "global_convergence",
        "final_structure",
        "final_observables",
        "diagnostics",
    ]
    assert schema["system"]["program"] == "PWSCF"
    assert schema["numerical_setup"]["k_points"]["mesh"] in (None, [6, 6, 1])  # synthetic fixture may omit explicit K_POINTS
    assert schema["relaxation_trajectory"][0]["scf_trajectory"][0]["total_energy"] == -10.0
    assert schema["relaxation_trajectory"][1]["forces"]["max_force"] == 0.0002 * (2 ** 0.5)
    assert schema["diagnostics"]["stability_report"]["overall_risk_level"] in {"low", "medium", "high"}


def test_parse_relax_output_reuses_preamble_unit_cell_volume() -> None:
    output = parse_relax_output(_SYNTH_RELAX_PREAMBLE_VOLUME, source="relax.out")

    assert output.final_observables["volume"] == 125.4321
