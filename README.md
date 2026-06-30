# VibeDFT

Public QE-first platform skeleton for deterministic DFT workflow execution,
cleaned-result normalization, and calculator-neutral analysis.

## Repository Status

This repository is being rebuilt as `VibeDFT v2`.

The canonical architecture is now:

```text
src/vibedft/
├── main/
├── calculator/
├── structure/
├── analysis/
└── _shared/
```

Phase 1 is `QE-first`. The first-class backend boundary is:

```text
src/vibedft/calculator/qe/
```

Each QE task package follows the same stage layout:

```text
<task>/
├── params.py
├── prepare.py
├── run.py
├── monitor.py
├── parse.py
└── clean.py
```

## Canonical vs Legacy

The repository still contains pre-v2 modules and docs so migration can happen
incrementally. Those directories are retained as legacy inventory, not as the
target architecture.

- Canonical v2 boundary: `main`, `calculator`, `structure`, `analysis`,
  `_shared`
- Legacy inventory: `agent`, `analyzers`, `classifiers`, `cli`, `convergence`,
  `core`, `decision`, `epw`, `frontend`, `generators`, `knowledge_base`,
  `models`, `parsers`, `postprocess`, `properties`, `research`, `semantics`,
  `server`, `spin`, `validators`

See:

- `docs/reference/vibedft-v2-platform-blueprint.md`
- `docs/reference/vibedft-v2-migration-map.md`
- `docs/reference/legacy-surface.md`

## Current State

This repository now carries the v2 platform frame plus the first concrete QE
adapter surfaces:

- top-level package boundary
- QE task skeletons
- cleaned-result contract
- migration documentation
- QE output event normalization
- SCF parse/monitor/readiness primitives
- relax and vc-relax parse/monitor/compare primitives
- phonon parse/monitor primitives

Unfilled QE tasks remain as explicit placeholders until they receive tests,
real-output fixtures, parser/monitor behavior, and cleaned-result adapters.
