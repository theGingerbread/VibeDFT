"""ASE-backed band-path and high-symmetry-point helpers for 2D materials.

ROADMAP §3.2: generic structure analysis (band-path computation) lives in
the analyzer layer and is allowed to import ``ase``. This module is a
data-only helper — it returns plain dicts that the plot layer (Sprint 3)
and the workflow generator consume. No matplotlib here.

The 2D materials VibeDFT targets (HfCl₂, HfBr₂, HfI₂, ZrX₂) are
hexagonal, so the canonical path is Γ-M-K-Γ. For non-hexagonal cells we
fall back to ``ase.dft.kpoints.bandpath`` with the full 3D cell and let
ASE pick the high-symmetry points.

ASE imports are confined to ``core/structure.py`` and this module. They
must NOT leak into ``parsers/`` or ``validators/`` — see
``ASE_INTEGRATION.md``.
"""

from __future__ import annotations

from pathlib import Path

from vibedft.core.structure import _ase_available, parse_structure


# ═══════════════════════════════════════════════════════════════════════════════
# 2D high-symmetry points (fractional, hexagonal BZ)
# ═══════════════════════════════════════════════════════════════════════════════

HIGH_SYMMETRY_2D: dict[str, list[float]] = {
    "Γ": [0.0, 0.0, 0.0],
    "M": [0.5, 0.0, 0.0],
    "K": [1.0 / 3.0, 1.0 / 3.0, 0.0],
    "K'": [-1.0 / 3.0, 1.0 / 3.0, 0.0],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

_GREEK: dict[str, str] = {"G": "Γ"}


def _label(name: str) -> str:
    """Map ASE's ASCII special-point names to VibeDFT display names."""
    return _GREEK.get(name, name)


def _path_string_to_segments(path_str: str) -> list[list[str]]:
    """Convert an ASE path string (e.g. ``'GMKG'`` or ``'GXSYGZURTZ,YT'``)
    into a list of ``[name1, name2]`` segments.

    Commas separate discontinuous subpaths; consecutive characters within
    a subpath form segments. Names are passed through :func:`_label`.
    """
    segments: list[list[str]] = []
    for sub in path_str.split(","):
        names = [_label(c) for c in sub]
        for i in range(len(names) - 1):
            segments.append([names[i], names[i + 1]])
    return segments


def _bandpath_dict(bp) -> dict:
    """Shape a raw ASE ``BandPath`` object into the VibeDFT band-path dict."""
    x, X, labels = bp.get_linear_kpoint_axis()
    special_points = {
        _label(k): [float(v[0]), float(v[1]), float(v[2])]
        for k, v in bp.special_points.items()
    }
    return {
        "kpoints": [[float(p[0]), float(p[1]), float(p[2])] for p in bp.kpts],
        "special_points": special_points,
        "path": _path_string_to_segments(bp.path),
        "x_coords": [float(v) for v in x],
        "x_special": [float(v) for v in X],
        "labels": [(float(X[i]), _label(labels[i])) for i in range(len(labels))],
    }


def _is_hexagonal(a: float, b: float, gamma: float, rtol: float = 0.05, atol_deg: float = 3.0) -> bool:
    """True when the in-plane lattice is hexagonal: ``a≈b`` and ``γ≈120°``."""
    return abs(a - b) <= rtol * max(a, b, 1e-9) and abs(gamma - 120.0) <= atol_deg


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════


def bandpath_2d_hex(a: float, b: float | None = None, n: int = 50) -> dict:
    """Return a band-path dict for a 2D hexagonal lattice (Γ-M-K-Γ).

    Parameters
    ----------
    a:
        In-plane lattice constant (Å). Used for the first lattice vector.
    b:
        Second in-plane lattice constant (Å). Defaults to ``a`` so the
        cell is exactly hexagonal when omitted.
    n:
        Target number of k-points per segment. ASE distributes the total
        ``n × n_segments`` points proportionally to each segment's
        Cartesian length, which keeps the k-space density uniform — the
        physically correct behaviour for band-structure plots.

    Returns
    -------
    dict
        ``kpoints`` (list of ``[kx, ky, kz]``), ``special_points``
        (name → ``[kx, ky, kz]``), ``path`` (list of ``[name1, name2]``
        segments), ``x_coords`` (cumulative Cartesian distance per
        k-point), ``x_special`` (x positions of the special points),
        ``labels`` (list of ``(x, name)`` tick tuples).

    Raises
    ------
    RuntimeError
        If the ``ase`` extra is not installed.
    """
    if not _ase_available():
        raise RuntimeError("bandpath requires the 'ase' extra")
    import numpy as np
    from ase.dft.kpoints import bandpath

    if b is None:
        b = a
    cell = np.array(
        [
            [a, 0.0, 0.0],
            [-b / 2.0, b * (3.0**0.5) / 2.0, 0.0],
            [0.0, 0.0, max(a, b) * 10.0],
        ]
    )
    special = {
        "G": [0.0, 0.0, 0.0],
        "M": [0.5, 0.0, 0.0],
        "K": [1.0 / 3.0, 1.0 / 3.0, 0.0],
    }
    n_segments = 3
    npoints = max(n * n_segments, n_segments + 1)
    bp = bandpath("GMKG", cell, npoints=npoints, special_points=special)
    return _bandpath_dict(bp)


def bandpath_for_structure(structure_path: Path | str, n: int = 50) -> dict | None:
    """Read a structure file and return the appropriate band-path dict.

    The structure is parsed via :func:`vibedft.core.structure.parse_structure`
    (the existing ASE-backed dispatcher). When the in-plane lattice is
    hexagonal (``a≈b`` and ``γ≈120°``) the result of
    :func:`bandpath_2d_hex` is returned. For any other lattice the full
    3D cell is handed to ``ase.dft.kpoints.bandpath`` and ASE selects the
    high-symmetry path.

    Returns ``None`` when ASE is unavailable, the file does not exist,
    or the structure cannot be parsed.
    """
    if not _ase_available():
        return None
    path = Path(structure_path)
    if not path.is_file():
        return None
    try:
        structure = parse_structure(path)
    except Exception:
        return None
    if structure is None or structure.lattice is None:
        return None

    lat = structure.lattice
    if _is_hexagonal(lat.a, lat.b, lat.gamma):
        return bandpath_2d_hex(lat.a, lat.b, n)

    import numpy as np
    from ase.dft.kpoints import bandpath

    cell = np.array(lat.matrix)
    try:
        bp = bandpath(None, cell, npoints=max(n, 4))
    except Exception:
        return None
    return _bandpath_dict(bp)


__all__ = [
    "HIGH_SYMMETRY_2D",
    "bandpath_2d_hex",
    "bandpath_for_structure",
]
