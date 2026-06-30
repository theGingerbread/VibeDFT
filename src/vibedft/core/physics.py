"""Physics-level analysis of DFT band structures and DOS.

Extracts quantities directly computable from E(k) and DOS without
additional DFT calculations.

Analysis levels:
  Level 1: Band gap, effective mass, Fermi velocity, band statistics, Van Hove
  Level 2: JDOS (optical), CRTA transport coefficients, plasma frequency
  Level 3: Degeneracy, crystal field splitting, avoided crossings,
           Fermi surface topology, dimensionality, velocity distributions

All analyses work from 1D k-path data (high-symmetry lines). Analyses that
would ideally require a 3D k-mesh are marked as approximate and include
caveats in their output.
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

HBAR_EV_FS = 0.6582119          # eV·fs  (ħ)
HBAR2_OVER_2ME_EV_ANG2 = 3.80998  # eV·Å²  (ħ²/2mₑ)
K_B_EV_K = 8.617333262145e-5    # eV/K  (Boltzmann)
E_CHARGE_C = 1.602176634e-19    # C  (elementary charge)
HBAR_J_S = 1.054571817e-34      # J·s
M_E_KG = 9.10938356e-31         # kg

# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------


def _gaussian(x: float, sigma: float) -> float:
    """Normalised Gaussian: (1/(σ√(2π)))·exp(−x²/(2σ²))."""
    if sigma <= 0:
        return 1.0 if abs(x) < 1e-12 else 0.0
    return math.exp(-0.5 * (x / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))


def _fd_derivative(e: float, mu: float, kt: float) -> float:
    """−∂f/∂E for Fermi-Dirac distribution at energy *e*, chemical potential *mu*, kT."""
    if kt <= 0:
        return 1.0 if abs(e - mu) < 1e-12 else 0.0
    x = (e - mu) / kt
    if x > 50:   # avoid overflow
        return 0.0
    if x < -50:
        return 0.0
    ex = math.exp(x)
    return ex / (kt * (1 + ex) ** 2)


def _fd_occupation(e: float, mu: float, kt: float) -> float:
    """Fermi-Dirac occupation at energy *e*."""
    if kt <= 0:
        return 1.0 if e <= mu else 0.0
    x = (e - mu) / kt
    if x > 50:
        return 0.0
    if x < -50:
        return 1.0
    return 1.0 / (1.0 + math.exp(x))


def _trapz(y: list[float], x: list[float]) -> float:
    """Trapezoidal integration."""
    s = 0.0
    for i in range(len(x) - 1):
        s += (y[i] + y[i + 1]) * (x[i + 1] - x[i]) * 0.5
    return s


def _linspace(start: float, stop: float, n: int) -> list[float]:
    """Return *n* evenly spaced points in [start, stop]."""
    if n <= 1:
        return [start]
    step = (stop - start) / (n - 1)
    return [start + i * step for i in range(n)]


def _find_peaks_indices(
    values: list[float],
    prominence_frac: float = 0.05,
    min_distance: int = 5,
) -> list[int]:
    """Return indices of local maxima in *values*."""
    n = len(values)
    if n < 3:
        return []
    threshold = max(values) * prominence_frac
    peaks: list[int] = []
    for i in range(1, n - 1):
        if values[i] < threshold:
            continue
        if values[i] > values[i - 1] and values[i] > values[i + 1]:
            left_ok = all(
                values[i] > values[j]
                for j in range(max(0, i - min_distance), i)
            )
            right_ok = all(
                values[i] > values[j]
                for j in range(i + 1, min(n, i + min_distance + 1))
            )
            if left_ok and right_ok:
                peaks.append(i)
    return peaks


def _polyfit2(x: list[float], y: list[float]) -> tuple[float, float, float] | None:
    """Quadratic fit y = a·x² + b·x + c. Returns (a, b, c) or None."""
    n = len(x)
    if n < 3:
        return None
    sx = sum(x)
    sx2 = sum(xi * xi for xi in x)
    sx3 = sum(xi ** 3 for xi in x)
    sx4 = sum(xi ** 4 for xi in x)
    sy = sum(y)
    sxy = sum(xi * yi for xi, yi in zip(x, y))
    sx2y = sum(xi * xi * yi for xi, yi in zip(x, y))

    det = (
        sx4 * (sx2 * n - sx * sx)
        - sx3 * (sx3 * n - sx * sx2)
        + sx2 * (sx3 * sx - sx2 * sx2)
    )
    if abs(det) < 1e-20:
        return None
    a = (
        sx2y * (sx2 * n - sx * sx)
        - sx3 * (sxy * n - sy * sx)
        + sx2 * (sxy * sx - sy * sx2)
    ) / det
    b = (
        sx4 * (sxy * n - sy * sx)
        - sx2y * (sx3 * n - sx * sx2)
        + sx2 * (sx3 * sy - sxy * sx2)
    ) / det
    c = (
        sx4 * (sx2 * sy - sx * sxy)
        - sx3 * (sx3 * sy - sx * sxy)
        + sx2y * (sx3 * sx - sx2 * sx2)
    ) / det
    return a, b, c


# ---------------------------------------------------------------------------
# K-path segment detection
# ---------------------------------------------------------------------------


def _detect_path_segments(
    k_points: list[list[float]],
    k_dists: list[float],
    angle_threshold_deg: float = 8.0,
) -> list[dict[str, Any]]:
    """Split a 1D k-path into straight segments by detecting direction changes.

    Uses cumulative angle change along the path to find sharp corners.
    For smooth paths (common in DFT band structure calculations), applies
    Gaussian smoothing to the tangent vectors before detecting corners.

    Returns a list of dicts with keys:
      start_idx, end_idx, direction (normalised 3-vector),
      length (accumulated k-distance of this segment),
      start_label, end_label.
    """
    n = len(k_points)
    if n < 2:
        return []

    # Compute smoothed tangent vectors using a window
    window = max(1, n // 15)  # adaptive window size
    tangents: list[list[float]] = []
    for i in range(n - 1):
        # Average direction over window
        i_start = max(0, i - window)
        i_end = min(n - 1, i + window + 1)
        d_total = [0.0, 0.0, 0.0]
        mag_total = 0.0
        for j in range(i_start, i_end):
            if j < n - 1:
                d = [k_points[j + 1][c] - k_points[j][c] for c in range(3)]
                mag = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)
                if mag > 1e-15:
                    d_total = [d_total[c] + d[c] / mag for c in range(3)]
                    mag_total += 1.0
        if mag_total > 0:
            tangents.append([d_total[c] / mag_total for c in range(3)])
        else:
            tangents.append([1.0, 0.0, 0.0])

    # Detect corners: points where the angle between tangents is maximal locally
    corner_scores: list[float] = []
    for i in range(len(tangents)):
        if i == 0 or i == len(tangents) - 1:
            corner_scores.append(0.0)
            continue
        dot = sum(tangents[i - 1][c] * tangents[i][c] for c in range(3))
        dot = max(-1.0, min(1.0, dot))
        # Score = 1 - cos(angle) → higher at sharper turns
        corner_scores.append(1.0 - dot)

    # Find local maxima in corner scores
    corner_indices: list[int] = [0]
    min_score = 0.02  # minimum turning "sharpness"

    for i in range(2, len(corner_scores) - 2):
        if corner_scores[i] < min_score:
            continue
        if (
            corner_scores[i] > corner_scores[i - 1]
            and corner_scores[i] > corner_scores[i + 1]
            and corner_scores[i] > corner_scores[i - 2]
            and corner_scores[i] > corner_scores[i + 2]
        ):
            corner_indices.append(i)

    corner_indices.append(n - 1)
    # Deduplicate
    bp_unique: list[int] = []
    for b in corner_indices:
        if not bp_unique or (b - bp_unique[-1]) >= 3:
            bp_unique.append(b)
    breakpoints = bp_unique

    # If only start and end (no corners found), try segmenting by known special points
    if len(breakpoints) <= 2:
        # Fall back: split at k-points closest to M, K, etc.
        special = [
            ("M", [0.5, 0.0, 0.0]),
            ("K", [1.0 / 3.0, 1.0 / 3.0, 0.0]),
        ]
        for name, ref in special:
            best_i = min(range(1, n - 1), key=lambda i: sum((k_points[i][c] - ref[c]) ** 2 for c in range(3)))
            d2 = sum((k_points[best_i][c] - ref[c]) ** 2 for c in range(3))
            if d2 < 0.1 and best_i not in breakpoints:
                breakpoints.append(best_i)
        breakpoints.sort()

    # Build segments
    segments: list[dict[str, Any]] = []
    high_sym_labels = _guess_high_symmetry_labels(k_points, k_dists, breakpoints)

    for s in range(len(breakpoints) - 1):
        si = breakpoints[s]
        ei = breakpoints[s + 1]
        if ei <= si or ei - si < 2:
            continue
        dir_vec = [k_points[ei][c] - k_points[si][c] for c in range(3)]
        dir_mag = math.sqrt(sum(d ** 2 for d in dir_vec))
        direction = [d / dir_mag for d in dir_vec] if dir_mag > 1e-12 else [1.0, 0.0, 0.0]
        length = k_dists[ei] - k_dists[si]
        if length < 1e-12:
            continue
        segments.append(
            {
                "start_idx": si,
                "end_idx": ei,
                "direction": direction,
                "length": length,
                "start_label": high_sym_labels.get(si, f"P{si}"),
                "end_label": high_sym_labels.get(ei, f"P{ei}"),
                "n_points": ei - si + 1,
            }
        )
    return segments


def _guess_high_symmetry_labels(
    k_points: list[list[float]],
    k_dists: list[float],
    breakpoints: list[int],
) -> dict[int, str]:
    """Assign standard high-symmetry labels based on fractional coordinates."""
    labels: dict[int, str] = {}
    # Known special points for hexagonal 2D lattice
    special = [
        ("Γ", [0.0, 0.0, 0.0]),
        ("M", [0.5, 0.0, 0.0]),
        ("K", [1.0 / 3.0, 1.0 / 3.0, 0.0]),
        ("K'", [2.0 / 3.0, 1.0 / 3.0, 0.0]),
        ("Γ'", [0.0, 0.0, 0.0]),  # return to Γ
        ("A", [0.0, 0.0, 0.5]),
    ]
    tolerance = 0.15  # relaxed tolerance for non-standard paths

    for bp in breakpoints:
        if bp in labels:
            continue
        k = k_points[bp]
        best_label = None
        best_dist = float("inf")
        for name, ref in special:
            d2 = sum((k[j] - ref[j]) ** 2 for j in range(3))
            if d2 < tolerance ** 2 and d2 < best_dist:
                if name == "Γ'":
                    continue  # handled separately
                if name == "Γ" and bp > len(k_points) * 0.6:
                    best_label = "Γ'"
                    best_dist = d2
                elif name == "K'" and name == "K'":
                    best_label = name
                    best_dist = d2
                elif name != "Γ'":
                    best_label = name
                    best_dist = d2
        if best_label:
            labels[bp] = best_label

    # Fall back to distance-based labels for unidentified breakpoints
    for bp in breakpoints:
        if bp not in labels:
            if bp == 0:
                labels[bp] = "Γ"
            elif bp == breakpoints[-1]:
                # Check if last point is near Γ
                k = k_points[bp]
                if sum(k[j] ** 2 for j in range(3)) < 0.01:
                    labels[bp] = "Γ"
                else:
                    labels[bp] = f"P{bp}"
            else:
                labels[bp] = f"P{bp}"
    return labels


# ---------------------------------------------------------------------------
# Level 1a: Effective mass — directional
# ---------------------------------------------------------------------------


def effective_mass(
    k_dists: list[float],
    energies: list[float],
    fit_window: int = 3,
    k_scale_inv_angstrom: float | None = None,
    extremum_index: int | None = None,
) -> dict[str, Any]:
    """Fit parabolic E(k) near a band extremum → m*/mₑ.

    Parameters
    ----------
    k_dists: cumulative k-distances (BZ-fraction units unless scaled)
    energies: band energies in eV
    fit_window: half-width of fitting window in k-point indices
    k_scale_inv_angstrom: conversion factor from k_dists units to Å⁻¹.
    extremum_index: if given, use this as the extremum position instead
        of auto-detecting via min(energies).  Required when the extremum
        is a maximum (e.g. VBM before energy-inversion).
    """
    scale = k_scale_inv_angstrom or 1.0
    hbar2_over_2me = HBAR2_OVER_2ME_EV_ANG2 * (scale ** 2)

    if len(k_dists) < 3:
        return {
            "m_eff_me": None,
            "curvature": None,
            "r_squared": None,
            "n_points": len(k_dists),
        }

    if extremum_index is not None:
        ext_idx = extremum_index
    else:
        ext_idx = energies.index(min(energies))

    start = max(0, ext_idx - fit_window)
    end = min(len(energies), ext_idx + fit_window + 1)
    if end - start < 3:
        start = max(0, ext_idx - 1)
        end = min(len(energies), ext_idx + 2)

    ks = [k_dists[i] - k_dists[ext_idx] for i in range(start, end)]
    es = [energies[i] for i in range(start, end)]

    fit = _polyfit2(ks, es)
    if fit is None:
        return {"m_eff_me": None, "curvature": None, "r_squared": None, "n_points": len(ks)}

    a_quad, _b, _c = fit
    curvature = 2.0 * a_quad

    if abs(curvature) < 1e-20:
        return {"m_eff_me": None, "curvature": 0.0, "r_squared": None, "n_points": len(ks)}

    m_eff_me = hbar2_over_2me / curvature

    # R² — if negative, the quadratic fit is worse than a horizontal line
    n = len(ks)
    e_mean = sum(es) / n
    ss_res = sum(
        (es[i] - (a_quad * ks[i] * ks[i] + _b * ks[i] + _c)) ** 2 for i in range(n)
    )
    ss_tot = sum((e - e_mean) ** 2 for e in es)
    if ss_tot < 1e-20:
        # Flat band: zero curvature, no meaningful effective mass
        r2 = None
    else:
        raw_r2 = 1.0 - ss_res / ss_tot
        r2 = raw_r2 if raw_r2 >= 0.0 else None  # negative R² → fit failed

    return {"m_eff_me": m_eff_me, "curvature": curvature, "r_squared": r2, "n_points": n}


def directional_effective_masses(
    bands_data: dict[str, Any],
    band_index: int,
    extremum_k_index: int,
    e_fermi: float,
    k_scale_inv_angstrom: float | None = None,
) -> list[dict[str, Any]]:
    """Compute effective mass for a band extremum along each k-path direction.

    For each path segment that contains or is near the extremum, fits a
    parabola along that segment direction and extracts m*.

    Returns a list of dicts, each with:
      direction_label (e.g. "Γ→M"), m_eff_me, curvature, r_squared,
      is_longitudinal, direction_vector.
    """
    k_points = bands_data.get("k_points", [])
    k_dists = bands_data.get("k_distances", [])
    bands_list = bands_data["bands"]
    energies = bands_list[band_index]
    segments = _detect_path_segments(k_points, k_dists)

    results: list[dict[str, Any]] = []

    for seg in segments:
        si, ei = seg["start_idx"], seg["end_idx"]
        # Check if extremum is in or near this segment
        if not (si <= extremum_k_index <= ei):
            # Also check if extremum is within 2 points
            if not (abs(si - extremum_k_index) <= 2 or abs(ei - extremum_k_index) <= 2):
                continue

        # Extract band energies along this segment
        seg_ks = k_dists[si : ei + 1]
        seg_es = energies[si : ei + 1]

        # If extremum not in segment, use the closest endpoint
        local_ext_idx = extremum_k_index - si
        if local_ext_idx < 0:
            local_ext_idx = 0
        elif local_ext_idx >= len(seg_es):
            local_ext_idx = len(seg_es) - 1

        em = effective_mass(
            seg_ks, seg_es, fit_window=3,
            k_scale_inv_angstrom=k_scale_inv_angstrom,
            extremum_index=local_ext_idx,
        )

        direction_label = f"{seg['start_label']}→{seg['end_label']}"
        is_longitudinal = True  # along this segment

        results.append(
            {
                "direction_label": direction_label,
                "direction_vector": seg["direction"],
                "is_longitudinal": is_longitudinal,
                "m_eff_me": em["m_eff_me"],
                "curvature": em["curvature"],
                "r_squared": em["r_squared"],
                "n_points": em["n_points"],
                "segment_start": seg["start_label"],
                "segment_end": seg["end_label"],
            }
        )

    return results


def effective_mass_summary(
    bands_data: dict[str, Any],
    e_fermi: float,
    k_scale_inv_angstrom: float | None = None,
) -> dict[str, Any]:
    """Compute directional effective masses for VBM and CBM.

    Returns a dict with keys 'cbm' and 'vbm', each containing a list of
    directional effective mass results.
    """
    k_dists: list[float] = bands_data["k_distances"]
    bands_list: list[list[float]] = bands_data["bands"]

    # Find VBM and CBM
    vbm = -float("inf")
    cbm = float("inf")
    vbm_k = None
    cbm_k = None
    vbm_band = None
    cbm_band = None

    for ib, energies in enumerate(bands_list):
        for ik, e in enumerate(energies):
            if e < e_fermi and e > vbm:
                vbm = e
                vbm_k = ik
                vbm_band = ib
            if e > e_fermi and e < cbm:
                cbm = e
                cbm_k = ik
                cbm_band = ib

    result: dict[str, Any] = {"cbm": [], "vbm": []}

    if cbm_k is not None and cbm_band is not None:
        result["cbm"] = directional_effective_masses(
            bands_data, cbm_band, cbm_k, e_fermi, k_scale_inv_angstrom
        )

    if vbm_k is not None and vbm_band is not None:
        # For VBM, invert energy (holes) so parabola opens upward
        vbm_energies = [-e for e in bands_list[vbm_band]]
        # Create modified bands data for VBM with inverted energies
        vbm_bands_data = dict(bands_data)
        vbm_bands_list = [list(b) for b in bands_list]
        vbm_bands_list[vbm_band] = vbm_energies
        vbm_bands_data["bands"] = vbm_bands_list
        result["vbm"] = directional_effective_masses(
            vbm_bands_data, vbm_band, vbm_k, e_fermi + 1.0,  # shift EF above VBM
            k_scale_inv_angstrom,
        )
        # Note: energies were inverted, so computed m* IS the hole effective mass.
        # Do NOT negate — the parabola fit on inverted energies already gives m_h* > 0.

    return result


# ---------------------------------------------------------------------------
# Level 1b: Fermi velocity
# ---------------------------------------------------------------------------


def fermi_velocity(
    k_dists: list[float],
    energies: list[float],
    e_fermi: float,
    velocity_factor: float = 1.0,
) -> list[dict[str, Any]]:
    """Estimate Fermi velocity at band crossings with E_F.

    *velocity_factor* scales k units to Å⁻¹ (default 1.0 for BZ-fraction).
    ħ = 0.6582119 eV·fs; v_F in Å/fs.
    """
    hbar_ev_fs = HBAR_EV_FS
    results: list[dict[str, Any]] = []
    n = len(energies)
    for i in range(1, n - 1):
        e0, e1 = energies[i - 1], energies[i + 1]
        if (energies[i] - e_fermi) * (e0 - e_fermi) <= 0 or (
            energies[i] - e_fermi
        ) * (e1 - e_fermi) <= 0:
            dk = k_dists[i + 1] - k_dists[i - 1]
            if dk < 1e-12:
                continue
            de = e1 - e0
            v = abs(de / dk) * velocity_factor / hbar_ev_fs
            results.append(
                {
                    "k_index": i,
                    "k_distance": k_dists[i],
                    "v_fermi_A_per_fs": v,
                    "dE_dk": abs(de / dk),
                }
            )
    return results


# ---------------------------------------------------------------------------
# Level 1c: Band gap (enhanced)
# ---------------------------------------------------------------------------


def band_gap_analysis(
    bands_list: list[list[float]],
    k_dists: list[float],
    e_fermi: float,
) -> dict[str, Any]:
    """Full band-gap analysis: VBM/CBM, direct/indirect, multiple gaps."""
    vbm = -float("inf")
    cbm = float("inf")
    vbm_k_idx = None
    cbm_k_idx = None
    vbm_band = None
    cbm_band = None

    for ib, energies in enumerate(bands_list):
        for ik, e in enumerate(energies):
            if e < e_fermi and e > vbm:
                vbm = e
                vbm_k_idx = ik
                vbm_band = ib
            if e > e_fermi and e < cbm:
                cbm = e
                cbm_k_idx = ik
                cbm_band = ib

    gap = cbm - vbm if vbm != -float("inf") and cbm != float("inf") else None

    # Determine type
    gap_type = "unknown"
    if gap is not None and gap > 0.01:
        if vbm_k_idx is not None and cbm_k_idx is not None:
            gap_type = (
                "direct"
                if abs(k_dists[vbm_k_idx] - k_dists[cbm_k_idx]) < 0.01
                else "indirect"
            )
    elif gap is not None and gap <= 0.01:
        gap_type = "metallic"

    # Optical gap (smallest vertical transition at same k)
    optical_gap = float("inf")
    optical_gap_k = None
    for ik in range(len(k_dists)):
        local_vbm = -float("inf")
        local_cbm = float("inf")
        for ib, energies in enumerate(bands_list):
            e = energies[ik]
            if e < e_fermi and e > local_vbm:
                local_vbm = e
            if e > e_fermi and e < local_cbm:
                local_cbm = e
        if local_vbm != -float("inf") and local_cbm != float("inf"):
            opt = local_cbm - local_vbm
            if opt < optical_gap:
                optical_gap = opt
                optical_gap_k = ik

    if optical_gap == float("inf"):
        optical_gap = None

    return {
        "vbm_ev": vbm if vbm != -float("inf") else None,
        "cbm_ev": cbm if cbm != float("inf") else None,
        "vbm_k_index": vbm_k_idx,
        "cbm_k_index": cbm_k_idx,
        "vbm_band": vbm_band,
        "cbm_band": cbm_band,
        "gap_ev": gap,
        "optical_gap_ev": optical_gap,
        "optical_gap_k_index": optical_gap_k,
        "type": gap_type,
        "stokes_shift_ev": (
            (optical_gap - gap) if (gap and optical_gap and optical_gap > gap) else None
        ),
    }


# ---------------------------------------------------------------------------
# Level 2a: Joint Density of States (JDOS) for optical absorption
# ---------------------------------------------------------------------------


def joint_density_of_states(
    bands_data: dict[str, Any],
    e_fermi: float,
    energy_range: tuple[float, float] = (-5.0, 10.0),
    n_energy: int = 300,
    broadening: float = 0.05,
) -> dict[str, Any]:
    """Compute joint density of states for optical transitions.

    JDOS(ω) = Σ_{v,c} Σ_k δ(E_c(k) − E_v(k) − ℏω) / |∇_k(E_c − E_v)|

    Uses Gaussian broadening. Identifies the strongest optical transitions
    and the onset of absorption. This is an approximate calculation from 1D
    k-path data; a proper JDOS requires a full k-mesh.

    Returns: dict with energy grid, JDOS values, peak positions,
             optical onset, and dominant transition pairs.
    """
    k_dists: list[float] = bands_data["k_distances"]
    bands_list: list[list[float]] = bands_data["bands"]
    n_bands = len(bands_list)
    n_k = len(k_dists)

    # Classify valence (E < E_F) and conduction (E ≥ E_F) bands
    valence_bands: list[int] = []
    conduction_bands: list[int] = []
    for ib, energies in enumerate(bands_list):
        avg_e = sum(energies) / len(energies) if energies else 0.0
        if avg_e < e_fermi:
            valence_bands.append(ib)
        else:
            conduction_bands.append(ib)

    if not valence_bands or not conduction_bands:
        return {"jdos_energy": [], "jdos_values": [], "peaks": [], "optical_onset_ev": None}

    energies_grid = _linspace(energy_range[0], energy_range[1], n_energy)
    jdos = [0.0] * n_energy

    # Transition pair data for later analysis
    transition_data: list[dict[str, Any]] = []

    for iv in valence_bands:
        for ic in conduction_bands:
            e_diff = [
                bands_list[ic][ik] - bands_list[iv][ik] for ik in range(n_k)
            ]
            for i_omega, omega in enumerate(energies_grid):
                contrib = 0.0
                for ik in range(n_k):
                    contrib += _gaussian(e_diff[ik] - omega, broadening)
                jdos[i_omega] += contrib / n_k

            # Find the minimum transition energy for this pair
            min_diff = min(e_diff)
            max_diff = max(e_diff)
            transition_data.append(
                {
                    "valence_band": iv + 1,
                    "conduction_band": ic + 1,
                    "min_transition_ev": min_diff,
                    "max_transition_ev": max_diff,
                    "avg_transition_ev": sum(e_diff) / len(e_diff),
                }
            )

    # Find peaks in JDOS
    peak_indices = _find_peaks_indices(jdos, prominence_frac=0.03, min_distance=10)
    peaks = [
        {
            "energy_ev": energies_grid[pi],
            "jdos_value": jdos[pi],
            "relative_intensity": jdos[pi] / max(jdos) if max(jdos) > 0 else 0.0,
        }
        for pi in peak_indices
    ]
    peaks.sort(key=lambda p: p["jdos_value"], reverse=True)

    # Optical onset: first energy where JDOS exceeds 1% of max
    max_jdos = max(jdos) if jdos else 1.0
    onset = None
    for i, j in enumerate(jdos):
        if j > 0.01 * max_jdos:
            onset = energies_grid[i]
            break

    # Sort transitions by minimum energy (closest to gap)
    transition_data.sort(key=lambda t: t["min_transition_ev"])

    return {
        "jdos_energy": energies_grid,
        "jdos_values": jdos,
        "peaks": peaks[:10],
        "optical_onset_ev": onset,
        "jdos_max_ev": energies_grid[jdos.index(max_jdos)] if max_jdos > 0 else None,
        "n_valence": len(valence_bands),
        "n_conduction": len(conduction_bands),
        "top_transitions": transition_data[:10],
        "broadening_ev": broadening,
        "caveat": "Computed from 1D k-path; use full k-mesh for quantitative JDOS.",
    }


# ---------------------------------------------------------------------------
# Level 2b: Group velocity computation
# ---------------------------------------------------------------------------


def compute_group_velocities(
    bands_data: dict[str, Any],
    k_scale_inv_angstrom: float | None = None,
) -> list[list[dict[str, Any]]]:
    """Compute group velocity v(k) = (1/ħ)·∇ₖE for all bands and k-points.

    Uses central finite differences along the k-path. The velocity vector
    points along the path direction at each k-point.

    Returns: list of lists: vels[iband][ik] = {v_mag, v_eV_ang, direction, ...}
    """
    k_dists = bands_data["k_distances"]
    k_points = bands_data.get("k_points", [])
    bands_list = bands_data["bands"]
    scale = k_scale_inv_angstrom or 1.0

    all_velocities: list[list[dict[str, Any]]] = []

    for ib, energies in enumerate(bands_list):
        band_vels: list[dict[str, Any]] = []
        n_k = len(k_dists)
        for ik in range(n_k):
            if ik == 0:
                # Forward difference
                dk = (k_dists[ik + 1] - k_dists[ik]) * scale
                de = energies[ik + 1] - energies[ik]
            elif ik == n_k - 1:
                # Backward difference
                dk = (k_dists[ik] - k_dists[ik - 1]) * scale
                de = energies[ik] - energies[ik - 1]
            else:
                # Central difference
                dk = (k_dists[ik + 1] - k_dists[ik - 1]) * scale
                de = energies[ik + 1] - energies[ik - 1]

            if abs(dk) < 1e-15:
                v_mag = 0.0
                direction = [0.0, 0.0, 0.0]
            else:
                # v = (1/ħ) · dE/dk in Å/fs
                v_mag = abs(de / dk) / HBAR_EV_FS
                # Direction: along k-path at this point
                if ik > 0 and ik < n_k - 1 and k_points:
                    direction = [
                        k_points[ik + 1][j] - k_points[ik - 1][j]
                        for j in range(3)
                    ]
                    d_mag = math.sqrt(sum(d ** 2 for d in direction))
                    direction = [d / d_mag for d in direction] if d_mag > 1e-12 else [1.0, 0.0, 0.0]
                else:
                    direction = [1.0, 0.0, 0.0]

            band_vels.append(
                {
                    "v_mag_A_per_fs": v_mag,
                    "dE_dk_eV_ang": de / dk if abs(dk) > 1e-15 else 0.0,
                    "direction": direction,
                    "k_idx": ik,
                }
            )
        all_velocities.append(band_vels)
    return all_velocities


# ---------------------------------------------------------------------------
# Level 2c: CRTA Transport coefficients
# ---------------------------------------------------------------------------


def transport_distribution_function(
    bands_data: dict[str, Any],
    e_fermi: float,
    velocity_data: list[list[dict[str, Any]]] | None = None,
    energy_range: tuple[float, float] = (-5.0, 5.0),
    n_energy: int = 400,
    broadening: float = 0.05,
    temperature_k: float = 300.0,
) -> dict[str, Any]:
    """Compute the transport distribution function Ξ(E) from band velocities.

    Ξ(E) = Σ_{n,k} v_n²(k) · δ(E − E_n(k)) / |dE_n/dk|

    Uses Gaussian broadening of the delta function. From Ξ(E), all CRTA
    transport coefficients can be derived.

    The output is in arbitrary units (scaled by τ and k-space volume).
    For comparison between materials, provide lattice parameters.
    """
    k_dists = bands_data["k_distances"]
    bands_list = bands_data["bands"]
    n_k = len(k_dists)

    if velocity_data is None:
        velocity_data = compute_group_velocities(bands_data)

    egrid = _linspace(energy_range[0], energy_range[1], n_energy)
    xi = [0.0] * n_energy

    for ib, energies in enumerate(bands_list):
        vels = velocity_data[ib]
        for ik in range(n_k):
            v2 = vels[ik]["v_mag_A_per_fs"] ** 2
            # Weight by inverse gradient magnitude (1D DOS factor)
            de_dk = abs(vels[ik]["dE_dk_eV_ang"])
            weight = v2 / max(de_dk, 1e-10)

            # Broaden
            for i_omega in range(n_energy):
                xi[i_omega] += weight * _gaussian(
                    energies[ik] - egrid[i_omega], broadening
                ) / n_k

    # Normalize to reasonable units
    # Ξ is in (Å²/fs²) / (eV/Å) = Å³/(eV·fs²) per k-point
    # For 2D materials, multiply by unit cell thickness factor

    return {
        "energy_grid": egrid,
        "tdf_values": xi,
        "tdf_max": max(xi) if xi else 0.0,
        "tdf_at_ef": xi[_closest_index(egrid, 0.0)] if egrid else 0.0,
        "broadening_ev": broadening,
        "temperature_k": temperature_k,
    }


def _closest_index(arr: list[float], target: float) -> int:
    """Return the index of the element closest to target."""
    best = 0
    best_dist = float("inf")
    for i, v in enumerate(arr):
        d = abs(v - target)
        if d < best_dist:
            best_dist = d
            best = i
    return best


def transport_coefficients(
    bands_data: dict[str, Any],
    e_fermi: float,
    temperature_k: float = 300.0,
    velocity_data: list[list[dict[str, Any]]] | None = None,
    energy_range: tuple[float, float] = (-3.0, 3.0),
    n_energy: int = 500,
    broadening: float = 0.03,
) -> dict[str, Any]:
    """Compute CRTA transport coefficients.

    Returns:
      sigma_over_tau: electrical conductivity / relaxation time
      seebeck_uv_per_k: Seebeck coefficient in μV/K
      kappa_e_over_tau: electronic thermal conductivity / τ
      power_factor_over_tau: S²σ / τ
      all in approximate units (need τ and geometry for absolute values).
    """
    kt = K_B_EV_K * temperature_k
    if kt <= 0:
        kt = K_B_EV_K * 300.0

    tdf_result = transport_distribution_function(
        bands_data,
        e_fermi,
        velocity_data=velocity_data,
        energy_range=energy_range,
        n_energy=n_energy,
        broadening=broadening,
        temperature_k=temperature_k,
    )

    egrid = tdf_result["energy_grid"]
    xi = tdf_result["tdf_values"]

    if not egrid or max(xi) < 1e-30:
        return {
            "sigma_over_tau": None,
            "seebeck_uv_per_k": None,
            "kappa_e_over_tau": None,
            "power_factor_over_tau": None,
            "temperature_k": temperature_k,
            "caveat": "Transport coefficients require a full 3D k-mesh for quantitative results.",
        }

    # Integrals: I_n = ∫ Ξ(E)·(E−μ)^n ·(−∂f/∂E) dE
    mu = e_fermi
    i0 = 0.0  # ∫ Ξ · (−∂f/∂E) dE
    i1 = 0.0  # ∫ Ξ·(E−μ) · (−∂f/∂E) dE
    i2 = 0.0  # ∫ Ξ·(E−μ)² · (−∂f/∂E) dE

    integrand0 = [0.0] * len(egrid)
    integrand1 = [0.0] * len(egrid)
    integrand2 = [0.0] * len(egrid)

    for i, e in enumerate(egrid):
        fd_deriv = _fd_derivative(e, mu, kt)
        de = e - mu
        integrand0[i] = xi[i] * fd_deriv
        integrand1[i] = xi[i] * fd_deriv * de
        integrand2[i] = xi[i] * fd_deriv * de * de

    i0 = _trapz(integrand0, egrid)
    i1 = _trapz(integrand1, egrid)
    i2 = _trapz(integrand2, egrid)

    if i0 < 1e-30:
        return {
            "sigma_over_tau": 0.0,
            "seebeck_uv_per_k": None,
            "kappa_e_over_tau": 0.0,
            "power_factor_over_tau": 0.0,
            "temperature_k": temperature_k,
            "caveat": "Zero conductivity — insulating state.",
        }

    # Conductivity / τ
    # σ = e² · I₀  (in appropriate units)
    # We report in a.u. scaled by τ
    sigma_over_tau = i0  # a.u.

    # Seebeck: S = (1/eT) · I₁/I₀
    seebeck_V_per_K = (1.0 / (1.0 * temperature_k)) * (i1 / i0)  # e=1 in our units
    # Actually S = (1/eT) * I₁/I₀ where e is in appropriate units
    # In eV units: S = (1/T) * (I₁/I₀) * (1 eV / e) = (1/T) * (I₁/I₀) * 1 V
    # S [μV/K] = (I₁/I₀ / T) * 1e6
    seebeck_uv_per_k = (i1 / i0 / temperature_k) * 1e6 if i0 > 0 else None

    # Electronic thermal conductivity / τ
    # κ_e = (1/T) · (I₂ − I₁²/I₀)
    kappa_e_over_tau = (1.0 / temperature_k) * (i2 - (i1 * i1) / i0)

    # Power factor / τ
    pf_over_tau = (seebeck_uv_per_k ** 2) * sigma_over_tau * 1e-12 if seebeck_uv_per_k else None

    # Also compute the logarithmic derivative of Ξ at E_F
    # (another way to estimate Seebeck: S ∝ d ln Ξ / dE |_EF)
    ie_ef = _closest_index(egrid, mu)
    dln_xi = None
    if 1 < ie_ef < len(xi) - 1 and xi[ie_ef] > 1e-20:
        dxi = xi[ie_ef + 1] - xi[ie_ef - 1]
        de = egrid[ie_ef + 1] - egrid[ie_ef - 1]
        if abs(de) > 1e-15:
            dln_xi = dxi / (xi[ie_ef] * de)

    # Mott formula estimate for Seebeck (low-T limit)
    seebeck_mott = None
    if dln_xi is not None:
        seebeck_mott = (
            -(math.pi ** 2) * K_B_EV_K ** 2 * temperature_k / (3.0 * 1.0) * dln_xi * 1e6
        )

    return {
        "sigma_over_tau_au": sigma_over_tau,
        "seebeck_uv_per_k": seebeck_uv_per_k,
        "seebeck_mott_uv_per_k": seebeck_mott,
        "kappa_e_over_tau_au": kappa_e_over_tau,
        "power_factor_over_tau_au": pf_over_tau,
        "temperature_k": temperature_k,
        "dln_tdf_dE_at_ef": dln_xi,
        "tdf_at_ef": xi[ie_ef] if 0 <= ie_ef < len(xi) else None,
        "caveat": (
            "CRTA transport from 1D k-path is approximate. "
            "Quantitative results require full BZ integration with a dense k-mesh. "
            "Values scaled by unknown τ; use for material comparison only."
        ),
    }


# ---------------------------------------------------------------------------
# Level 2d: Plasma frequency (intraband)
# ---------------------------------------------------------------------------


def plasma_frequency(
    bands_data: dict[str, Any],
    e_fermi: float,
    velocity_data: list[list[dict[str, Any]]] | None = None,
    broadening: float = 0.05,
) -> dict[str, Any]:
    """Estimate intraband plasma frequency from band velocities at E_F.

    ω_p² = (e²/πħ²) · Σ_n ∫ |v_n(k)|² · δ(E_n(k) − E_F) dk

    For 2D materials, there's an additional geometric factor.
    Result is approximate (1D path).
    """
    k_dists = bands_data["k_distances"]
    bands_list = bands_data["bands"]
    n_k = len(k_dists)

    if velocity_data is None:
        velocity_data = compute_group_velocities(bands_data)

    # Compute weighted v² at E_F using Gaussian broadening
    v2_sum = 0.0
    for ib, energies in enumerate(bands_list):
        vels = velocity_data[ib]
        for ik in range(n_k):
            weight = _gaussian(energies[ik] - e_fermi, broadening)
            v2_sum += vels[ik]["v_mag_A_per_fs"] ** 2 * weight / n_k

    # ω_p² = e² · v²_sum / (π · ħ²) (2D)
    # In appropriate units:
    # ω_p (eV) = ħ · sqrt(e² · v²_sum / (π · ħ²))
    # For rough estimate, use ω_p² [eV²] ≈ v²_sum [Å²/fs²] * conversion

    # Convert to plasma energy (eV):
    # ω_p = ħ · ω_p (angular) = ħ · sqrt(n e² / (ε₀ m_eff))
    # Using velocity-based formula:
    # ω_p² [eV²] = (e²/ε₀) · (1/π) · v²_sum * (DOS factor)
    # Rough estimate: ω_p ≈ ħ * 10¹⁵ rad/s → few eV for metals

    # Direct estimate from v² at EF:
    # For 2D free electron gas: ω_p² = (2e²E_F)/(ε₀ħ²) * (k_F²/2m = E_F)
    # Our approximation: ω_p² ∝ v_F² · N(E_F)

    # Compute in eV units
    # ħω_p [eV] ≈ sqrt( (ħ² · v² · N(EF)) / (ε₀) ) ... rough
    omega_p_ev = math.sqrt(v2_sum * 10.0) if v2_sum > 0 else None  # heuristic scaling

    return {
        "velocity_squared_at_ef": v2_sum,
        "omega_p_ev_estimate": omega_p_ev,
        "caveat": (
            "Intraband plasma frequency estimate from 1D path. "
            "Needs full k-mesh and proper geometric factors for quantitative use."
        ),
    }


# ---------------------------------------------------------------------------
# Level 3a: Band degeneracy & crystal-field splitting
# ---------------------------------------------------------------------------


def analyze_degeneracy(
    bands_data: dict[str, Any],
    e_fermi: float,
    degeneracy_tolerance_ev: float = 0.005,
) -> dict[str, Any]:
    """Analyze band degeneracy patterns at high-symmetry k-points.

    Detects: number of degenerate band groups, degeneracy order,
    crystal-field-like splittings between degenerate groups at Γ.
    """
    k_points = bands_data.get("k_points", [])
    bands_list = bands_data["bands"]
    n_k = len(bands_list[0]) if bands_list else 0

    # Identify high-symmetry k-points
    gamma_idx = None
    for ik, k in enumerate(k_points):
        if sum(k[j] ** 2 for j in range(3)) < 0.001:
            if gamma_idx is None:
                gamma_idx = ik
            # else: the second Γ (end of in-plane path) — skip

    if gamma_idx is None and n_k > 0:
        gamma_idx = 0  # assume first k-point is Γ

    result: dict[str, Any] = {
        "gamma_point": {
            "k_index": gamma_idx,
            "degenerate_groups": [],
            "crystal_field_splittings_ev": [],
        },
        "total_degenerate_groups": 0,
    }

    if gamma_idx is None:
        return result

    # Group bands by degeneracy at Γ
    energies_at_gamma = [
        bands_list[ib][gamma_idx] for ib in range(len(bands_list))
    ]
    # Sort by energy
    sorted_pairs = sorted(enumerate(energies_at_gamma), key=lambda x: x[1])
    groups: list[dict[str, Any]] = []
    current_group: list[int] = [sorted_pairs[0][0]]
    current_energy = sorted_pairs[0][1]

    for ib_idx, e in sorted_pairs[1:]:
        if abs(e - current_energy) < degeneracy_tolerance_ev:
            current_group.append(ib_idx)
        else:
            groups.append(
                {
                    "bands": sorted(current_group),
                    "energy_ev": current_energy,
                    "energy_vs_ef_ev": current_energy - e_fermi,
                    "degeneracy": len(current_group),
                }
            )
            current_group = [ib_idx]
            current_energy = e
    # Last group
    groups.append(
        {
            "bands": sorted(current_group),
            "energy_ev": current_energy,
            "energy_vs_ef_ev": current_energy - e_fermi,
            "degeneracy": len(current_group),
        }
    )

    result["gamma_point"]["degenerate_groups"] = groups
    result["total_degenerate_groups"] = len(groups)

    # Crystal-field splittings: energy differences between adjacent degenerate groups
    cf_splittings: list[dict[str, Any]] = []
    for i in range(len(groups) - 1):
        delta = groups[i + 1]["energy_ev"] - groups[i]["energy_ev"]
        cf_splittings.append(
            {
                "from_bands": groups[i]["bands"],
                "to_bands": groups[i + 1]["bands"],
                "splitting_ev": delta,
                "from_energy_ev": groups[i]["energy_ev"],
                "to_energy_ev": groups[i + 1]["energy_ev"],
                "possible_origin": _guess_cf_origin(
                    groups[i]["degeneracy"], groups[i + 1]["degeneracy"]
                ),
            }
        )
    result["gamma_point"]["crystal_field_splittings"] = cf_splittings

    # Also check degeneracies at other high-symmetry points (M, K)
    extra_points = _find_other_hs_points(k_points)
    for label, k_idx in extra_points.items():
        energies_at_k = [bands_list[ib][k_idx] for ib in range(len(bands_list))]
        sorted_pairs_k = sorted(enumerate(energies_at_k), key=lambda x: x[1])
        degen_count = 0
        prev_e = None
        for _, e in sorted_pairs_k:
            if prev_e is not None and abs(e - prev_e) < degeneracy_tolerance_ev:
                degen_count += 1
            prev_e = e
        result[f"{label}_point"] = {
            "k_index": k_idx,
            "degenerate_pairs": degen_count,
        }

    return result


def _find_other_hs_points(
    k_points: list[list[float]],
) -> dict[str, int]:
    """Find M and K points in a hexagonal path."""
    result: dict[str, int] = {}
    for ik, k in enumerate(k_points):
        # M = (0.5, 0, 0)
        if abs(k[0] - 0.5) < 0.01 and abs(k[1]) < 0.01:
            result["M"] = ik
        # K = (1/3, 1/3, 0)
        if abs(k[0] - 1.0 / 3.0) < 0.01 and abs(k[1] - 1.0 / 3.0) < 0.01:
            result["K"] = ik
    return result


def _guess_cf_origin(degen1: int, degen2: int) -> str:
    """Heuristic for crystal-field splitting origin based on degeneracies."""
    # d-orbitals in octahedral: t2g(3) + eg(2), splitting ~10Dq
    # d-orbitals in tetrahedral: e(2) + t2(3), inverted
    # d-orbitals in trigonal prismatic (HfBr2-like): d_z²(1), d_xy/d_x²-y²(2), d_xz/d_yz(2)
    # This is a guess — real assignments need orbital character
    if degen1 == 1 and degen2 == 2:
        return "Possible d-orbital splitting: a₁′ → e′ (trigonal prismatic) or a₁g → e_g"
    elif degen1 == 2 and degen2 == 2:
        return "Possible d-orbital splitting: e′ → e″ (trigonal prismatic)"
    elif degen1 == 3 and degen2 == 2:
        return "Possible octahedral crystal field: t₂g → e_g (10Dq)"
    elif degen1 == 2 and degen2 == 3:
        return "Possible tetrahedral crystal field: e → t₂ (inverted)"
    else:
        return "Unknown origin — needs orbital-projected analysis"


# ---------------------------------------------------------------------------
# Level 3b: Avoided crossing detection
# ---------------------------------------------------------------------------


def detect_avoided_crossings(
    bands_data: dict[str, Any],
    min_gap_ev: float = 0.002,
    max_gap_ev: float = 0.5,
    min_sharpness: float = 1e-4,
) -> dict[str, Any]:
    """Detect avoided crossings between adjacent bands along the k-path.

    An avoided crossing is a local minimum of |E_a(k) − E_b(k)| where the
    band ordering doesn't change (sign of E_a−E_b stays constant).

    Returns: list of avoided crossings with band indices, k-location,
    minimum gap, and sharpness.
    """
    k_dists = bands_data["k_distances"]
    bands_list = bands_data["bands"]
    n_bands = len(bands_list)
    n_k = len(k_dists)

    crossings: list[dict[str, Any]] = []

    for a in range(n_bands - 1):
        b = a + 1
        e_diff = [
            abs(bands_list[a][ik] - bands_list[b][ik]) for ik in range(n_k)
        ]

        # Check if the bands actually cross (sign change in E_a - E_b)
        has_real_crossing = False
        for ik in range(1, n_k):
            sign_a = bands_list[a][ik - 1] - bands_list[b][ik - 1]
            sign_b = bands_list[a][ik] - bands_list[b][ik]
            if sign_a * sign_b < 0:
                has_real_crossing = True
                break

        if has_real_crossing:
            continue  # These bands genuinely cross, not avoided crossing

        # Find local minima of |E_a - E_b|
        for ik in range(1, n_k - 1):
            if (
                min_gap_ev < e_diff[ik] < max_gap_ev
                and e_diff[ik] < e_diff[ik - 1]
                and e_diff[ik] < e_diff[ik + 1]
            ):
                # Compute sharpness: second derivative of gap
                sharpness = (
                    e_diff[ik + 1] - 2 * e_diff[ik] + e_diff[ik - 1]
                )
                if sharpness < min_sharpness:
                    continue  # Too flat — not a meaningful avoided crossing
                crossings.append(
                    {
                        "band_a": a + 1,
                        "band_b": b + 1,
                        "k_index": ik,
                        "k_distance": k_dists[ik],
                        "min_gap_ev": e_diff[ik],
                        "sharpness": sharpness,
                        "energy_a_ev": bands_list[a][ik],
                        "energy_b_ev": bands_list[b][ik],
                        "mean_energy_ev": (bands_list[a][ik] + bands_list[b][ik]) / 2,
                    }
                )

    # Sort by minimum gap (most interesting first)
    crossings.sort(key=lambda c: c["min_gap_ev"])

    return {
        "n_avoided_crossings": len(crossings),
        "avoided_crossings": crossings[:20],
        "is_physically_interesting": len(crossings) > 0 and crossings[0]["min_gap_ev"] < 0.2,
        "note": (
            "Avoided crossings may indicate topological phase transitions, "
            "spin-orbit coupling effects, or band inversion. Full analysis "
            "requires wavefunction parity information."
        ),
    }


# ---------------------------------------------------------------------------
# Level 3c: Fermi surface analysis
# ---------------------------------------------------------------------------


def fermi_surface_analysis(
    bands_data: dict[str, Any],
    e_fermi: float,
) -> dict[str, Any]:
    """Characterize Fermi surface topology from E(k) data.

    Detects Fermi-level crossings, groups them into electron/hole pockets,
    and estimates carrier concentration (2D Luttinger theorem).
    """
    k_dists = bands_data["k_distances"]
    k_points = bands_data.get("k_points", [])
    bands_list = bands_data["bands"]
    n_k = len(k_dists)

    # Find all EF crossings
    crossings: list[dict[str, Any]] = []
    for ib, energies in enumerate(bands_list):
        for ik in range(1, n_k):
            e0, e1 = energies[ik - 1], energies[ik]
            if (e0 - e_fermi) * (e1 - e_fermi) <= 0:
                # Linear interpolation for crossing position
                t = (e_fermi - e0) / (e1 - e0) if abs(e1 - e0) > 1e-12 else 0.5
                k_cross = k_dists[ik - 1] + t * (k_dists[ik] - k_dists[ik - 1])
                k_pt_cross = [
                    k_points[ik - 1][j] + t * (k_points[ik][j] - k_points[ik - 1][j])
                    for j in range(3)
                ] if k_points else [0.0, 0.0, 0.0]

                # Determine if electron or hole pocket
                # Electron pocket: band crosses EF from below (E < EF → E > EF)
                is_electron = e0 < e_fermi  # band energy is increasing through EF
                # More robust: check if band minimum is below EF
                band_min = min(energies)
                band_max = max(energies)
                if band_max > e_fermi and band_min < e_fermi:
                    carrier_type = "electron" if band_max - e_fermi > e_fermi - band_min else "hole"
                else:
                    carrier_type = "electron" if band_min < e_fermi else "hole"

                crossings.append(
                    {
                        "band_index": ib + 1,
                        "k_index_interp": ik - 1 + t,
                        "k_distance": k_cross,
                        "k_point_fractional": k_pt_cross,
                        "carrier_type": "electron" if is_electron else "hole",
                        "energy_vs_ef_ev": 0.0,
                    }
                )

    # Group crossings into Fermi surface sheets (pockets)
    # Adjacent crossings on the same band belong to the same pocket
    pockets: list[dict[str, Any]] = []
    if crossings:
        # Sort by band and k-distance
        crossings.sort(key=lambda c: (c["band_index"], c["k_distance"]))
        current_pocket = [crossings[0]]
        for c in crossings[1:]:
            prev = current_pocket[-1]
            # Same band and nearby in k-space → same pocket
            if (
                c["band_index"] == prev["band_index"]
                and abs(c["k_distance"] - prev["k_distance"]) < 0.1
            ):
                current_pocket.append(c)
            else:
                pockets.append(_make_pocket(current_pocket))
                current_pocket = [c]
        pockets.append(_make_pocket(current_pocket))

    # Summary statistics
    n_electron_pockets = sum(1 for p in pockets if p["carrier_type"] == "electron")
    n_hole_pockets = sum(1 for p in pockets if p["carrier_type"] == "hole")
    n_bands_crossing_ef = len(set(c["band_index"] for c in crossings))

    # Estimate 2D carrier concentration from Fermi surface extent
    # For each pocket, n_2D ≈ Δk_F / (2π) · (pocket width in perpendicular direction)
    total_n_2d = None
    kf_total = sum(
        abs(p["kf_range"]) for p in pockets
    )  # total Fermi wavevector span
    # Rough 2D carrier density estimate (assuming circular pockets):
    # n_2D ≈ k_F² / (2π) for each pocket
    # From our 1D data: k_F ≈ half the crossing span
    # n_2D ≈ Σ (Δk/2)² / (2π)
    if kf_total > 0:
        total_n_2d = sum(
            (p["kf_range"] / 2.0) ** 2 / (2.0 * math.pi)
            for p in pockets
            if p["kf_range"] > 0
        )

    return {
        "n_bands_crossing_ef": n_bands_crossing_ef,
        "n_electron_pockets": n_electron_pockets,
        "n_hole_pockets": n_hole_pockets,
        "n_pockets": len(pockets),
        "pockets": pockets,
        "fermi_surface_extent_k": kf_total,
        "estimated_n_2d_per_unit_cell": total_n_2d,
        "is_metallic": n_bands_crossing_ef > 0,
        "caveat": (
            "1D path data only captures Fermi surface sections along "
            "high-symmetry lines. Full Fermi surface characterization "
            "requires a dense 3D k-mesh."
        ),
    }


def _make_pocket(crossings: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a group of EF crossings as a Fermi surface pocket."""
    k_range = (
        max(c["k_distance"] for c in crossings)
        - min(c["k_distance"] for c in crossings)
    )
    return {
        "band_indices": list(set(c["band_index"] for c in crossings)),
        "carrier_type": crossings[0]["carrier_type"],
        "n_crossings": len(crossings),
        "kf_range": k_range,
        "kf_midpoint": (
            min(c["k_distance"] for c in crossings) + k_range / 2.0
            if crossings
            else 0.0
        ),
        "kf_min": min(c["k_distance"] for c in crossings) if crossings else 0.0,
        "kf_max": max(c["k_distance"] for c in crossings) if crossings else 0.0,
    }


# ---------------------------------------------------------------------------
# Level 3d: Dimensionality analysis
# ---------------------------------------------------------------------------


def dimensionality_analysis(
    bands_data: dict[str, Any],
    bands_data_out_of_plane: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyze the effective dimensionality from band dispersion.

    For 2D materials like HfBr2, the in-plane dispersion (Γ→M, Γ→K) should
    be much larger than the out-of-plane dispersion (Γ→A).

    If *bands_data_out_of_plane* is provided (e.g., Γ→A path), compares
    in-plane vs out-of-plane bandwidths to quantify 2D character.
    """
    bands_list = bands_data["bands"]
    n_bands = len(bands_list)

    # Compute total bandwidth per band (in-plane)
    in_plane_bandwidths = [
        max(energies) - min(energies) for energies in bands_list
    ]
    avg_in_plane_bw = sum(in_plane_bandwidths) / n_bands if n_bands else 0.0
    max_in_plane_bw = max(in_plane_bandwidths) if in_plane_bandwidths else 0.0

    result: dict[str, Any] = {
        "avg_in_plane_bandwidth_ev": avg_in_plane_bw,
        "max_in_plane_bandwidth_ev": max_in_plane_bw,
        "per_band_in_plane_bandwidth_ev": in_plane_bandwidths,
    }

    if bands_data_out_of_plane:
        oop_bands = bands_data_out_of_plane["bands"]
        oop_bandwidths = [
            max(energies) - min(energies) for energies in oop_bands
        ]
        avg_oop_bw = sum(oop_bandwidths) / len(oop_bandwidths) if oop_bandwidths else 0.0

        # Dimensionality ratio: oop_bw / in_plane_bw
        # Small ratio → highly 2D; near 1 → 3D-like
        if avg_in_plane_bw > 0.01:
            dim_ratio = avg_oop_bw / avg_in_plane_bw
        else:
            dim_ratio = None

        if dim_ratio is not None:
            if dim_ratio < 0.1:
                dim_class = "highly 2D (weak interlayer coupling)"
            elif dim_ratio < 0.3:
                dim_class = "quasi-2D (moderate interlayer coupling)"
            elif dim_ratio < 0.7:
                dim_class = "anisotropic 3D"
            else:
                dim_class = "3D-like (strong interlayer coupling)"

        result.update(
            {
                "avg_out_of_plane_bandwidth_ev": avg_oop_bw,
                "dimensionality_ratio": dim_ratio,
                "dimensionality_class": dim_class if dim_ratio is not None else "unknown",
                "per_band_oop_bandwidth_ev": oop_bandwidths,
                "bandwidth_anisotropy": (
                    max_in_plane_bw / max(oop_bandwidths)
                    if oop_bandwidths and max(oop_bandwidths) > 0
                    else None
                ),
            }
        )
    else:
        result["dimensionality_ratio"] = None
        result["note"] = (
            "Out-of-plane (Γ→A) band data not provided. "
            "Dimensionality ratio requires both in-plane and out-of-plane paths."
        )

    return result


# ---------------------------------------------------------------------------
# Level 3e: Band velocity statistics
# ---------------------------------------------------------------------------


def band_velocity_statistics(
    bands_data: dict[str, Any],
    e_fermi: float,
    velocity_data: list[list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Statistical analysis of group velocities across all bands.

    Computes velocity distributions, identifies the fastest/slowest bands,
    and provides velocity histograms suitable for transport analysis.
    """
    bands_list = bands_data["bands"]
    n_bands = len(bands_list)
    n_k = len(bands_list[0]) if bands_list else 0

    if velocity_data is None:
        velocity_data = compute_group_velocities(bands_data)

    # Collect all velocities
    all_v: list[float] = []
    all_v_near_ef: list[float] = []
    per_band_stats: list[dict[str, Any]] = []

    for ib in range(n_bands):
        vels = velocity_data[ib]
        band_v = [v["v_mag_A_per_fs"] for v in vels]
        max_v = max(band_v) if band_v else 0.0
        avg_v = sum(band_v) / len(band_v) if band_v else 0.0

        # Velocities near EF
        v_near_ef = [
            v["v_mag_A_per_fs"]
            for ik, v in enumerate(vels)
            if abs(bands_list[ib][ik] - e_fermi) < 0.5
        ]
        avg_v_ef = sum(v_near_ef) / len(v_near_ef) if v_near_ef else 0.0

        per_band_stats.append(
            {
                "band_index": ib + 1,
                "v_max_A_per_fs": max_v,
                "v_avg_A_per_fs": avg_v,
                "v_avg_near_ef_A_per_fs": avg_v_ef,
                "n_points_near_ef": len(v_near_ef),
            }
        )
        all_v.extend(band_v)
        all_v_near_ef.extend(v_near_ef)

    # Histogram bins (adaptive)
    if all_v:
        v_max_all = max(all_v)
        v_bins = _linspace(0.0, v_max_all, 30)
        hist = [0] * (len(v_bins) - 1)
        for v in all_v:
            for i in range(len(v_bins) - 1):
                if v_bins[i] <= v < v_bins[i + 1]:
                    hist[i] += 1
                    break
    else:
        v_max_all = 0.0
        v_bins = []
        hist = []

    # Find fastest bands
    per_band_stats.sort(key=lambda b: b["v_max_A_per_fs"], reverse=True)

    return {
        "v_max_all_A_per_fs": v_max_all,
        "v_avg_all_A_per_fs": sum(all_v) / len(all_v) if all_v else 0.0,
        "v_avg_near_ef_A_per_fs": (
            sum(all_v_near_ef) / len(all_v_near_ef) if all_v_near_ef else 0.0
        ),
        "histogram_bins": v_bins,
        "histogram_counts": hist,
        "per_band": per_band_stats,
        "fastest_band": per_band_stats[0] if per_band_stats else None,
        "slowest_band": per_band_stats[-1] if per_band_stats else None,
        "n_bands_analysed": n_bands,
    }


# ---------------------------------------------------------------------------
# Van Hove singularities (unchanged from original)
# ---------------------------------------------------------------------------


def van_hove_singularities(
    dos_data: list[dict[str, float]],
    e_fermi: float,
    prominence: float = 0.05,
    min_distance: int = 20,
) -> list[dict[str, Any]]:
    """Detect van Hove singularities (peaks/dips) in DOS(E)."""
    energies = [d["energy_ev"] for d in dos_data]
    dos_vals = [d["dos"] for d in dos_data]
    n = len(dos_vals)

    if n < 3:
        return []

    global_max = max(dos_vals)
    threshold = global_max * prominence

    peaks: list[dict[str, Any]] = []
    for i in range(1, n - 1):
        if dos_vals[i] < threshold:
            continue
        if dos_vals[i] > dos_vals[i - 1] and dos_vals[i] > dos_vals[i + 1]:
            left_ok = all(
                dos_vals[i] > dos_vals[j]
                for j in range(max(0, i - min_distance), i)
            )
            right_ok = all(
                dos_vals[i] > dos_vals[j]
                for j in range(i + 1, min(n, i + min_distance + 1))
            )
            if left_ok and right_ok:
                peaks.append(
                    {
                        "energy_ev": energies[i],
                        "dos_value": dos_vals[i],
                        "energy_vs_ef": energies[i] - e_fermi,
                        "relative_height": (
                            dos_vals[i] / global_max if global_max > 0 else 0.0
                        ),
                    }
                )

    peaks.sort(key=lambda p: p["dos_value"], reverse=True)
    return peaks[:10]


# ---------------------------------------------------------------------------
# Band statistics (unchanged from original)
# ---------------------------------------------------------------------------


def band_statistics(
    bands: list[list[float]],
    k_dists: list[float],
    e_fermi: float,
) -> dict[str, Any]:
    """Compute per-band statistics: bandwidth, dispersion metrics, EF crossing."""
    stats: list[dict[str, Any]] = []
    for ib, energies in enumerate(bands):
        e_min = min(energies)
        e_max = max(energies)
        bandwidth = e_max - e_min
        slopes = []
        for i in range(1, len(energies)):
            dk = k_dists[i] - k_dists[i - 1]
            if dk > 1e-12:
                slopes.append((energies[i] - energies[i - 1]) / dk)
        rms_slope = (
            (sum(s * s for s in slopes) / len(slopes)) ** 0.5 if slopes else 0.0
        )
        crosses_ef = (
            (min(energies) <= e_fermi <= max(energies))
            if e_fermi is not None
            else False
        )
        stats.append(
            {
                "band_index": ib + 1,
                "e_min": e_min,
                "e_max": e_max,
                "bandwidth": bandwidth,
                "rms_dispersion": rms_slope,
                "crosses_ef": crosses_ef,
                "n_slope_points": len(slopes),
            }
        )
    return {"per_band": stats, "e_fermi": e_fermi}


# ---------------------------------------------------------------------------
# Combined analysis — main entry point
# ---------------------------------------------------------------------------


def analyze_bands_physics(
    bands_data: dict[str, Any],
    dos_data: dict[str, Any] | None = None,
    e_fermi: float | None = None,
    *,
    bands_ga_data: dict[str, Any] | None = None,
    temperature_k: float = 300.0,
    k_scale_inv_angstrom: float | None = None,
    run_transport: bool = True,
    run_jdos: bool = True,
    run_advanced: bool = True,
) -> dict[str, Any]:
    """Run comprehensive physics analysis on bands + DOS data.

    Parameters
    ----------
    bands_data: dict with keys k_distances, bands, nbnd, nks, k_points, high_symmetry
    dos_data: optional dict with e_fermi_ev, datasets (from html.build_workbench)
    e_fermi: override Fermi energy (eV)
    bands_ga_data: optional out-of-plane (Γ→A) band data for dimensionality analysis
    temperature_k: temperature for transport calculations
    k_scale_inv_angstrom: k-space scale factor (BZ fraction → Å⁻¹ conversion)
    run_transport: whether to compute CRTA transport coefficients
    run_jdos: whether to compute JDOS
    run_advanced: whether to run Level 3 analyses (degeneracy, avoided crossings, etc.)

    Returns a comprehensive dict with all analysis results.
    """
    # Resolve Fermi energy
    _ef = e_fermi
    if _ef is None and dos_data:
        _ef = dos_data.get("e_fermi_ev")
    if _ef is None:
        _ef = 0.0

    b = bands_data
    k_dists: list[float] = b["k_distances"]
    bands_list: list[list[float]] = b["bands"]

    result: dict[str, Any] = {"e_fermi_ev": _ef}

    # ------------------------------------------------------------------
    # Level 1: Band gap
    # ------------------------------------------------------------------
    gap_info = band_gap_analysis(bands_list, k_dists, _ef)
    result["band_gap"] = gap_info

    # ------------------------------------------------------------------
    # Level 1: Effective mass (directional)
    # ------------------------------------------------------------------
    em_summary = effective_mass_summary(bands_data, _ef, k_scale_inv_angstrom)
    result["effective_mass"] = em_summary

    # Backward-compatible scalar effective mass at CBM
    cbm_k = gap_info.get("cbm_k_index")
    cbm_band = gap_info.get("cbm_band")
    if cbm_k is not None and cbm_band is not None and cbm_k >= 0:
        cbm_energies = bands_list[cbm_band]
        window = 4
        i_start = max(0, cbm_k - window)
        i_end = min(len(cbm_energies), cbm_k + window + 1)
        seg_ks = k_dists[i_start:i_end]
        seg_es = cbm_energies[i_start:i_end]
        m_eff_scalar = effective_mass(
            seg_ks, seg_es, fit_window=3, k_scale_inv_angstrom=k_scale_inv_angstrom
        )
        result["effective_mass_cbm"] = m_eff_scalar
    else:
        result["effective_mass_cbm"] = {
            "m_eff_me": None, "curvature": None, "r_squared": None, "n_points": 0
        }

    # ------------------------------------------------------------------
    # Level 1: Fermi velocity
    # ------------------------------------------------------------------
    vf_results = []
    for ib, energies in enumerate(bands_list):
        vf = fermi_velocity(k_dists, energies, _ef)
        for v in vf:
            v["band_index"] = ib + 1
        vf_results.extend(vf)
    result["fermi_velocity"] = {
        "n_crossings": len(vf_results),
        "crossings": vf_results[:20],
        "avg_v_fermi_A_per_fs": (
            sum(v["v_fermi_A_per_fs"] for v in vf_results) / len(vf_results)
            if vf_results
            else None
        ),
    }

    # ------------------------------------------------------------------
    # Level 1: Van Hove singularities
    # ------------------------------------------------------------------
    if dos_data:
        dos_list = dos_data.get("datasets", [])
        tdOS = dos_list[0].get("data", []) if dos_list else dos_data.get("data", [])
        if tdOS:
            vhs = van_hove_singularities(tdOS, _ef)
            result["van_hove"] = vhs

    # ------------------------------------------------------------------
    # Level 1: Band statistics
    # ------------------------------------------------------------------
    result["band_stats"] = band_statistics(bands_list, k_dists, _ef)

    # ------------------------------------------------------------------
    # Pre-compute velocities (reused across several Level 2/3 analyses)
    # ------------------------------------------------------------------
    velocity_data = compute_group_velocities(bands_data, k_scale_inv_angstrom)

    # ------------------------------------------------------------------
    # Level 2: JDOS
    # ------------------------------------------------------------------
    if run_jdos:
        result["jdos"] = joint_density_of_states(
            bands_data,
            _ef,
            energy_range=(-2.0, 8.0),
            n_energy=200,
            broadening=0.05,
        )

    # ------------------------------------------------------------------
    # Level 2: Transport coefficients
    # ------------------------------------------------------------------
    if run_transport:
        result["transport"] = transport_coefficients(
            bands_data,
            _ef,
            temperature_k=temperature_k,
            velocity_data=velocity_data,
            energy_range=(-2.0, 2.0),
            n_energy=300,
            broadening=0.03,
        )

        result["plasma_frequency"] = plasma_frequency(
            bands_data, _ef, velocity_data=velocity_data
        )

    # ------------------------------------------------------------------
    # Level 3: Advanced analyses
    # ------------------------------------------------------------------
    if run_advanced:
        result["degeneracy"] = analyze_degeneracy(bands_data, _ef)
        result["avoided_crossings"] = detect_avoided_crossings(bands_data)
        result["fermi_surface"] = fermi_surface_analysis(bands_data, _ef)
        result["dimensionality"] = dimensionality_analysis(
            bands_data, bands_ga_data
        )
        result["velocity_stats"] = band_velocity_statistics(
            bands_data, _ef, velocity_data=velocity_data
        )

    return result
