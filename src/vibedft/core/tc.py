"""TC (superconducting transition temperature) analysis.

Parses lambda.x output, implements the two-grid Tc overlap algorithm
from DFT STANDARDS.md §2.5, and provides structured Tc results.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class LambdaOutput:
    """Parsed lambda.x output."""

    degauss_values: list[float] = field(default_factory=list)
    lambda_values: list[float] = field(default_factory=list)
    omega_log_values: list[float] = field(default_factory=list)
    tc_values: list[float] = field(default_factory=list)
    nef_values: list[float] = field(default_factory=list)
    nan_rows: list[int] = field(default_factory=list)
    n_rows: int = 0
    mustar: float = 0.10

    @property
    def has_data(self) -> bool:
        return self.n_rows > 0


@dataclass
class TcOverlapResult:
    """Result of two-grid Tc overlap analysis."""

    tc_point_k: float | None = None
    degauss_ry: float | None = None
    overlap_status: str = "unknown"  # pass | fail | single_grid | no_data
    overlap_start_degauss: float | None = None
    overlap_end_degauss: float | None = None
    relative_deviation_pct: float | None = None
    nan_rows_a: list[int] = field(default_factory=list)
    nan_rows_b: list[int] = field(default_factory=list)
    message: str = ""


@dataclass
class Alpha2FData:
    """Parsed alpha2F spectral function data."""

    omega_values_cm1: list[float] = field(default_factory=list)
    alpha2f_values: list[float] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return bool(self.omega_values_cm1)

    @property
    def n_points(self) -> int:
        return len(self.omega_values_cm1)

    @property
    def omega_min_cm1(self) -> float | None:
        return min(self.omega_values_cm1) if self.omega_values_cm1 else None

    @property
    def omega_max_cm1(self) -> float | None:
        return max(self.omega_values_cm1) if self.omega_values_cm1 else None

    @property
    def alpha2f_max(self) -> float | None:
        return max(self.alpha2f_values) if self.alpha2f_values else None


@dataclass
class LambdaDatData:
    """Parsed cumulative lambda.dat data."""

    omega_values_cm1: list[float] = field(default_factory=list)
    cumulative_lambda_values: list[float] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return bool(self.omega_values_cm1)

    @property
    def n_points(self) -> int:
        return len(self.omega_values_cm1)

    @property
    def lambda_final(self) -> float | None:
        return self.cumulative_lambda_values[-1] if self.cumulative_lambda_values else None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_lambdax_output(filepath: Path | str) -> LambdaOutput:
    """Parse a QE lambda.x output file into structured data.

    Extracts degauss, lambda, omega_log, Tc, and N(Ef) from the
    McMillan-Allen-Dynes table.
    """
    path = Path(filepath)
    if not path.is_file():
        return LambdaOutput()

    text = path.read_text(encoding="utf-8", errors="replace")
    result = LambdaOutput()

    # Extract mu* (Coulomb pseudopotential)
    m_mustar = re.search(r"mu\*\s*=\s*([\d.]+)", text)
    if m_mustar:
        result.mustar = float(m_mustar.group(1))

    # ── Pass 1: parse detailed section ──
    # Format:  lambda = 1.136259 (   1.136199 )  <log w>=   73.595 K  N(Ef)= 16.848587 at degauss= 0.001
    # Collect: degauss → lambda, omega_log, N(Ef)
    detail_rows: list[dict[str, float]] = []
    for line in text.splitlines():
        if "lambda =" not in line or "degauss=" not in line:
            continue
        m_lam = re.search(r"lambda\s*=\s*([\d.]+)", line)
        m_w = re.search(r"<log w>\s*=\s*([\d.]+)\s*K", line)
        m_nef = re.search(r"N\(Ef\)\s*=\s*([\d.]+)", line)
        m_dg = re.search(r"degauss\s*=\s*([\d.]+)", line)
        if m_lam and m_dg:
            detail_rows.append({
                "degauss": float(m_dg.group(1)),
                "lambda": float(m_lam.group(1)),
                "omega_log": float(m_w.group(1)) if m_w else 0.0,
                "nef": float(m_nef.group(1)) if m_nef else 0.0,
            })

    # ── Pass 2: parse compact Tc table ──
    # Format:  lambda        omega_log          T_c
    #            1.13626        73.595              6.147
    in_tc_table = False
    tc_rows: list[dict[str, float]] = []
    for line in text.splitlines():
        ls = line.strip()
        if "lambda" in ls.lower() and "omega_log" in ls.lower() and "t_c" in ls.lower():
            in_tc_table = True
            continue
        if not in_tc_table:
            continue
        if not ls or ls.startswith("=") or ls.startswith("-"):
            continue
        parts = ls.split()
        if len(parts) != 3:
            continue
        try:
            lam = float(parts[0])
            omega = float(parts[1])
            tc = float(parts[2])
        except (ValueError, IndexError):
            continue
        tc_rows.append({"lambda": lam, "omega_log": omega, "tc": tc})

    # ── Merge: match detail rows to Tc rows by position ──
    # If counts match, zip directly; otherwise match by lambda proximity
    if len(detail_rows) == len(tc_rows) and detail_rows:
        for dr, tr in zip(detail_rows, tc_rows):
            dg = dr["degauss"]
            lam = dr["lambda"]
            omega = dr["omega_log"]
            tc = tr["tc"]
            nef = dr["nef"]
            if math.isnan(lam) or math.isnan(omega) or math.isnan(tc):
                result.nan_rows.append(result.n_rows)
                result.degauss_values.append(dg)
                result.lambda_values.append(float("nan"))
                result.omega_log_values.append(float("nan"))
                result.tc_values.append(float("nan"))
                result.nef_values.append(float("nan"))
            else:
                result.degauss_values.append(dg)
                result.lambda_values.append(lam)
                result.omega_log_values.append(omega)
                result.tc_values.append(tc)
                result.nef_values.append(nef)
            result.n_rows += 1
    elif detail_rows and tc_rows:
        # Match by nearest lambda
        for dr in detail_rows:
            best_tc = min(tc_rows, key=lambda tr: abs(tr["lambda"] - dr["lambda"]))
            dg = dr["degauss"]
            lam = dr["lambda"]
            omega = dr["omega_log"]
            tc = best_tc["tc"]
            nef = dr["nef"]
            if math.isnan(lam) or math.isnan(omega) or math.isnan(tc):
                result.nan_rows.append(result.n_rows)
            result.degauss_values.append(dg)
            result.lambda_values.append(lam)
            result.omega_log_values.append(omega)
            result.tc_values.append(tc)
            result.nef_values.append(nef)
            result.n_rows += 1
    elif tc_rows:
        # Some lambda.x outputs only keep the compact lambda/omega_log/Tc table
        # without the preceding degauss-resolved detail lines.
        for row_index, tr in enumerate(tc_rows):
            lam = tr["lambda"]
            omega = tr["omega_log"]
            tc = tr["tc"]
            if math.isnan(lam) or math.isnan(omega) or math.isnan(tc):
                result.nan_rows.append(result.n_rows)
            result.degauss_values.append(float(row_index))
            result.lambda_values.append(lam)
            result.omega_log_values.append(omega)
            result.tc_values.append(tc)
            result.nef_values.append(0.0)
            result.n_rows += 1

    # ── Fallback: legacy degauss-in-column format ──
    if result.n_rows == 0:
        in_table = False
        for line in text.splitlines():
            ls = line.strip()
            if "lambda" in ls.lower() and "omega_log" in ls.lower() and "t_c" in ls.lower():
                in_table = True
                continue
            if not in_table:
                continue
            if not ls or ls.startswith("=") or ls.startswith("-"):
                continue
            parts = ls.split()
            if len(parts) < 4:
                continue
            try:
                dg = float(parts[0])
                lam = float(parts[1])
                omega = float(parts[2])
                tc = float(parts[3])
            except (ValueError, IndexError):
                continue
            if math.isnan(lam) or math.isnan(omega) or math.isnan(tc):
                result.nan_rows.append(result.n_rows)
            m_nef = re.search(r"N\(Ef\)\s*=\s*([\d.]+)", ls, re.IGNORECASE)
            result.degauss_values.append(dg)
            result.lambda_values.append(lam)
            result.omega_log_values.append(omega)
            result.tc_values.append(tc)
            result.nef_values.append(float(m_nef.group(1)) if m_nef else 0.0)
            result.n_rows += 1

    return result


def parse_alpha2f_dat(filepath: Path | str) -> Alpha2FData:
    """Parse two-column ``alpha2F.dat`` spectral data.

    The first numeric column is treated as frequency and the second as
    alpha²F.  Header and comment lines are ignored.
    """
    path = Path(filepath)
    result = Alpha2FData()
    if not path.is_file():
        result.parse_errors.append(f"alpha2F.dat not found: {path}")
        return result

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ls = line.strip()
        if not ls or ls.startswith("#") or ls.startswith("!"):
            continue
        parts = ls.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            omega = float(parts[0])
            alpha2f = float(parts[1])
        except ValueError:
            continue
        result.omega_values_cm1.append(omega)
        result.alpha2f_values.append(alpha2f)

    if not result.has_data:
        result.parse_errors.append(f"alpha2F.dat has no numeric spectral rows: {path}")
    return result


def parse_lambda_dat(filepath: Path | str) -> LambdaDatData:
    """Parse cumulative ``lambda.dat`` data.

    The first numeric column is treated as frequency and the final numeric
    column as cumulative lambda, which handles common QE/EPW variants with
    intermediate columns.
    """
    path = Path(filepath)
    result = LambdaDatData()
    if not path.is_file():
        result.parse_errors.append(f"lambda.dat not found: {path}")
        return result

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ls = line.strip()
        if not ls or ls.startswith("#") or ls.startswith("!"):
            continue
        parts = ls.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            values = [float(part) for part in parts]
        except ValueError:
            continue
        result.omega_values_cm1.append(values[0])
        result.cumulative_lambda_values.append(values[-1])

    if not result.has_data:
        result.parse_errors.append(f"lambda.dat has no numeric cumulative rows: {path}")
    return result


def analyze_superconductivity_reliability(
    lambdax_path: Path | str,
    *,
    phonon_freq_path: Path | str | None = None,
    alpha2f_path: Path | str | None = None,
    lambda_dat_path: Path | str | None = None,
    epw_path: Path | str | None = None,
    mustar_values: tuple[float, ...] = (0.08, 0.10, 0.15),
):
    """Return an evidence-backed reliability gate for EPC/Tc conclusions.

    Negative signed phonon frequencies and non-finite lambda.x rows block any
    physical Tc claim.  QE lambda.x-only evidence remains LOW reliability;
    alpha2F plus cumulative lambda raises this to MEDIUM; HIGH is reserved for
    explicit EPW evidence.
    """
    from vibedft.core.phonon import parse_freq_gp
    from vibedft.research.models import (
        AnalysisResult,
        ArtifactType,
        EvidenceRef,
        PhysicsDescriptor,
        ReliabilityLevel,
        ResultStatus,
    )

    lambdax = parse_lambdax_output(lambdax_path)
    warnings: list[str] = []
    blockers: list[str] = []
    evidence: list[EvidenceRef] = [
        EvidenceRef(
            artifact_path=str(lambdax_path),
            artifact_type=ArtifactType.LAMBDAX,
            parser_name="vibedft.core.tc.parse_lambdax_output",
            parsed_quantity="lambda_omega_log_tc",
            raw_value={
                "n_rows": lambdax.n_rows,
                "mustar": lambdax.mustar,
                "lambda_values": lambdax.lambda_values,
                "omega_log_values": lambdax.omega_log_values,
                "tc_values": lambdax.tc_values,
                "nan_rows": lambdax.nan_rows,
            },
            summary=f"lambda.x rows={lambdax.n_rows}, nan_rows={len(lambdax.nan_rows)}",
            reliability=ReliabilityLevel.LOW,
        )
    ]

    if not lambdax.has_data:
        blockers.append("lambda.x evidence is missing or contains no parseable Tc rows")

    non_finite_rows = _non_finite_lambdax_rows(lambdax)
    if non_finite_rows:
        blockers.append(
            "NaN/non-finite lambda, omega_log, or Tc values block superconductivity claim "
            f"(rows: {non_finite_rows})"
        )

    phonon_min: float | None = None
    phonon_imaginary_count: int | None = None
    if phonon_freq_path is not None:
        phonon = parse_freq_gp(phonon_freq_path)
        phonon_min = phonon.min_frequency_cm1 if phonon.has_data else None
        phonon_imaginary_count = phonon.n_imaginary if phonon.has_data else None
        phonon_blockers: list[str] = []
        if not phonon.has_data:
            phonon_blockers.append("phonon frequency evidence is missing or empty")
        elif phonon.min_frequency_cm1 < 0:
            phonon_blockers.append(
                "negative phonon frequency blocks EPC/Tc conclusion: "
                f"min_frequency_cm1={phonon.min_frequency_cm1:.3f}"
            )
        blockers.extend(phonon_blockers)
        evidence.append(
            EvidenceRef(
                artifact_path=str(phonon_freq_path),
                artifact_type=ArtifactType.DYN,
                parser_name="vibedft.core.phonon.parse_freq_gp",
                parsed_quantity="signed_phonon_frequencies",
                raw_value={
                    "n_qpoints": phonon.n_qpoints,
                    "n_branches": phonon.n_branches,
                    "min_frequency_cm1": phonon_min,
                    "imaginary_modes": phonon.imaginary_modes,
                },
                summary=(
                    f"freq.gp qpoints={phonon.n_qpoints}, "
                    f"min={phonon_min if phonon_min is not None else 'NA'} cm^-1"
                ),
                blockers=phonon_blockers,
                reliability=ReliabilityLevel.MEDIUM if phonon.has_data else ReliabilityLevel.LOW,
            )
        )

    alpha2f: Alpha2FData | None = None
    if alpha2f_path is not None:
        alpha2f = parse_alpha2f_dat(alpha2f_path)
        warnings.extend(alpha2f.parse_errors)
        evidence.append(
            EvidenceRef(
                artifact_path=str(alpha2f_path),
                artifact_type=ArtifactType.A2F,
                parser_name="vibedft.core.tc.parse_alpha2f_dat",
                parsed_quantity="alpha2f_spectrum",
                raw_value={
                    "n_points": alpha2f.n_points,
                    "omega_min_cm1": alpha2f.omega_min_cm1,
                    "omega_max_cm1": alpha2f.omega_max_cm1,
                    "alpha2f_max": alpha2f.alpha2f_max,
                },
                summary=f"alpha2F points={alpha2f.n_points}",
                warnings=list(alpha2f.parse_errors),
                reliability=ReliabilityLevel.MEDIUM if alpha2f.has_data else ReliabilityLevel.LOW,
            )
        )

    lambda_dat: LambdaDatData | None = None
    if lambda_dat_path is not None:
        lambda_dat = parse_lambda_dat(lambda_dat_path)
        warnings.extend(lambda_dat.parse_errors)
        evidence.append(
            EvidenceRef(
                artifact_path=str(lambda_dat_path),
                artifact_type=ArtifactType.OUTPUT,
                parser_name="vibedft.core.tc.parse_lambda_dat",
                parsed_quantity="cumulative_lambda",
                raw_value={
                    "n_points": lambda_dat.n_points,
                    "lambda_final": lambda_dat.lambda_final,
                },
                summary=f"lambda.dat points={lambda_dat.n_points}",
                warnings=list(lambda_dat.parse_errors),
                reliability=ReliabilityLevel.MEDIUM if lambda_dat.has_data else ReliabilityLevel.LOW,
            )
        )

    has_epw = epw_path is not None and Path(epw_path).is_file()
    if epw_path is not None:
        epw_warning = "" if has_epw else f"EPW evidence path is missing: {epw_path}"
        if epw_warning:
            warnings.append(epw_warning)
        evidence.append(
            EvidenceRef(
                artifact_path=str(epw_path),
                artifact_type=ArtifactType.OUTPUT,
                parser_name="vibedft.core.tc.analyze_superconductivity_reliability",
                parsed_quantity="epw_presence",
                raw_value={"exists": has_epw},
                summary="EPW evidence availability for HIGH reliability gate.",
                warnings=[epw_warning] if epw_warning else [],
                reliability=ReliabilityLevel.HIGH if has_epw else ReliabilityLevel.LOW,
            )
        )

    reliability = ReliabilityLevel.LOW
    if (
        not blockers
        and alpha2f is not None
        and alpha2f.has_data
        and lambda_dat is not None
        and lambda_dat.has_data
    ):
        reliability = ReliabilityLevel.MEDIUM
    if not blockers and has_epw:
        reliability = ReliabilityLevel.HIGH

    lambda_max, omega_at_lambda_max, tc_at_lambda_max = _lambdax_max_triplet(lambdax)
    summary_value = {
        "lambda_max": lambda_max,
        "omega_log_at_lambda_max": omega_at_lambda_max,
        "tc_at_lambda_max": tc_at_lambda_max,
        "mustar": lambdax.mustar,
        "phonon_min_frequency_cm1": phonon_min,
        "phonon_imaginary_count": phonon_imaginary_count,
        "has_alpha2f": alpha2f.has_data if alpha2f is not None else False,
        "has_cumulative_lambda": lambda_dat.has_data if lambda_dat is not None else False,
        "has_epw": has_epw,
    }
    descriptors = [
        PhysicsDescriptor(
            name="superconductivity_summary",
            value=summary_value,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=reliability,
        ),
        PhysicsDescriptor(
            name="superconductivity_reliability",
            value=reliability.value,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=reliability,
        ),
        PhysicsDescriptor(
            name="mustar_sensitivity",
            value=_mustar_sensitivity(lambda_max, omega_at_lambda_max, mustar_values),
            unit="K",
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.LOW,
        ),
    ]

    if not lambdax.has_data:
        status = ResultStatus.INSUFFICIENT_EVIDENCE
    elif blockers:
        status = ResultStatus.BLOCKED
    elif warnings:
        status = ResultStatus.WARNING
    else:
        status = ResultStatus.PASS

    return AnalysisResult(
        id="analysis.superconductivity_reliability",
        parser_name="vibedft.core.tc.analyze_superconductivity_reliability",
        status=status,
        parsed_quantity="superconductivity_reliability",
        evidence=evidence,
        descriptors=descriptors,
        raw_value=summary_value,
        summary="Evidence-backed EPC/Tc reliability gate.",
        warnings=warnings,
        blockers=blockers,
        reliability=reliability,
        metadata={
            "forbidden_conclusions": [
                "Do not report a physical Tc from unstable phonons or non-finite EPC evidence."
            ] if blockers else [],
        },
    )


# ---------------------------------------------------------------------------
# Tc overlap algorithm
# ---------------------------------------------------------------------------


def compute_tc_overlap(
    file_a: Path | str,
    file_b: Path | str,
    *,
    label_a: str = "grid_a",
    label_b: str = "grid_b",
    rel_tol_pct: float = 1.0,
) -> TcOverlapResult:
    """Compute Tc overlap between two lambda.x outputs.

    Algorithm (from DFT STANDARDS.md §2.5):
    1. Extract degauss → Tc mapping from both files
    2. Rebuild common degauss axis via linear interpolation
    3. Find continuous region where |Tc_a - Tc_b| / mean(|Tc_a|, |Tc_b|) ≤ rel_tol_pct%
    4. Report overlap status and Tc_Point
    """
    data_a = parse_lambdax_output(file_a)
    data_b = parse_lambdax_output(file_b)

    if not data_a.has_data or not data_b.has_data:
        return TcOverlapResult(
            overlap_status="no_data",
            message="One or both lambda.x outputs have no data rows",
            nan_rows_a=data_a.nan_rows,
            nan_rows_b=data_b.nan_rows,
        )

    if data_a.nan_rows or data_b.nan_rows:
        result = TcOverlapResult(
            overlap_status="warn_nan",
            nan_rows_a=data_a.nan_rows,
            nan_rows_b=data_b.nan_rows,
            message=f"NaN rows: {label_a}={len(data_a.nan_rows)}, {label_b}={len(data_b.nan_rows)}. "
                    "Tc_Point may be unreliable.",
        )
    else:
        result = TcOverlapResult(
            overlap_status="unknown",
            nan_rows_a=data_a.nan_rows,
            nan_rows_b=data_b.nan_rows,
        )

    # Build common degauss axis (union of both, sorted)
    all_degauss = sorted(set(data_a.degauss_values + data_b.degauss_values))
    if len(all_degauss) < 3:
        result.overlap_status = "single_grid"
        result.message = "Insufficient degauss points for overlap analysis"
        return result

    # Interpolate Tc values onto common axis
    tc_a_interp = _linear_interpolate(
        all_degauss, data_a.degauss_values, data_a.tc_values
    )
    tc_b_interp = _linear_interpolate(
        all_degauss, data_b.degauss_values, data_b.tc_values
    )

    # Find continuous overlap segments — each is a (start_dg, end_dg, length) tuple
    min_consecutive = 3  # minimum consecutive points for stable overlap
    segments: list[tuple[float, float, int]] = []
    seg_start: float | None = None
    seg_end: float | None = None
    seg_len = 0

    for i, dg in enumerate(all_degauss):
        ta, tb = tc_a_interp[i], tc_b_interp[i]
        if math.isnan(ta) or math.isnan(tb) or ta <= 0 or tb <= 0:
            if seg_len >= min_consecutive and seg_start is not None and seg_end is not None:
                segments.append((seg_start, seg_end, seg_len))
            seg_start = None
            seg_end = None
            seg_len = 0
            continue

        mean_abs = (abs(ta) + abs(tb)) / 2.0
        if mean_abs < 1e-6:
            if seg_len >= min_consecutive and seg_start is not None and seg_end is not None:
                segments.append((seg_start, seg_end, seg_len))
            seg_start = None
            seg_end = None
            seg_len = 0
            continue

        rel_diff = abs(ta - tb) / mean_abs * 100.0

        if rel_diff <= rel_tol_pct:
            if seg_start is None:
                seg_start = dg
            seg_len += 1
            seg_end = dg
        else:
            if seg_len >= min_consecutive and seg_start is not None and seg_end is not None:
                segments.append((seg_start, seg_end, seg_len))
            seg_start = None
            seg_end = None
            seg_len = 0

    # Flush trailing segment
    if seg_len >= min_consecutive and seg_start is not None and seg_end is not None:
        segments.append((seg_start, seg_end, seg_len))

    if not segments:
        result.overlap_status = "fail"
        result.message = (
            f"No stable overlap region found between {label_a} and {label_b} "
            f"(rel_tol={rel_tol_pct}%, min_consecutive={min_consecutive}). "
            f"Check k-point convergence."
        )
        return result

    # Use the longest qualifying segment
    best = max(segments, key=lambda s: s[2])
    overlap_start, overlap_end, _ = best
    result.overlap_start_degauss = overlap_start
    result.overlap_end_degauss = overlap_end
    result.relative_deviation_pct = None  # computed below

    # Compute Tc_Point: average Tc in the best overlap segment
    overlap_tcs_a = []
    overlap_tcs_b = []
    for i, dg in enumerate(all_degauss):
        if overlap_start <= dg <= overlap_end:
            ta, tb = tc_a_interp[i], tc_b_interp[i]
            if not (math.isnan(ta) or math.isnan(tb) or ta <= 0 or tb <= 0):
                overlap_tcs_a.append(ta)
                overlap_tcs_b.append(tb)

    if overlap_tcs_a:
        avg_tc_a = sum(overlap_tcs_a) / len(overlap_tcs_a)
        avg_tc_b = sum(overlap_tcs_b) / len(overlap_tcs_b)
        result.tc_point_k = (avg_tc_a + avg_tc_b) / 2.0
        result.degauss_ry = (overlap_start + overlap_end) / 2.0
        mean_abs = (abs(avg_tc_a) + abs(avg_tc_b)) / 2.0
        if mean_abs > 1e-6:
            result.relative_deviation_pct = abs(avg_tc_a - avg_tc_b) / mean_abs * 100.0

        result.overlap_status = "pass"
        n_seg = len(segments)
        seg_info = f"({n_seg} qualifying segment{'s' if n_seg > 1 else ''}" if n_seg > 0 else ""
        seg_info += f", longest={best[2]} pts)" if n_seg > 0 else ""
        result.message = (
            f"Tc_Point = {result.tc_point_k:.2f} K "
            f"at degauss ≈ {result.degauss_ry:.4f} Ry "
            f"(overlap: {overlap_start:.4f}–{overlap_end:.4f} Ry, "
            f"Δ = {result.relative_deviation_pct:.2f}% {seg_info})"
        )
    else:
        result.overlap_status = "fail"
        result.message = "No valid data points in overlap region"

    return result


def _linear_interpolate(
    x_target: list[float],
    x_src: list[float],
    y_src: list[float],
) -> list[float]:
    """Linear interpolation of (x_src, y_src) onto x_target grid."""
    result = []
    n = len(x_src)
    if n == 0:
        return [float("nan")] * len(x_target)

    for xt in x_target:
        if xt <= x_src[0]:
            result.append(y_src[0])
        elif xt >= x_src[-1]:
            result.append(y_src[-1])
        else:
            # Find bracket
            for i in range(n - 1):
                if x_src[i] <= xt <= x_src[i + 1]:
                    if x_src[i + 1] - x_src[i] < 1e-15:
                        result.append(y_src[i])
                    else:
                        t = (xt - x_src[i]) / (x_src[i + 1] - x_src[i])
                        y = y_src[i] + t * (y_src[i + 1] - y_src[i])
                        result.append(y)
                    break
            else:
                result.append(float("nan"))
    return result


def _non_finite_lambdax_rows(data: LambdaOutput) -> list[int]:
    """Return row indices with NaN/Inf lambda, omega_log, or Tc."""
    rows = set(data.nan_rows)
    for i in range(data.n_rows):
        values = (
            data.lambda_values[i],
            data.omega_log_values[i],
            data.tc_values[i],
        )
        if any(not math.isfinite(value) for value in values):
            rows.add(i)
    return sorted(rows)


def _lambdax_max_triplet(data: LambdaOutput) -> tuple[float | None, float | None, float | None]:
    """Return lambda_max plus corresponding omega_log and Tc."""
    valid: list[tuple[float, float, float]] = []
    for i in range(data.n_rows):
        lam = data.lambda_values[i]
        omega = data.omega_log_values[i]
        tc = data.tc_values[i]
        if math.isfinite(lam) and math.isfinite(omega) and math.isfinite(tc):
            valid.append((lam, omega, tc))
    if not valid:
        return None, None, None
    return max(valid, key=lambda row: row[0])


def _mustar_sensitivity(
    lambda_value: float | None,
    omega_log_k: float | None,
    mustar_values: tuple[float, ...],
) -> dict[str, float | None]:
    """Compute Allen-Dynes Tc for a small μ* grid."""
    result: dict[str, float | None] = {}
    for mustar in mustar_values:
        key = f"{mustar:.2f}"
        tc = _allen_dynes_tc(lambda_value, omega_log_k, mustar)
        result[key] = tc if tc is not None and math.isfinite(tc) else None
    return result


def _allen_dynes_tc(
    lambda_value: float | None,
    omega_log_k: float | None,
    mustar: float,
) -> float | None:
    """McMillan-Allen-Dynes Tc estimate in K."""
    if lambda_value is None or omega_log_k is None:
        return None
    if lambda_value <= 0 or omega_log_k <= 0:
        return None
    denominator = lambda_value - mustar * (1.0 + 0.62 * lambda_value)
    if denominator <= 0:
        return None
    exponent = -1.04 * (1.0 + lambda_value) / denominator
    return omega_log_k / 1.2 * math.exp(exponent)


# ---------------------------------------------------------------------------
# Simple query helpers
# ---------------------------------------------------------------------------


def get_lambda_max(data: LambdaOutput) -> float | None:
    """Return the maximum lambda value (excluding NaN)."""
    valid = [v for v in data.lambda_values if not math.isnan(v)]
    return max(valid) if valid else None


def get_tc_at_lambda_max(data: LambdaOutput) -> float | None:
    """Return Tc at the degauss point with maximum lambda."""
    valid = [(data.lambda_values[i], data.tc_values[i])
             for i in range(data.n_rows)
             if not math.isnan(data.lambda_values[i]) and not math.isnan(data.tc_values[i])]
    if not valid:
        return None
    return max(valid, key=lambda x: x[0])[1]
