"""Tests for evidence-based LLM Agent (Sprint 10)."""

import io
import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from vibedft.server.storage import reset_workspace
    reset_workspace()
    from vibedft.server.app import create_app
    from fastapi.testclient import TestClient
    return TestClient(create_app())


def _scf_in() -> io.BytesIO:
    return io.BytesIO(b"&CONTROL calculation='scf' prefix='test' outdir='./out_scf/' pseudo_dir='/pseudo/' /\n"
                      b"&SYSTEM ibrav=0 nat=1 ntyp=1 ecutwfc=60 ecutrho=480 occupations='smearing' degauss=0.005 /\n"
                      b"&ELECTRONS conv_thr=1.0d-12 /\n"
                      b"ATOMIC_SPECIES X 1.0 X.UPF\nATOMIC_POSITIONS crystal X 0 0 0\n"
                      b"K_POINTS automatic 12 12 1 0 0 0\nCELL_PARAMETERS angstrom 3 0 0  0 3 0  0 0 30\n")


def _bad_q2r() -> io.BytesIO:
    return io.BytesIO(b"&INPUT fildyn='test.dyn' flfrc='test.fc' zasr='crystal' la2F=.true. /\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Evidence Pack
# ═══════════════════════════════════════════════════════════════════════════════


def test_evidence_pack_redacts_paths(monkeypatch):
    """Evidence pack must redact private paths."""
    from vibedft.agent.evidence_pack import build_evidence_pack
    from vibedft.agent.safety import redact_private

    monkeypatch.setenv("VIBEDFT_PRIVATE_TOKENS", "private-cluster,private-user")
    text = "File at /home/private-user/work/private-cluster/test/scf.out failed on private-cluster"
    redacted = redact_private(text)
    assert "private-cluster" not in redacted
    assert "private-user" not in redacted
    assert "/home/<user>/" in redacted


def test_evidence_pack_from_review():
    """Build evidence pack from a real review result."""
    from vibedft.agent.evidence_pack import build_evidence_pack
    # Test with None inputs — should not crash
    pack = build_evidence_pack()
    assert "summary" in pack
    assert "issues" in pack
    assert pack["issues"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# Explanation Agent (fallback mode)
# ═══════════════════════════════════════════════════════════════════════════════


def test_explain_review_fallback():
    """Fallback explanation must work without LLM."""
    from vibedft.agent.explanation_agent import explain_review
    result = explain_review(None)
    assert "explanation" in result
    assert result["mode"] == "fallback"
    assert "No issues" in result["explanation"]


def test_explain_api_endpoint(client):
    """Agent explain-review API must return valid JSON."""
    files = [("files", ("scf.in", _scf_in(), "text/plain"))]
    r = client.post("/api/agent/explain-review", files=files)
    assert r.status_code == 200
    data = r.json()
    assert "explanation" in data
    assert "mode" in data


# ═══════════════════════════════════════════════════════════════════════════════
# Fix Suggestion Agent
# ═══════════════════════════════════════════════════════════════════════════════


def test_suggest_fixes_for_la2f():
    """la2F error must get a precise fix suggestion."""
    # Create a mock review-like object with a la2F issue
    class MockIssue:
        id = "q2r.la2f.forbidden"
        severity = type('Sev', (), {'value': 'error'})
        message = "la2F=.true. will crash q2r.x"
        detail = ""
        source_file = "q2r.in"

    class MockReview:
        all_issues = [MockIssue()]

    from vibedft.agent.fix_suggestion_agent import suggest_fixes
    result = suggest_fixes(MockReview())
    assert len(result["suggestions"]) >= 1
    assert any("la2F" in s["fix"] for s in result["suggestions"])


def test_suggest_fixes_api(client):
    """Fix API must return valid suggestions."""
    files = [
        ("files", ("scf.in", _scf_in(), "text/plain")),
        ("files", ("q2r.in", _bad_q2r(), "text/plain")),
    ]
    r = client.post("/api/agent/suggest-fixes", files=files)
    assert r.status_code == 200
    data = r.json()
    assert "suggestions" in data
    assert "mode" in data


# ═══════════════════════════════════════════════════════════════════════════════
# Next Step Agent
# ═══════════════════════════════════════════════════════════════════════════════


def test_next_steps_fallback():
    """Fallback next steps must include actionable recommendations."""
    from vibedft.agent.next_step_agent import recommend_next_steps
    result = recommend_next_steps(None)
    assert len(result["steps"]) >= 1
    assert result["mode"] == "fallback"


def test_next_steps_api(client):
    """Next-steps API must return valid recommendations."""
    files = [("files", ("scf.in", _scf_in(), "text/plain"))]
    r = client.post("/api/agent/next-steps", files=files)
    assert r.status_code == 200
    data = r.json()
    assert "steps" in data
    assert len(data["steps"]) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Safety
# ═══════════════════════════════════════════════════════════════════════════════


def test_safety_no_fabrication_in_fallback():
    """Fallback explanations must NOT fabricate Tc/λ/material data."""
    from vibedft.agent.explanation_agent import explain_review
    result = explain_review(None)
    text = result["explanation"]
    # Should not contain made-up values
    assert "λ=" not in text or "not available" in text.lower()
    assert "Tc=" not in text or "not available" in text.lower()
