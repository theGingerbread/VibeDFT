"""Command registry and execution handlers for VibeDFT v2 CLI."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from vibedft._shared.contracts import CleanedResult
from vibedft.calculator.qe.nscf.clean import clean_nscf_text
from vibedft.calculator.qe.relax.clean import clean_relax_text
from vibedft.calculator.qe.scf.clean import clean_scf_text
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
)


__all__ = [
    "COMMANDS",
    "CommandExecution",
    "CommandSpec",
    "find_command",
]
