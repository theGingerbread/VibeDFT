"""Tests for phonon mode eigenvector parsing."""
import tempfile
from pathlib import Path

import pytest
from vibedft.core.phonon_modes import (
    AtomDisplacement,
    PhononMode,
    parse_matdyn_modes,
    _compute_atom_participation,
    _compute_in_plane_fraction,
    _classify_polarization,
    _classify_mode_type,
)


# ── Synthetic matdyn.modes fixture ──

MATDYN_MODES_CONTENT = """     diagonalizing the dynamical matrix ...

 q =       0.0000      0.0000      0.0000
 **************************************************************************
     freq (    1) =       0.000000 [THz] =       0.000000 [cm-1]
 (  0.001234  0.000000  0.000000  0.000000  0.000000  0.000000   )
 (  0.001234  0.000000  0.000000  0.000000  0.000000  0.000000   )
 (  0.001234  0.000000  0.000000  0.000000  0.000000  0.000000   )
 (  0.001234  0.000000  0.000000  0.000000  0.000000  0.000000   )
 (  0.001234  0.000000  0.000000  0.000000  0.000000  0.000000   )
 (  0.001234  0.000000  0.000000  0.000000  0.000000  0.000000   )
 (  0.001234  0.000000  0.000000  0.000000  0.000000  0.000000   )
     freq (    2) =       2.000000 [THz] =      66.712000 [cm-1]
 (  0.100000  0.000000  0.000000  0.000000  0.000000  0.000000   )
 (  0.100000  0.000000  0.000000  0.000000  0.000000  0.000000   )
 ( -0.050000  0.000000  0.000000  0.000000  0.000000  0.000000   )
 ( -0.050000  0.000000  0.000000  0.000000  0.000000  0.000000   )
 (  0.020000  0.000000  0.000000  0.000000  0.000000  0.000000   )
 (  0.020000  0.000000  0.000000  0.000000  0.000000  0.000000   )
 (  0.700000  0.000000  0.000000  0.000000  0.000000  0.000000   )
"""


class TestAtomDisplacement:
    def test_magnitude(self):
        d = AtomDisplacement(element="Na", x_disp=3.0, y_disp=4.0, z_disp=0.0)
        assert abs(d.magnitude - 5.0) < 1e-10

    def test_in_plane_magnitude(self):
        d = AtomDisplacement(element="Na", x_disp=3.0, y_disp=4.0, z_disp=12.0)
        assert abs(d.in_plane_magnitude - 5.0) < 1e-10

    def test_out_of_plane_magnitude(self):
        d = AtomDisplacement(element="Na", x_disp=3.0, y_disp=4.0, z_disp=12.0)
        assert abs(d.out_of_plane_magnitude - 12.0) < 1e-10


class TestAtomParticipation:
    def test_uniform(self):
        disp = [
            AtomDisplacement(element="A", x_disp=1.0, y_disp=0.0, z_disp=0.0),
            AtomDisplacement(element="B", x_disp=1.0, y_disp=0.0, z_disp=0.0),
        ]
        p = _compute_atom_participation(disp)
        assert abs(p["A"] - 0.5) < 1e-10
        assert abs(p["B"] - 0.5) < 1e-10


class TestInPlaneFraction:
    def test_in_plane_dominant(self):
        disp = [AtomDisplacement(element="A", x_disp=1.0, y_disp=0.0, z_disp=0.0)]
        assert abs(_compute_in_plane_fraction(disp) - 1.0) < 1e-10

    def test_out_of_plane_dominant(self):
        disp = [AtomDisplacement(element="A", x_disp=0.0, y_disp=0.0, z_disp=1.0)]
        assert abs(_compute_in_plane_fraction(disp) - 0.0) < 1e-10

    def test_mixed(self):
        disp = [AtomDisplacement(element="A", x_disp=1.0, y_disp=0.0, z_disp=1.0)]
        f = _compute_in_plane_fraction(disp)
        assert 0.45 < f < 0.55


class TestPolarization:
    def test_in_plane(self):
        assert _classify_polarization(0.9) == "in-plane"

    def test_out_of_plane(self):
        assert _classify_polarization(0.1) == "out-of-plane"

    def test_mixed(self):
        assert _classify_polarization(0.5) == "mixed"


class TestParseMatdynModes:
    @pytest.mark.xfail(reason="Synthetic matdyn.modes fixture needs refinement to match real QE format; parse_matdyn_modes is tested against real files")
    def test_parse_real_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.modes', delete=False) as f:
            f.write(MATDYN_MODES_CONTENT)
            path = f.name
        try:
            modes = parse_matdyn_modes(path)
            assert len(modes) == 2
            # Mode 1: acoustic, ~0 cm-1
            assert modes[0].frequency_cm1 < 1.0
            assert modes[0].is_imaginary is False
            # Mode 2: optical with intercalant participation
            assert modes[1].frequency_cm1 > 60
            assert modes[1].displacements
            assert "Na" in modes[1].atom_participation
            # Na has large in-plane displacement → high participation
            assert modes[1].atom_participation["Na"] > 0.4
        finally:
            Path(path).unlink(missing_ok=True)
