"""Tests for v2 command registry matching and invariants."""

from __future__ import annotations

from vibedft.main.commands import COMMANDS, find_command


def test_command_registry_matches_qe_scf_review() -> None:
    spec, remaining = find_command(["qe", "scf", "review", "scf.out", "--pretty"])

    assert spec is not None
    assert spec.command_id == "qe.scf.review"
    assert spec.path == ("qe", "scf", "review")
    assert remaining == ["scf.out", "--pretty"]


def test_command_registry_matches_qe_relax_review() -> None:
    spec, remaining = find_command(["qe", "relax", "review", "relax.out", "--output", "result.json"])

    assert spec is not None
    assert spec.command_id == "qe.relax.review"
    assert spec.path == ("qe", "relax", "review")
    assert remaining == ["relax.out", "--output", "result.json"]


def test_command_registry_matches_qe_vc_relax_review() -> None:
    spec, remaining = find_command(
        ["qe", "vc-relax", "review", "vc-relax.out", "--fail-on-block", "x"]
    )

    assert spec is not None
    assert spec.command_id == "qe.vc_relax.review"
    assert spec.path == ("qe", "vc-relax", "review")
    assert remaining == ["vc-relax.out", "--fail-on-block", "x"]


def test_command_registry_matches_qe_nscf_review() -> None:
    spec, remaining = find_command(["qe", "nscf", "review", "nscf.out", "--pretty"])

    assert spec is not None
    assert spec.command_id == "qe.nscf.review"
    assert spec.path == ("qe", "nscf", "review")
    assert remaining == ["nscf.out", "--pretty"]


def test_command_registry_matches_qe_dos_review() -> None:
    spec, remaining = find_command(["qe", "dos", "review", "dos.out", "--output", "result.json"])

    assert spec is not None
    assert spec.command_id == "qe.dos.review"
    assert spec.path == ("qe", "dos", "review")
    assert remaining == ["dos.out", "--output", "result.json"]


def test_command_registry_matches_qe_pdos_review() -> None:
    spec, remaining = find_command(["qe", "pdos", "review", "pdos.out", "--pretty"])

    assert spec is not None
    assert spec.command_id == "qe.pdos.review"
    assert spec.path == ("qe", "pdos", "review")
    assert remaining == ["pdos.out", "--pretty"]


def test_command_registry_matches_qe_pp_review() -> None:
    spec, remaining = find_command(["qe", "pp", "review", "pp.out", "--pretty"])

    assert spec is not None
    assert spec.command_id == "qe.pp.review"
    assert spec.path == ("qe", "pp", "review")
    assert remaining == ["pp.out", "--pretty"]


def test_command_registry_matches_qe_bands_review() -> None:
    spec, remaining = find_command(["qe", "bands", "review", "bands.out", "--pretty"])

    assert spec is not None
    assert spec.command_id == "qe.bands.review"
    assert spec.path == ("qe", "bands", "review")
    assert remaining == ["bands.out", "--pretty"]


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
