"""Tests for ASE-backed band-path helpers (ROADMAP §3.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vibedft.analyzers.structure_tools import (
    HIGH_SYMMETRY_2D,
    bandpath_2d_hex,
    bandpath_for_structure,
)
from vibedft.core.structure import _ase_available

FIXTURES = Path(__file__).parent / "fixtures"
HEX_QE_INPUT = FIXTURES / "mini_qe" / "scf.in"


# ── HIGH_SYMMETRY_2D ──


def test_high_symmetry_2d_has_expected_keys():
    assert set(["Γ", "M", "K"]).issubset(HIGH_SYMMETRY_2D.keys())


def test_high_symmetry_2d_k_point():
    k = HIGH_SYMMETRY_2D["K"]
    assert len(k) == 3
    assert k[0] == pytest.approx(1.0 / 3.0)
    assert k[1] == pytest.approx(1.0 / 3.0)
    assert k[2] == pytest.approx(0.0)


def test_high_symmetry_2d_gamma_and_m():
    assert HIGH_SYMMETRY_2D["Γ"] == [0.0, 0.0, 0.0]
    assert HIGH_SYMMETRY_2D["M"] == [0.5, 0.0, 0.0]


# ── bandpath_2d_hex ──


REQUIRED_KEYS = {"kpoints", "special_points", "path", "x_coords", "x_special", "labels"}


@pytest.mark.skipif(not _ase_available(), reason="requires the 'ase' extra")
def test_bandpath_2d_hex_has_required_keys():
    d = bandpath_2d_hex(3.5, n=10)
    assert isinstance(d, dict)
    assert REQUIRED_KEYS.issubset(d.keys())


@pytest.mark.skipif(not _ase_available(), reason="requires the 'ase' extra")
def test_bandpath_2d_hex_kpoints_shape():
    d = bandpath_2d_hex(3.5, n=10)
    kpts = d["kpoints"]
    assert isinstance(kpts, list)
    assert len(kpts) >= 3
    for k in kpts:
        assert isinstance(k, list)
        assert len(k) == 3
        assert all(isinstance(c, float) for c in k)


@pytest.mark.skipif(not _ase_available(), reason="requires the 'ase' extra")
def test_bandpath_2d_hex_special_points_contain_gmk():
    d = bandpath_2d_hex(3.5, n=10)
    sp = d["special_points"]
    assert "Γ" in sp and "M" in sp and "K" in sp
    assert sp["Γ"] == [0.0, 0.0, 0.0]
    assert sp["M"][0] == pytest.approx(0.5)
    assert sp["K"][0] == pytest.approx(1.0 / 3.0)


@pytest.mark.skipif(not _ase_available(), reason="requires the 'ase' extra")
def test_bandpath_2d_hex_path_has_three_segments():
    d = bandpath_2d_hex(3.5, n=10)
    path = d["path"]
    assert isinstance(path, list)
    assert len(path) == 3
    for seg in path:
        assert isinstance(seg, list)
        assert len(seg) == 2
        assert all(isinstance(name, str) for name in seg)
    names = [name for seg in path for name in seg]
    assert "Γ" in names and "M" in names and "K" in names


@pytest.mark.skipif(not _ase_available(), reason="requires the 'ase' extra")
def test_bandpath_2d_hex_x_coords_monotonic():
    d = bandpath_2d_hex(3.5, n=20)
    x = d["x_coords"]
    assert isinstance(x, list)
    assert len(x) == len(d["kpoints"])
    assert x[0] == pytest.approx(0.0)
    for i in range(1, len(x)):
        assert x[i] >= x[i - 1] - 1e-9


@pytest.mark.skipif(not _ase_available(), reason="requires the 'ase' extra")
def test_bandpath_2d_hex_labels_match_x_special():
    d = bandpath_2d_hex(3.5, n=10)
    labels = d["labels"]
    x_special = d["x_special"]
    assert isinstance(labels, list)
    assert len(labels) == len(x_special)
    for (xpos, name), xs in zip(labels, x_special):
        assert isinstance(name, str)
        assert xpos == pytest.approx(xs)
    assert labels[0][1] == "Γ"
    assert labels[-1][1] == "Γ"


@pytest.mark.skipif(not _ase_available(), reason="requires the 'ase' extra")
def test_bandpath_2d_hex_b_defaults_to_a():
    d = bandpath_2d_hex(3.5, n=10)
    sp = d["special_points"]
    assert sp["M"] == [0.5, 0.0, 0.0]


def test_bandpath_2d_hex_raises_without_ase(monkeypatch):
    import vibedft.analyzers.structure_tools as st

    monkeypatch.setattr(st, "_ase_available", lambda: False)
    with pytest.raises(RuntimeError, match="ase"):
        bandpath_2d_hex(3.5, n=10)


# ── bandpath_for_structure ──


@pytest.mark.skipif(not _ase_available(), reason="requires the 'ase' extra")
def test_bandpath_for_structure_hex_fixture():
    d = bandpath_for_structure(HEX_QE_INPUT, n=12)
    assert d is not None
    assert REQUIRED_KEYS.issubset(d.keys())
    sp = d["special_points"]
    assert "Γ" in sp and "M" in sp and "K" in sp
    assert len(d["kpoints"]) >= 3
    assert len(d["path"]) == 3


@pytest.mark.skipif(not _ase_available(), reason="requires the 'ase' extra")
def test_bandpath_for_structure_nonexistent_file_returns_none(tmp_path: Path):
    result = bandpath_for_structure(tmp_path / "does_not_exist.in", n=10)
    assert result is None


@pytest.mark.skipif(not _ase_available(), reason="requires the 'ase' extra")
def test_bandpath_for_structure_writes_and_reads_tmp_hex(tmp_path: Path):
    qe = tmp_path / "hex.in"
    qe.write_text(
        "&CONTROL\n  calculation = 'scf'\n  prefix = 't'\n/\n"
        "&SYSTEM\n  ibrav = 0\n  nat = 1\n  ntyp = 1\n  ecutwfc = 40\n/\n"
        "&ELECTRONS\n/\n"
        "ATOMIC_SPECIES\n  H 1.0 H.UPF\n"
        "ATOMIC_POSITIONS crystal\n  H 0.0 0.0 0.0\n"
        "CELL_PARAMETERS angstrom\n"
        "  3.50  0.00  0.00\n"
        "  -1.75  3.03  0.00\n"
        "  0.00  0.00  30.00\n"
        "K_POINTS automatic\n  6 6 1  0 0 0\n"
    )
    d = bandpath_for_structure(qe, n=8)
    assert d is not None
    assert "Γ" in d["special_points"]
    assert "M" in d["special_points"]
    assert "K" in d["special_points"]


def test_bandpath_for_structure_returns_none_without_ase(monkeypatch, tmp_path: Path):
    import vibedft.analyzers.structure_tools as st

    monkeypatch.setattr(st, "_ase_available", lambda: False)
    assert bandpath_for_structure(HEX_QE_INPUT, n=10) is None
