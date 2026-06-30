# Changelog

## v0.1.0 (2026-06-09)

### Sprint 1: File Inspection
- Parser: Fortran namelist + QE card block parser (`qe_input_parser.py`)
- Classifier: program detection (pw/ph/q2r/matdyn/lambda/dos/bands/projwfc) + task type inference
- Models: `InspectionResult`, `TaskRecord`, `FileRecord`, `SanityIssue`
- CLI: `vibedft inspect file1.in file2.out --json`

### Sprint 2: Case Review
- Validators: per-program rules for pw.x, ph.x, q2r.x, matdyn.x, lambda.x
- Workflow matcher: 7 known QE workflows, completeness scoring
- Knowledge base: error patterns, warning rules, postprocess map (YAML)
- CLI: `vibedft review --case-dir ... --json`

### Sprint 3: Postprocess & Report
- Artifact model: figure (base64 PNG), table, text, JSON
- Plot generators: band structure, DOS/PDOS, phonon dispersion, α²F/Tc
- Dispatcher: maps detected tasks to plot generators
- Static HTML report builder (7 sections, self-contained)
- CLI: `vibedft report generate --case-dir ... --html report.html`

### Sprint 4: Physics Insight Layer
- 5 analyzers: superconductivity, stability, electronic, material, workflow health
- MaterialReport: 4 scores + overall verdict + recommendation
- Insights with evidence links back to source files
- Tc overlap analysis integrated into physics pipeline

### Sprint 5: Convergence & Batch
- Batch scanner: discovers case subdirectories
- Parameter extractor: k-grid, q-grid, ecut, degauss from inputs
- Metrics extractor: λ, Tc, ωlog, DOS@EF, phonon stability
- Convergence analyzer: Δλ<0.05, ΔTc<0.5K, Δωlog<5% criteria
- CLI: `vibedft convergence --root ... --html convergence.html`

### Sprint 5.5: Real-case Hardening
- DJ_*/Talos Slurm wrapper detection
- ph.x output misclassification fix (lambda heuristic reordered)
- dos.x / bands.x / projwfc.x / lambda.x input recognition
- Verdict aggregation: CRITICAL errors cap physics scores
- Validated on real HfI2 e=0.02 doping data (80 files, 5 stages)

### Sprint 6: Workflow Generator
- 16-stage superconductivity DAG planner
- QE input builder + Slurm script builder
- 10 Jinja2 templates with hard constraints embedded
- PH_STABILITY/PH_EPC separation, no la2F in q2r/matdyn
- CLI: `vibedft plan superconductivity --structure ...`

### Sprint 7: Regression Fixtures
- 16 sanitized QE fixtures (mini_qe, bad_la2f, slurm_wrapped, unknown_inputs, tc_overlap_fail)
- 13 regression smoke tests
- Architecture, CLI reference, and validation rules documentation

### Sprint 8: FastAPI Local Server
- 6 API endpoints + artifact download/list
- Workspace sandbox with path traversal protection
- Pydantic request/response schemas
- CLI: `vibedft server --host 127.0.0.1 --port 8765`

### Sprint 9: Frontend Workbench
- React/Vite/TypeScript single-page app
- 5 tab views: Inspect, Review, Report, Convergence, Plan
- Dropzone, IssueTable, PhysicsCards, AgentPanel components
- Dark theme matching reports
- `vibedft server --with-frontend`

### Sprint 10: Evidence-bound LLM Agent
- Evidence Pack builder (redacted, safe JSON from deterministic results)
- 3 agents: explain, suggest-fixes, next-steps
- Fallback mode works without LLM (deterministic rules)
- Private path/server/account redaction
- Frontend AgentPanel with fixed-action buttons

### Sprint 11: Release Hardening
- MIT License
- pyproject.toml: full metadata, dependency groups
- README rewrite
- GitHub Actions CI
- Privacy audit
- 216 tests
