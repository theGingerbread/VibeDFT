"""FastAPI app factory — wraps the VibeDFT kernel as a local API.

Default: localhost-only, no QE execution, all files in managed workspaces.
"""

from __future__ import annotations

import shutil
import zipfile
import io
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from vibedft.server.schemas import (
    HealthResponse,
    InspectResponse,
    ReviewRequest,
    ReviewResponse,
    ReportRequest,
    ReportResponse,
    ConvergenceRequest,
    ConvergenceResponse,
    PlanRequest,
    PlanResponse,
    ArtifactListResponse,
)
from vibedft.server.storage import get_workspace, reset_workspace


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    reset_workspace()
    yield


def create_app(with_frontend: bool = False) -> FastAPI:
    app = FastAPI(
        title="VibeDFT API",
        version="0.2.0",
        lifespan=_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:*", "http://127.0.0.1:*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _register_routes(app)

    if with_frontend:
        _mount_frontend(app)

    return app


def _mount_frontend(app: FastAPI) -> None:
    """Mount the built React frontend at /"""
    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if not (frontend_dist / "index.html").is_file():
        return

    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/", response_class=HTMLResponse)
    async def frontend_index():
        return (frontend_dist / "index.html").read_text()


def _register_routes(app: FastAPI) -> None:
    # ── Health ──
    @app.get("/health", response_model=HealthResponse)
    async def health():
        return HealthResponse()

    # ── Inspect ──
    @app.post("/api/inspect/files", response_model=InspectResponse)
    async def inspect_files_endpoint(files: list[UploadFile] = File(...)):
        ws = get_workspace()
        saved: list[Path] = []
        for f in files:
            dest = ws.upload_dir() / (f.filename or "upload")
            dest.write_bytes(await f.read())
            saved.append(dest)

        from vibedft.classifiers.task_classifier import inspect_files
        result = inspect_files(saved)
        return InspectResponse(
            files=[_file_record_dict(fr) for fr in result.files],
            tasks=[_task_record_dict(tr) for tr in result.tasks],
            issues=[_issue_dict(iss) for iss in result.issues],
        )

    # ── Review ──
    @app.post("/api/review/case", response_model=ReviewResponse)
    async def review_case_endpoint(
        files: list[UploadFile] = File(...),
        body: Optional[ReviewRequest] = None,
    ):
        ws = get_workspace()
        cid = (body and body.case_id) or "case"
        case_dir = ws.case_dir(cid)
        (case_dir / "input").mkdir(exist_ok=True)
        (case_dir / "output").mkdir(exist_ok=True)

        for f in files:
            fn = f.filename or "file"
            # Sort into input/ vs output/ by extension
            if fn.endswith(".in") or fn.endswith(".inp"):
                dest = case_dir / "input" / fn
            else:
                dest = case_dir / "output" / fn
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(await f.read())

        from vibedft.core.review import review_case
        from vibedft.analyzers.orchestrator import run_physics_analysis
        review = review_case(case_dir)
        physics = run_physics_analysis(case_dir, review_result=review)

        return ReviewResponse(
            case_dir=str(case_dir),
            files_scanned=review.files_scanned,
            files_inspected=review.files_inspected,
            summary=review.summary,
            next_step=review.next_step,
            n_errors=review.n_errors,
            n_warnings=review.n_warnings,
            best_workflow=(review.best_match.workflow.__dict__ if review.best_match else None),
            tasks=[_task_record_dict(t) for t in review.inspection.tasks],
            inspection=review.inspection.to_dict(),
            validation_issues=[_issue_dict(iss) for iss in review.validation_issues],
            workflow_matches=[_workflow_match_dict(m) for m in review.workflow_matches],
            physics=physics.to_dict() if physics else None,
        )

    # ── Report ──
    @app.post("/api/report/case", response_model=ReportResponse)
    async def report_case_endpoint(
        files: list[UploadFile] = File(...),
        body: Optional[ReportRequest] = None,
    ):
        ws = get_workspace()
        cid = "report_case"
        case_dir = ws.case_dir(cid)
        (case_dir / "input").mkdir(exist_ok=True)
        (case_dir / "output").mkdir(exist_ok=True)

        for f in files:
            fn = f.filename or "file"
            dest = case_dir / "output" / fn if f.filename and f.filename.endswith(".out") else case_dir / "input" / fn
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(await f.read())

        title = (body and body.title) or "VibeDFT Report"
        art_dir = ws.artifact_dir()
        art_id = "report"
        out_html = art_dir / f"{art_id}.html"

        from vibedft.core.report_builder import build_static_report
        build_static_report(case_dir, title=title, output=out_html)

        return ReportResponse(artifact_id=art_id)

    # ── Convergence ──
    @app.post("/api/convergence/root", response_model=ConvergenceResponse)
    async def convergence_endpoint(
        files: list[UploadFile] = File(...),
        body: Optional[ConvergenceRequest] = None,
    ):
        ws = get_workspace()
        root = ws.case_dir("batch_root")
        root.mkdir(exist_ok=True)

        # Each uploaded file goes into a subdirectory based on its path prefix
        for f in files:
            fn = f.filename or "file"
            # If filename contains "/", treat it as subdir path
            dest = root / fn
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(await f.read())

        from vibedft.core.batch_review import run_convergence_analysis
        title = (body and body.title) or "Convergence Report"
        report, artifacts = run_convergence_analysis(root, title=title)

        return ConvergenceResponse(
            n_cases=len(report.rows),
            overall_confidence=report.overall_confidence,
            varying_params=report.varying_params,
            converged=report.converged_params,
            unconverged=report.unconverged_params,
            rows=[{
                "case": r.case_name, "k_grid": r.k_grid, "q_grid": r.q_grid,
                "lambda_max": r.lambda_max, "tc_max_K": r.tc_max_K,
                "omega_log_K": r.omega_log_K, "confidence": r.confidence,
            } for r in report.rows],
            warnings=report.warnings,
        )

    # ── Plan ──
    @app.post("/api/plan/superconductivity", response_model=PlanResponse)
    async def plan_superconductivity_endpoint(body: PlanRequest):
        from vibedft.generators.manifest import CLUSTER_DEBUG, CLUSTER_PROD
        from vibedft.generators.workflow_planner import plan_superconductivity
        from vibedft.core.workflow_executor import execute_plan

        ws = get_workspace()
        profile_map = {"cluster_debug": CLUSTER_DEBUG, "cluster_prod": CLUSTER_PROD}
        profile = profile_map.get(body.profile, CLUSTER_DEBUG)

        out_dir = ws.case_dir("planned_workflow")

        plan = plan_superconductivity(
            structure_file="structure.cif",  # placeholder — structure not uploaded via API yet
            engine=body.engine,
            profile=profile,
            output_root=out_dir,
            material_prefix=body.prefix,
            ecutwfc=body.ecutwfc,
            ecutrho=body.ecutrho,
            tot_charge=body.tot_charge,
        )
        execute_plan(plan)

        # Zip the output
        art_dir = ws.artifact_dir()
        zip_path = art_dir / f"{plan.plan_id}.zip"
        _zip_directory(out_dir, zip_path)

        return PlanResponse(
            plan_id=plan.plan_id,
            n_stages=len(plan.stages),
            stages=[{
                "id": s.id, "kind": s.kind.value, "directory": s.directory,
                "cores": s.cores, "walltime": s.walltime,
            } for s in plan.stages],
            artifact_id=f"{plan.plan_id}.zip",
        )

    # ── Agent endpoints ──

    @app.post("/api/agent/explain-review")
    async def agent_explain_review(files: list[UploadFile] = File(...)):
        ws = get_workspace()
        cid = "agent_case"
        case_dir = ws.case_dir(cid)
        (case_dir / "input").mkdir(exist_ok=True)
        (case_dir / "output").mkdir(exist_ok=True)
        for f in files:
            fn = f.filename or "file"
            dest = case_dir / "output" / fn if fn.endswith(".out") else case_dir / "input" / fn
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(await f.read())

        from vibedft.core.review import review_case
        from vibedft.analyzers.orchestrator import run_physics_analysis
        from vibedft.agent.explanation_agent import explain_review

        review = review_case(case_dir)
        physics = run_physics_analysis(case_dir, review_result=review)
        result = explain_review(review, physics_report=physics)
        return result

    @app.post("/api/agent/suggest-fixes")
    async def agent_suggest_fixes(files: list[UploadFile] = File(...)):
        ws = get_workspace()
        cid = "agent_case"
        case_dir = ws.case_dir(cid)
        (case_dir / "input").mkdir(exist_ok=True)
        (case_dir / "output").mkdir(exist_ok=True)
        for f in files:
            fn = f.filename or "file"
            dest = case_dir / "output" / fn if fn.endswith(".out") else case_dir / "input" / fn
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(await f.read())

        from vibedft.core.review import review_case
        from vibedft.agent.fix_suggestion_agent import suggest_fixes

        review = review_case(case_dir)
        result = suggest_fixes(review)
        return result

    @app.post("/api/agent/next-steps")
    async def agent_next_steps(files: list[UploadFile] = File(...)):
        ws = get_workspace()
        cid = "agent_case"
        case_dir = ws.case_dir(cid)
        (case_dir / "input").mkdir(exist_ok=True)
        (case_dir / "output").mkdir(exist_ok=True)
        for f in files:
            fn = f.filename or "file"
            dest = case_dir / "output" / fn if fn.endswith(".out") else case_dir / "input" / fn
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(await f.read())

        from vibedft.core.review import review_case
        from vibedft.analyzers.orchestrator import run_physics_analysis
        from vibedft.agent.next_step_agent import recommend_next_steps

        review = review_case(case_dir)
        physics = run_physics_analysis(case_dir, review_result=review)
        result = recommend_next_steps(review, physics_report=physics)
        return result

    # ── Artifact download ──
    @app.get("/api/artifacts/{artifact_id}")
    async def download_artifact(artifact_id: str):
        ws = get_workspace()
        art_path = ws.artifact_dir() / artifact_id
        if not art_path.exists():
            raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_id}")
        media_type = "application/zip" if artifact_id.endswith(".zip") else "text/html"
        return FileResponse(art_path, media_type=media_type, filename=artifact_id)

    @app.get("/api/artifacts", response_model=ArtifactListResponse)
    async def list_artifacts():
        ws = get_workspace()
        art_dir = ws.artifact_dir()
        items = []
        for p in sorted(art_dir.iterdir()):
            if p.is_file():
                items.append({"id": p.name, "size": p.stat().st_size})
        return ArtifactListResponse(artifacts=items)


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _file_record_dict(fr: Any) -> dict:
    return {
        "path": getattr(fr, "path", ""),
        "type": getattr(fr, "type", ""),
        "parse_status": getattr(fr, "parse_status", ""),
        "program": getattr(fr, "program", "").value if hasattr(getattr(fr, "program", ""), "value") else str(getattr(fr, "program", "")),
        "summary": getattr(fr, "summary", ""),
    }


def _task_record_dict(tr: Any) -> dict:
    return {
        "program": tr.program.value if hasattr(tr.program, "value") else str(tr.program),
        "task_type": tr.task_type.value if hasattr(tr.task_type, "value") else str(tr.task_type),
        "source_file": tr.source_file,
        "confidence": tr.confidence,
        "key_params": tr.key_params,
    }


def _issue_dict(iss: Any) -> dict:
    return {
        "id": getattr(iss, "id", ""),
        "severity": getattr(iss, "severity", "").value if hasattr(getattr(iss, "severity", ""), "value") else str(getattr(iss, "severity", "")),
        "message": getattr(iss, "message", ""),
        "source_file": getattr(iss, "source_file", ""),
        "detail": getattr(iss, "detail", ""),
    }


def _workflow_match_dict(m: Any) -> dict:
    return {
        "workflow_id": m.workflow.workflow_id,
        "label": m.workflow.label,
        "completeness": m.completeness,
        "present_steps": [s.value for s in m.present_steps],
        "missing_steps": [s.label for s in m.missing_steps],
    }


def _zip_directory(root: Path, output: Path) -> None:
    """Zip a directory tree."""
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in root.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(root))
