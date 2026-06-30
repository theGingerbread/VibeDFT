"""Agent-facing CLI entrypoints for VibeDFT."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from vibedft.calculator.qe.scf.clean import clean_scf_text
from vibedft.cli.main import main as legacy_main


def _json_default(value: Any) -> str:
    """Serialize uncommon objects in CLI payloads."""

    if isinstance(value, Path):
        return str(value)
    return str(value)


def _run_qe_scf_review(argv: Sequence[str]) -> None:
    parser = argparse.ArgumentParser(prog="vibedft qe scf review")
    parser.add_argument("output_file", type=Path, help="QE pw.x output file to review")
    parser.add_argument("--output", type=Path, default=None, help="Write JSON output to this path")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument(
        "--fail-on-block",
        action="store_true",
        help="Exit with code 2 when review status is BLOCK",
    )

    args = parser.parse_args(list(argv))
    try:
        result = clean_scf_text(args.output_file, source=args.output_file)
        payload = {
            "command": "qe.scf.review",
            "ok": True,
            "result": asdict(result),
        }
        _emit_json(payload, pretty=args.pretty, output=args.output)

        if args.fail_on_block and result.status == "block":
            raise SystemExit(2)
        return

    except Exception as exc:  # pylint: disable=broad-except
        payload = {
            "command": "qe.scf.review",
            "ok": False,
            "error": {
                "type": exc.__class__.__name__,
                "message": str(exc),
            },
        }
        payload_text = json.dumps(
            payload,
            indent=2 if args.pretty else None,
            default=_json_default,
            ensure_ascii=False,
        )
        print(payload_text)
        if args.output is not None:
            try:
                _safe_emit_json_file(payload_text, args.output)
            except Exception:
                pass
        raise SystemExit(1)


def _safe_emit_json_file(payload_text: str, output: Path) -> None:
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload_text + "\n", encoding="utf-8")


def _emit_json(payload: dict[str, Any], *, pretty: bool, output: Path | None) -> str:
    payload_text = json.dumps(
        payload,
        indent=2 if pretty else None,
        default=_json_default,
        ensure_ascii=False,
    )
    if output is not None:
        _safe_emit_json_file(payload_text, output)
    print(payload_text)
    return payload_text


def main(argv: Sequence[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:3] == ["qe", "scf", "review"]:
        _run_qe_scf_review(argv[3:])
        return
    return legacy_main(argv)


__all__ = ["main"]
