"""Tests for CLI response envelope serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass

from vibedft.main.envelopes import CommandEnvelope, envelope_to_json_text, error_envelope, ok_envelope


@dataclass(frozen=True)
class _SampleResult:
    task: str
    status: str


def test_ok_envelope_serializable() -> None:
    envelope = ok_envelope(
        "qe.scf.review",
        _SampleResult(task="scf", status="pass"),
    )
    payload_text = envelope_to_json_text(envelope, pretty=False)
    payload = json.loads(payload_text)

    assert payload["command"] == "qe.scf.review"
    assert payload["ok"] is True
    assert payload["result"]["task"] == "scf"
    assert payload["result"]["status"] == "pass"
    assert "error" not in payload or payload["error"] is None


def test_error_envelope_serializable() -> None:
    exc = ValueError("invalid output")
    envelope = error_envelope("qe.scf.review", exc)
    payload_text = envelope_to_json_text(envelope, pretty=False)
    payload = json.loads(payload_text)

    assert payload["command"] == "qe.scf.review"
    assert payload["ok"] is False
    assert payload["error"]["type"] == "ValueError"
    assert payload["error"]["message"] == "invalid output"


def test_dataclass_result_is_dict_in_json() -> None:
    envelope = CommandEnvelope(
        command="qe.scf.review",
        ok=True,
        result=_SampleResult(task="scf", status="warn"),
    )

    payload_text = envelope_to_json_text(envelope, pretty=False)
    payload = json.loads(payload_text)

    assert payload["result"]["task"] == "scf"
    assert payload["result"]["status"] == "warn"


def test_pretty_payload_is_parseable_json() -> None:
    envelope = ok_envelope(
        "qe.scf.review",
        {"task": "scf", "status": "warn"},
    )
    payload_text = envelope_to_json_text(envelope, pretty=True)

    # The prettified output must still be valid JSON.
    parsed = json.loads(payload_text)

    assert parsed["command"] == "qe.scf.review"
    assert parsed["ok"] is True
    assert parsed["error"] is None
