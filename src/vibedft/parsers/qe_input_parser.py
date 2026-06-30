"""Deterministic parser for Quantum ESPRESSO input files.

Covers pw.x, ph.x, q2r.x, matdyn.x, and lambda.x inputs.
Handles Fortran namelist syntax, QE card blocks, and free-format input.

Key entry point: :func:`parse_qe_input` — file path → :class:`QEInput`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from vibedft.models.inspection import (
    CardBlock,
    NamelistBlock,
    QEInput,
    QEProgram,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════


def parse_qe_input(filepath: Path | str) -> QEInput:
    """Parse a Quantum ESPRESSO input file into a structured :class:`QEInput`.

    Handles pw.x, ph.x, q2r.x, matdyn.x, and lambda.x formats.
    """
    path = Path(filepath)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return QEInput(
            source_path=str(path),
            program=QEProgram.UNKNOWN,
            parse_errors=[f"Cannot read file: {exc}"],
        )
    result = _parse_qe_text(text, source_path=str(path))
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Internal parsing
# ═══════════════════════════════════════════════════════════════════════════════

# Cards recognised across supported QE programs.  Names are uppercase for
# matching; the parser does case-insensitive comparison.
_KNOWN_CARDS = frozenset({
    "ATOMIC_SPECIES", "ATOMIC_POSITIONS", "K_POINTS",
    "CELL_PARAMETERS", "OCCUPATIONS", "CONSTRAINTS",
    "ATOMIC_FORCES", "CLIMBING_IMAGES",
})

# Programs that use only a single &INPUT namelist (or variant names)
_POSTPROC_NAMELISTS = frozenset({"INPUT", "INPUTPH", "INPUTPP"})


def _parse_qe_text(text: str, *, source_path: str = "") -> QEInput:
    """Parse QE input text into a QEInput."""
    result = QEInput(source_path=source_path, raw_text=text)
    lines = text.splitlines()

    # ── Strip comments and blank lines for structural parsing ──
    # We keep raw text for reference, but parse from cleaned lines.
    cleaned: list[str] = []
    for line in lines:
        # Remove inline comments (but NOT if the '!' is inside a quoted string)
        unquoted = _strip_fortran_comment(line)
        stripped = unquoted.strip()
        if stripped:
            cleaned.append(stripped)

    if not cleaned:
        result.parse_errors.append("File is empty or contains only comments")
        return result

    # ── Detect free-format input (lambda.x style) ──
    # If the first non-comment line does NOT start with '&' and is not a known
    # card, treat the whole file as free-format.
    first = cleaned[0]
    if not first.startswith("&") and first.split()[0].upper() not in _KNOWN_CARDS:
        # Might be lambda.x free-format or unrecognised
        result.raw_text = text
        # Defer program detection to the classifier
        return result

    # ── Parse blocks (namelists + cards) in order ──
    i = 0
    while i < len(cleaned):
        line = cleaned[i]

        if line.startswith("&"):
            # ── Namelist ──
            nl_block, consumed = _consume_namelist(cleaned, i)
            if nl_block is not None:
                key = nl_block.name.lower()
                if key in result.namelists:
                    # Merge duplicate namelists (rare but legal in some QE inputs)
                    result.namelists[key].params.update(nl_block.params)
                    result.namelists[key].raw_lines.extend(nl_block.raw_lines)
                else:
                    result.namelists[key] = nl_block
            i += consumed
        else:
            # ── Card ──
            first_word = line.split()[0].upper() if line.split() else ""
            if first_word in _KNOWN_CARDS:
                card, consumed = _consume_card(cleaned, i)
                if card is not None:
                    result.cards[card.name.upper()] = card
                i += consumed
            else:
                i += 1  # skip unrecognised lines (shouldn't happen often)

    # ── Identify program ──
    result.program = _identify_program(result)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Namelist consumer
# ═══════════════════════════════════════════════════════════════════════════════


def _consume_namelist(lines: list[str], start: int) -> tuple[NamelistBlock | None, int]:
    """Consume one Fortran namelist starting at ``lines[start]``.

    Returns ``(NamelistBlock, lines_consumed)``.
    """
    header = lines[start]
    m = re.match(r"^&(\w+)", header, re.IGNORECASE)
    if not m:
        return None, 1
    name = m.group(1)

    raw_lines = [header]
    params: dict[str, Any] = {}

    # Handle single-line namelist: &NAME key=val key=val ... /
    header_body = header[header.index("&") + len(m.group(0)):]  # everything after &NAME
    header_body = header_body.strip()
    if header_body.endswith("/"):
        body = header_body[:-1].strip()
        _assign_namelist_params(body, params)
        return NamelistBlock(name=name, params=params, raw_lines=raw_lines), 1

    if header_body:
        _assign_namelist_params(header_body, params)

    i = start + 1

    # Collect all key=value pairs until the terminating '/'
    while i < len(lines):
        raw_lines.append(lines[i])
        stripped = lines[i]

        if stripped.rstrip().endswith("/"):
            # Last line of namelist — strip trailing '/' then parse
            body = stripped.rstrip()[:-1]  # Remove trailing '/'
            _assign_namelist_params(body, params)
            i += 1
            break
        else:
            _assign_namelist_params(stripped, params)
            i += 1

    return NamelistBlock(name=name, params=params, raw_lines=raw_lines), i - start


def _assign_namelist_params(body: str, params: dict[str, Any]) -> None:
    """Extract ``key = value`` pairs from namelist body and merge into *params*.

    Handles both comma-separated and space-separated Fortran namelist syntax
    by using a regex that matches ``key = value`` patterns directly.
    """
    # Regex matching key = value for Fortran namelist values:
    #   'string' | "string" | .bool. | number[dD]exponent | bare_word
    _KV_RE = re.compile(
        r"(\w+)\s*=\s*"
        r"("
        r"'[^']*'"           # single-quoted
        r"|\"[^\"]*\""       # double-quoted
        r"|\.\w+\.?"         # .true. / .false.
        r"|[\d]*\.?[\d]+[dD][+\-]?\d+"  # Fortran d/D exponent: 1.0d-16, 1d-5, 2.5D+03
        r"|[\d]*\.[\d]+(?:[eE][+\-]?\d+)?"  # float with decimal
        r"|[\d]+"                  # plain integer
        r")",
        re.IGNORECASE,
    )

    pos = 0
    while pos < len(body):
        m = _KV_RE.search(body, pos)
        if not m:
            break
        key = m.group(1).lower()
        raw_val = m.group(2).strip()
        val = _parse_fortran_value(raw_val)

        if key in params and isinstance(params[key], list):
            if isinstance(val, list):
                params[key].extend(val)
            else:
                params[key].append(val)
        else:
            params[key] = val
        pos = m.end()


def _split_namelist_by_spaces(body: str) -> list[str]:
    """Split a space-separated Fortran namelist body into ``key=value`` segments.

    Uses a character-by-character state machine that tracks quote context
    and detects ``<value> <whitespace> <key>=`` transitions.
    """
    segments: list[str] = []
    in_single = False
    in_double = False
    buf = ""
    i = 0
    n = len(body)

    while i < n:
        ch = body[i]

        if in_single:
            buf += ch
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            buf += ch
            if ch == '"':
                in_double = False
            i += 1
            continue

        if ch == "'":
            in_single = True
            buf += ch
            i += 1
            continue
        if ch == '"':
            in_double = True
            buf += ch
            i += 1
            continue

        # Check for whitespace → next key transition
        if ch.isspace() and buf.strip():
            # Peek ahead: after whitespace, is the next non-space part a "key="?
            j = i + 1
            while j < n and body[j].isspace():
                j += 1
            # Extract the next word
            k = j
            while k < n and (body[k].isalnum() or body[k] == "_"):
                k += 1
            next_word = body[j:k] if k > j else ""
            # Check if next_word is followed by '='
            while k < n and body[k].isspace():
                k += 1
            is_next_pair = (next_word and k < n and body[k] == "=" and
                            next_word.lower() not in (".true.", ".false.", "true", "false"))

            if is_next_pair and buf.rstrip().endswith(("'", '"')):
                # Completed a quoted value → flush
                segments.append(buf.strip())
                buf = ""
                i += 1
                continue
            elif is_next_pair and not (in_single or in_double):
                # Try to determine if we're at a boundary
                # Check if what's in buf looks like a complete key=value
                if "=" in buf:
                    segments.append(buf.strip())
                    buf = ""
                    i += 1
                    continue

        buf += ch
        i += 1

    if buf.strip():
        segments.append(buf.strip())

    return segments if len(segments) > 1 else [body]


def _split_namelist_segments(body: str) -> list[str]:
    """Split a namelist body line at top-level commas."""
    segments: list[str] = []
    depth_paren = 0
    in_quote = False
    quote_char = ""
    start = 0
    for i, ch in enumerate(body):
        if in_quote:
            if ch == quote_char:
                in_quote = False
            continue
        if ch in ("'", '"'):
            in_quote = True
            quote_char = ch
            continue
        if ch == "(":
            depth_paren += 1
            continue
        if ch == ")":
            depth_paren -= 1
            continue
        if ch == "," and depth_paren == 0:
            segments.append(body[start:i])
            start = i + 1
    segments.append(body[start:])
    return segments


# ═══════════════════════════════════════════════════════════════════════════════
# Card consumer
# ═══════════════════════════════════════════════════════════════════════════════


def _consume_card(lines: list[str], start: int) -> tuple[CardBlock | None, int]:
    """Consume one QE card block starting at ``lines[start]``.

    Returns ``(CardBlock, lines_consumed)``.
    """
    header_parts = lines[start].split()
    card_name = header_parts[0].upper()

    # Detect: "CARD_NAME option val1 val2 ..." — remainder after option keyword
    # For cards like K_POINTS, the option is "automatic"/"gamma"/etc.
    # For cards like ATOMIC_SPECIES, there is no option — data follows immediately.
    # Heuristic: if second word looks like a card option (all-alpha), treat
    # remainder as option; otherwise treat everything after card_name as data.
    option = ""
    data_from_header: list[str] = []
    if len(header_parts) > 1:
        second = header_parts[1].lower().strip("()")  # strip parens: (angstrom) → angstrom
        one_word_options = {"automatic", "gamma", "crystal", "alat", "bohr", "angstrom",
                            "tpiba", "tpiba_b", "cubic", "cartesian"}
        if second in one_word_options:
            option = second
            # Everything after the option word is data
            if len(header_parts) > 2:
                data_from_header = header_parts[2:]
        else:
            # No recognized option — rest is data
            data_from_header = header_parts[1:]

    raw_lines = [lines[start]]
    rows: list[list[str]] = []
    if data_from_header:
        rows.append(data_from_header)
    i = start + 1

    while i < len(lines):
        stripped = lines[i]
        # Stop at next namelist or card
        if stripped.startswith("&"):
            break
        first_word = stripped.split()[0].upper() if stripped.split() else ""
        if first_word in _KNOWN_CARDS:
            break
        raw_lines.append(stripped)
        # Parse data row
        tokens = stripped.split()
        if tokens:
            rows.append(tokens)
        i += 1

    return CardBlock(name=card_name, option=option, rows=rows, raw_lines=raw_lines), i - start


# ═══════════════════════════════════════════════════════════════════════════════
# Fortran value conversion
# ═══════════════════════════════════════════════════════════════════════════════


def _parse_fortran_value(raw: str) -> Any:
    """Convert a Fortran literal to a Python value.

    Handles:
      - strings: ``'abc'`` or ``"abc"``
      - booleans: ``.true.`` / ``.false.``
      - integers
      - floats (including d/D exponents)
      - lists: ``val1, val2, val3``
    """
    raw = raw.strip()

    # ── Quoted string ──
    if (raw.startswith("'") and raw.endswith("'")) or \
       (raw.startswith('"') and raw.endswith('"')):
        return raw[1:-1]

    # ── Boolean ──
    low = raw.lower()
    if low in (".true.", "true"):
        return True
    if low in (".false.", "false"):
        return False

    # ── Comma-separated list (recursive) ──
    if "," in raw:
        parts = _split_namelist_segments(raw)
        values = [_parse_fortran_value(p) for p in parts if p.strip()]
        if len(values) == 1:
            return values[0]
        return values

    # ── Numeric ──
    return _parse_fortran_number(raw)


def _parse_fortran_number(raw: str) -> int | float | str:
    """Parse a single Fortran numeric literal."""
    s = raw.strip()
    # Replace Fortran double-precision exponent: 1.0d-5 → 1.0e-5
    s_replaced = re.sub(r"([\d.]+)[dD]([+\-]?\d+)", r"\1e\2", s)
    try:
        if "." in s_replaced or "e" in s_replaced.lower():
            return float(s_replaced)
        return int(s_replaced)
    except (ValueError, OverflowError):
        return s  # return as-is string if unparseable


# ═══════════════════════════════════════════════════════════════════════════════
# Program identification
# ═══════════════════════════════════════════════════════════════════════════════


def _identify_program(result: QEInput) -> QEProgram:
    """Identify which QE program an input file belongs to.

    Priority: ph.x > q2r.x > matdyn.x > pw.x
    """
    nl_keys = set(result.namelists.keys())

    # ph.x always has &INPUTPH
    if "inputph" in nl_keys:
        return QEProgram.PH

    # ── Post-processing programs: dos.x / bands.x / projwfc.x ──
    # These use their own namelist names: &dos, &bands, &projwfc, &inputpp
    if "dos" in nl_keys:
        return QEProgram.DOS
    if "bands" in nl_keys:
        return QEProgram.BANDS
    if "projwfc" in nl_keys:
        return QEProgram.PROJWFC
    if "inputpp" in nl_keys:
        inp = result.namelists.get("inputpp")
        if inp is not None:
            if "filpdos" in inp.params:
                return QEProgram.PROJWFC
            if "fildos" in inp.params:
                return QEProgram.DOS
            # pp.x: &INPUTPP with plot_num/filplot/fildyn-style plot params.
            # Distinguished from projwfc/dos by the absence of filpdos/fildos
            # and the presence of plot_num, filplot, or &PLOT namelist.
            if any(k in inp.params for k in ("plot_num", "filplot", "weight")):
                return QEProgram.PP
            # If a &PLOT namelist is present, this is definitely pp.x
            if "plot" in nl_keys:
                return QEProgram.PP
            # Fallback: &INPUTPP without dos/projwfc markers → pp.x
            return QEProgram.PP

    # q2r.x / matdyn.x / dynmat.x / lambda.x all use &INPUT or &input
    if "input" in nl_keys:
        inp = result.namelists.get("input")
        if inp is not None:
            params = inp.params
            # lambda.x: has mustar, or has emax, or has only lambda-specific params
            if "mustar" in params:
                return QEProgram.LAMBDA
            if "emax" in params and "fildyn" not in params and "flfrc" not in params:
                return QEProgram.LAMBDA
            # dynmat.x: &input with fildyn + filmol/asr/dmrx — diagonalizes a
            # dynamical matrix to produce phonon modes/eigenvectors. Distinguished
            # from q2r.x (zasr+flfrc) and matdyn.x (flfrq/dos/q_in_band_form) by
            # filmol/filxsf/fildof, or by asr alone (when no zasr/flfrc/flfrq).
            if "fildyn" in params and any(
                k in params for k in ("filmol", "filxsf", "fildof")
            ):
                return QEProgram.DYNMAT
            if "fildyn" in params and "asr" in params and not any(
                k in params for k in ("zasr", "flfrc", "flfrq", "q_in_band_form")
            ):
                return QEProgram.DYNMAT
            # q2r.x: has fildyn and zasr, NO flfrq, NO dos, NO fildos
            if "fildyn" in params and "zasr" in params and "flfrq" not in params:
                if "fildos" not in params:  # make sure it's not dos.x
                    return QEProgram.Q2R
            # matdyn.x: has flfrq or flfrc or dos or q_in_band_form
            if any(k in params for k in ("flfrq", "q_in_band_form", "q_in_cryst_coord")):
                return QEProgram.MATDYN
            if params.get("dos") is True or "fldos" in params:
                return QEProgram.MATDYN
            # dos.x via &input: has fildos, prefix, outdir; no fildyn
            if "fildos" in params and "fildyn" not in params:
                return QEProgram.DOS
            # Generic fallback for unrecognised &input
            return QEProgram.UNKNOWN

    # pw.x: has &CONTROL with calculation key
    if "control" in nl_keys:
        return QEProgram.PW

    # If only &SYSTEM or &ELECTRONS (unusual), still pw.x
    if nl_keys & {"system", "electrons", "ions", "cell"}:
        return QEProgram.PW

    return QEProgram.UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _strip_fortran_comment(line: str) -> str:
    """Remove Fortran inline comment (``!``) while preserving quoted strings."""
    result: list[str] = []
    in_single = False
    in_double = False
    for ch in line:
        if in_single:
            result.append(ch)
            if ch == "'":
                in_single = False
            continue
        if in_double:
            result.append(ch)
            if ch == '"':
                in_double = False
            continue
        if ch == "'":
            in_single = True
            result.append(ch)
            continue
        if ch == '"':
            in_double = True
            result.append(ch)
            continue
        if ch == "!":
            break  # rest is comment
        result.append(ch)
    return "".join(result)
