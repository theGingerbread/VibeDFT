"""Fermi surface analysis: BXSF parser and integrity checks.

Handles QE fs.x output in XCrySDen BXSF format (BEGIN_BLOCK_BANDGRID_3D).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class BxsfData:
    """Parsed QE Fermi surface BXSF file."""

    filename: str = ""
    n_bands: int = 0
    n_k1: int = 0
    n_k2: int = 0
    n_k3: int = 0
    n_kpoints: int = 0
    fermi_energy_ev: float | None = None
    origin: list[float] = field(default_factory=list)
    reciprocal_vectors: list[list[float]] = field(default_factory=list)
    band_energies: list[list[float]] = field(default_factory=list)
    bands_crossing_ef: list[int] = field(default_factory=list)
    band_min: list[float] = field(default_factory=list)
    band_max: list[float] = field(default_factory=list)
    band_point_counts: list[int] = field(default_factory=list)
    """Per-band energy point count. Should equal n_kpoints for each band."""
    has_data: bool = False
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_fermi_surface(self) -> bool:
        """True if at least one band crosses the Fermi level."""
        return len(self.bands_crossing_ef) > 0

    def summary(self) -> str:
        lines = [
            f"Fermi Surface: {self.filename}",
            f"Grid: {self.n_k1}×{self.n_k2}×{self.n_k3} ({self.n_kpoints} k-points)",
            f"Bands: {self.n_bands}",
        ]
        if self.fermi_energy_ev is not None:
            lines.append(f"Fermi Energy: {self.fermi_energy_ev:.4f} eV")
        if self.bands_crossing_ef:
            lines.append(f"Bands crossing EF: {self.bands_crossing_ef}")
        else:
            lines.append("No bands cross EF (insulator or no FS data)")
        if self.parse_errors:
            lines.append("Parse errors:")
            for e in self.parse_errors[:5]:
                lines.append(f"  {e}")
        return "\n".join(lines)


@dataclass
class FsOutData:
    """Parsed QE fs.x output summary."""

    filename: str = ""
    job_done: bool = False
    crossing_band_count: int | None = None
    fermi_energy_ev: float | None = None
    warnings: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# BXSF Parser
# ---------------------------------------------------------------------------


def parse_bxsf(filepath: Path | str) -> BxsfData:
    """Parse a QE fs.x BXSF file (XCrySDen format).

    Format::

        BEGIN_INFO
          Fermi Energy: -1.112
        END_INFO
        BEGIN_BLOCK_BANDGRID_3D
          band_energies
          BANDGRID_3D_BANDS
          <n_bands>
          <n_k1> <n_k2> <n_k3>
          <k1_1> <k2_1> <k3_1>
          ...
          BAND: <iband>
          <E(1,1,1)> <E(2,1,1)> ... <E(n_k1,1,1)>
          <E(1,2,1)> <E(2,2,1)> ...
          ...
        END_BLOCK_BANDGRID_3D
    """
    path = Path(filepath)
    result = BxsfData(filename=path.name)

    if not path.is_file():
        result.parse_errors.append(f"File not found: {filepath}")
        return result

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result.parse_errors.append(f"Read error: {exc}")
        return result

    lines = text.splitlines()

    # Extract Fermi energy from INFO block
    in_info = False
    for line in lines:
        line_stripped = line.strip()
        if "BEGIN_INFO" in line_stripped:
            in_info = True
            continue
        if "END_INFO" in line_stripped:
            in_info = False
            continue
        if in_info and "Fermi Energy" in line_stripped:
            m = re.search(r"Fermi Energy[:\s]+([-\d.]+)", line_stripped)
            if m:
                result.fermi_energy_ev = float(m.group(1))

    # Parse supported BANDGRID dialects.
    in_grid = False
    header_state = "search"
    band_idx = -1

    for line in lines:
        ls = line.strip()
        upper = ls.upper()
        if not ls:
            continue
        if "BEGIN_BLOCK_BANDGRID_3D" in upper:
            in_grid = True
            continue
        if "END_BLOCK_BANDGRID_3D" in upper or upper.startswith("END_BANDGRID"):
            in_grid = False
            continue
        if _is_grid_marker(upper):
            in_grid = True
            header_state = "n_bands"
            continue
        if not in_grid:
            continue

        band_match = re.search(r"\bBAND\s*:?\s*(\d+)", ls, re.IGNORECASE)
        if band_match:
            band_idx = int(band_match.group(1))
            _ensure_band_slot(result, band_idx)
            header_state = "band_data"
            continue

        if header_state == "n_bands":
            ints = _parse_ints(ls)
            if ints:
                result.n_bands = ints[0]
                header_state = "dims"
            continue

        if header_state == "dims":
            ints = _parse_ints(ls)
            if len(ints) >= 3:
                result.n_k1 = ints[0]
                result.n_k2 = ints[1]
                result.n_k3 = ints[2]
                result.n_kpoints = result.n_k1 * result.n_k2 * result.n_k3
                header_state = "origin"
            continue

        if header_state == "origin":
            values = _parse_floats(ls)
            if len(values) >= 3:
                result.origin = values[:3]
                header_state = "reciprocal"
            continue

        if header_state == "reciprocal":
            values = _parse_floats(ls)
            if len(values) >= 3:
                result.reciprocal_vectors.append(values[:3])
                if len(result.reciprocal_vectors) >= 3:
                    header_state = "before_band"
            continue

        if header_state == "before_band":
            continue

        if header_state == "band_data":
            energies = _parse_floats(ls)
            if not energies:
                continue

            ib = band_idx - 1
            if 0 <= ib < len(result.band_min):
                for e in energies:
                    result.band_energies[ib].append(e)
                    result.band_point_counts[ib] += 1
                    if e < result.band_min[ib]:
                        result.band_min[ib] = e
                    if e > result.band_max[ib]:
                        result.band_max[ib] = e

    # Validate per-band point counts against expected grid size
    expected_n = result.n_kpoints
    for ib in range(len(result.band_point_counts)):
        count = result.band_point_counts[ib]
        if count != expected_n and expected_n > 0:
            result.parse_errors.append(
                f"Band {ib + 1}: read {count} energy points, expected {expected_n} "
                f"(BXSF may be truncated or corrupted)"
            )
            if count == 0:
                result.band_min[ib] = float("inf")
                result.band_max[ib] = float("-inf")

    # Validate that all declared bands have data
    if len(result.band_point_counts) != result.n_bands:
        result.parse_errors.append(
            f"Declared {result.n_bands} bands but only read {len(result.band_point_counts)} "
            f"(BXSF is truncated — missing BAND blocks)"
        )

    # Determine which bands cross EF
    ef = result.fermi_energy_ev or 0.0
    for ib in range(len(result.band_min)):
        if result.band_min[ib] <= ef <= result.band_max[ib]:
            result.bands_crossing_ef.append(ib + 1)

    # has_data is true only when we have bands AND no truncation errors for all bands
    result.has_data = (
        result.n_bands > 0
        and result.n_kpoints > 0
        and len(result.parse_errors) == 0
    )

    if not result.has_data and len(result.parse_errors) == 0:
        result.parse_errors.append("No BANDGRID_3D data block found")

    return result


def parse_fs_out(filepath: Path | str) -> FsOutData:
    """Parse QE ``fs.x`` output for EF-crossing count and energy reference."""

    path = Path(filepath)
    result = FsOutData(filename=path.name)
    if not path.is_file():
        result.parse_errors.append(f"File not found: {filepath}")
        return result

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result.parse_errors.append(f"Read error: {exc}")
        return result

    result.job_done = "JOB DONE" in text.upper()
    crossing = re.search(
        r"(\d+)\s+bands?.{0,80}?cross(?:ing)?\s+E\s*f\s*=\s*([-+]?\d+(?:\.\d*)?(?:[EeDd][-+]?\d+)?)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if crossing:
        result.crossing_band_count = int(crossing.group(1))
        result.fermi_energy_ev = _to_float(crossing.group(2))
    else:
        ef_match = re.search(
            r"\bE\s*f\s*=\s*([-+]?\d+(?:\.\d*)?(?:[EeDd][-+]?\d+)?)",
            text,
            re.IGNORECASE,
        )
        if ef_match:
            result.fermi_energy_ev = _to_float(ef_match.group(1))
        result.warnings.append("No EF-crossing band count found in fs.out")

    return result


def slice_kx_ky(data: BxsfData, band_index: int, k3_index: int = 0) -> list[list[float]]:
    """Return a 2D kx-ky energy slice for a parsed BXSF band."""

    if band_index < 1 or band_index > len(data.band_energies):
        return []
    if data.n_k1 <= 0 or data.n_k2 <= 0 or data.n_k3 <= 0:
        return []
    if k3_index < 0 or k3_index >= data.n_k3:
        return []

    values = data.band_energies[band_index - 1]
    offset = k3_index * data.n_k1 * data.n_k2
    needed = offset + data.n_k1 * data.n_k2
    if len(values) < needed:
        return []

    grid = []
    for iy in range(data.n_k2):
        start = offset + iy * data.n_k1
        grid.append(values[start : start + data.n_k1])
    return grid


def analyze_fermi_surface(
    bxsf_path: Path | str,
    fs_out_path: Path | str | None = None,
    *,
    energy_tolerance_ev: float = 0.05,
):
    """Build an evidence-backed Fermi-surface analysis result."""

    from vibedft.research.models import (
        AnalysisResult,
        ArtifactType,
        EvidenceRef,
        PhysicsDescriptor,
        ReliabilityLevel,
        ResultStatus,
    )

    bxsf = parse_bxsf(bxsf_path)
    warnings: list[str] = []
    blockers = list(bxsf.parse_errors)
    evidence = [
        EvidenceRef(
            artifact_path=str(bxsf_path),
            artifact_type=ArtifactType.BANDS,
            parser_name="vibedft.core.fs.parse_bxsf",
            parsed_quantity="fermi_surface_bxsf",
            raw_value={
                "grid": [bxsf.n_k1, bxsf.n_k2, bxsf.n_k3],
                "fermi_energy_ev": bxsf.fermi_energy_ev,
                "bands_crossing_ef": bxsf.bands_crossing_ef,
            },
            summary=f"BXSF grid {bxsf.n_k1}x{bxsf.n_k2}x{bxsf.n_k3}; {len(bxsf.bands_crossing_ef)} EF-crossing bands.",
            blockers=list(bxsf.parse_errors),
            reliability=ReliabilityLevel.MEDIUM if bxsf.has_data else ReliabilityLevel.LOW,
        )
    ]

    fs_out: FsOutData | None = None
    if fs_out_path is not None:
        fs_out = parse_fs_out(fs_out_path)
        blockers.extend(fs_out.parse_errors)
        warnings.extend(fs_out.warnings)
        evidence.append(
            EvidenceRef(
                artifact_path=str(fs_out_path),
                artifact_type=ArtifactType.OUTPUT,
                parser_name="vibedft.core.fs.parse_fs_out",
                parsed_quantity="fs_out_crossing_count",
                raw_value={
                    "fermi_energy_ev": fs_out.fermi_energy_ev,
                    "crossing_band_count": fs_out.crossing_band_count,
                    "job_done": fs_out.job_done,
                },
                summary="fs.out crossing-band count and energy reference.",
                warnings=list(fs_out.warnings),
                blockers=list(fs_out.parse_errors),
                reliability=ReliabilityLevel.MEDIUM,
            )
        )
        if (
            bxsf.fermi_energy_ev is not None
            and fs_out.fermi_energy_ev is not None
            and abs(bxsf.fermi_energy_ev - fs_out.fermi_energy_ev) > energy_tolerance_ev
        ):
            warnings.append(
                "BXSF/fs.out energy reference mismatch: "
                f"BXSF EF={bxsf.fermi_energy_ev:.6f} eV, "
                f"fs.out EF={fs_out.fermi_energy_ev:.6f} eV"
            )

    topology = _fermi_surface_topology(bxsf) if bxsf.has_data else {}
    descriptors = [
        PhysicsDescriptor(
            name="fs_topology_summary",
            value=topology,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if bxsf.has_data else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="ef_crossing_bands",
            value=bxsf.bands_crossing_ef,
            evidence=evidence,
            reliability=ReliabilityLevel.MEDIUM,
        ),
        PhysicsDescriptor(
            name="nesting_score",
            value=topology.get("nesting_score") if topology else None,
            evidence=evidence,
            reliability=ReliabilityLevel.LOW,
        ),
    ]

    if blockers:
        status = ResultStatus.BLOCKED
    elif warnings:
        status = ResultStatus.WARNING
    else:
        status = ResultStatus.PASS

    return AnalysisResult(
        id="analysis.fermi_surface",
        parser_name="vibedft.core.fs.analyze_fermi_surface",
        status=status,
        parsed_quantity="fermi_surface_topology",
        evidence=evidence,
        descriptors=descriptors,
        summary="Evidence-backed Fermi surface topology analysis.",
        warnings=warnings,
        blockers=blockers,
        reliability=ReliabilityLevel.MEDIUM if bxsf.has_data else ReliabilityLevel.LOW,
        metadata={"fs_out_job_done": fs_out.job_done if fs_out else None},
    )


def _fermi_surface_topology(data: BxsfData) -> dict[str, Any]:
    ef = data.fermi_energy_ev if data.fermi_energy_ev is not None else 0.0
    pockets: list[dict[str, Any]] = []
    total_crossing_edges = 0
    total_edges = 0
    slopes: list[float] = []

    for band_index in data.bands_crossing_ef:
        values = data.band_energies[band_index - 1]
        below = sum(1 for value in values if value < ef)
        above = sum(1 for value in values if value > ef)
        if below == 0 or above == 0:
            carrier_type = "mixed"
        elif below < above:
            carrier_type = "electron"
        elif above < below:
            carrier_type = "hole"
        else:
            carrier_type = "mixed"

        grid = slice_kx_ky(data, band_index)
        velocity = _estimate_grid_velocity(grid, ef)
        total_crossing_edges += velocity["crossing_edges"]
        total_edges += velocity["total_edges"]
        slopes.extend(velocity["abs_slopes"])
        pockets.append(
            {
                "band_index": band_index,
                "carrier_type": carrier_type,
                "n_points_below_ef": below,
                "n_points_above_ef": above,
                "energy_min_ev": data.band_min[band_index - 1],
                "energy_max_ev": data.band_max[band_index - 1],
            }
        )

    nesting_score = (total_crossing_edges / total_edges) if total_edges else 0.0
    return {
        "has_fermi_surface": data.has_fermi_surface,
        "ef_crossing_bands": data.bands_crossing_ef,
        "n_pockets": len(pockets),
        "pockets": pockets,
        "n_electron_pockets": sum(1 for p in pockets if p["carrier_type"] == "electron"),
        "n_hole_pockets": sum(1 for p in pockets if p["carrier_type"] == "hole"),
        "n_mixed_pockets": sum(1 for p in pockets if p["carrier_type"] == "mixed"),
        "nesting_score": nesting_score,
        "fermi_velocity": {
            "mean_abs_slope_ev": sum(slopes) / len(slopes) if slopes else 0.0,
            "max_abs_slope_ev": max(slopes) if slopes else 0.0,
            "crossing_edges": total_crossing_edges,
        },
    }


def _estimate_grid_velocity(grid: list[list[float]], ef: float) -> dict[str, Any]:
    crossing_edges = 0
    total_edges = 0
    slopes: list[float] = []
    for y, row in enumerate(grid):
        for x, value in enumerate(row):
            for nx, ny in ((x + 1, y), (x, y + 1)):
                if ny >= len(grid) or nx >= len(grid[ny]):
                    continue
                other = grid[ny][nx]
                total_edges += 1
                if (value - ef) * (other - ef) <= 0:
                    crossing_edges += 1
                    slopes.append(abs(other - value))
    return {
        "crossing_edges": crossing_edges,
        "total_edges": total_edges,
        "abs_slopes": slopes,
    }


def _ensure_band_slot(result: BxsfData, band_index: int) -> None:
    while len(result.band_energies) < band_index:
        result.band_energies.append([])
        result.band_min.append(float("inf"))
        result.band_max.append(float("-inf"))
        result.band_point_counts.append(0)


def _is_grid_marker(line: str) -> bool:
    return (
        "BANDGRID" in line
        and "BLOCK" not in line
        and (
            "BANDS" in line
            or line.startswith("BEGIN_BANDGRID_3D")
            or line.startswith("BEGIN_BANDGRID")
        )
    )


def _parse_ints(line: str) -> list[int]:
    values: list[int] = []
    for token in line.split():
        try:
            values.append(int(token))
        except ValueError:
            return []
    return values


def _parse_floats(line: str) -> list[float]:
    values: list[float] = []
    for token in line.split():
        try:
            values.append(_to_float(token))
        except ValueError:
            return []
    return values


def _to_float(token: str) -> float:
    return float(token.replace("D", "E").replace("d", "e"))
