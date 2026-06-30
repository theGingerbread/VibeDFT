"""Regression tests for the reorg governance script."""

from __future__ import annotations

import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_check_module():
    module_path = PROJECT_ROOT / "scripts" / "reorg_health_check.py"
    spec = importlib.util.spec_from_file_location("reorg_health_check", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _write_doc_tree(tmp_path: Path, include_index_links: bool = True):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# a\n", encoding="utf-8")
    (docs / "b.md").write_text("# b\n", encoding="utf-8")
    (docs / "INDEX.md").write_text(
        "# INDEX\n\n- [a](a.md)\n- [b](b.md)\n",
        encoding="utf-8",
    )
    if not include_index_links:
        (docs / "INDEX.md").write_text("# INDEX\n\n- [a](a.md)\n", encoding="utf-8")


def _write_stages_map(tmp_path: Path):
    stages = tmp_path / "workflows"
    stages.mkdir()
    (stages / "stages.yaml").write_text(
        """
stages:
  - stage_id: 00_structure
  - stage_id: 01_pseudopotentials
""".lstrip(),
        encoding="utf-8",
    )
    stage_map = tmp_path / "stage_map.md"
    stage_map.write_text(
        """
00_structure
01_pseudopotentials
""".lstrip(),
        encoding="utf-8",
    )
    return stages / "stages.yaml", stage_map


def test_reorg_health_check_pass(tmp_path: Path):
    """PASS when docs index and stage-map are consistent."""
    _write_doc_tree(tmp_path)
    stages_path, stage_map_path = _write_stages_map(tmp_path)
    reorg = _load_check_module()

    summary = reorg.run_checks(
        docs_root=tmp_path / "docs",
        index_path=tmp_path / "docs" / "INDEX.md",
        stages_path=stages_path,
        stage_map_path=stage_map_path,
        skip_cases=True,
    )

    assert summary["status"] == "PASS"
    assert summary["docs"]["missing_in_index"] == []
    assert summary["docs"]["unknown_in_index"] == []
    assert summary["stages"]["missing_in_map"] == []


def test_reorg_health_check_fails_on_index_miss(tmp_path: Path):
    """FAIL when INDEX misses a markdown file under docs."""
    _write_doc_tree(tmp_path, include_index_links=False)
    stages_path, stage_map_path = _write_stages_map(tmp_path)
    reorg = _load_check_module()

    summary = reorg.run_checks(
        docs_root=tmp_path / "docs",
        index_path=tmp_path / "docs" / "INDEX.md",
        stages_path=stages_path,
        stage_map_path=stage_map_path,
        skip_cases=True,
    )

    assert summary["status"] == "FAIL"
    assert "b.md" in summary["docs"]["missing_in_index"]


def test_reorg_health_check_fails_on_stage_map_miss(tmp_path: Path):
    """FAIL when stage map omits a stage defined in stages.yaml."""
    _write_doc_tree(tmp_path)
    stages_path, broken_map = _write_stages_map(tmp_path)

    # remove one stage from map
    broken_map.write_text("00_structure\n", encoding="utf-8")

    reorg = _load_check_module()
    summary = reorg.run_checks(
        docs_root=tmp_path / "docs",
        index_path=tmp_path / "docs" / "INDEX.md",
        stages_path=stages_path,
        stage_map_path=broken_map,
        skip_cases=True,
    )

    assert summary["status"] == "FAIL"
    assert "01_pseudopotentials" in summary["stages"]["missing_in_map"]
