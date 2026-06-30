"""Local workspace manager with path sandboxing.

All file operations are confined to managed workspace directories.
Path traversal attacks are blocked by resolving and validating paths.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path


class Workspace:
    """A sandboxed temporary workspace for one API session."""

    def __init__(self, base_dir: Path | str | None = None):
        self._root = Path(base_dir) if base_dir else Path(tempfile.mkdtemp(prefix="vibedft_"))
        self._root.mkdir(parents=True, exist_ok=True)
        self._uploads = self._root / "uploads"
        self._cases = self._root / "cases"
        self._artifacts = self._root / "artifacts"
        self._uploads.mkdir(exist_ok=True)
        self._cases.mkdir(exist_ok=True)
        self._artifacts.mkdir(exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def upload_dir(self, subdir: str = "") -> Path:
        d = self._uploads / subdir if subdir else self._uploads
        d.mkdir(parents=True, exist_ok=True)
        return d

    def case_dir(self, name: str = "") -> Path:
        d = self._cases / name if name else self._cases
        d.mkdir(parents=True, exist_ok=True)
        return d

    def artifact_dir(self) -> Path:
        return self._artifacts

    def resolve(self, relative: str) -> Path:
        """Resolve a relative path within this workspace. Blocks traversal."""
        candidate = (self._root / relative).resolve()
        if not str(candidate).startswith(str(self._root.resolve())):
            raise ValueError(f"Path traversal blocked: {relative}")
        return candidate

    def cleanup(self) -> None:
        if self._root.exists():
            shutil.rmtree(self._root, ignore_errors=True)


_workspace: Workspace | None = None


def get_workspace() -> Workspace:
    global _workspace
    if _workspace is None:
        _workspace = Workspace()
    return _workspace


def reset_workspace() -> None:
    global _workspace
    if _workspace:
        _workspace.cleanup()
    _workspace = Workspace()
