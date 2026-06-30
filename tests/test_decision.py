"""Tests for Integrated 2D Materials Decision Layer (Sprint 13)."""

import os
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "vibedft", *args],
        cwd=PROJECT_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Decision Logic (unit tests with mock evidence)
# ═══════════════════════════════════════════════════════════════════════════════


def test_decision_blocked_by_la2f():
    """Case with la2F critical error must be BLOCKED."""
    from vibedft.decision.publication_gate import decide, DecisionResult, GateLevel

    class MockIssue:
        id = "q2r.la2f.forbidden"
        severity = type('S', (), {'value': 'error'})()
        message = "la2F will crash q2r.x"
        detail = ""
        source_file = "q2r.in"

    class MockReview:
        all_issues = [MockIssue()]
        best_match = None

    result = decide(".", review_result=MockReview())
    assert result.gate == GateLevel.BLOCKED
    assert "la2f" in result.primary_blocker.lower()


def test_decision_blocked_by_imaginary_modes():
    """Non-Γ imaginary modes should BLOCK."""
    from vibedft.decision.publication_gate import decide, GateLevel

    class MockPhysics:
        def to_dict(self):
            return {
                "scores": {"stability": 4, "electronic": 6, "superconductivity": 5, "workflow_confidence": 5},
                "key_values": {"n_imaginary_non_gamma": 3},
                "insights": [],
            }

    class MockReview:
        all_issues = []
        best_match = None

    result = decide(".", review_result=MockReview(), physics_report=MockPhysics())
    assert result.gate == GateLevel.BLOCKED


def test_decision_needs_convergence():
    """Low SC score with no critical errors → NEEDS_CONVERGENCE."""
    from vibedft.decision.publication_gate import decide, GateLevel

    class MockPhysics:
        def to_dict(self):
            return {
                "scores": {"stability": 7, "electronic": 6, "superconductivity": 3, "workflow_confidence": 5},
                "key_values": {"n_imaginary_non_gamma": 0},
                "insights": [],
            }

    class MockReview:
        all_issues = []
        best_match = None

    result = decide(".", review_result=MockReview(), physics_report=MockPhysics())
    assert result.gate == GateLevel.NEEDS_CONVERGENCE


def test_decision_promising():
    """Decent scores, no issues → PROMISING or better."""
    from vibedft.decision.publication_gate import decide, GateLevel

    class MockPhysics:
        def to_dict(self):
            return {
                "scores": {"stability": 8, "electronic": 7, "superconductivity": 8, "workflow_confidence": 7},
                "key_values": {"n_imaginary_non_gamma": 0, "lambda_max": 1.2, "tc_max_K": 8.5},
                "insights": [{"level": "positive", "message": "Dynamically stable"}],
            }

    class MockWfMatch:
        workflow_id = "qe.ph_epc.v1"; label = "EPC"
        completeness = 0.9; missing_steps = []

    class MockReview:
        all_issues = []
        best_match = MockWfMatch()

    result = decide(".", review_result=MockReview(), physics_report=MockPhysics())
    assert result.gate in (GateLevel.PROMISING, GateLevel.READY_FOR_FIGURES)


def test_decision_next_actions_blocked():
    """Blocked cases must have concrete fix actions."""
    from vibedft.decision.publication_gate import decide

    class MockIssue:
        id = "q2r.la2f.forbidden"
        severity = type('S', (), {'value': 'error'})()
        message = "la2F will crash"
        detail = ""
        source_file = "q2r.in"

    class MockReview:
        all_issues = [MockIssue()]
        best_match = None

    result = decide(".", review_result=MockReview())
    assert len(result.next_actions) >= 1
    assert any("la2f" in a.lower() for a in result.next_actions)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════


def test_decide_cli_on_empty_dir(tmp_path):
    """vibedft decide should run on any directory."""
    result = run_cli("decide", "--case-dir", str(tmp_path), "--json")
    assert result.returncode == 0, result.stderr


def test_decide_cli_on_valid_case(tmp_path):
    """Decide on a case with a valid SCF file."""
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "scf.out").write_text(
        "Program PWSCF v.7.2\nSelf-consistent Calculation\n"
        "convergence has been achieved\n! total energy = -100.0 Ry\nJOB DONE\n"
    )
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "scf.in").write_text(
        "&CONTROL calculation='scf' prefix='test' outdir='./out/' pseudo_dir='/pseudo/' /\n"
        "&SYSTEM ibrav=0 nat=1 ntyp=1 ecutwfc=60 ecutrho=480 /\n"
        "&ELECTRONS conv_thr=1.0d-12 /\n"
        "ATOMIC_SPECIES X 1.0 X.UPF\nATOMIC_POSITIONS crystal X 0 0 0\n"
        "K_POINTS automatic 12 12 1 0 0 0\nCELL_PARAMETERS angstrom 3 0 0  0 3 0  0 0 30\n"
    )
    result = run_cli("decide", "--case-dir", str(tmp_path), "--json")
    assert result.returncode == 0, result.stderr
    import json
    data = json.loads(result.stdout)
    assert "gate" in data
    assert "summary" in data
