"""Tests for v2 command registry matching and invariants."""

from __future__ import annotations

from vibedft.main.commands import COMMANDS, find_command


def test_command_registry_matches_qe_scf_review() -> None:
    spec, remaining = find_command(["qe", "scf", "review", "scf.out", "--pretty"])

    assert spec is not None
    assert spec.command_id == "qe.scf.review"
    assert spec.path == ("qe", "scf", "review")
    assert remaining == ["scf.out", "--pretty"]


def test_unknown_command_does_not_match_registry() -> None:
    spec, remaining = find_command(["qe", "scf", "status"])

    assert spec is None
    assert remaining == ["qe", "scf", "status"]

    fallback_spec, _ = find_command(["legacy", "cmd"])
    assert fallback_spec is None


def test_command_registry_has_unique_command_ids_and_paths() -> None:
    ids = [spec.command_id for spec in COMMANDS]
    assert len(ids) == len(set(ids))

    paths = [spec.path for spec in COMMANDS]
    assert len(paths) == len(set(paths))
