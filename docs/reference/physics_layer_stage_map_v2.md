# Physics Layer Stage Map v2

This map keeps the public `workflows/stages.yaml` stage identifiers visible to
the repository health check. The v2 platform keeps these workflow stages as
legacy migration inventory until each stage is re-expressed through the
`calculator -> cleaned result -> analysis` boundary.

## Stage IDs

- `00_structure`
- `01_pseudopotentials`
- `02_preconv`
- `03_relax`
- `04_conv`
- `05_final_relax`
- `06_scf`
- `07_bands`
- `08_dos`
- `09_charge`
- `10_workfunction`
- `11_bader`
- `12_ph_stability`
- `13_q2r_matdyn`
- `14_epc`
- `15_tc`
- `16_elastic`
- `17_aimd`
- `18_exfoliation`
- `19_optical`
- `20_report`
