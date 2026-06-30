"""Path-aware privacy audit for public CI.

The audit is deliberately stricter for runtime source than for test fixtures:
source must not carry real workstation or cluster details, while fixtures are
checked by their own regression test with a small allowlist for templates.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


_BINARY_EXTS = {
    ".DS_Store",
    ".gif",
    ".gz",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".tar",
    ".zip",
}

_PRIVATE_PATH_PATTERNS = (
    re.compile(r"/home/[A-Za-z0-9._-]+/(?:Software|software|work|calc|data)\S*"),
    re.compile("/data/" + "intel" + r"(?:/|\b)\S*"),
)


@dataclass(frozen=True)
class PrivacyViolation:
    """Single private-data match found by the audit."""

    relative_path: str
    line_number: int
    matched: str
    line: str


@dataclass(frozen=True)
class PrivacyAuditResult:
    """Privacy audit result."""

    violations: list[PrivacyViolation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def audit_privacy(
    *,
    root: Path | str,
    paths: list[str] | tuple[str, ...],
    excludes: list[str] | tuple[str, ...] = (),
    private_tokens: list[str] | tuple[str, ...] = (),
) -> PrivacyAuditResult:
    """Scan selected paths for private host, account, and install details."""
    root_path = Path(root).resolve()
    exclude_paths = tuple((root_path / item).resolve() for item in excludes)
    token_patterns = tuple(
        re.compile(rf"\b{re.escape(token)}\b")
        for token in private_tokens
        if token and len(token) >= 3
    )

    violations: list[PrivacyViolation] = []
    for file_path in _iter_text_files(root_path, paths, exclude_paths):
        rel = file_path.relative_to(root_path).as_posix()
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for matched in _line_matches(line, token_patterns):
                violations.append(
                    PrivacyViolation(
                        relative_path=rel,
                        line_number=line_number,
                        matched=matched,
                        line=line.strip(),
                    )
                )
    return PrivacyAuditResult(violations=violations)


def private_tokens_from_env() -> tuple[str, ...]:
    """Return comma/whitespace separated private tokens configured for CI."""
    raw = os.environ.get("VIBEDFT_PRIVATE_TOKENS", "")
    return tuple(token for token in re.split(r"[\s,]+", raw) if token)


def _iter_text_files(
    root_path: Path,
    paths: list[str] | tuple[str, ...],
    exclude_paths: tuple[Path, ...],
):
    for item in paths:
        base = (root_path / item).resolve()
        if not base.exists() or _is_excluded(base, exclude_paths):
            continue
        if base.is_file():
            if not _looks_binary(base):
                yield base
            continue
        for path in base.rglob("*"):
            if _is_excluded(path, exclude_paths):
                continue
            if path.is_file() and not _looks_binary(path):
                yield path


def _line_matches(line: str, token_patterns: tuple[re.Pattern[str], ...]) -> list[str]:
    matches: list[str] = []
    for pattern in _PRIVATE_PATH_PATTERNS:
        matches.extend(match.group(0) for match in pattern.finditer(line))
    for pattern in token_patterns:
        matches.extend(match.group(0) for match in pattern.finditer(line))
    return matches


def _is_excluded(path: Path, exclude_paths: tuple[Path, ...]) -> bool:
    parts = set(path.parts)
    if ".git" in parts or "__pycache__" in parts:
        return True
    return any(path == excluded or excluded in path.parents for excluded in exclude_paths)


def _looks_binary(path: Path) -> bool:
    return path.suffix.lower() in {ext.lower() for ext in _BINARY_EXTS}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit source paths for private data.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument(
        "--paths",
        nargs="+",
        default=["src", "tests/fixtures"],
        help="Paths to scan relative to the repository root.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Path to exclude, relative to the repository root. May be repeated.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    result = audit_privacy(
        root=args.root,
        paths=args.paths,
        excludes=args.exclude,
        private_tokens=private_tokens_from_env(),
    )
    if result.ok:
        print("Privacy audit passed: no private data found.")
        return 0

    print("PRIVACY VIOLATIONS FOUND:")
    for violation in result.violations:
        print(
            f"{violation.relative_path}:{violation.line_number}: "
            f"{violation.matched}: {violation.line}"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
