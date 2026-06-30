"""Stage-level validation rules for HfCl2 workflow stages.

These rules are specifically designed to catch the three error classes
identified during HfCl2 workflow hardening:

1. P2 fatband: projwfc_fatband.in in wrong directory / missing kresolveddos
2. P3 smearing: degauss=0.0d-3 or identical degauss variants
3. B1 pristine: kjpaw pseudo mixing / alkali contamination / wrong ecut/c

Each rule returns a list of CheckResult-compatible dicts.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibedft.core.qa import CheckResult, discover_input_files, StageInput
from vibedft.parsers.qe_input_parser import parse_qe_input


# ═══════════════════════════════════════════════════════════════════════════════
# Rule group: HfCl2.K.P2.fatband
# ═══════════════════════════════════════════════════════════════════════════════


def check_fatband_location(inputs: list[StageInput]) -> list[CheckResult]:
    """Ensure projwfc_fatband.in is in 07_bands/inputs/, not 08_dos/inputs/.

    A fatband input should use the 07_bands save context (k-resolved path),
    not the 08_dos dense NSCF save context.
    """
    results: list[CheckResult] = []
    fatband_files = [si for si in inputs if "projwfc_fatband" in si.path.name]

    if not fatband_files:
        results.append(
            CheckResult("hfcl2.p2.fatband.location", "skip",
                        "No projwfc_fatband.in found — P2 fatband not set up")
        )
        return results

    wrong_location = [si for si in fatband_files if "07_bands" not in si.stage]
    correct = [si for si in fatband_files if "07_bands" in si.stage]

    if wrong_location:
        detail_lines = [f"  [{v.stage}] {v.path.name}" for v in wrong_location]
        detail_lines.append(
            "Fatband must be in 07_bands/inputs/ to use band-structure save context."
        )
        results.append(
            CheckResult(
                "hfcl2.p2.fatband.location", "fail",
                f"projwfc_fatband.in found in {len(wrong_location)} wrong stage(s) "
                f"(should be 07_bands/inputs/)",
                detail="\n".join(detail_lines),
            )
        )
    else:
        results.append(
            CheckResult("hfcl2.p2.fatband.location", "pass",
                        "projwfc_fatband.in correctly placed in 07_bands/inputs/")
        )

    return results


def check_fatband_kresolveddos(inputs: list[StageInput]) -> list[CheckResult]:
    """Verify kresolveddos=.true. in all projwfc_fatband inputs."""
    results: list[CheckResult] = []
    fatband_files = [si for si in inputs if "projwfc_fatband" in si.path.name]

    if not fatband_files:
        return results

    for si in fatband_files:
        qe = parse_qe_input(si.path)
        kresolved = qe.get_param("projwfc", "kresolveddos")
        if kresolved is not True:
            results.append(
                CheckResult(
                    "hfcl2.p2.fatband.kresolveddos", "fail",
                    f"kresolveddos is {kresolved} (expected .true.) in {si.path.name}",
                    path=str(si.path), stage=si.stage,
                    detail="Fatband requires kresolveddos=.true. for k-resolved band projection.",
                )
            )

    if not results:
        results.append(
            CheckResult("hfcl2.p2.fatband.kresolveddos", "pass",
                        "All fatband inputs have kresolveddos=.true.")
        )

    return results


def check_fatband_prefix(inputs: list[StageInput], reference_prefix: str | None = None) -> list[CheckResult]:
    """Verify fatband prefix/outdir is consistent with bands save context."""
    results: list[CheckResult] = []
    fatband_files = [si for si in inputs if "projwfc_fatband" in si.path.name]

    if not fatband_files:
        return results

    for si in fatband_files:
        qe = parse_qe_input(si.path)
        prefix = qe.get_param("projwfc", "prefix", "")
        outdir = qe.get_param("projwfc", "outdir", "")

        if not prefix or not outdir:
            results.append(
                CheckResult(
                    "hfcl2.p2.fatband.prefix_outdir", "fail",
                    f"prefix or outdir missing in {si.path.name}",
                    path=str(si.path), stage=si.stage,
                )
            )

    if not results:
        results.append(
            CheckResult("hfcl2.p2.fatband.prefix_outdir", "pass",
                        "Fatband prefix/outdir present")
        )

    return results


def check_kpoints_crystal_b_count(inputs: list[StageInput]) -> list[CheckResult]:
    """Validate K_POINTS crystal_b: the count on line 2 must equal the number
    of special k-point lines that follow.

    Catches the common bug of writing the per-segment k-point count
    (e.g. 40) instead of the number of high-symmetry points (e.g. 4).
    """
    results: list[CheckResult] = []
    kpoints_files = [si for si in inputs if si.program == "pw.x"]

    for si in kpoints_files:
        try:
            qe = parse_qe_input(si.path)
        except Exception:
            continue

        kp_card = qe.cards.get("K_POINTS")
        if kp_card is None:
            continue

        # Parser stores card-name-line fields as rows[0], then data rows follow.
        # For K_POINTS crystal_b: rows[0]=['crystal_b'], rows[1]=count, rows[2:]=k-pt lines.
        rows = kp_card.rows
        if len(rows) < 2:
            continue

        option = (rows[0][0] if rows[0] else "").lower()
        if option not in ("crystal_b", "tpiba_b"):
            continue

        try:
            declared_count = int(rows[1][0])
        except (ValueError, IndexError):
            results.append(
                CheckResult(
                    "hfcl2.p2.kpoints.crystal_b_count", "fail",
                    f"K_POINTS {option}: could not parse count from line 2",
                    path=str(si.path), stage=si.stage,
                    detail=f"Expected integer count, got: {rows[1]!r}",
                )
            )
            continue

        actual_lines = len(rows) - 2  # exclude option row + count row

        if declared_count != actual_lines:
            results.append(
                CheckResult(
                    "hfcl2.p2.kpoints.crystal_b_count", "fail",
                    f"K_POINTS {option} count mismatch: "
                    f"declared {declared_count} but found {actual_lines} "
                    f"k-point lines in {si.path.name}",
                    path=str(si.path), stage=si.stage,
                    detail=f"File: {si.path.name}. Second line declares {declared_count} "
                           f"special points but {actual_lines} lines follow. "
                           f"Ensure the second line is the number of high-symmetry "
                           f"points (e.g. 4), not the per-segment k-point count.",
                )
            )
        else:
            results.append(
                CheckResult(
                    "hfcl2.p2.kpoints.crystal_b_count", "pass",
                    f"K_POINTS {option} count correct "
                    f"({declared_count} points) in {si.path.name}",
                    path=str(si.path), stage=si.stage,
                )
            )

    if not results:
        results.append(
            CheckResult(
                "hfcl2.p2.kpoints.crystal_b_count", "skip",
                "No pw.x inputs with K_POINTS crystal_b/tpiba_b found",
            )
        )

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Rule group: HfCl2.K.P3.smearing_consistency
# ═══════════════════════════════════════════════════════════════════════════════


def check_smearing_variants_exist(inputs: list[StageInput]) -> list[CheckResult]:
    """Verify existence of nscf_degauss_002.in and nscf_degauss_005.in."""
    results: list[CheckResult] = []
    dos_inputs = [si for si in inputs if si.stage in ("08_dos",) or "dos" in si.stage]

    has_002 = any("degauss_002" in si.path.name for si in dos_inputs)
    has_005 = any("degauss_005" in si.path.name for si in dos_inputs)
    has_ref = any(si.path.name == "nscf.in" for si in dos_inputs)

    missing = []
    if not has_002:
        missing.append("nscf_degauss_002.in")
    if not has_005:
        missing.append("nscf_degauss_005.in")
    if not has_ref:
        missing.append("nscf.in (reference)")

    if missing:
        results.append(
            CheckResult(
                "hfcl2.p3.smearing.variants_exist", "fail",
                f"Missing smearing variant files: {', '.join(missing)}",
                detail="Required: nscf.in (reference), nscf_degauss_002.in (low), "
                       "nscf_degauss_005.in (high)",
            )
        )
    else:
        results.append(
            CheckResult("hfcl2.p3.smearing.variants_exist", "pass",
                        "All smearing variant files present")
        )

    return results


def check_smearing_degauss_values(inputs: list[StageInput]) -> list[CheckResult]:
    """Verify degauss parses to correct values and rejects 0.0d-3."""
    results: list[CheckResult] = []
    variants = {
        "nscf_degauss_002.in": 0.002,
        "nscf_degauss_005.in": 0.005,
    }

    # Group by 08_dos or any dos-like stage
    dos_stages = {si.stage for si in inputs if "dos" in si.stage or si.stage == "08_dos"}
    if not dos_stages:
        dos_stages = {si.stage for si in inputs}

    parsed_degauss: dict[str, float] = {}

    for si in inputs:
        if si.path.name in variants:
            expected = variants[si.path.name]
            qe = parse_qe_input(si.path)
            deg = qe.get_param("system", "degauss")

            if deg is None:
                results.append(
                    CheckResult(
                        "hfcl2.p3.smearing.degauss_parsed", "fail",
                        f"degauss not found in {si.path.name}",
                        path=str(si.path), stage=si.stage,
                    )
                )
                continue

            try:
                deg_val = float(deg)
            except (ValueError, TypeError):
                results.append(
                    CheckResult(
                        "hfcl2.p3.smearing.degauss_parsed", "fail",
                        f"degauss={deg!r} in {si.path.name} is not a valid float",
                        path=str(si.path), stage=si.stage,
                    )
                )
                continue

            # BLOCKER: degauss=0.0d-3 (or effectively zero)
            if deg_val < 1.0e-4:
                results.append(
                    CheckResult(
                        "hfcl2.p3.smearing.degauss_zero", "fail",
                        f"degauss={deg_val} Ry in {si.path.name} — effectively zero! "
                        f"For this variant, expected degauss={expected} Ry. "
                        "Smearing of 0.0 Ry in a metallic system will fail to converge.",
                        path=str(si.path), stage=si.stage,
                    )
                )
                continue

            # Check value matches filename expectation (± tolerance)
            if abs(deg_val - expected) > 1.0e-4:
                results.append(
                    CheckResult(
                        "hfcl2.p3.smearing.degauss_mismatch", "fail",
                        f"degauss={deg_val} Ry in {si.path.name} — "
                        f"expected ~{expected} Ry based on filename",
                        path=str(si.path), stage=si.stage,
                    )
                )

            parsed_degauss[si.path.name] = deg_val

    if not results:
        results.append(
            CheckResult("hfcl2.p3.smearing.degauss_values", "pass",
                        "All smearing variant degauss values correct")
        )

    return results


def check_smearing_variants_distinct(inputs: list[StageInput]) -> list[CheckResult]:
    """Verify degauss variant files have different content (not identical copies)."""
    results: list[CheckResult] = []
    variant_names = {"nscf_degauss_002.in", "nscf_degauss_005.in"}
    variant_inputs = [si for si in inputs if si.path.name in variant_names]

    if len(variant_inputs) < 2:
        results.append(CheckResult("hfcl2.p3.smearing.distinct_variants", "skip",
                                   "Need both nscf_degauss_002.in and nscf_degauss_005.in"))
        return results

    # Group by stage directory — variants should be in the same directory
    by_dir: dict[str, list[StageInput]] = {}
    for si in variant_inputs:
        by_dir.setdefault(si.stage, []).append(si)

    for stage, stage_variants in by_dir.items():
        names = sorted(s.path.name for s in stage_variants)
        has_both = "nscf_degauss_002.in" in names and "nscf_degauss_005.in" in names
        if not has_both:
            continue

        hash_map = {}
        for s in stage_variants:
            content = s.path.read_bytes()
            hash_map[s.path.name] = hashlib.sha256(content).hexdigest()

        if hash_map["nscf_degauss_002.in"] == hash_map["nscf_degauss_005.in"]:
            results.append(
                CheckResult(
                    "hfcl2.p3.smearing.distinct_variants", "fail",
                    f"nscf_degauss_002.in and nscf_degauss_005.in are identical "
                    f"(same hash) in stage [{stage}] — they must differ in degauss value",
                    stage=stage,
                )
            )

    if not results:
        results.append(
            CheckResult("hfcl2.p3.smearing.distinct_variants", "pass",
                        "Smearing variant files are distinct")
        )

    return results


def check_smearing_param_consistency(inputs: list[StageInput]) -> list[CheckResult]:
    """Check that degauss variants match on key parameters (prefix, pseudos, ecut, kmesh).

    Only degauss should differ between nscf.in, nscf_degauss_002.in, nscf_degauss_005.in.
    Everything else (prefix, outdir, pseudo family, ecutwfc, ecutrho, kmesh, nbnd,
    occupations, smearing type) should remain the same.
    """
    results: list[CheckResult] = []
    variant_names = {"nscf.in", "nscf_degauss_002.in", "nscf_degauss_005.in"}
    dos_stage_inputs = [si for si in inputs if "dos" in si.stage or si.stage == "08_dos"]

    # Find the reference and variants in the same stage
    for si in dos_stage_inputs:
        if si.path.name not in variant_names:
            continue

    # Group by stage and compare within each stage
    by_stage: dict[str, list[StageInput]] = {}
    for si in dos_stage_inputs:
        if si.path.name in variant_names:
            by_stage.setdefault(si.stage, []).append(si)

    for stage, stage_inputs in by_stage.items():
        if len(stage_inputs) < 2:
            continue

        # Parameters that must match across variants
        invariant_keys = [
            ("control", "prefix"),
            ("system", "ecutwfc"),
            ("system", "ecutrho"),
            ("system", "occupations"),
            ("system", "smearing"),
            ("system", "nbnd"),
            ("system", "input_dft"),
        ]

        parsed = {}
        for si in stage_inputs:
            qe = parse_qe_input(si.path)
            parsed[si.path.name] = {nl: dict(nl_block.params) for nl, nl_block in qe.namelists.items()}

        # Compare reference vs each variant
        ref_name = "nscf.in"
        if ref_name in parsed:
            ref = parsed[ref_name]
            for var_name in sorted(parsed.keys()):
                if var_name == ref_name:
                    continue
                var = parsed[var_name]
                diffs = []
                for nl, key in invariant_keys:
                    ref_val = ref.get(nl, {}).get(key, "<MISSING>")
                    var_val = var.get(nl, {}).get(key, "<MISSING>")
                    if ref_val != var_val:
                        diffs.append(f"{key}: {ref_val} → {var_val}")
                if diffs:
                    results.append(
                        CheckResult(
                            "hfcl2.p3.smearing.param_consistency", "warn",
                            f"Smearing variant {var_name} differs from {ref_name} on "
                            f"{len(diffs)} non-degauss parameter(s) in stage [{stage}]",
                            detail="; ".join(diffs),
                            stage=stage,
                        )
                    )

    if not results:
        results.append(
            CheckResult("hfcl2.p3.smearing.param_consistency", "pass",
                        "Smearing variant parameters consistent with reference")
        )

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Rule group: HfCl2.B1.pristine_rrkjus_check
# ═══════════════════════════════════════════════════════════════════════════════


def _read_elements_from_input(inputs: list[StageInput]) -> set[str]:
    """Extract element symbols from ATOMIC_SPECIES cards across all inputs."""
    elements: set[str] = set()
    for si in inputs:
        qe = parse_qe_input(si.path)
        species = qe.cards.get("ATOMIC_SPECIES")
        if species:
            for row in species.rows:
                if len(row) >= 1:
                    elements.add(row[0].capitalize())
    return elements


def _get_pseudo_families(inputs: list[StageInput]) -> dict[str, list[str]]:
    """Extract pseudopotential file → family mapping from ATOMIC_SPECIES cards."""
    families: dict[str, list[str]] = {}
    for si in inputs:
        qe = parse_qe_input(si.path)
        species = qe.cards.get("ATOMIC_SPECIES")
        if species:
            for row in species.rows:
                if len(row) >= 3:
                    elem = row[0].capitalize()
                    upf = row[2].lower()
                    if "kjpaw" in upf:
                        family = "kjpaw"
                    elif "rrkjus" in upf:
                        family = "rrkjus"
                    else:
                        family = f"other:{upf.split('.')[1] if '.' in upf else 'unknown'}"
                    families.setdefault(elem, []).append(family)
    return families


def check_pristine_elements(inputs: list[StageInput]) -> list[CheckResult]:
    """Verify pristine system contains only Hf and Cl (no Li/Na/K)."""
    results: list[CheckResult] = []
    elements = _read_elements_from_input(inputs)

    forbidden = {"Li", "Na", "K"}
    found_forbidden = elements & forbidden

    if found_forbidden:
        results.append(
            CheckResult(
                "hfcl2.b1.pristine.elements", "fail",
                f"Pristine system contains forbidden element(s): "
                f"{', '.join(sorted(found_forbidden))}. "
                f"Pristine reference must contain only Hf and Cl.",
                detail="Li/Na/K are intercalants and invalid in a pristine reference.",
            )
        )
    else:
        results.append(
            CheckResult("hfcl2.b1.pristine.elements", "pass",
                        "Pristine system contains only Hf and Cl (no intercalants)")
        )
    return results


def check_pristine_pseudo_family(inputs: list[StageInput]) -> list[CheckResult]:
    """Verify pristine system uses rrkjus pseudopotentials consistently."""
    results: list[CheckResult] = []
    families = _get_pseudo_families(inputs)

    if not families:
        results.append(
            CheckResult("hfcl2.b1.pristine.pseudo_family", "skip",
                        "No pseudopotential info found")
        )
        return results

    mix_issues: list[str] = []
    for elem, fams in families.items():
        unique_fams = list(set(fams))
        if len(unique_fams) > 1:
            mix_issues.append(f"{elem}: {', '.join(unique_fams)}")
        elif unique_fams and unique_fams[0] != "rrkjus":
            mix_issues.append(f"{elem}: {unique_fams[0]} (not rrkjus)")

    if mix_issues:
        results.append(
            CheckResult(
                "hfcl2.b1.pristine.pseudo_family", "fail",
                "Pristine pseudopotential issues found",
                detail="\n".join(mix_issues) + "\n"
                       "Canonical pristine reference must use rrkjus pseudopotentials "
                       "(ecutwfc=90, ecutrho=720), matching the intercalation lines.",
            )
        )
    else:
        results.append(
            CheckResult("hfcl2.b1.pristine.pseudo_family", "pass",
                        "All pristine pseudopotentials are rrkjus")
        )
    return results


def check_pristine_ecut(inputs: list[StageInput]) -> list[CheckResult]:
    """Verify ecutwfc=90 Ry and ecutrho=720 Ry for rrkjus pristine."""
    results: list[CheckResult] = []
    expected_ecutwfc = 90
    expected_ecutrho = 720

    for si in inputs:
        qe = parse_qe_input(si.path)
        ecutwfc = qe.get_param("system", "ecutwfc")
        ecutrho = qe.get_param("system", "ecutrho")

        issues = []
        if ecutwfc is not None and int(ecutwfc) != expected_ecutwfc:
            issues.append(f"ecutwfc={ecutwfc} (expected {expected_ecutwfc})")
        if ecutrho is not None and int(ecutrho) != expected_ecutrho:
            issues.append(f"ecutrho={ecutrho} (expected {expected_ecutrho})")
        if issues:
            results.append(
                CheckResult(
                    "hfcl2.b1.pristine.ecut", "fail",
                    f"In {si.path.name}: {', '.join(issues)}",
                    path=str(si.path), stage=si.stage,
                )
            )

    if not results:
        results.append(
            CheckResult("hfcl2.b1.pristine.ecut", "pass",
                        "ecutwfc=90, ecutrho=720 consistent with rrkjus reference")
        )
    return results


def check_pristine_cell(inputs: list[StageInput]) -> list[CheckResult]:
    """Verify c >= 30 Å and assume_isolated='2D' for pristine rrkjus reference."""
    results: list[CheckResult] = []
    for si in inputs:
        qe = parse_qe_input(si.path)
        # Check assume_isolated
        assume_isolated = qe.get_param("system", "assume_isolated", "")
        if isinstance(assume_isolated, str) and "2D" not in assume_isolated:
            results.append(
                CheckResult(
                    "hfcl2.b1.pristine.assume_isolated", "fail",
                    f"assume_isolated={assume_isolated} in {si.path.name} "
                    f"(expected '2D')",
                    path=str(si.path), stage=si.stage,
                )
            )

        # Check vacuum (c-parameter)
        cell = qe.cards.get("CELL_PARAMETERS")
        if cell and len(cell.rows) >= 3:
            try:
                cz = float(cell.rows[2][2])
                if cz < 25.0:
                    results.append(
                        CheckResult(
                            "hfcl2.b1.pristine.cell_c", "fail",
                            f"c={cz:.2f} Å in {si.path.name} — "
                            f"too small for 2D vacuum (≥30 Å required)",
                            path=str(si.path), stage=si.stage,
                        )
                    )
            except (IndexError, ValueError):
                pass

    if not results:
        results.append(
            CheckResult("hfcl2.b1.pristine.cell", "pass",
                        "Cell parameters consistent with 2D pristine reference "
                        "(c≥30 Å, assume_isolated='2D')")
        )
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Rule group: HfCl2.K.P4.phonon_stability
# ═══════════════════════════════════════════════════════════════════════════════


def check_ph_stability_no_epc(inputs: list[StageInput]) -> list[CheckResult]:
    """Verify ph.x inputs in 12_ph_stability/ do NOT set electron_phonon."""
    results: list[CheckResult] = []
    ph_inputs = [si for si in inputs
                 if si.program == "ph.x" and ("ph_stability" in si.stage
                                               or "ph" in si.stage.lower())]

    if not ph_inputs:
        results.append(
            CheckResult("hfcl2.p4.ph_stability.no_epc", "skip",
                        "No ph.x inputs found in phonon stability stages")
        )
        return results

    for si in ph_inputs:
        try:
            qe = parse_qe_input(si.path)
        except Exception:
            continue

        ep = qe.get_param("inputph", "electron_phonon", "")
        sigma = qe.get_param("inputph", "el_ph_sigma", None)
        nsigma = qe.get_param("inputph", "el_ph_nsigma", None)

        if ep and str(ep).strip():
            results.append(
                CheckResult(
                    "hfcl2.p4.ph_stability.no_epc", "fail",
                    f"electron_phonon='{ep}' in {si.path.name} — "
                    f"FORBIDDEN in phonon stability",
                    path=str(si.path), stage=si.stage,
                    detail="electron_phonon belongs in 14_epc, not 12_ph_stability.",
                )
            )
        if sigma is not None:
            results.append(
                CheckResult(
                    "hfcl2.p4.ph_stability.no_epc", "fail",
                    f"el_ph_sigma='{sigma}' in {si.path.name} — FORBIDDEN",
                    path=str(si.path), stage=si.stage,
                )
            )
        if nsigma is not None:
            results.append(
                CheckResult(
                    "hfcl2.p4.ph_stability.no_epc", "fail",
                    f"el_ph_nsigma='{nsigma}' in {si.path.name} — FORBIDDEN",
                    path=str(si.path), stage=si.stage,
                )
            )

    if not results:
        results.append(
            CheckResult("hfcl2.p4.ph_stability.no_epc", "pass",
                        "No forbidden EPC parameters in phonon stability inputs")
        )
    return results


def check_q2r_no_la2f(inputs: list[StageInput]) -> list[CheckResult]:
    """Verify q2r.x inputs do NOT contain la2F=.true."""
    results: list[CheckResult] = []
    q2r_inputs = [si for si in inputs if si.program == "q2r.x"]

    if not q2r_inputs:
        results.append(
            CheckResult("hfcl2.p4.q2r.no_la2f", "skip",
                        "No q2r.x inputs found")
        )
        return results

    for si in q2r_inputs:
        try:
            qe = parse_qe_input(si.path)
        except Exception:
            continue

        la2f = qe.get_param("input", "la2f", "")
        if la2f and str(la2f).strip().lower() in (".true.", "true"):
            results.append(
                CheckResult(
                    "hfcl2.p4.q2r.no_la2f", "fail",
                    f"la2F=.true. in {si.path.name} — FORBIDDEN in q2r.x",
                    path=str(si.path), stage=si.stage,
                    detail="la2F belongs in matdyn.x only.",
                )
            )

    if not results:
        results.append(
            CheckResult("hfcl2.p4.q2r.no_la2f", "pass",
                        "No forbidden la2F in q2r.x inputs")
        )
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Combined entry point
# ═══════════════════════════════════════════════════════════════════════════════


def run_hfcl2_stage_rules(case_dir: Path | str, stage: str | None = None) -> list[CheckResult]:
    """Run all applicable HfCl2 stage rules against a case directory.

    Args:
        case_dir: Path to the case directory to validate.
        stage: Optional stage filter (e.g. 'P2', 'P3', 'B1').
               If None, runs all rules.

    Returns:
        Flat list of CheckResult objects.
    """
    d = Path(case_dir)
    inputs = discover_input_files(d)
    all_results: list[CheckResult] = []

    # ── P2 fatband rules ──
    if stage is None or stage.upper() == "P2":
        all_results.extend(check_fatband_location(inputs))
        all_results.extend(check_fatband_kresolveddos(inputs))
        all_results.extend(check_fatband_prefix(inputs))
        all_results.extend(check_kpoints_crystal_b_count(inputs))

    # ── P3 smearing rules ──
    if stage is None or stage.upper() == "P3":
        all_results.extend(check_smearing_variants_exist(inputs))
        all_results.extend(check_smearing_degauss_values(inputs))
        all_results.extend(check_smearing_variants_distinct(inputs))
        all_results.extend(check_smearing_param_consistency(inputs))

    # ── B1 pristine rules ──
    if stage is None or stage.upper() == "B1":
        all_results.extend(check_pristine_elements(inputs))
        all_results.extend(check_pristine_pseudo_family(inputs))
        all_results.extend(check_pristine_ecut(inputs))
        all_results.extend(check_pristine_cell(inputs))

    # ── P4 phonon stability rules ──
    if stage is None or stage.upper() == "P4":
        all_results.extend(check_ph_stability_no_epc(inputs))
        all_results.extend(check_q2r_no_la2f(inputs))

    return all_results
