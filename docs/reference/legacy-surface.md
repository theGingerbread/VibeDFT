# Legacy Surface

The directories below remain in the repository only as migration inventory.
They are not canonical for `VibeDFT v2`.

## Legacy package surface

- `src/vibedft/agent/`
- `src/vibedft/analyzers/`
- `src/vibedft/classifiers/`
- `src/vibedft/cli/`
- `src/vibedft/convergence/`
- `src/vibedft/core/`
- `src/vibedft/decision/`
- `src/vibedft/epw/`
- `src/vibedft/frontend/`
- `src/vibedft/generators/`
- `src/vibedft/knowledge_base/`
- `src/vibedft/models/`
- `src/vibedft/parsers/`
- `src/vibedft/postprocess/`
- `src/vibedft/properties/`
- `src/vibedft/research/`
- `src/vibedft/semantics/`
- `src/vibedft/server/`
- `src/vibedft/spin/`
- `src/vibedft/validators/`

## Canonical package surface

- `src/vibedft/main/`
- `src/vibedft/calculator/`
- `src/vibedft/structure/`
- `src/vibedft/analysis/`
- `src/vibedft/_shared/`

## Rule

When a legacy capability is migrated, the v2 version must be expressed inside
the canonical surface instead of extending the old package hierarchy.
