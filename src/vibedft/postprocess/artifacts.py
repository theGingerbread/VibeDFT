"""Artifact data model — the stable contract between postprocess and report.

Every Artifact carries full provenance so HTML / JSON / agent consumers can
trace each value back to its source file and parser.
"""

from __future__ import annotations

import base64
import io
import json as _json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import matplotlib.figure

ArtifactKind = Literal["figure", "table", "text", "json"]


@dataclass
class Artifact:
    """One post-processed result: a figure, table, text block, or raw JSON.

    All data is embedded (figures as base64 PNG), so the artifact is
    self-contained and serialisable to JSON.
    """

    id: str
    kind: ArtifactKind
    title: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    source_files: list[str] = field(default_factory=list)
    provenance: dict[str, str] = field(default_factory=dict)
    caption: str = ""

    # ── Convenience constructors ──

    @classmethod
    def figure(
        cls,
        id: str,
        title: str,
        fig: matplotlib.figure.Figure | None = None,
        *,
        source_files: list[str] | None = None,
        provenance: dict[str, str] | None = None,
        caption: str = "",
        png_base64: str = "",
    ) -> "Artifact":
        """Create a figure artifact from a matplotlib Figure or raw base64 PNG."""
        if fig is not None:
            png_base64 = _figure_to_base64(fig)
        return cls(
            id=id, kind="figure", title=title,
            data={"png_base64": png_base64},
            source_files=source_files or [],
            provenance=provenance or {},
            caption=caption,
        )

    @classmethod
    def table(
        cls,
        id: str,
        title: str,
        headers: list[str],
        rows: list[list[Any]],
        *,
        source_files: list[str] | None = None,
        provenance: dict[str, str] | None = None,
        caption: str = "",
    ) -> "Artifact":
        """Create a table artifact."""
        return cls(
            id=id, kind="table", title=title,
            data={"headers": headers, "rows": rows},
            source_files=source_files or [],
            provenance=provenance or {},
            caption=caption,
        )

    @classmethod
    def text(
        cls,
        id: str,
        title: str,
        body: str,
        *,
        source_files: list[str] | None = None,
        provenance: dict[str, str] | None = None,
    ) -> "Artifact":
        """Create a text artifact."""
        return cls(
            id=id, kind="text", title=title,
            data={"body": body},
            source_files=source_files or [],
            provenance=provenance or {},
        )

    @classmethod
    def json_artifact(
        cls,
        id: str,
        title: str,
        payload: dict[str, Any],
        *,
        source_files: list[str] | None = None,
        provenance: dict[str, str] | None = None,
    ) -> "Artifact":
        """Create a JSON data artifact."""
        return cls(
            id=id, kind="json", title=title,
            data=payload,
            source_files=source_files or [],
            provenance=provenance or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "data": self.data,
            "source_files": self.source_files,
            "provenance": self.provenance,
            "caption": self.caption,
        }


def _figure_to_base64(fig: matplotlib.figure.Figure) -> str:
    """Encode a matplotlib Figure as a base64 PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")
