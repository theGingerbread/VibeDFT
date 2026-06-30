"""Validation rules for intercalation site screening.

These rules cover the seven intercalation-specific failure modes identified
during HfCl2 / HfBr2 / HfI2 intercalation work:

1. ``intercalation.relax_not_converged`` — BFGS/vc-relax did not converge.
2. ``intercalation.short_M_X_bond`` — Li/Na/K–X distance below empirical floor.
3. ``intercalation.high_symmetry_saddle_risk`` — intercalant parked on a
   high-symmetry TOP column with no off-center relax test.
4. ``intercalation.no_site_comparison`` — only one site screened, so
   "lowest energy configuration" cannot be claimed.
5. ``phonon.imaginary_intercalant_slip`` — imaginary mode dominated by the
   intercalant displacement (>50 %), blocking EPC.
6. ``sc.ph_stability_failed_but_epc_present`` — PH stability gate failed
   yet EPC outputs exist (critical inconsistency).
7. ``tc.max_used_as_final`` — report cites ``tc_max_K`` instead of the
   two-grid overlap ``tc_point_K``.

Each rule is a ``validate_*`` function taking ``case_dir: Path`` and
returning ``list[SanityIssue]``.  The aggregator
``run_intercalation_rules(case_dir)`` runs all seven and is wired into
``vibedft qa all`` via :func:`vibedft.core.qa.qa_all`.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from vibedft.models.inspection import SanityIssue, Severity
from vibedft.parsers.qe_input_parser import parse_qe_input


# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

# Empirical minimum M–X distances (Å) below which the bond is suspiciously short.
_M_X_THRESHOLDS: dict[str, float] = {
    "Li": 2.0,
    "Na": 2.4,
    "K": 2.8,
}

# Intercalant elements recognised by these rules.
_INTERCALANTS: set[str] = {"Li", "Na", "K", "Rb", "Cs"}

# Halogen / chalcogen partners that form the host lattice.
_HOST_ANIONS: set[str] = {"Cl", "Br", "I", "S", "Se", "Te", "O", "F"}

# Tolerance for "x ≈ 0, y ≈ 0" high-symmetry column test (crystal coords).
_HIGH_SYM_TOL: float = 0.02

# Imaginary frequency threshold (cm⁻¹).  Frequencies more negative than this
# are treated as genuinely imaginary (not numerical noise).
_IMAG_FREQ_CM: float = -10.0

# Fraction of total displacement magnitude that must come from the
# intercalant atom for the slip rule to fire.
_INTERCALANT_DISP_FRACTION: float = 0.50


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _read_text(path: Path) -> str:
    """Read a file safely, returning '' on error."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _find_rx_outputs(case_dir: Path) -> list[Path]:
    """Find all rx.out / vc-relax output files in the case tree."""
    candidates: list[Path] = []
    # Common naming: rx.out, vc-relax.out, relax.out
    for pattern in ("rx.out", "vc-relax.out", "vc_relax.out", "relax.out"):
        candidates.extend(case_dir.rglob(pattern))
    # Also any .out file whose stem contains "rx" or "relax"
    for f in case_dir.rglob("*.out"):
        stem = f.stem.lower()
        if "rx" in stem or "relax" in stem:
            if f not in candidates:
                candidates.append(f)
    return sorted(set(candidates))


def _find_rx_inputs(case_dir: Path) -> list[Path]:
    """Find all rx.in / vc-relax input files in the case tree."""
    candidates: list[Path] = []
    for pattern in ("rx.in", "vc-relax.in", "vc_relax.in", "relax.in"):
        candidates.extend(case_dir.rglob(pattern))
    for f in case_dir.rglob("*.in"):
        stem = f.stem.lower()
        if "rx" in stem or "relax" in stem:
            if f not in candidates:
                candidates.append(f)
    return sorted(set(candidates))


def _parse_atomic_positions(qe) -> list[tuple[str, float, float, float]]:
    """Extract (element, x, y, z) tuples from ATOMIC_POSITIONS crystal/angstrom."""
    card = qe.cards.get("ATOMIC_POSITIONS")
    if card is None or not card.rows:
        return []
    positions: list[tuple[str, float, float, float]] = []
    for row in card.rows:
        if len(row) < 4:
            continue
        elem = row[0].capitalize()
        try:
            x, y, z = float(row[1]), float(row[2]), float(row[3])
        except (ValueError, IndexError):
            continue
        positions.append((elem, x, y, z))
    return positions


def _parse_cell_parameters_angstrom(qe) -> list[list[float]] | None:
    """Return 3×3 cell vectors in Å, or None if unavailable."""
    card = qe.cards.get("CELL_PARAMETERS")
    if card is None or len(card.rows) < 3:
        return None
    option = (card.option or "").lower()
    vectors: list[list[float]] = []
    for row in card.rows[:3]:
        try:
            vectors.append([float(row[0]), float(row[1]), float(row[2])])
        except (ValueError, IndexError):
            return None
    # Convert bohr → Å if needed (1 bohr = 0.529177 Å)
    if "bohr" in option:
        vectors = [[c * 0.529177 for c in v] for v in vectors]
    return vectors


def _crystal_to_cartesian(
    frac: tuple[float, float, float], cell: list[list[float]]
) -> tuple[float, float, float]:
    """Convert fractional (crystal) coordinates to Cartesian Å."""
    x, y, z = frac
    cx = cell[0][0] * x + cell[1][0] * y + cell[2][0] * z
    cy = cell[0][1] * x + cell[1][1] * y + cell[2][1] * z
    cz = cell[0][2] * x + cell[1][2] * y + cell[2][2] * z
    return (cx, cy, cz)


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Euclidean distance between two 3-vectors."""
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def _nearest_anion_distance(
    intercalant_pos: tuple[str, float, float, float],
    positions: list[tuple[str, float, float, float]],
    cell: list[list[float]] | None,
) -> tuple[str, float] | None:
    """Return (anion_element, distance_Å) of the nearest host anion.

    Handles crystal coordinates by converting to Cartesian.  If ``cell`` is
    None, assumes positions are already in Å (angstrom option).
    """
    elem_i, xi, yi, zi = intercalant_pos
    if cell is not None:
        cart_i = _crystal_to_cartesian((xi, yi, zi), cell)
    else:
        cart_i = (xi, yi, zi)

    best: tuple[str, float] | None = None
    for elem_j, xj, yj, zj in positions:
        if elem_j not in _HOST_ANIONS:
            continue
        if cell is not None:
            cart_j = _crystal_to_cartesian((xj, yj, zj), cell)
        else:
            cart_j = (xj, yj, zj)
        d = _distance(cart_i, cart_j)
        if best is None or d < best[1]:
            best = (elem_j, d)
    return best


def _is_high_symmetry_column(x: float, y: float) -> bool:
    """True if (x, y) ≈ (0, 0) or (1, 1) in crystal coords (TOP site)."""
    # Normalise to [0, 1) then check proximity to 0 or 1
    nx = x - math.floor(x)
    ny = y - math.floor(y)
    near_zero = (nx < _HIGH_SYM_TOL or nx > 1.0 - _HIGH_SYM_TOL) and (
        ny < _HIGH_SYM_TOL or ny > 1.0 - _HIGH_SYM_TOL
    )
    return near_zero


def _count_intercalation_sites(case_dir: Path) -> int:
    """Count distinct intercalation site directories.

    Looks for sibling directories matching ``<Intercalant>_<N>`` (e.g.
    ``K_1``, ``Na_2``, ``Li_3``) or screening sub-trees containing
    multiple ``*/outputs/rx.out`` files.
    """
    site_dirs: set[Path] = set()
    # Pattern 1: <Intercalant>_<N> directories (K_1, Na_2, ...)
    for sub in case_dir.iterdir():
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        if re.match(r"^(Li|Na|K|Rb|Cs)_\d+", sub.name, re.IGNORECASE):
            site_dirs.add(sub)
    # Pattern 2: screening/<Intercalant>_<N> (K-screening/K_1, ...)
    for sub in case_dir.iterdir():
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        for sub2 in sub.iterdir():
            if not sub2.is_dir() or sub2.name.startswith("."):
                continue
            if re.match(r"^(Li|Na|K|Rb|Cs)_\d+", sub2.name, re.IGNORECASE):
                site_dirs.add(sub2)
    # Pattern 3: distinct rx.out files (each represents a site)
    rx_outs = _find_rx_outputs(case_dir)
    if rx_outs and not site_dirs:
        return len(rx_outs)
    return len(site_dirs) if site_dirs else len(rx_outs)


def _find_matdyn_modes(case_dir: Path) -> list[Path]:
    """Find matdyn.modes files in the case tree."""
    return sorted(case_dir.rglob("matdyn.modes"))


def _find_dynmat_outputs(case_dir: Path) -> list[Path]:
    """Find dynmat.x output files."""
    candidates: list[Path] = []
    for pattern in ("dynmat.out", "*.dynmat.out"):
        candidates.extend(case_dir.rglob(pattern))
    return sorted(set(candidates))


def _parse_matdyn_modes(path: Path) -> list[dict]:
    """Parse a matdyn.modes file.

    Returns a list of mode dicts, each with:
      ``freq_cm`` (float), ``q`` (str), ``displacements`` (list of (dx,dy,dz) per atom).

    The matdyn.modes format::

         q =   0.0000  0.0000  0.0000
         freq ( 1) =  -21.106897 [cm-1]
         ( dx dy dz )   # atom 1
         ( dx dy dz )   # atom 2
         ...
    """
    text = _read_text(path)
    if not text:
        return []

    modes: list[dict] = []
    lines = text.splitlines()
    i = 0
    n_atoms = 0
    current_q = ""
    while i < len(lines):
        line = lines[i].strip()
        # q-point header
        q_match = re.match(r"^q\s*=\s*([\d\s\.\-+]+)", line)
        if q_match:
            current_q = q_match.group(1).strip()
            i += 1
            continue
        # frequency line
        freq_match = re.match(r"^freq\s*\(\s*(\d+)\s*\)\s*=\s*([-\d\.]+)\s*\[cm-1\]", line)
        if freq_match:
            freq_cm = float(freq_match.group(2))
            # Collect displacement lines: each atom has one ( dx dy dz ) line
            displacements: list[tuple[float, float, float]] = []
            j = i + 1
            while j < len(lines):
                dline = lines[j].strip()
                d_match = re.match(
                    r"^\(\s*([-\d\.+]+)\s+([-\d\.+]+)\s+([-\d\.+]+)\s*\)", dline
                )
                if not d_match:
                    break
                displacements.append(
                    (float(d_match.group(1)), float(d_match.group(2)), float(d_match.group(3)))
                )
                j += 1
            n_atoms = max(n_atoms, len(displacements))
            modes.append({
                "freq_cm": freq_cm,
                "q": current_q,
                "displacements": displacements,
            })
            i = j
            continue
        i += 1
    return modes


def _intercalant_atom_index(
    positions: list[tuple[str, float, float, float]],
) -> int | None:
    """Return the 0-based index of the first intercalant atom in positions."""
    for idx, (elem, *_rest) in enumerate(positions):
        if elem in _INTERCALANTS:
            return idx
    return None


def _displacement_magnitude(d: tuple[float, float, float]) -> float:
    return math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)


def _find_freq_gp_files(case_dir: Path) -> list[Path]:
    """Find phonon dispersion .freq.gp files."""
    return sorted(case_dir.rglob("*.freq.gp"))


def _has_non_gamma_imaginary(freq_gp: Path) -> bool:
    """Check if a .freq.gp file has imaginary modes at non-Gamma q-points.

    The first column is the q-path coordinate; the remaining columns are
    frequencies in cm⁻¹.  Gamma is the first row (q=0).  Any negative
    frequency < ``_IMAG_FREQ_CM`` at q > 0 counts as a non-Gamma imaginary mode.
    """
    text = _read_text(freq_gp)
    if not text:
        return False
    lines = text.strip().splitlines()
    for idx, line in enumerate(lines):
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            q_coord = float(parts[0])
        except ValueError:
            continue
        # Skip Gamma (first row, q≈0)
        if idx == 0 and abs(q_coord) < 1e-4:
            continue
        for token in parts[1:]:
            try:
                freq = float(token)
            except ValueError:
                continue
            if freq < _IMAG_FREQ_CM:
                return True
    return False


def _find_epc_outputs(case_dir: Path) -> tuple[list[Path], list[Path]]:
    """Return (lambdax_files, alpha2f_files) found in the case tree."""
    lambdax = sorted(case_dir.rglob("lambdax.out"))
    alpha2f = sorted(case_dir.rglob("alpha2F.dat"))
    return lambdax, alpha2f


def _find_report_files(case_dir: Path) -> list[Path]:
    """Find markdown report files that might cite Tc values."""
    candidates: list[Path] = []
    for pattern in ("*.md", "*.txt"):
        for f in case_dir.rglob(pattern):
            if f.is_file() and "node_modules" not in str(f):
                candidates.append(f)
    # Prioritise report directories
    report_dirs = ["20_report", "report", "reports", "docs"]
    prioritised: list[Path] = []
    for f in candidates:
        if any(rd in str(f) for rd in report_dirs):
            prioritised.append(f)
    # Fall back to all candidates if no report dir found
    return sorted(set(prioritised)) if prioritised else sorted(set(candidates))


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 1: intercalation.relax_not_converged
# ═══════════════════════════════════════════════════════════════════════════════


def validate_relax_not_converged(case_dir: Path) -> list[SanityIssue]:
    """ERROR: BFGS "convergence not achieved" in rx.out or vc-relax output.

    Scans all relax/vc-relax output files for the QE BFGS failure signature
    ``"convergence not achieved"`` or the absence of ``"End final coordinates"``
    in a vc-relax run.  Blocks formal site ranking because the geometry is
    not at a true minimum.
    """
    issues: list[SanityIssue] = []
    for out_path in _find_rx_outputs(case_dir):
        text = _read_text(out_path)
        if not text:
            continue
        rel = str(out_path.relative_to(case_dir)) if out_path.is_relative_to(case_dir) else str(out_path)

        # Explicit BFGS failure message
        if re.search(r"convergence not achieved", text, re.IGNORECASE):
            issues.append(SanityIssue(
                id="intercalation.relax_not_converged",
                severity=Severity.ERROR,
                message=f"BFGS convergence not achieved in {rel}",
                source_file=str(out_path),
                detail="The ionic relaxation did not reach the force/energy threshold. "
                       "This site's geometry is not at a minimum — formal site ranking "
                       "is blocked until the relax converges.",
            ))
            continue

        # vc-relax without "End final coordinates" → did not finish
        is_vc_relax = bool(re.search(r"calculation\s*=\s*['\"]vc-relax['\"]", text, re.IGNORECASE))
        has_bfgs = "bfgs" in text.lower()
        if is_vc_relax and has_bfgs and "End final coordinates" not in text:
            issues.append(SanityIssue(
                id="intercalation.relax_not_converged",
                severity=Severity.ERROR,
                message=f"vc-relax output {rel} has no 'End final coordinates' — "
                        "relaxation incomplete",
                source_file=str(out_path),
                detail="A vc-relax run that started BFGS but never printed final "
                       "coordinates did not converge. Re-run with more ionic steps "
                       "or looser thresholds.",
            ))

    return issues


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 2: intercalation.short_M_X_bond
# ═══════════════════════════════════════════════════════════════════════════════


def validate_short_M_X_bond(case_dir: Path) -> list[SanityIssue]:
    """WARNING: Li/Na/K–X nearest distance below empirical threshold.

    Parses each intercalation input (rx.in) for ATOMIC_POSITIONS and
    CELL_PARAMETERS, identifies the intercalant atom, and computes the
    nearest anion distance.  Thresholds are element-dependent:
    Li–X < 2.0 Å, Na–X < 2.4 Å, K–X < 2.8 Å.
    """
    issues: list[SanityIssue] = []
    for in_path in _find_rx_inputs(case_dir):
        try:
            qe = parse_qe_input(in_path)
        except Exception:
            continue
        positions = _parse_atomic_positions(qe)
        if not positions:
            continue

        cell = _parse_cell_parameters_angstrom(qe)
        # If cell is None, assume positions are in Å (angstrom option)
        pos_card = qe.cards.get("ATOMIC_POSITIONS")
        pos_option = pos_card.option if pos_card else ""
        if cell is None and "angstrom" not in (pos_option or "").lower():
            # Cannot compute distances without cell info
            continue

        rel = str(in_path.relative_to(case_dir)) if in_path.is_relative_to(case_dir) else str(in_path)

        for pos in positions:
            elem, *_ = pos
            if elem not in _INTERCALANTS:
                continue
            threshold = _M_X_THRESHOLDS.get(elem)
            if threshold is None:
                continue
            nearest = _nearest_anion_distance(pos, positions, cell)
            if nearest is None:
                continue
            anion_elem, dist = nearest
            if dist < threshold:
                issues.append(SanityIssue(
                    id="intercalation.short_M_X_bond",
                    severity=Severity.WARNING,
                    message=f"{elem}–{anion_elem} distance {dist:.2f} Å < "
                            f"threshold {threshold:.1f} Å in {rel}",
                    source_file=str(in_path),
                    detail=f"Empirical minimum {elem}–X distance is {threshold:.1f} Å. "
                           "A shorter bond suggests the intercalant is too close to the "
                           "host anion layer — check the initial site geometry or "
                           "increase the starting z-separation.",
                ))
    return issues


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 3: intercalation.high_symmetry_saddle_risk
# ═══════════════════════════════════════════════════════════════════════════════


def validate_high_symmetry_saddle_risk(case_dir: Path) -> list[SanityIssue]:
    """WARNING: intercalant at high-symmetry TOP column with no off-center test.

    Detects intercalants placed at (x≈0, y≈0) in crystal coordinates — the
    high-symmetry column site (TOP).  Such sites are often saddle points
    rather than true minima.  If no off-center relaxation test is found in
    the case directory, this rule fires a warning.
    """
    issues: list[SanityIssue] = []
    # Look for evidence of an off-center relax test: directories or files
    # containing "offcenter", "off_center", "displaced", "saddle"
    has_offcenter_test = False
    for f in case_dir.rglob("*"):
        name_lower = f.name.lower()
        if any(kw in name_lower for kw in ("offcenter", "off_center", "displaced", "saddle")):
            has_offcenter_test = True
            break
        try:
            if f.is_file() and any(kw in _read_text(f).lower()
                                   for kw in ("offcenter", "off_center", "displaced site")):
                has_offcenter_test = True
                break
        except OSError:
            continue

    for in_path in _find_rx_inputs(case_dir):
        try:
            qe = parse_qe_input(in_path)
        except Exception:
            continue
        positions = _parse_atomic_positions(qe)
        if not positions:
            continue

        rel = str(in_path.relative_to(case_dir)) if in_path.is_relative_to(case_dir) else str(in_path)

        for elem, x, y, _z in positions:
            if elem not in _INTERCALANTS:
                continue
            if _is_high_symmetry_column(x, y) and not has_offcenter_test:
                issues.append(SanityIssue(
                    id="intercalation.high_symmetry_saddle_risk",
                    severity=Severity.WARNING,
                    message=f"{elem} at high-symmetry TOP site "
                            f"(x={x:.4f}, y={y:.4f}) in {rel} with no off-center "
                            "relax test found",
                    source_file=str(in_path),
                    detail="Intercalants on the high-symmetry column (x≈0, y≈0) may "
                           "sit on a saddle point rather than a true minimum. Run an "
                           "off-center relaxation (displace by ~0.1 Å in x/y) and "
                           "check whether the intercalant returns to the column or "
                           "settles at a lower-symmetry site.",
                ))
    return issues


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 4: intercalation.no_site_comparison
# ═══════════════════════════════════════════════════════════════════════════════


def validate_no_site_comparison(case_dir: Path) -> list[SanityIssue]:
    """WARNING: only one intercalation site found — cannot claim lowest energy.

    Counts distinct intercalation site directories or rx.out files.  If only
    one site was screened, any claim of "lowest energy configuration" is
    unsupported.
    """
    issues: list[SanityIssue] = []
    n_sites = _count_intercalation_sites(case_dir)
    if n_sites <= 1:
        issues.append(SanityIssue(
            id="intercalation.no_site_comparison",
            severity=Severity.WARNING,
            message=f"Only {n_sites} intercalation site found — cannot claim "
                    "'lowest energy configuration'",
            source_file=str(case_dir),
            detail="At least two intercalation sites (e.g. TOP vs HOLLOW_A vs "
                   "HOLLOW_B) must be screened and their relaxed energies compared "
                   "before ranking. A single-site result does not establish the "
                   "global minimum.",
        ))
    return issues


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 5: phonon.imaginary_intercalant_slip
# ═══════════════════════════════════════════════════════════════════════════════


def validate_imaginary_intercalant_slip(case_dir: Path) -> list[SanityIssue]:
    """ERROR: imaginary mode where intercalant contributes >50 % of displacement.

    Parses ``matdyn.modes`` (or dynmat.x output) for imaginary frequencies
    (freq < −10 cm⁻¹).  For each imaginary mode, computes the fraction of
    total displacement magnitude contributed by the intercalant atom.  If
    that fraction exceeds 50 %, the mode is an intercalant slip mode and
    EPC is blocked.
    """
    issues: list[SanityIssue] = []

    # Gather mode files: matdyn.modes first, then dynmat outputs
    mode_files = _find_matdyn_modes(case_dir) + _find_dynmat_outputs(case_dir)
    if not mode_files:
        return issues

    # We need the atomic positions to identify which atom is the intercalant.
    # Look for a matching rx.in or any input with ATOMIC_POSITIONS.
    intercalant_idx: int | None = None
    for in_path in _find_rx_inputs(case_dir):
        try:
            qe = parse_qe_input(in_path)
        except Exception:
            continue
        positions = _parse_atomic_positions(qe)
        intercalant_idx = _intercalant_atom_index(positions)
        if intercalant_idx is not None:
            break

    for mode_path in mode_files:
        modes = _parse_matdyn_modes(mode_path)
        if not modes:
            continue
        rel = str(mode_path.relative_to(case_dir)) if mode_path.is_relative_to(case_dir) else str(mode_path)

        for mode in modes:
            freq_cm = mode["freq_cm"]
            if freq_cm >= _IMAG_FREQ_CM:
                continue  # not imaginary
            disps = mode["displacements"]
            if not disps:
                continue

            # If we know the intercalant index, check its contribution
            if intercalant_idx is not None and intercalant_idx < len(disps):
                int_disp = _displacement_magnitude(disps[intercalant_idx])
                total_disp = sum(_displacement_magnitude(d) for d in disps)
                if total_disp > 0:
                    fraction = int_disp / total_disp
                    if fraction > _INTERCALANT_DISP_FRACTION:
                        issues.append(SanityIssue(
                            id="phonon.imaginary_intercalant_slip",
                            severity=Severity.ERROR,
                            message=f"Imaginary mode ({freq_cm:.1f} cm⁻¹) at "
                                    f"q=({mode['q']}) dominated by intercalant "
                                    f"displacement ({fraction*100:.0f} % > 50 %)",
                            source_file=str(mode_path),
                            detail="An imaginary phonon mode where the intercalant "
                                   "contributes the majority of the displacement "
                                   "indicates the intercalant is not stable at this "
                                   "site — it will slip. EPC is blocked until the "
                                   "intercalant site is stabilised (off-center "
                                   "relaxation or a different site).",
                        ))
            else:
                # No intercalant index identified — still flag imaginary modes
                # as a potential slip risk (lower confidence)
                issues.append(SanityIssue(
                    id="phonon.imaginary_intercalant_slip",
                    severity=Severity.ERROR,
                    message=f"Imaginary mode ({freq_cm:.1f} cm⁻¹) at "
                            f"q=({mode['q']}) — intercalant displacement "
                            "contribution could not be determined",
                    source_file=str(mode_path),
                    detail="An imaginary phonon mode was found but the intercalant "
                           "atom index could not be identified from the input files. "
                           "Treat as a potential intercalant slip until mode-resolved "
                           "analysis confirms the displacement pattern.",
                ))
    return issues


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 6: sc.ph_stability_failed_but_epc_present
# ═══════════════════════════════════════════════════════════════════════════════


def validate_ph_stability_failed_but_epc_present(case_dir: Path) -> list[SanityIssue]:
    """ERROR: PH stability gate failed but EPC outputs are present.

    Scans ``*.freq.gp`` files for non-Gamma imaginary modes (stability gate
    failure).  If any are found *and* EPC outputs (``lambdax.out``,
    ``alpha2F.dat``) exist in the case tree, this is a critical
    inconsistency — EPC should not have been run on an unstable structure.
    """
    issues: list[SanityIssue] = []
    freq_gp_files = _find_freq_gp_files(case_dir)
    if not freq_gp_files:
        return issues

    stability_failed = False
    failed_file: Path | None = None
    for fg in freq_gp_files:
        if _has_non_gamma_imaginary(fg):
            stability_failed = True
            failed_file = fg
            break

    if not stability_failed:
        return issues

    lambdax_files, alpha2f_files = _find_epc_outputs(case_dir)
    if lambdax_files or alpha2f_files:
        epc_names = []
        if lambdax_files:
            epc_names.append(f"lambdax.out ({len(lambdax_files)})")
        if alpha2f_files:
            epc_names.append(f"alpha2F.dat ({len(alpha2f_files)})")
        issues.append(SanityIssue(
            id="sc.ph_stability_failed_but_epc_present",
            severity=Severity.ERROR,
            message="PH stability gate failed (non-Gamma imaginary modes) but "
                    "EPC outputs present: " + ", ".join(epc_names),
            source_file=str(failed_file) if failed_file else str(case_dir),
            detail="The phonon stability gate failed — the structure has imaginary "
                   "modes at non-Gamma q-points and is dynamically unstable. EPC "
                   "(λ, Tc) computed on an unstable structure is physically "
                   "meaningless. Remove the EPC outputs and re-stabilise the "
                   "structure before running EPC again.",
        ))
    return issues


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 7: tc.max_used_as_final
# ═══════════════════════════════════════════════════════════════════════════════


def validate_tc_max_used_as_final(case_dir: Path) -> list[SanityIssue]:
    """WARNING: report uses ``tc_max_K`` instead of ``tc_point_K``.

    Scans report/markdown files for citations of ``tc_max`` (single-grid
    Tc) without a corresponding ``tc_point`` (two-grid overlap).  Recommends
    using the two-grid overlap Tc for the final reported value.
    """
    issues: list[SanityIssue] = []
    report_files = _find_report_files(case_dir)
    if not report_files:
        return issues

    # Patterns that indicate tc_max is being used as the final Tc
    tc_max_patterns = [
        re.compile(r"\btc_max[_K]?\b", re.IGNORECASE),
        re.compile(r"Tc[_\s]*max\b", re.IGNORECASE),
        re.compile(r"tc\s*=\s*tc_max", re.IGNORECASE),
    ]
    tc_point_patterns = [
        re.compile(r"\btc_point[_K]?\b", re.IGNORECASE),
        re.compile(r"Tc[_\s]*Point\b", re.IGNORECASE),
        re.compile(r"two.grid.*overlap", re.IGNORECASE),
    ]

    for report_path in report_files:
        text = _read_text(report_path)
        if not text:
            continue
        mentions_tc_max = any(p.search(text) for p in tc_max_patterns)
        mentions_tc_point = any(p.search(text) for p in tc_point_patterns)
        if mentions_tc_max and not mentions_tc_point:
            rel = str(report_path.relative_to(case_dir)) if report_path.is_relative_to(case_dir) else str(report_path)
            issues.append(SanityIssue(
                id="tc.max_used_as_final",
                severity=Severity.WARNING,
                message=f"Report {rel} cites tc_max_K without tc_point_K — "
                        "single-grid Tc used as final",
                source_file=str(report_path),
                detail="The single-grid tc_max_K is a preliminary estimate. "
                       "For a publishable Tc, run two k/q grids and report the "
                       "overlap Tc_Point. Using tc_max_K as the final value "
                       "overstates the precision of the result.",
            ))
    return issues


# ═══════════════════════════════════════════════════════════════════════════════
# Aggregator
# ═══════════════════════════════════════════════════════════════════════════════


# Ordered list of all intercalation rule functions.
_INTERCALATION_RULES = (
    validate_relax_not_converged,
    validate_short_M_X_bond,
    validate_high_symmetry_saddle_risk,
    validate_no_site_comparison,
    validate_imaginary_intercalant_slip,
    validate_ph_stability_failed_but_epc_present,
    validate_tc_max_used_as_final,
)


def run_intercalation_rules(case_dir: Path | str) -> list[SanityIssue]:
    """Run all intercalation validation rules against a case directory.

    Args:
        case_dir: Path to the case directory to validate.

    Returns:
        Flat list of all :class:`SanityIssue` objects found, in rule order.
    """
    d = Path(case_dir)
    if not d.is_dir():
        return []
    all_issues: list[SanityIssue] = []
    for rule_fn in _INTERCALATION_RULES:
        try:
            all_issues.extend(rule_fn(d))
        except Exception:
            # A single rule failure must not crash the whole pipeline
            continue
    return all_issues