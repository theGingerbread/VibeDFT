"""Tests for goal-acceptance command."""

import json
import subprocess
import sys
import os
from pathlib import Path

from vibedft.goal_acceptance import run_goal_acceptance

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "vibedft", *args],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _write_goal_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    docs_root = root / "docs"
    workflows_root = root / "workflows"
    docs_root.mkdir()
    workflows_root.mkdir()
    (docs_root / "INDEX.md").write_text("- [a.md](a.md)\n", encoding="utf-8")
    (docs_root / "a.md").write_text("# a\n", encoding="utf-8")
    (workflows_root / "stages.yaml").write_text(
        "stages:\n  - stage_id: 00_structure\n  - stage_id: 01_pseudopotentials\n",
        encoding="utf-8",
    )
    stage_map = root / "physics_map.md"
    stage_map.write_text("00_structure\n01_pseudopotentials\n", encoding="utf-8")
    return docs_root / "INDEX.md", workflows_root / "stages.yaml", stage_map, docs_root


def _write_case_warning_fixture(case_root: Path, *, high_warning_count: int = 1) -> None:
    case_root.mkdir(parents=True)
    input_dir = case_root / "inputs"
    input_dir.mkdir()
    (input_dir / "mystery.in").write_text("&UNKNOWN\nfoo=1.0\n/\n", encoding="utf-8")
    output_dir = case_root / "output"
    output_dir.mkdir()

    out_text = "JOB DONE\nconvergence has been achieved\n"
    if high_warning_count >= 3:
        out_text += "nan\n"  # triggers output.no_nan warning
    (output_dir / "scf.out").write_text(out_text, encoding="utf-8")

    if high_warning_count >= 2:
        (output_dir / "small.dos").write_text("0", encoding="utf-8")
        (output_dir / "small.bands").write_text("0", encoding="utf-8")


def test_cli_goal_acceptance_pass(tmp_path: Path):
    index_path, stages_path, stage_map_path, docs_root = _write_goal_fixture(tmp_path)
    result = run_cli(
        "goal",
        "--json",
        "--skip-cases",
        "--docs-root", str(docs_root),
        "--index", str(index_path),
        "--stages", str(stages_path),
        "--stage-map", str(stage_map_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["overall_status"] == "PASS"
    assert payload["docs"]["missing_in_index"] == []
    assert payload["stages"]["missing_in_map"] == []
    assert payload["blocked_gates"] == []


def test_cli_goal_acceptance_blocked_on_index_miss(tmp_path: Path):
    index_path, stages_path, stage_map_path, docs_root = _write_goal_fixture(tmp_path)
    (docs_root / "b.md").write_text("# b\n", encoding="utf-8")
    # remove b.md from index to trigger block
    result = run_cli(
        "goal",
        "--json",
        "--skip-cases",
        "--docs-root", str(docs_root),
        "--index", str(index_path),
        "--stages", str(stages_path),
        "--stage-map", str(stage_map_path),
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout.strip())
    assert payload["overall_status"] == "BLOCK"
    assert payload["blocked_gates"], "Blocked case should report at least one blocked gate"


def test_goal_acceptance_concern_with_case_audit_warning(tmp_path: Path):
    root = tmp_path
    index_path, stages_path, stage_map_path, docs_root = _write_goal_fixture(root)
    _write_case_warning_fixture(root / "cases" / "warn_case", high_warning_count=1)

    payload = run_goal_acceptance(
        project_root=root,
        docs_root=docs_root,
        index_path=index_path,
        stages_path=stages_path,
        stage_map_path=stage_map_path,
        skip_cases=True,
        audit_cases=True,
        case_root=root / "cases",
        case_max=10,
    )

    assert payload["overall_status"] == "CONCERN"
    assert payload["warning_gates"] or payload["high_warning_gates"]
    assert payload["cases"]["enabled"] is True
    assert payload["cases"]["audited"] == 1
    assert 8.5 <= payload["score"] < 10


def test_goal_acceptance_block_due_to_low_score(tmp_path: Path):
    root = tmp_path
    index_path, stages_path, stage_map_path, docs_root = _write_goal_fixture(root)
    _write_case_warning_fixture(root / "cases" / "warn_case", high_warning_count=3)

    payload = run_goal_acceptance(
        project_root=root,
        docs_root=docs_root,
        index_path=index_path,
        stages_path=stages_path,
        stage_map_path=stage_map_path,
        skip_cases=True,
        audit_cases=True,
        case_root=root / "cases",
        case_max=10,
    )

    assert payload["overall_status"] == "BLOCK"
    assert payload["score"] < 6.0


def test_goal_acceptance_case_audit_handles_corrupt_case_as_blocked_gate(
    tmp_path: Path, monkeypatch: object
):
    root = tmp_path
    index_path, stages_path, stage_map_path, docs_root = _write_goal_fixture(root)

    broken_case = root / "cases" / "broken_case"
    broken_case.mkdir(parents=True)
    monkeypatched = {"called": False}

    def _boom(_: Path) -> None:
        monkeypatched["called"] = True
        raise RuntimeError("qa parsing failed")

    monkeypatch.setattr("vibedft.goal_acceptance.qa_all", _boom)

    payload = run_goal_acceptance(
        project_root=root,
        docs_root=docs_root,
        index_path=index_path,
        stages_path=stages_path,
        stage_map_path=stage_map_path,
        skip_cases=True,
        audit_cases=True,
        case_root=root / "cases",
        case_max=10,
    )

    assert monkeypatched["called"] is True
    assert payload["overall_status"] == "BLOCK"
    assert payload["cases"]["enabled"] is True
    assert payload["cases"]["audited"] == 1
    assert payload["cases"]["items"]
    assert any("qa_exception" in gate for gate in payload["cases"]["items"][0]["blocked_gates"])
