"""Shared k-path normalisation for band structure visualisation.

Extracted from html.py:_detect_high_symmetry so that report sections,
existing workbench, and future overlay/comparison code use the same logic.
"""

from __future__ import annotations

from typing import Any


def compute_k_distances(k_points: list[list[float]]) -> list[float]:
    """Cumulative Euclidean distance along a k-point path."""
    dists = []
    cum = 0.0
    prev = None
    for k in k_points:
        if prev is not None:
            d2 = sum((k[i] - prev[i]) ** 2 for i in range(3))
            cum += d2 ** 0.5
        dists.append(cum)
        prev = k
    return dists


def detect_high_symmetry(
    k_points: list[list[float]],
    k_dists: list[float],
) -> list[dict[str, Any]]:
    """Detect high-symmetry k-points along a band-structure path.

    Uses smoothed tangent vectors to find corners (direction changes),
    then labels breakpoints sequentially for standard paths and falls
    back to coordinate matching.
    """
    n = len(k_points)
    if n < 3:
        return [{"label": "Γ", "distance": k_dists[0]}]

    # Smoothed tangent vectors
    window = max(1, n // 20)
    tangents = []
    for i in range(n - 1):
        i0 = max(0, i - window)
        i1 = min(n - 1, i + window + 1)
        d = [k_points[i1][c] - k_points[i0][c] for c in range(3)]
        mag = (d[0]**2 + d[1]**2 + d[2]**2) ** 0.5
        tangents.append([d[c]/mag for c in range(3)] if mag > 1e-12 else [1.0, 0.0, 0.0])

    # Corner detection: local maxima of 1 - cos(angle)
    scores = []
    for i in range(len(tangents)):
        if i == 0 or i == len(tangents) - 1:
            scores.append(0.0)
            continue
        dot = sum(tangents[i-1][c] * tangents[i][c] for c in range(3))
        dot = max(-1.0, min(1.0, dot))
        scores.append(1.0 - dot)

    breakpoints = [0]
    for i in range(2, len(scores) - 2):
        if (scores[i] > 0.03 and scores[i] > scores[i-1] and scores[i] > scores[i+1]
            and scores[i] > scores[i-2] and scores[i] > scores[i+2]):
            breakpoints.append(i)
    breakpoints.append(n - 1)

    # Deduplicate
    bp_clean = [0]
    for b in breakpoints[1:]:
        if b - bp_clean[-1] >= 3:
            bp_clean.append(b)
    breakpoints = bp_clean

    # Sequential labelling: 4 breakpoints → Γ, M, K, Γ
    n_bp = len(breakpoints)
    if n_bp == 2:     labels = ["Γ", "Γ"]
    elif n_bp == 3:   labels = ["Γ", "X", "Γ"]
    elif n_bp == 4:   labels = ["Γ", "M", "K", "Γ"]
    elif n_bp == 5:   labels = ["Γ", "M", "K", "M", "Γ"]
    else:
        labels = ["Γ"]
        mid = ["M", "K", "X", "Y", "Z", "W"]
        for i in range(1, n_bp - 1):
            labels.append(mid[(i-1) % len(mid)])
        labels.append("Γ")

    hs = []
    for i, bp in enumerate(breakpoints):
        label = labels[i] if i < len(labels) else f"P{bp}"
        if label in ("X", "Y", "Z", "W", f"P{bp}"):
            label = _classify_kpoint(k_points[bp], bp, n)
        hs.append({"label": label, "distance": k_dists[bp]})

    # Deduplicate by label+proximity
    deduped = []
    for h in hs:
        if deduped and deduped[-1]["label"] == h["label"] and abs(deduped[-1]["distance"] - h["distance"]) < 0.01:
            continue
        deduped.append(h)
    if deduped and deduped[0]["label"] != "Γ":
        deduped[0]["label"] = "Γ"

    return deduped


def _classify_kpoint(k: list[float], idx: int, n_total: int) -> str:
    """Heuristic coordinate-based classification of a k-point."""
    kx, ky, kz = k[0], k[1], k[2]
    d2_origin = kx**2 + ky**2 + kz**2
    if d2_origin < 0.005:
        return "Γ"
    if abs(kz - 0.5) < 0.05:
        return "A"
    if abs(kx - 0.5) < 0.04:
        return "M"
    d2_k = (kx - 1.0/3)**2 + (ky - 1.0/3)**2 + kz**2
    d2_kc = (kx - 1.0/3)**2 + (ky - 0.57735)**2 + kz**2
    if min(d2_k, d2_kc) < 0.04:
        return "K"
    if idx == 0:
        return "Γ"
    if idx == n_total - 1:
        return "Γ"
    return f"Q{idx}"
