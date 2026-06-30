SLURM_RUNBOOK = """# VibeDFT Slurm Runbook

Slurm is mandatory for server-side calculations.

## Agent Execution Flow

The Agent drives the full lifecycle locally. Each step must be recorded in the calculation log before proceeding.

### 1. Initialize Case
```
vibedft case init --software qe --workflow qe.scf.v1 --material HfBr2 --profile qe-hfx2-test --case-id HfBr2-test --output-dir cases
```
Creates `cases/HfBr2-test/{input,output,logs,vibedft.case.yaml}`.

### 2. Build Setup Window
```
vibedft setup build --software qe --workflow qe.scf.v1 --material HfBr2 --profile qe-hfx2-test --output-dir cases/HfBr2-test/setup
```
Creates `setup.html` and `vibedft.request.yaml`. The Agent opens `setup.html`, reviews every parameter, and flags deviations from recommended values.

### 3. Confirm Parameters
Agent proposes any changes via `vibedft.request.yaml`. User must explicitly confirm before rendering. Never silently modify parameters.

### 4. Render Inputs Locally
```
vibedft render --software qe --workflow qe.scf.v1 --material HfBr2 --profile qe-hfx2-test > cases/HfBr2-test/input/scf.in
```
Agent validates: no leftover Jinja2 placeholders, key params match confirmed set.

### 5. Transfer Inputs to Server
```
scp -r cases/HfBr2-test/input <CLUSTER_USER>@<CLUSTER_HOST>:<REMOTE_WORKDIR>/HfBr2-test/
```
Record: local path, remote host, remote path, file count.

### 6. Submit Through Slurm
On the server:
```
cd <REMOTE_WORKDIR>/HfBr2-test
sbatch job.slurm
```
Direct execution on the login node is FORBIDDEN. Record: job id, nodes, ntasks, walltime.
If sbatch fails, STOP and report the error.

### 7. Monitor Slurm
```
squeue -u $USER
sacct -j <job_id>
```
Poll until terminal state. Record: final state, exit code.

Failure handling:

| State           | Agent Action |
|-----------------|--------------|
| COMPLETED (0)   | Proceed to retrieve results |
| FAILED / non-0  | Pull output anyway, analyze, report error to user |
| TIMEOUT         | Propose walltime increase or param reduction; resubmit only after user confirms |
| CANCELLED       | Ask user whether to resubmit |

Never silently retry a failed Slurm job.

### 8. Retrieve Results
```
scp -r <CLUSTER_USER>@<CLUSTER_HOST>:<REMOTE_WORKDIR>/HfBr2-test/output cases/HfBr2-test/
```
Pull outputs back before any post-processing. Remote-only files are not final evidence.

### 9. Analyze Locally
```
vibedft analyze cases/HfBr2-test/output/scf.out --json > cases/HfBr2-test/output/analysis.json
```
Record: convergence state, total energy, Fermi energy, wall time, warnings.

### 10. Final Log Summary
Populate the Final Status section in `logs/calculation.md`:
```markdown
## Final Status
- Calculation: COMPLETED / FAILED
- Total Energy: xxx Ry
- SCF Converged: yes / no (xx iterations)
- Slurm Job: 12345  state=COMPLETED  walltime=xx:xx:xx
- Warnings: [list or "none"]
- Errors: [list or "none"]
```

## Forbidden

- Do not run QE/VASP/CP2K directly on a login node.
- Do not bypass Slurm with direct remote execution.
- Do not mark a calculation complete without a local `logs/calculation.md` entry.
- Do not post-process remote files in place without pulling the evidence back.
- Do not hard-code real server paths, host names, or user accounts in source code or examples.
"""
