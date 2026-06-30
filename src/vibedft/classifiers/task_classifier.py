"""Classify QE calculation purpose from parsed input or output content.

Priority order (content-based, never filename-based):
  lambda.x > matdyn.x > q2r.x > ph.x > pw.x

Each classifier returns ``(TaskRecord, list[SanityIssue])``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from vibedft.models.inspection import (
    EvidenceRef,
    FileRecord,
    InspectionResult,
    QEInput,
    QEProgram,
    SanityIssue,
    Severity,
    TaskRecord,
    TaskType,
)
from vibedft.parsers.qe_input_parser import parse_qe_input


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════


def inspect_files(filepaths: list[Path | str]) -> InspectionResult:
    """Inspect one or more QE files and return a full :class:`InspectionResult`.

    This is the main entry point for ``vibedft inspect``.
    """
    result = InspectionResult()
    paths = [Path(p) for p in filepaths]

    for p in paths:
        file_rec, tasks, issues = _inspect_one_file(p)
        result.files.append(file_rec)
        result.tasks.extend(tasks)
        result.issues.extend(issues)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Per-file inspector
# ═══════════════════════════════════════════════════════════════════════════════


def _inspect_one_file(path: Path) -> tuple[FileRecord, list[TaskRecord], list[SanityIssue]]:
    """Inspect a single file. Returns (FileRecord, tasks, issues)."""
    file_rec = FileRecord(path=str(path))
    tasks: list[TaskRecord] = []
    issues: list[SanityIssue] = []

    if not path.is_file():
        file_rec.parse_status = "failed"
        file_rec.parse_errors = [f"File not found: {path}"]
        issues.append(SanityIssue(
            id="file.not_found", severity=Severity.ERROR,
            message=f"File not found: {path}", source_file=str(path),
        ))
        return file_rec, tasks, issues

    # Data files — recognise but don't parse as QE input/output
    suffix = path.suffix.lower()
    stem = path.name.lower()

    # Data file patterns — by suffix, filename prefix, or numeric dyn suffix
    is_data = False
    data_label = "data"

    # Numeric dyn files: .dyn0, .dyn1, ... .dyn10
    if len(suffix) >= 4 and suffix.startswith(".dyn") and suffix[4:].isdigit():
        is_data = True
        data_label = "dynamical matrix"
    elif suffix == ".dyn":
        is_data = True
        data_label = "dynamical matrix"

    # Suffix-based
    _data_suffixes = {
        ".dos": "DOS data", ".gnu": "bands (gnuplot)", ".gp": "phonon dispersion",
        ".fc": "force constants", ".bxsf": "Fermi surface", ".phdos": "phonon DOS",
        ".elf": "ELF", ".elf2d": "ELF 2D", ".modes": "phonon modes",
        ".lines": "q-point weights", ".err": "Slurm stderr",
        ".slurm": "Slurm script",
    }
    if not is_data:
        for sfx, label in _data_suffixes.items():
            if suffix == sfx or stem.endswith(sfx):
                is_data = True
                data_label = label
                break

    # Filename-prefix-based
    _data_prefixes = {
        "alpha2f": "α²F data", "a2f": "α²F data", "lambda.dat": "λ scan",
        "gam.lines": "q-point weights", "elph.inp_lambda": "EPC matrix elements",
        "elph.gamma": "EPC gamma", "a2fq2r": "q-resolved α²F",
        "a2fmatdyn": "matdyn α²F", "matdyn.dos": "phonon DOS",
        "matdyn.modes": "phonon modes", "acf.dat": "Bader ACF",
        "avg.dat": "planar average",
    }
    if not is_data:
        for prefix, label in _data_prefixes.items():
            if stem.startswith(prefix):
                is_data = True
                data_label = label
                break

    # Generic .dat files (but NOT .out or .in renamed)
    if not is_data and suffix == ".dat" and stem not in ("bands.dat",):
        is_data = True
        data_label = "data"

    if is_data:
        file_rec.type = "data"
        file_rec.parse_status = "ok"
        file_rec.summary = data_label
        return file_rec, tasks, issues

    if is_data:
        return file_rec, tasks, issues

    if suffix == ".in" or suffix == ".inp":
        file_rec.type = "input"
        file_rec, tasks, issues = _inspect_input(path, file_rec)
    elif suffix == ".out" or suffix == ".output":
        file_rec.type = "output"
        file_rec, tasks, issues = _inspect_output(path, file_rec)
    # EPW files (.epw, .epwout)
    elif "epw" in path.name.lower() and (suffix in (".in", ".out", ".epw", ".epwout")):
        file_rec.type = "input" if suffix == ".in" else "output"
        file_rec, tasks, issues = _inspect_epw_file(path, file_rec)
    else:
        # Try both
        file_rec.type = "unknown"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            file_rec.parse_status = "failed"
            file_rec.parse_errors = ["Cannot read file"]
            return file_rec, tasks, issues

        if "&" in text[:2000] and "/" in text[:2000]:
            file_rec.type = "input"
            file_rec, tasks, issues = _inspect_input(path, file_rec)
        elif "Program " in text[:2000] or "JOB DONE" in text[-500:]:
            file_rec.type = "output"
            file_rec, tasks, issues = _inspect_output(path, file_rec)
        else:
            file_rec.parse_status = "failed"
            file_rec.parse_errors = ["Cannot determine file type"]
            issues.append(SanityIssue(
                id="file.unknown_type", severity=Severity.ERROR,
                message="Cannot determine whether this is an input or output file",
                source_file=str(path),
            ))

    return file_rec, tasks, issues


# ═══════════════════════════════════════════════════════════════════════════════
# Input inspection
# ═══════════════════════════════════════════════════════════════════════════════


def _inspect_epw_file(
    path: Path, file_rec: FileRecord,
) -> tuple[FileRecord, list[TaskRecord], list[SanityIssue]]:
    """Inspect an EPW input or output file."""
    tasks: list[TaskRecord] = []
    issues: list[SanityIssue] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        file_rec.parse_status = "failed"
        return file_rec, tasks, issues

    from vibedft.models.inspection import QEProgram
    file_rec.program = QEProgram.UNKNOWN  # EPW isn't a standard QE program
    file_rec.parse_status = "ok"

    if "EPW" in text or "Wannier" in text or "electron-phonon" in text.lower():
        file_rec.summary = "EPW calculation"
        tasks.append(TaskRecord(
            program=QEProgram.UNKNOWN, task_type=TaskType.LAMBDA_TC,
            source_file=str(path), confidence="medium",
        ))

    return file_rec, tasks, issues


def _inspect_input(
    path: Path,
    file_rec: FileRecord,
) -> tuple[FileRecord, list[TaskRecord], list[SanityIssue]]:
    """Inspect a QE input (.in) file."""
    qe_input = parse_qe_input(path)
    tasks: list[TaskRecord] = []
    issues: list[SanityIssue] = []

    if qe_input.parse_errors:
        file_rec.parse_status = "partial" if qe_input.program != QEProgram.UNKNOWN else "failed"
        file_rec.parse_errors = qe_input.parse_errors
        for err in qe_input.parse_errors:
            issues.append(SanityIssue(
                id="parse.error", severity=Severity.ERROR,
                message=err, source_file=str(path),
            ))
    else:
        file_rec.parse_status = "ok"

    file_rec.program = qe_input.program
    file_rec.summary = _make_input_summary(qe_input)

    # Classify task
    task = _classify_from_input(qe_input)
    task.source_file = str(path)
    tasks.append(task)

    # Run basic sanity checks
    sanity = _sanity_check_input(qe_input)
    issues.extend(sanity)

    return file_rec, tasks, issues


def _classify_from_input(qe_input: QEInput) -> TaskRecord:
    """Classify computation purpose from parsed QE input.

    Priority: ph.x (epc) > ph.x (stability) > q2r.x > matdyn.x > pw.x
    """
    prog = qe_input.program
    params: dict[str, Any] = {}

    # ── ph.x ──
    if prog == QEProgram.PH:
        elph = qe_input.get_param("inputph", "electron_phonon", "")
        ldisp = qe_input.get_param("inputph", "ldisp", False)
        params = {
            "prefix": qe_input.get_param("inputph", "prefix", ""),
            "outdir": qe_input.get_param("inputph", "outdir", ""),
            "fildyn": qe_input.get_param("inputph", "fildyn", ""),
            "nq1": qe_input.get_param("inputph", "nq1", None),
            "nq2": qe_input.get_param("inputph", "nq2", None),
            "nq3": qe_input.get_param("inputph", "nq3", None),
            "ldisp": ldisp,
            "electron_phonon": elph,
            "tr2_ph": qe_input.get_param("inputph", "tr2_ph", None),
        }
        if elph and str(elph).strip():
            return TaskRecord(program=prog, task_type=TaskType.PH_EPC,
                              source_file=qe_input.source_path,
                              key_params=params, confidence="high")
        return TaskRecord(program=prog, task_type=TaskType.PH_STABILITY,
                          source_file=qe_input.source_path,
                          key_params=params, confidence="high")

    # ── q2r.x ──
    if prog == QEProgram.Q2R:
        inp = qe_input.namelists.get("input")
        if inp:
            params = dict(inp.params)
        return TaskRecord(program=prog, task_type=TaskType.Q2R,
                          source_file=qe_input.source_path,
                          key_params=params, confidence="high")

    # ── lambda.x ──
    if prog == QEProgram.LAMBDA:
        inp = qe_input.namelists.get("input")
        if inp:
            params = dict(inp.params)
        return TaskRecord(program=QEProgram.LAMBDA, task_type=TaskType.LAMBDA_TC,
                          source_file=qe_input.source_path,
                          key_params=params, confidence="high")

    # ── matdyn.x ──
    if prog == QEProgram.MATDYN:
        inp = qe_input.namelists.get("input")
        if inp:
            params = dict(inp.params)
        has_dos = params.get("dos", False)
        return TaskRecord(
            program=prog,
            task_type=TaskType.MATDYN_DOS if has_dos else TaskType.MATDYN_DISP,
            source_file=qe_input.source_path,
            key_params=params, confidence="high",
        )

    # ── lambda.x (free-format, no namelists) ──
    if prog == QEProgram.UNKNOWN and qe_input.raw_text.strip():
        # Try to detect lambda.x from content: mustar + emax + degauss values
        if _looks_like_lambda_input(qe_input.raw_text):
            return TaskRecord(program=QEProgram.LAMBDA, task_type=TaskType.LAMBDA_TC,
                              source_file=qe_input.source_path,
                              key_params=_extract_lambda_params(qe_input.raw_text),
                              confidence="medium")

    # ── dos.x ──
    if prog == QEProgram.DOS:
        params = {}
        inp = qe_input.namelists.get("dos") or qe_input.namelists.get("inputpp") or qe_input.namelists.get("input")
        if inp:
            params = dict(inp.params)
        return TaskRecord(program=QEProgram.DOS, task_type=TaskType.UNKNOWN,
                          source_file=qe_input.source_path,
                          key_params=params, confidence="high")

    # ── bands.x ──
    if prog == QEProgram.BANDS:
        params = {}
        inp = qe_input.namelists.get("bands") or qe_input.namelists.get("inputpp")
        if inp:
            params = dict(inp.params)
        return TaskRecord(program=QEProgram.BANDS, task_type=TaskType.UNKNOWN,
                          source_file=qe_input.source_path,
                          key_params=params, confidence="high")

    # ── projwfc.x ──
    if prog == QEProgram.PROJWFC:
        params = {}
        inp = qe_input.namelists.get("projwfc") or qe_input.namelists.get("inputpp")
        if inp:
            params = dict(inp.params)
        return TaskRecord(program=QEProgram.PROJWFC, task_type=TaskType.UNKNOWN,
                          source_file=qe_input.source_path,
                          key_params=params, confidence="high")

    # ── pp.x (post-processing: charge/potential plotter) ──
    if prog == QEProgram.PP:
        params = {}
        inp = qe_input.namelists.get("inputpp")
        if inp:
            params = dict(inp.params)
        return TaskRecord(program=QEProgram.PP, task_type=TaskType.PP_RHO,
                          source_file=qe_input.source_path,
                          key_params=params, confidence="high")

    # ── average.x (planar/spherical average of charge/potential) ──
    # average.x shares &INPUTPP with pp.x; _identify_program currently
    # routes shared &INPUTPP to pp.x, so this branch is only reached when
    # a future enhancement disambiguates average.x inputs.
    if prog == QEProgram.AVERAGE:
        params = {}
        inp = qe_input.namelists.get("inputpp")
        if inp:
            params = dict(inp.params)
        return TaskRecord(program=QEProgram.AVERAGE,
                          task_type=TaskType.PLANAR_AVERAGE,
                          source_file=qe_input.source_path,
                          key_params=params, confidence="high")

    # ── dynmat.x (dynamical matrix diagonalization) ──
    if prog == QEProgram.DYNMAT:
        params = {}
        inp = qe_input.namelists.get("input")
        if inp:
            params = dict(inp.params)
        return TaskRecord(program=QEProgram.DYNMAT, task_type=TaskType.DYNMAT,
                          source_file=qe_input.source_path,
                          key_params=params, confidence="high")

    # ── pw.x ──
    if prog == QEProgram.PW or qe_input.namelists.get("control"):
        ctrl = qe_input.namelists.get("control")
        calc = ctrl.params.get("calculation", "scf") if ctrl else "scf"
        params = {
            "calculation": calc,
            "prefix": qe_input.get_param("control", "prefix", ""),
            "outdir": qe_input.get_param("control", "outdir", ""),
            "pseudo_dir": qe_input.get_param("control", "pseudo_dir", ""),
        }
        task_map = {
            "scf": TaskType.SCF,
            "nscf": TaskType.NSCF,
            "relax": TaskType.RELAX,
            "vc-relax": TaskType.VC_RELAX,
            "bands": TaskType.BANDS,
            "md": TaskType.AIMD,
        }
        task_type = task_map.get(str(calc).lower(), TaskType.UNKNOWN)
        return TaskRecord(program=QEProgram.PW, task_type=task_type,
                          source_file=qe_input.source_path,
                          key_params=params, confidence="high")

    # ── Fallback: try raw text heuristics ──
    return _classify_from_raw_text(qe_input)


def _classify_from_raw_text(qe_input: QEInput) -> TaskRecord:
    """Last-resort classification from raw text content."""
    text = qe_input.raw_text or ""

    if _looks_like_lambda_input(text):
        return TaskRecord(program=QEProgram.LAMBDA, task_type=TaskType.LAMBDA_TC,
                          source_file=qe_input.source_path,
                          key_params=_extract_lambda_params(text),
                          confidence="low")

    return TaskRecord(program=QEProgram.UNKNOWN, task_type=TaskType.UNKNOWN,
                      source_file=qe_input.source_path, confidence="low")


# ═══════════════════════════════════════════════════════════════════════════════
# Basic sanity checks (input)
# ═══════════════════════════════════════════════════════════════════════════════


def _sanity_check_input(qe_input: QEInput) -> list[SanityIssue]:
    """Run basic sanity checks on a parsed QE input."""
    issues: list[SanityIssue] = []
    src = qe_input.source_path
    prog = qe_input.program

    # ── Parseability ──
    if qe_input.parse_errors:
        issues.append(SanityIssue(
            id="parse.failed", severity=Severity.ERROR,
            message=f"Parse errors: {'; '.join(qe_input.parse_errors[:3])}",
            source_file=src,
        ))
        return issues

    # ── Program identified ──
    if prog == QEProgram.UNKNOWN:
        issues.append(SanityIssue(
            id="program.unknown", severity=Severity.WARNING,
            message="Could not identify QE program from namelists", source_file=src,
        ))
        return issues

    issues.append(SanityIssue(
        id="program.identified", severity=Severity.INFO,
        message=f"Identified program: {prog.value}", source_file=src,
    ))

    # ── pw.x checks ──
    if prog == QEProgram.PW:
        _check_pw_input(qe_input, src, issues)

    # ── ph.x checks ──
    if prog == QEProgram.PH:
        _check_ph_input(qe_input, src, issues)

    # ── q2r.x checks ──
    if prog == QEProgram.Q2R:
        _check_q2r_input(qe_input, src, issues)

    # ── matdyn.x checks ──
    if prog == QEProgram.MATDYN:
        _check_matdyn_input(qe_input, src, issues)

    # ── lambda.x checks ──
    if prog == QEProgram.LAMBDA:
        _check_lambda_input(qe_input, src, issues)

    # ── Essential cards ──
    _check_essential_cards(qe_input, src, issues)

    return issues


def _check_pw_input(qe_input: QEInput, src: str, issues: list[SanityIssue]) -> None:
    """Sanity checks specific to pw.x inputs."""
    calc = qe_input.get_param("control", "calculation", "")
    prefix = qe_input.get_param("control", "prefix", "")
    outdir = qe_input.get_param("control", "outdir", "")
    pseudo_dir = qe_input.get_param("control", "pseudo_dir", "")

    if not calc:
        issues.append(SanityIssue(
            id="pw.calculation.missing", severity=Severity.ERROR,
            message="&CONTROL: calculation not specified", source_file=src,
        ))
    elif str(calc).lower() not in ("scf", "nscf", "relax", "vc-relax", "bands", "md", "vc-md"):
        issues.append(SanityIssue(
            id="pw.calculation.invalid", severity=Severity.WARNING,
            message=f"Unusual calculation type: '{calc}'", source_file=src,
            detail=f"Expected one of: scf, nscf, relax, vc-relax, bands",
        ))

    if not prefix:
        issues.append(SanityIssue(
            id="pw.prefix.missing", severity=Severity.ERROR,
            message="&CONTROL: prefix is required", source_file=src,
        ))

    if not outdir:
        issues.append(SanityIssue(
            id="pw.outdir.missing", severity=Severity.WARNING,
            message="&CONTROL: outdir not specified (defaults to './')", source_file=src,
        ))

    if not pseudo_dir:
        issues.append(SanityIssue(
            id="pw.pseudo_dir.missing", severity=Severity.ERROR,
            message="&CONTROL: pseudo_dir is required", source_file=src,
        ))


def _check_ph_input(qe_input: QEInput, src: str, issues: list[SanityIssue]) -> None:
    """Sanity checks specific to ph.x inputs."""
    prefix = qe_input.get_param("inputph", "prefix", "")
    outdir = qe_input.get_param("inputph", "outdir", "")
    fildyn = qe_input.get_param("inputph", "fildyn", "")
    ldisp = qe_input.get_param("inputph", "ldisp", None)
    nq3 = qe_input.get_param("inputph", "nq3", None)
    elph = qe_input.get_param("inputph", "electron_phonon", "")

    if not prefix:
        issues.append(SanityIssue(
            id="ph.prefix.missing", severity=Severity.ERROR,
            message="&INPUTPH: prefix is required (must match scf)", source_file=src,
        ))
    if not outdir:
        issues.append(SanityIssue(
            id="ph.outdir.missing", severity=Severity.ERROR,
            message="&INPUTPH: outdir is required", source_file=src,
        ))
    if not fildyn:
        issues.append(SanityIssue(
            id="ph.fildyn.missing", severity=Severity.WARNING,
            message="&INPUTPH: fildyn not specified (default: 'dyn')", source_file=src,
        ))
    if ldisp is False:
        issues.append(SanityIssue(
            id="ph.ldisp.disabled", severity=Severity.INFO,
            message="ldisp=.false. — single-q phonon, not a full dispersion", source_file=src,
        ))
    if nq3 is not None and nq3 != 1:
        issues.append(SanityIssue(
            id="ph.nq3.not_one", severity=Severity.WARNING,
            message=f"nq3={nq3} — for 2D materials, nq3 should be 1", source_file=src,
        ))
    if elph and str(elph).strip():
        issues.append(SanityIssue(
            id="ph.epc.enabled", severity=Severity.INFO,
            message=f"electron_phonon='{elph}' — EPC calculation enabled", source_file=src,
        ))


def _check_q2r_input(qe_input: QEInput, src: str, issues: list[SanityIssue]) -> None:
    """Sanity checks specific to q2r.x inputs."""
    inp = qe_input.namelists.get("input")
    if inp is None:
        return
    fildyn = inp.params.get("fildyn", "")
    flfrc = inp.params.get("flfrc", "")
    la2f = inp.params.get("la2f", None)

    if not fildyn:
        issues.append(SanityIssue(
            id="q2r.fildyn.missing", severity=Severity.ERROR,
            message="&INPUT: fildyn is required for q2r.x", source_file=src,
        ))
    if not flfrc:
        issues.append(SanityIssue(
            id="q2r.flfrc.missing", severity=Severity.ERROR,
            message="&INPUT: flfrc is required for q2r.x", source_file=src,
        ))
    if la2f is True:
        issues.append(SanityIssue(
            id="q2r.la2f.forbidden", severity=Severity.ERROR,
            message="la2F=.true. will crash q2r.x — remove it", source_file=src,
        ))


def _check_matdyn_input(qe_input: QEInput, src: str, issues: list[SanityIssue]) -> None:
    """Sanity checks specific to matdyn.x inputs."""
    inp = qe_input.namelists.get("input")
    if inp is None:
        return
    flfrc = inp.params.get("flfrc", "")
    flfrq = inp.params.get("flfrq", "")
    la2f = inp.params.get("la2f", None)
    dos = inp.params.get("dos", False)

    if not flfrc:
        issues.append(SanityIssue(
            id="matdyn.flfrc.missing", severity=Severity.ERROR,
            message="&INPUT: flfrc is required for matdyn.x", source_file=src,
        ))
    if not flfrq:
        issues.append(SanityIssue(
            id="matdyn.flfrq.missing", severity=Severity.INFO,
            message="&INPUT: flfrq not specified (phonon DOS mode?)", source_file=src,
        ))
    dos_mode = dos is True or str(dos).strip().lower() in {".true.", "true", "t"}
    if la2f is True and not dos_mode:
        issues.append(SanityIssue(
            id="matdyn.la2f.forbidden", severity=Severity.ERROR,
            message="la2F=.true. should not be in ordinary matdyn.x line/dispersion input",
            source_file=src,
        ))


def _check_lambda_input(qe_input: QEInput, src: str, issues: list[SanityIssue]) -> None:
    """Sanity checks specific to lambda.x inputs."""
    inp = qe_input.namelists.get("input")
    if inp is None:
        return
    mustar = inp.params.get("mustar", None)
    if mustar is None:
        issues.append(SanityIssue(
            id="lambda.mustar.missing", severity=Severity.WARNING,
            message="&INPUT: mu* (mustar) not specified; using QE default (0.1)", source_file=src,
        ))
    elif isinstance(mustar, (int, float)):
        if mustar < 0 or mustar > 0.5:
            issues.append(SanityIssue(
                id="lambda.mustar.out_of_range", severity=Severity.WARNING,
                message=f"mu* = {mustar} is outside typical range (0.08–0.15)", source_file=src,
            ))


def _check_essential_cards(qe_input: QEInput, src: str, issues: list[SanityIssue]) -> None:
    """Check for presence of essential card blocks."""
    prog = qe_input.program
    cards = qe_input.cards

    if prog == QEProgram.PW or prog == QEProgram.UNKNOWN:
        if "ATOMIC_SPECIES" not in cards:
            issues.append(SanityIssue(
                id="cards.atomic_species.missing", severity=Severity.ERROR,
                message="ATOMIC_SPECIES card is missing", source_file=src,
            ))
        if "ATOMIC_POSITIONS" not in cards:
            issues.append(SanityIssue(
                id="cards.atomic_positions.missing", severity=Severity.ERROR,
                message="ATOMIC_POSITIONS card is missing", source_file=src,
            ))
        if "K_POINTS" not in cards:
            issues.append(SanityIssue(
                id="cards.kpoints.missing", severity=Severity.ERROR,
                message="K_POINTS card is missing", source_file=src,
            ))


# ═══════════════════════════════════════════════════════════════════════════════
# Output inspection
# ═══════════════════════════════════════════════════════════════════════════════


def _inspect_output(
    path: Path,
    file_rec: FileRecord,
) -> tuple[FileRecord, list[TaskRecord], list[SanityIssue]]:
    """Inspect a QE output (.out) file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        file_rec.parse_status = "failed"
        file_rec.parse_errors = [str(exc)]
        return file_rec, [], [
            SanityIssue(id="file.read_error", severity=Severity.ERROR,
                        message=f"Cannot read: {exc}", source_file=str(path)),
        ]

    tasks: list[TaskRecord] = []
    issues: list[SanityIssue] = []

    # Detect program from output signature
    prog = _detect_program_from_output(text)
    file_rec.program = prog

    if prog == QEProgram.UNKNOWN:
        file_rec.parse_status = "failed"
        issues.append(SanityIssue(
            id="output.program.unknown", severity=Severity.ERROR,
            message="Could not identify QE program from output content", source_file=str(path),
        ))
        return file_rec, tasks, issues

    file_rec.parse_status = "ok"
    file_rec.summary = _make_output_summary(text, prog)

    # Check for JOB DONE
    job_done = "JOB DONE" in text
    if not job_done:
        issues.append(SanityIssue(
            id="output.job_done.missing", severity=Severity.ERROR,
            message="JOB DONE not found — calculation may have crashed or been interrupted",
            source_file=str(path),
        ))
    else:
        issues.append(SanityIssue(
            id="output.job_done", severity=Severity.INFO,
            message="JOB DONE — calculation completed normally", source_file=str(path),
        ))

    # Check SCF convergence (for pw.x)
    if prog == QEProgram.PW:
        conv = "convergence has been achieved" in text
        if conv:
            issues.append(SanityIssue(
                id="output.scf.converged", severity=Severity.INFO,
                message="SCF converged", source_file=str(path),
            ))
        else:
            issues.append(SanityIssue(
                id="output.scf.not_converged", severity=Severity.ERROR,
                message="SCF did not converge", source_file=str(path),
            ))

    # Check for NaN
    nan_count = len(re.findall(r"(?i)\bnan\b", text))
    if nan_count > 0:
        issues.append(SanityIssue(
            id="output.nan.found", severity=Severity.WARNING,
            message=f"NaN values found ({nan_count} occurrences)", source_file=str(path),
        ))

    # Build task record
    task = TaskRecord(program=prog, source_file=str(path), confidence="high")
    task.task_type = _infer_task_type_from_output(text, prog)
    tasks.append(task)

    return file_rec, tasks, issues


def _detect_program_from_output(text: str) -> QEProgram:
    """Detect QE program from output file signature.

    Priority: explicit ``Program XXX`` header > JOB DONE > lambda heuristic.
    For Slurm/Talos/oneAPI wrapper files, scans past the wrapper header.
    """
    # ── Strip wrapper headers (Talos / SBATCH / oneAPI setup) ──
    # Cluster wrapper outputs prepend an environment-setup block before the
    # real QE output. The QE ``Program XXX v.Y`` header is unambiguous and
    # never appears in the wrapper, so we can safely search the whole file
    # body. We still skip the first ~30 lines for the lambda/JOB-DONE
    # heuristics below to avoid matching wrapper text.
    search_text = text
    wrapper_markers = ("[Talos]", "#SBATCH", ":: initializing oneapi",
                       ":: initializing oneAPI", "slurm_script:",
                       "setvars.sh", "oneAPI environment")
    if any(m in text[:800] for m in wrapper_markers):
        lines = text.splitlines()
        mid = min(len(lines), 40)
        search_text = "\n".join(lines[mid:])

    # ── Explicit "Program XXX v.Y" header (most reliable) ──
    # Search the FULL text — the Program header is unambiguous and may sit
    # far into the file when a wrapper header is present.
    prog_map = [
        (r"Program\s+(?:PW(?:scf)?|PW)\s+v\.", QEProgram.PW),
        (r"Program\s+PH(?:onon)?\s+v\.", QEProgram.PH),
        (r"Program\s+Q2R\s+v\.", QEProgram.Q2R),
        (r"Program\s+MATDYN\s+v\.", QEProgram.MATDYN),
        (r"Program\s+DOS\s+v\.", QEProgram.DOS),
        (r"Program\s+BANDS\s+v\.", QEProgram.BANDS),
        (r"Program\s+PROJWFC\s+v\.", QEProgram.PROJWFC),
        (r"Program\s+FS\s+v\.", QEProgram.FS),
        (r"Program\s+POST-PROC\s+v\.", QEProgram.PP),
        (r"Program\s+FERMI\s+v\.", QEProgram.FS),
        (r"Program\s+AVERAGE\s+v\.", QEProgram.AVERAGE),
        (r"Program\s+DYNMAT\s+v\.", QEProgram.DYNMAT),
    ]
    for pattern, prog in prog_map:
        if re.search(pattern, text, re.IGNORECASE):
            return prog

    # ── Fallback: JOB DONE without clear program ID ──
    if "JOB DONE" in search_text:
        return QEProgram.PW  # most likely

    # ── dynmat.x — no "Program" header, but prints a distinctive banner ──
    if "diagonalizing the dynamical matrix" in search_text:
        return QEProgram.DYNMAT

    # ── lambda.x — check LAST (distinctive patterns but no "Program" header) ──
    # Only apply this if NO explicit program was found above, to avoid
    # misclassifying ph.x output (which may contain "lambda" in its text).
    if _looks_like_lambda_output(search_text):
        return QEProgram.LAMBDA

    return QEProgram.UNKNOWN


def _infer_task_type_from_output(text: str, prog: QEProgram) -> TaskType:
    """Infer task type from output content."""
    if prog == QEProgram.PW:
        # pw.x MD (calculation='md') — check BEFORE relax/scf since MD output
        # also embeds "Self-consistent Calculation" blocks per MD step.
        if re.search(r"calculation\s*=\s*['\"]?md['\"]?", text, re.IGNORECASE):
            return TaskType.AIMD
        if ("molecular dynamics" in text.lower()
                or "Starting temp" in text
                or "Velocities used" in text):
            return TaskType.AIMD
        # relax/vc-relax outputs embed many "Self-consistent Calculation"
        # blocks (one per ionic step). Check BFGS/relax markers FIRST so a
        # vc-relax run is not misclassified as scf.
        if "BFGS Geometry Optimization" in text or "ionic minimization" in text.lower():
            if "variable-cell" in text.lower() or "vc-relax" in text.lower():
                return TaskType.VC_RELAX
            return TaskType.RELAX
        # Pure SCF / NSCF (no ionic loop)
        if "Self-consistent Calculation" in text:
            return TaskType.SCF
        if "Non-Self-consistent Calculation" in text:
            return TaskType.NSCF
        # Try calculation = 'xxx' from echo of input
        m = re.search(r"calculation\s*=\s*['\"]?(\w[\w-]*)['\"]?", text)
        if m:
            calc = m.group(1).lower()
            task_map = {
                "scf": TaskType.SCF, "nscf": TaskType.NSCF,
                "relax": TaskType.RELAX, "vc-relax": TaskType.VC_RELAX,
                "bands": TaskType.BANDS, "md": TaskType.AIMD,
            }
            if calc in task_map:
                return task_map[calc]
        return TaskType.SCF  # default for pw.x with JOB DONE

    if prog == QEProgram.PH:
        if "electron_phonon" in text.lower() or "elph" in text.lower():
            return TaskType.PH_EPC
        return TaskType.PH_STABILITY

    if prog == QEProgram.Q2R:
        return TaskType.Q2R

    if prog == QEProgram.MATDYN:
        if "phonon dos" in text.lower() or "fldos" in text.lower():
            return TaskType.MATDYN_DOS
        return TaskType.MATDYN_DISP

    if prog == QEProgram.LAMBDA:
        return TaskType.LAMBDA_TC

    if prog == QEProgram.PP:
        return TaskType.PP_RHO

    if prog == QEProgram.AVERAGE:
        return TaskType.PLANAR_AVERAGE

    if prog == QEProgram.FS:
        return TaskType.UNKNOWN

    if prog == QEProgram.DYNMAT:
        return TaskType.DYNMAT

    return TaskType.UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════════
# lambda.x detection (free-format, no namelists)
# ═══════════════════════════════════════════════════════════════════════════════


def _looks_like_lambda_input(text: str) -> bool:
    """Heuristic: does raw text look like a lambda.x input file?

    Key distinctive feature: references elph_dir/elph.inp_lambda.* files,
    or has the classic mustar/emax/degauss-list free-format structure.
    """
    # Strongest signal: references to elph_dir (EPC matrix elements)
    if "elph_dir" in text or "elph.inp_lambda" in text:
        return True

    # Classic format: mustar, emax, then degauss list
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("!")]
    if len(lines) < 2:
        return False

    # First non-comment line should be parseable as a number
    try:
        float(lines[0].split()[0])
    except (ValueError, IndexError):
        return False

    # Classic two-line format: mu* + degauss list
    if len(lines) == 2:
        parts = lines[1].split()
        if len(parts) >= 3:
            try:
                _ = [float(v) for v in parts]
                return True
            except ValueError:
                pass
        return False

    # Three-line format: mu*, emax, degauss list
    # — requires second line to be a single integer (emax), third line floats
    if len(lines) >= 3:
        parts2 = lines[1].split()
        parts3 = lines[2].split()
        if len(parts2) == 1 and len(parts3) >= 3:
            try:
                int(parts2[0])
                _ = [float(v) for v in parts3]
                return True
            except (ValueError, IndexError):
                pass

    return False


def _looks_like_lambda_output(text: str) -> bool:
    """Heuristic: does output text look like lambda.x output?

    Requires at least 3 strong indicators to avoid misclassifying ph.x
    output (which may mention "lambda" in other contexts like
    "lambda ... representation").
    """
    # Strong indicators — very lambda.x-specific patterns
    strong = [
        "omega_log",        # λ-specific column header
        "T_c",              # Tc column header
        "McMillan",         # McMillan-Allen-Dynes formula
        "Allen-Dynes",
        "degauss",          # degauss scanning is lambda.x-specific
        "N(Ef)",            # DOS at Fermi from lambda.x
        "elph",             # EPC matrix elements
    ]
    # Weak indicators (appear in ph.x output too, so don't count alone)
    weak = [
        "lambda",
        "electron-phonon",
    ]

    strong_score = sum(1 for ind in strong if ind.lower() in text.lower())
    weak_score = sum(1 for ind in weak if ind.lower() in text.lower())

    # Need at least 2 strong indicators, or 1 strong + 2 weak
    return strong_score >= 2 or (strong_score >= 1 and weak_score >= 2)


def _extract_lambda_params(text: str) -> dict[str, Any]:
    """Extract key params from lambda.x free-format input."""
    lines = [l.strip() for l in text.splitlines()
             if l.strip() and not l.strip().startswith("!")]
    params: dict[str, Any] = {}
    if lines:
        try:
            params["mustar"] = float(lines[0].split()[0])
        except (ValueError, IndexError):
            pass
    return params


# ═══════════════════════════════════════════════════════════════════════════════
# Summary helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_input_summary(qe_input: QEInput) -> str:
    """Human-readable one-line summary of a parsed QE input."""
    prog = qe_input.program.value
    parts = [f"program={prog}"]

    if qe_input.program == QEProgram.PW:
        calc = qe_input.get_param("control", "calculation", "?")
        prefix = qe_input.get_param("control", "prefix", "?")
        parts.append(f"calculation={calc}")
        parts.append(f"prefix='{prefix}'")

    elif qe_input.program == QEProgram.PH:
        elph = qe_input.get_param("inputph", "electron_phonon", "")
        nq = [
            qe_input.get_param("inputph", "nq1", "?"),
            qe_input.get_param("inputph", "nq2", "?"),
            qe_input.get_param("inputph", "nq3", "?"),
        ]
        parts.append(f"nq={'x'.join(str(x) for x in nq)}")
        if elph:
            parts.append("EPC=enabled")

    elif qe_input.program == QEProgram.Q2R:
        inp = qe_input.namelists.get("input")
        if inp:
            fildyn = inp.params.get("fildyn", "?")
            parts.append(f"fildyn='{fildyn}'")

    elif qe_input.program == QEProgram.MATDYN:
        inp = qe_input.namelists.get("input")
        if inp:
            dos = inp.params.get("dos", False)
            parts.append("dos" if dos else "dispersion")

    return ", ".join(parts)


def _make_output_summary(text: str, prog: QEProgram) -> str:
    """Human-readable one-line summary of QE output."""
    parts = [f"program={prog.value}"]
    if "JOB DONE" in text:
        parts.append("JOB_DONE=yes")
    else:
        parts.append("JOB_DONE=no")
    if prog == QEProgram.PW:
        m = re.search(r"!\s+total energy\s+=\s+([-\d.]+)\s+Ry", text)
        if m:
            parts.append(f"E_tot={m.group(1)} Ry")
    return ", ".join(parts)
