# QE Relax Pipeline

This package provides QE `pw.x` relax/vc-relax output parsing and monitoring.

## Exposed API

- `parse_relax_output` / `parse_relax_outputs`
- `monitor_relax_output`
- `compare_relax_outputs` (multi-output ranking + stability-aware comparison)

## Typical flow

1. `parse_relax_output` parses a single relax log into a nested trajectory.
2. `monitor_relax_output` classifies runtime state (`completed|running|blocked|oscillating|failed|no_data`).
3. `compare_relax_outputs` compares multiple candidate relax trajectories.
