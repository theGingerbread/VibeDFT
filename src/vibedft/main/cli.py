"""Agent-facing CLI entrypoints for VibeDFT."""

from __future__ import annotations

from pathlib import Path
import sys
from vibedft.cli.main import main as legacy_main
from typing import Sequence

from vibedft.main.commands import CommandExecution, find_command
from vibedft.main.envelopes import CommandEnvelope, envelope_to_json_text, error_envelope


def _safe_emit_json_file(payload_text: str, output: Path) -> None:
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload_text + "\n", encoding="utf-8")


def _emit_json(command_envelope: CommandEnvelope, *, pretty: bool) -> str:
    return envelope_to_json_text(command_envelope, pretty=pretty)


def _emit_command_result(execution: CommandExecution) -> tuple[str, int]:
    payload_text = _emit_json(execution.envelope, pretty=execution.pretty)
    exit_code = execution.exit_code
    if execution.output is not None:
        try:
            _safe_emit_json_file(payload_text, execution.output)
        except Exception as exc:
            error_payload = error_envelope(execution.envelope.command, exc)
            payload_text = envelope_to_json_text(error_payload, pretty=execution.pretty)
            try:
                _safe_emit_json_file(payload_text, execution.output)
            except Exception:
                pass
            exit_code = 1
    print(payload_text)
    return payload_text, exit_code


def main(argv: Sequence[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    command, command_args = find_command(argv)
    if command is None:
        # Transitional fallback: legacy CLI remains for backward compatibility until all
        # v2 command handlers are fully migrated and validated.
        return legacy_main(argv)

    execution = command.handler(command_args)
    _, exit_code = _emit_command_result(execution)
    raise SystemExit(exit_code)


__all__ = ["main"]
