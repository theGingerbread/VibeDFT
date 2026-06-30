"""Tests for VibeDFT FastAPI server (Sprint 8)."""

import io
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    """FastAPI TestClient with a fresh workspace."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from vibedft.server.storage import reset_workspace
    reset_workspace()
    from vibedft.server.app import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    return TestClient(app)


def _mini_scf_in() -> io.BytesIO:
    return io.BytesIO(b"""\
&CONTROL calculation='scf' prefix='test' outdir='./out_scf/' pseudo_dir='/pseudo/' /
&SYSTEM ibrav=0 nat=1 ntyp=1 ecutwfc=60 ecutrho=480 occupations='smearing' degauss=0.005 /
&ELECTRONS conv_thr=1.0d-12 /
ATOMIC_SPECIES X 1.0 X.UPF
ATOMIC_POSITIONS crystal X 0 0 0
K_POINTS automatic 12 12 1 0 0 0
CELL_PARAMETERS angstrom 3 0 0  0 3 0  0 0 30
""")


def _mini_scf_out() -> io.BytesIO:
    return io.BytesIO(b"""\
     Program PWSCF v.7.2 starts
     Self-consistent Calculation
     convergence has been achieved
!    total energy              =    -100.0 Ry
     JOB DONE
""")


def _mini_ph_in() -> io.BytesIO:
    return io.BytesIO(b"""\
&INPUTPH prefix='test' outdir='./out_scf/' fildyn='test.dyn' ldisp=.true. nq1=8 nq2=8 nq3=1 tr2_ph=1.0d-14 /
""")


def _bad_q2r_in() -> io.BytesIO:
    return io.BytesIO(b"""\
&INPUT fildyn='test.dyn' flfrc='test.fc' zasr='crystal' la2F=.true. /
""")


def test_server_pydantic_models_avoid_pep604_optional_forward_refs():
    """Pydantic on Python 3.9 cannot evaluate postponed `X | None` annotations."""
    from pydantic import BaseModel
    import vibedft.server.schemas as schemas

    for _, obj in inspect.getmembers(schemas, inspect.isclass):
        if issubclass(obj, BaseModel) and obj is not BaseModel:
            for annotation in obj.__annotations__.values():
                assert "| None" not in str(annotation)


# ═══════════════════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════════════════


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# Inspect
# ═══════════════════════════════════════════════════════════════════════════════


def test_inspect_scf_input(client):
    files = [("files", ("scf.in", _mini_scf_in(), "text/plain"))]
    r = client.post("/api/inspect/files", files=files)
    assert r.status_code == 200
    data = r.json()
    assert len(data["files"]) == 1
    assert data["files"][0]["program"] == "pw.x"


def test_inspect_multiple_files(client):
    files = [
        ("files", ("scf.in", _mini_scf_in(), "text/plain")),
        ("files", ("scf.out", _mini_scf_out(), "text/plain")),
    ]
    r = client.post("/api/inspect/files", files=files)
    assert r.status_code == 200
    data = r.json()
    assert len(data["files"]) == 2


def test_inspect_detects_la2f(client):
    files = [("files", ("q2r.in", _bad_q2r_in(), "text/plain"))]
    r = client.post("/api/inspect/files", files=files)
    assert r.status_code == 200
    data = r.json()
    issue_ids = [i["id"] for i in data["issues"]]
    assert any("la2f" in iid.lower() for iid in issue_ids), \
        f"la2F not detected in q2r. Issues: {data['issues']}"


# ═══════════════════════════════════════════════════════════════════════════════
# Review
# ═══════════════════════════════════════════════════════════════════════════════


def test_review_case(client):
    files = [
        ("files", ("scf.in", _mini_scf_in(), "text/plain")),
        ("files", ("scf.out", _mini_scf_out(), "text/plain")),
        ("files", ("ph.in", _mini_ph_in(), "text/plain")),
    ]
    r = client.post("/api/review/case", files=files)
    assert r.status_code == 200
    data = r.json()
    assert data["files_scanned"] >= 1
    assert data["summary"]
    assert "tasks" in data
    assert "physics" in data


# ═══════════════════════════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════════════════════════


def test_report_generation(client):
    files = [
        ("files", ("scf.in", _mini_scf_in(), "text/plain")),
        ("files", ("scf.out", _mini_scf_out(), "text/plain")),
    ]
    r = client.post("/api/report/case", files=files)
    assert r.status_code == 200
    data = r.json()
    assert data["artifact_id"] == "report"

    # Download the artifact
    r2 = client.get(f"/api/artifacts/{data['artifact_id']}.html")
    assert r2.status_code == 200
    assert "<html" in r2.text.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Plan
# ═══════════════════════════════════════════════════════════════════════════════


def test_plan_superconductivity(client):
    r = client.post("/api/plan/superconductivity", json={
        "prefix": "test", "ecutwfc": 60, "ecutrho": 480,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["n_stages"] >= 10
    assert data["artifact_id"]

    # Download the zip
    r2 = client.get(f"/api/artifacts/{data['artifact_id']}")
    assert r2.status_code == 200
    assert r2.headers["content-type"] == "application/zip"


# ═══════════════════════════════════════════════════════════════════════════════
# Path safety
# ═══════════════════════════════════════════════════════════════════════════════


def test_artifact_path_traversal_blocked(client):
    """Path traversal outside artifact dir must be blocked."""
    r = client.get("/api/artifacts/../../../etc/passwd")
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# Convergence
# ═══════════════════════════════════════════════════════════════════════════════


def test_convergence_batch(client):
    # Create two subdirs with lambdax.out files via upload
    files = [
        ("files", ("ph64/output/lambdax.out", io.BytesIO(b"""\
     lambda = 1.200 (   1.200 )  <log w>=   180.0 K  N(Ef)= 10.0 at degauss= 0.005
        lambda        omega_log          T_c
          1.20000        180.000              8.500
"""), "text/plain")),
        ("files", ("ph96/output/lambdax.out", io.BytesIO(b"""\
     lambda = 1.180 (   1.180 )  <log w>=   178.0 K  N(Ef)= 9.9 at degauss= 0.005
        lambda        omega_log          T_c
          1.18000        178.000              8.100
"""), "text/plain")),
    ]
    r = client.post("/api/convergence/root", files=files)
    assert r.status_code == 200
    data = r.json()
    assert data["n_cases"] >= 1
