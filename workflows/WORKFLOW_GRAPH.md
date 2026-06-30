# VibeDFT QE_DFT — Workflow Dependency Graph

```
                         [00_structure]
                       (CIF/XYZ -> QE geometry)
                              |
                         [01_pseudopotentials]
                       (select + validate pseudo)
                              |
                          [02_preconv]
                       (coarse ecut/k bounds)
                              |
                          [03_relax]
                       (coarse vc-relax, cell_dofree=2Dxy)
                              |
                           [04_conv]
                   (ecut/kmesh/vacuum/smearing convergence)
                              |
                        [05_final_relax]  <-- CANONICAL GEOMETRY
                   (production vc-relax, converged params)
                              |
                         [06_scf]  <-- CRITICAL CHOKEPOINT
                      (charge density for everything)
         ___________/    |     \_____________
        /         /      |        \           \
       /         /       |         \           \
[07_bands]  [08_dos]  [12_ph_stability]  [19_optical]   [06_scf_dense]
(band      (NSCF+      (phonon stability,  (dielectric    (SEPARATE dense
 structure) dos.x+       NO el_ph!)         function)      SCF for EPC)
            projwfc.x)        |                                |
            /  |  \      [13_q2r_matdyn]  <-- TERMINAL    [14_epc]
           /   |   \     (q2r.x: NO la2F!            (ph.x: WITH el_ph!
[09_charge] [10_wf] [11_bader]  matdyn.x: disp)        internal q2r/matdyn
(planar     (work    (Bader                              with la2F=.true.)
 average)    func)    QTAIM)                                  |
                                                         [15_tc]
                                                   (lambda.x: Tc estimate)

[16_elastic]     [17_aimd]     [18_exfoliation]
(elastic          (MD @ T)      (cleavage energy)
 constants)


                         [20_report]
                   (aggregate ALL -> physics verdict)
```

## Linear Chains

```
Chain A (Geometry):      00 -> 01 -> 02 -> 03 -> 04 -> 05
Chain B (Electronic):    06 -> 07
Chain C (DOS/Charge):    06 -> 08 -> 09 / 10 / 11
Chain D (Phonon Stability):  06 -> 12 -> 13  [TERMINAL — does NOT feed EPC]
Chain E (SC-EPC):        06_dense -> 14 -> 15  [SEPARATE chain, independent of D]
Chain F (Properties):    05 -> 16 / 17 / 18
Chain G (Optical):       06 -> 19
Chain H (Report):        ALL -> 20
```

## Critical Stage Boundaries

| Boundary | Why |
|----------|-----|
| **03_relax != 05_final_relax** | Coarse vs converged parameters |
| **PH_STABILITY (12) != PH_EPC (14)** | Different SCF, different q-mesh, different purpose |
| **13_q2r_matdyn TERMINATES stability** | Does NOT feed EPC chain (avoids file-link contamination) |
| **14_epc starts FRESH from 06_scf_dense** | EPC has its own internal q2r/matdyn stages |
| **la2F NOT in q2r.x (13)** | la2F is a matdyn.x parameter, not q2r.x |
| **Tc (15) requires EPC (14)** | Two-grid overlap between dense k/q mandatory |
| **08_dos uses dos.x** | DOS is NOT a native pw.x calculation mode |
| **09_charge != 11_bader** | Spatial distribution vs atomic partitioning |

## Directory Semantics

| Directory | Role |
|-----------|------|
| `workflows/` | **Canonical stage contracts** — pure metadata, no material data |
| `cases/` | **Material-specific instances** — QE inputs, outputs, reports |
| `src/vibedft/` | Python implementation (parsers, rules, analyzers, CLI) |
| `tests/` | Pytest suite + minimal fixtures |
