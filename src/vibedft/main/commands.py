"""Command registry and execution handlers for VibeDFT v2 CLI."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from vibedft._shared.contracts import CleanedResult
from vibedft.calculator.qe.dos.clean import clean_dos_text
from vibedft.calculator.qe.bands.clean import clean_bands_text
from vibedft.calculator.qe.nscf.clean import clean_nscf_text
from vibedft.calculator.qe.relax.clean import clean_relax_text
from vibedft.calculator.qe.pdos.clean import clean_pdos_text
from vibedft.calculator.qe.scf.clean import clean_scf_text
from vibedft.calculator.qe.pp.clean import clean_pp_text
from vibedft.calculator.qe.vc_relax.clean import clean_vc_relax_text
from vibedft.main.envelopes import CommandEnvelope, error_envelope, ok_envelope


@dataclass(frozen=True)
class CommandExecution:
    """Result of handling one command."""

    envelope: CommandEnvelope
    exit_code: int = 0
    pretty: bool = False
    output: Path | None = None


@dataclass(frozen=True)
class CommandSpec:
    """Metadata + dispatch for a CLI command."""

    command_id: str
    path: tuple[str, ...]
    description: str
    handler: Callable[[Sequence[str]], CommandExecution]


Cleaner = Callable[[str | Path, str | Path | None], CleanedResult]


def _resolve_dos_data_file(output_file: Path) -> Path | None:
    """Resolve an optional DOS data file from a standard sidecar naming convention."""

    candidates = [
        output_file.with_suffix(".dos"),
        output_file.with_suffix(".dat"),
        output_file.with_suffix(".dos.dat"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


def _resolve_bands_data_file(output_file: Path) -> Path | None:
    """Resolve optional bands data file from output-path sidecar naming conventions."""

    candidates = [
        output_file.with_suffix(".bands"),
        output_file.with_suffix(".dat"),
        output_file.with_suffix(".bands.dat"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


def _resolve_pp_data_files(output_file: Path) -> list[Path]:
    """Resolve pp artifact sidecars from common naming and per-output suffix conventions."""

    candidate_exts = [
        ".dat",
        ".cube",
        ".xsf",
        ".pp",
        ".pp.dat",
        ".pp.cube",
    ]
    candidates: list[Path] = [output_file.with_suffix(ext) for ext in candidate_exts]
    candidates.extend(output_file.parent.glob(f"{output_file.stem}.*"))

    def _is_usable(path: Path) -> bool:
        if not path.is_file():
            return False
        if path == output_file:
            return False
        suffixes = {".out", ".json", ".log"}
        return path.suffix.lower() not in suffixes and path.name.lower() not in suffixes

    filtered = [path for path in candidates if _is_usable(path)]
    return sorted(set(filtered), key=lambda item: str(item))


def _parse_embedded_pdos_filenames(text: str) -> list[str]:
    """Parse projection filenames from stdout-like text."""

    return [
        match
        for match in re.findall(r"(\S+pdos[^\s,;]*)", text, flags=re.IGNORECASE)
    ]


def _resolve_pdos_projection_files(output_file: Path) -> list[Path]:
    """Resolve projection files from output text or same-directory sidecars."""

    if not output_file.is_file():
        return []

    text = output_file.read_text(encoding="utf-8", errors="replace")
    candidate_names = _parse_embedded_pdos_filenames(text)

    resolved: list[Path] = []
    for name in candidate_names:
        candidate = Path(name)
        if not candidate.is_absolute():
            candidate = output_file.parent / candidate
        if candidate.is_file():
            resolved.append(candidate)

    if resolved:
        # If parser output already advertises explicit filenames, trust that list.
        return sorted(set(resolved), key=lambda item: str(item))

    fallback = sorted(output_file.parent.glob("*.pdos*"))
    return [path for path in fallback if path.is_file()]


def _run_clean_review_command(
    argv: Sequence[str],
    *,
    command_id: str,
    prog: str,
    output_help: str,
    cleaner: Cleaner,
) -> CommandExecution:
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("output_file", type=Path, help=output_help)
    parser.add_argument("--output", type=Path, default=None, help="Write JSON output to this path")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument(
        "--fail-on-block",
        action="store_true",
        help="Exit with code 2 when review status is BLOCK",
    )

    args = parser.parse_args(list(argv))

    try:
        # Keep source metadata explicitly tied to the output path to preserve input provenance.
        result = cleaner(args.output_file, source=args.output_file)
        exit_code = 2 if args.fail_on_block and result.status == "block" else 0
        return CommandExecution(
            envelope=ok_envelope(command_id, result),
            exit_code=exit_code,
            pretty=args.pretty,
            output=args.output,
        )

    except Exception as exc:  # pylint: disable=broad-except
        return CommandExecution(
            envelope=error_envelope(command_id, exc),
            exit_code=1,
            pretty=args.pretty,
            output=args.output,
        )


# NOTE: output_help is reserved for future extension and mirrors the shape used by existing handlers.
def _run_qe_scf_review(argv: Sequence[str]) -> CommandExecution:
    return _run_clean_review_command(
        argv,
        command_id="qe.scf.review",
        prog="vibedft qe scf review",
        output_help="QE pw.x output file to review",
        cleaner=clean_scf_text,
    )


def _run_qe_relax_review(argv: Sequence[str]) -> CommandExecution:
    return _run_clean_review_command(
        argv,
        command_id="qe.relax.review",
        prog="vibedft qe relax review",
        output_help="QE pw.x relax output file to review",
        cleaner=clean_relax_text,
    )


def _run_qe_vc_relax_review(argv: Sequence[str]) -> CommandExecution:
    return _run_clean_review_command(
        argv,
        command_id="qe.vc_relax.review",
        prog="vibedft qe vc-relax review",
        output_help="QE pw.x vc-relax output file to review",
        cleaner=clean_vc_relax_text,
    )


def _run_qe_dos_review(argv: Sequence[str]) -> CommandExecution:
    def _clean(output_file: Path, source: str | Path | None) -> CleanedResult:
        data_file = _resolve_dos_data_file(Path(output_file))
        return clean_dos_text(Path(output_file), source=source, data_file=data_file)

    return _run_clean_review_command(
        argv,
        command_id="qe.dos.review",
        prog="vibedft qe dos review",
        output_help="QE dos.x output file to review",
        cleaner=_clean,
    )


def _run_qe_pdos_review(argv: Sequence[str]) -> CommandExecution:
    def _clean(output_file: Path, source: str | Path | None) -> CleanedResult:
        pdos_files = _resolve_pdos_projection_files(Path(output_file))
        return clean_pdos_text(Path(output_file), source=source, pdos_files=pdos_files)

    return _run_clean_review_command(
        argv,
        command_id="qe.pdos.review",
        prog="vibedft qe pdos review",
        output_help="QE projwfc.x / PDOS output file to review",
        cleaner=_clean,
    )


def _run_qe_bands_review(argv: Sequence[str]) -> CommandExecution:
    def _clean(output_file: Path, source: str | Path | None) -> CleanedResult:
        data_file = _resolve_bands_data_file(Path(output_file))
        return clean_bands_text(Path(output_file), source=source, data_file=data_file)

    return _run_clean_review_command(
        argv,
        command_id="qe.bands.review",
        prog="vibedft qe bands review",
        output_help="QE bands.x output file to review",
        cleaner=_clean,
    )


def _run_qe_pp_review(argv: Sequence[str]) -> CommandExecution:
    def _clean(output_file: Path, source: str | Path | None) -> CleanedResult:
        data_files = _resolve_pp_data_files(Path(output_file))
        return clean_pp_text(Path(output_file), source=source, data_files=data_files)

    return _run_clean_review_command(
        argv,
        command_id="qe.pp.review",
        prog="vibedft qe pp review",
        output_help="QE pp.x output file to review",
        cleaner=_clean,
    )


def _run_qe_nscf_review(argv: Sequence[str]) -> CommandExecution:
    return _run_clean_review_command(
        argv,
        command_id="qe.nscf.review",
        prog="vibedft qe nscf review",
        output_help="QE pw.x nscf output file to review",
        cleaner=clean_nscf_text,
    )


def find_command(argv: Sequence[str]) -> tuple[CommandSpec | None, list[str]]:
    """Find the first matching command and return the command spec + remaining args."""

    argv_tuple = tuple(argv)
    best_match: CommandSpec | None = None
    for spec in COMMANDS:
        path = spec.path
        if len(path) > len(argv_tuple):
            continue
        if argv_tuple[: len(path)] == path and (
            best_match is None or len(path) > len(best_match.path)
        ):
            best_match = spec

    if best_match is None:
        return None, list(argv_tuple)

    return best_match, list(argv_tuple[len(best_match.path) :])


COMMANDS = (
    CommandSpec(
        command_id="qe.scf.review",
        path=("qe", "scf", "review"),
        description="Review QE pw.x SCF output and emit CleanedResult JSON.",
        handler=_run_qe_scf_review,
    ),
    CommandSpec(
        command_id="qe.relax.review",
        path=("qe", "relax", "review"),
        description="Review QE pw.x relax output and emit CleanedResult JSON.",
        handler=_run_qe_relax_review,
    ),
    CommandSpec(
        command_id="qe.vc_relax.review",
        path=("qe", "vc-relax", "review"),
        description="Review QE pw.x vc-relax output and emit CleanedResult JSON.",
        handler=_run_qe_vc_relax_review,
    ),
    CommandSpec(
        command_id="qe.nscf.review",
        path=("qe", "nscf", "review"),
        description="Review QE pw.x NSCF output and emit CleanedResult JSON.",
        handler=_run_qe_nscf_review,
    ),
    CommandSpec(
        command_id="qe.dos.review",
        path=("qe", "dos", "review"),
        description="Review QE dos.x output and emit CleanedResult JSON.",
        handler=_run_qe_dos_review,
    ),
    CommandSpec(
        command_id="qe.pdos.review",
        path=("qe", "pdos", "review"),
        description="Review QE projwfc.x / PDOS output and emit CleanedResult JSON.",
        handler=_run_qe_pdos_review,
    ),
    CommandSpec(
        command_id="qe.bands.review",
        path=("qe", "bands", "review"),
        description="Review QE bands.x output and emit CleanedResult JSON.",
        handler=_run_qe_bands_review,
    ),
    CommandSpec(
        command_id="qe.pp.review",
        path=("qe", "pp", "review"),
        description="Review QE pp.x output and emit CleanedResult JSON.",
        handler=_run_qe_pp_review,
    ),
)


__all__ = [
    "COMMANDS",
    "CommandExecution",
    "CommandSpec",
    "find_command",
]
