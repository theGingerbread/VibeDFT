"""Safety filters for LLM prompts — redact private data, enforce evidence binding.

The agent must NEVER:
- See raw uploaded file paths (only relative paths within workspace)
- See server hostnames, user accounts, or real cluster paths
- Fabricate material names, Tc, λ, or structural properties
- Suggest direct QE/sbatch execution
"""

from __future__ import annotations

import os
import re

# Patterns to redact from prompts before sending to LLM
_PRIVATE_PATTERNS: list[tuple[str, str]] = [
    # Server / user paths (aggressive: replace entire path after /home/ or /Users/)
    (r"/home/\S+", "/home/<user>/<redacted>"),
    (r"/Users/\S+", "/Users/<user>/<redacted>"),
    (r"/private/tmp/\S*", "/tmp/<redacted>"),
    (r"/var/folders/\S+?/T/\S*", "/tmp/<redacted>"),
    # Hostnames
    (r"host\s*=\s*['\"]?\w+['\"]?", "host=<cluster>"),
    # SSH targets
    (r"\w+@\w[\w.]*", "<user>@<host>"),
]


def redact_private(text: str) -> str:
    """Remove server paths, hostnames, account names from text."""
    for pattern, replacement in _PRIVATE_PATTERNS:
        text = re.sub(pattern, replacement, text)
    for token in _private_tokens_from_env():
        text = re.sub(rf"\b{re.escape(token)}\b", "<private>", text)
    return text


def _private_tokens_from_env() -> tuple[str, ...]:
    raw = os.environ.get("VIBEDFT_PRIVATE_TOKENS", "")
    return tuple(token for token in re.split(r"[\s,]+", raw) if len(token) >= 3)


# Evidence binding — injected into every prompt
EVIDENCE_CONSTRAINT = """\
CRITICAL RULES:
1. Every claim MUST cite an evidence_id or issue_id from the evidence pack.
2. If no evidence exists for a claim, say "insufficient evidence" — do NOT guess.
3. Do NOT invent material names, Tc values, λ values, or structural data.
4. Do NOT suggest direct QE execution or sbatch submission.
5. Do NOT override the deterministic verdict — only explain it.
6. Keep responses under 300 words.
"""


def build_system_prompt(role: str) -> str:
    """Build a system prompt for a specific agent role."""
    return (
        f"You are a VibeDFT {role} agent. You explain DFT calculation results "
        f"for 2D materials researchers. You only use the provided evidence pack. "
        f"Never fabricate data.\n\n{EVIDENCE_CONSTRAINT}"
    )
