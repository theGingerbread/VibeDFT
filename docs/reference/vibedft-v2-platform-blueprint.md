# VibeDFT v2 Platform Blueprint

## Goal

Rebuild `VibeDFT` as a public, QE-first platform repository rather than a
research-case repository.

## Platform Boundary

- `main/` owns CLI, config, routing, and project layout.
- `calculator/` owns calculator-specific preparation, execution, monitoring,
  parsing, and cleaned-result emission.
- `structure/` owns structure-centric transforms and batch utilities.
- `analysis/` owns physics analysis on cleaned results only.
- `_shared/` owns internal contracts, errors, and shared helpers.

## Phase 1 Scope

Phase 1 is `QE-first`. The repository carries the multi-layer platform shape,
but only `calculator/qe/` is scaffolded as a first-class backend.

The first implemented backend surfaces are intentionally narrow:

- common QE output event detection
- SCF parsing, monitoring, and workflow-readiness assessment
- relax / vc-relax parsing, monitoring, and run comparison
- phonon parsing and monitoring

## QE Task Contract

Each QE task module follows the same internal layout:

```text
calculator/qe/<task>/
├── params.py
├── prepare.py
├── run.py
├── monitor.py
├── parse.py
└── clean.py
```

`parse.py` may preserve QE-specific semantics. `clean.py` must terminate in a
calculator-neutral cleaned result contract for downstream `analysis/`.

Until a task has real-output tests and a cleaned-result adapter, its stage files
remain contractual placeholders rather than production workflow support.

## Migration Rule

The current repository content is treated as legacy implementation inventory.
Nothing from the legacy tree is canonical in v2 unless it is explicitly
re-expressed inside the v2 package boundary.
