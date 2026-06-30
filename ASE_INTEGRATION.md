# ASE Integration Notice

**VibeDFT calls [ASE](https://wiki.fysik.dtu.dk/ase/) (Atomic Simulation
Environment) for structure I/O and symmetry analysis.**

This file is the canonical reference for *how* the integration is wired,
so any contributor working in `src/vibedft/` can quickly locate the
boundary between ASE (generic) and VibeDFT (deterministic, QE-native,
evidence-tracked).

## Install the ASE backend

```bash
# Recommended on Preston's Mac (Python 3.14)
pip install -e ".[all]"

# Minimal ASE-only install (no plot/server)
pip install -e ".[ase]"
```

ASE ≥ 3.22 and spglib ≥ 2.0 are declared as the `ase` extra in
`pyproject.toml`. They are **optional** — VibeDFT falls back to the
legacy regex parser when ASE is missing (POSCAR + QE input only; **CIF
is unsupported in fallback mode**).

## Where VibeDFT calls ASE

| File | Calls | Purpose |
|---|---|---|
| `src/vibedft/core/structure.py` | `ase.io.read`, `ase.Atoms`, `ase.build.*` (planned) | Structure parsing + structural manipulation |
| `src/vibedft/core/structure.py` | `spglib.get_symmetry_dataset` | Space-group / Wyckoff positions (via ASE dep) |
| `src/vibedft/cli.py` (subcommand `analyze structure`) | `parse_structure` dispatcher | Routes `.cif` → ASE, `.in/.inp` → `espresso-in`, etc. |

The single integration point is `core/structure.py`. ASE is never
imported elsewhere in the package — this keeps the deterministic
parser/classifier/validator/agent path free of generic-scientific-Python
coupling.

## The ASE ↔ VibeDFT division of labour

| Concern | Owner | Notes |
|---|---|---|
| Read CIF / POSCAR / QE-in / QE-out | **ASE** via `ase.io.read` | With fallback to regex parser |
| Build / mutate structures (`bulk`, `surface`, `adsorbate`) | **ASE** directly | VibeDFT exposes nothing here — use ASE in your notebook/script |
| Space-group / Wyckoff / symm ops | **spglib** (via ASE) | ASE pulls spglib in on most platforms |
| QE namelist parsing (`&CONTROL`, `&SYSTEM`, …) | **VibeDFT** `parsers/qe_input_parser.py` | Out of ASE's scope; kept as-is |
| Hard-rule validation (la2F, PH≠EPC, nq3=1) | **VibeDFT** `validators/` | Deterministic, QE-specific |
| 2D metrics (vacuum sufficiency, layer count, buckling) | **VibeDFT** `compute_2d_metrics` | Works on `Structure` dataclass; format-agnostic |
| Physics verdict scoring + evidence packs | **VibeDFT** `decision/`, `agent/` | No ASE involvement; LLM never sees raw files |

## Public API (stable contract)

`core/structure.py` exposes the following names. Their signatures and
return types are part of the stable API — downstream modules
(`analyzers/material_analyzer.py`, `core/report.py`, `cli.py`) rely on
these. **Do not change them when upgrading ASE.**

```python
# Dataclasses (frozen shape)
Lattice(matrix: list[list[float]])
Atom(element: str, x: float, y: float, z: float, label: str = "")
Structure(lattice, atoms, formula, source)
TwoDMetrics(vacuum_thickness_ang, layer_thickness_ang, interlayer_distance_ang,
            slab_has_vacuum, vacuum_sufficient, n_layers, buckling_ang)

# Parsers — return a Structure (or None on parse failure)
parse_structure(filepath) -> Structure | None       # dispatcher; routes by extension
parse_structure_from_qe_input(path) -> Structure | None
parse_structure_from_qe_output(path) -> Structure | None   # ASE espresso-out, index=-1
parse_structure_from_poscar(path) -> Structure | None      # also accepts CIF/XYZ when ASE present
parse_structure_from_cif(path) -> Structure | None         # requires the ase extra

# Cross-conversion (requires the ase extra)
Structure.to_ase_atoms() -> ase.Atoms

# Analysis
compute_2d_metrics(structure) -> TwoDMetrics
compute_symmetry(structure) -> dict[str, Any]
```

## Backend probe

ASE availability is checked once and cached:

```python
from vibedft.core.structure import _ase_available
_ase_available()  # bool — True iff ase + spglib both importable
```

All ASE imports go through this probe, so the fallback path stays
intact and the test suite runs identically with or without ASE
installed.

## Upgrading ASE

The integration only depends on the stable `ase.io.read`/`ase.Atoms`
surface, which has been stable since ASE 3.22 (2022). When bumping:

- Check `ase.io.read(format='espresso-in'|'espresso-out'|'cif'|'vasp')`
  behaves the same on the HfBr2 / HfI2 fixture set
- Run `pytest tests/test_report.py tests/test_physics_analyzers.py -v`
  to confirm the structure-extraction path is unaffected
- The `index=-1` argument to `espresso-out` selects the last frame
  (relaxed geometry for vc-relax); keep this convention

## See also

- `README.md` — overall project purpose and roadmap
- `docs/reference/architecture.md` — full pipeline diagram
- `docs/roadmaps/ROADMAP.md` — near-term plan incl. the ASE-backed analyzer
  extensions (the original mandate lived in the now-superseded 2026-06-07
  roadmap, §2.1)
- `src/vibedft/core/structure.py` — the integration implementation
```