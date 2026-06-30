// VibeDFT API client — calls local FastAPI server endpoints.

const BASE = '';

export interface InspectResult {
  files: FileRecord[];
  tasks: TaskRecord[];
  issues: Issue[];
}

export interface FileRecord {
  path: string; type: string; parse_status: string;
  program: string; summary: string;
}

export interface TaskRecord {
  program: string; task_type: string; source_file: string;
  confidence: string; key_params: Record<string, unknown>;
}

export interface Issue {
  id: string; severity: string; message: string;
  source_file: string; detail: string;
}

export interface ReviewResult {
  case_dir: string; files_scanned: number; files_inspected: number;
  summary: string; next_step: string;
  n_errors: number; n_warnings: number;
  tasks: TaskRecord[];
  validation_issues: Issue[];
  workflow_matches: WorkflowMatch[];
  physics: PhysicsReport | null;
}

export interface WorkflowMatch {
  workflow_id: string; label: string; completeness: number;
  present_steps: string[]; missing_steps: string[];
}

export interface PhysicsReport {
  scores: { stability: number; electronic: number; superconductivity: number; workflow_confidence: number };
  overall_verdict: string; recommendation: string;
  insights: PhysicsInsight[];
}

export interface PhysicsInsight {
  id: string; category: string; level: string; message: string; detail: string;
}

export interface PlanResult {
  plan_id: string; n_stages: number;
  stages: StageSpec[]; artifact_id: string | null;
}

export interface StageSpec {
  id: string; kind: string; directory: string; cores: number; walltime: string;
}

export interface ConvergenceResult {
  n_cases: number; overall_confidence: string;
  varying_params: string[]; converged: string[]; unconverged: string[];
  rows: ConvergenceRow[]; warnings: string[];
}

export interface ConvergenceRow {
  case: string; k_grid: string; q_grid: string;
  lambda_max: number | null; tc_max_K: number | null;
  omega_log_K: number | null; confidence: string;
}

export async function health(): Promise<{status: string}> {
  const r = await fetch(`${BASE}/health`);
  return r.json();
}

export async function inspectFiles(files: File[]): Promise<InspectResult> {
  const fd = new FormData();
  files.forEach(f => fd.append('files', f));
  const r = await fetch(`${BASE}/api/inspect/files`, { method: 'POST', body: fd });
  return r.json();
}

export async function reviewCase(files: File[]): Promise<ReviewResult> {
  const fd = new FormData();
  files.forEach(f => fd.append('files', f));
  const r = await fetch(`${BASE}/api/review/case`, { method: 'POST', body: fd });
  return r.json();
}

export async function generateReport(files: File[], title?: string): Promise<{artifact_id: string}> {
  const fd = new FormData();
  files.forEach(f => fd.append('files', f));
  const r = await fetch(`${BASE}/api/report/case`, { method: 'POST', body: fd });
  return r.json();
}

export async function convergenceAnalysis(files: File[]): Promise<ConvergenceResult> {
  const fd = new FormData();
  files.forEach(f => fd.append('files', f));
  const r = await fetch(`${BASE}/api/convergence/root`, { method: 'POST', body: fd });
  return r.json();
}

export async function planWorkflow(params: {
  prefix: string; ecutwfc: number; ecutrho: number;
  tot_charge: number; profile: string;
}): Promise<PlanResult> {
  const r = await fetch(`${BASE}/api/plan/superconductivity`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(params),
  });
  return r.json();
}

export function artifactUrl(id: string): string {
  return `${BASE}/api/artifacts/${id}`;
}
