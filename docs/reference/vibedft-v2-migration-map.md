# VibeDFT v2 Migration Map

This repository establishes the v2 package boundary and starts migrating the
first QE calculator surfaces behind that boundary.

## What is canonical now

- `src/vibedft/main/`
- `src/vibedft/calculator/`
- `src/vibedft/structure/`
- `src/vibedft/analysis/`
- `src/vibedft/_shared/`

## What remains legacy

All pre-existing modules outside the v2 boundary are treated as migration
inventory. They are still present in the repository, but they are not the
target architecture for future fill-in work.

## Intended next migration order

1. Harden `CleanedResult` and shared result/error contracts.
2. Add cleaned-result adapters for `calculator/qe/scf`, `relax`, `vc_relax`,
   and `phonon`.
3. Migrate `calculator/qe/bands`, `dos`, and `pdos` from legacy parser logic.
4. Fill execution-oriented stages: `params.py`, `prepare.py`, `run.py`.
5. Build `analysis/` only against cleaned results, not raw QE outputs.

## Already Started

- `calculator/qe/common/output_events.py`
- `calculator/qe/scf/parse.py`
- `calculator/qe/scf/monitor.py`
- `calculator/qe/relax/parse.py`
- `calculator/qe/relax/monitor.py`
- `calculator/qe/relax/compare.py`
- `calculator/qe/vc_relax/parse.py`
- `calculator/qe/vc_relax/monitor.py`
- `calculator/qe/phonon/parse.py`
- `calculator/qe/phonon/monitor.py`
