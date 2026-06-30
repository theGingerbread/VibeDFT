"""Unified Analyzer ABC and section-result protocol (ROADMAP §3.1).

Every physics analyzer subclasses ``Analyzer`` and exposes a uniform
``discover → parse → summarize → insights → plots → provenance`` pipeline.
``run_analyzer`` wires the steps together into a ``SectionResult`` that the
report layer (and future orchestrator migration) can consume directly.

The existing module-level ``extract_*`` / ``analyze_*`` functions are NOT
removed — concrete analyzers wrap them, so the orchestrator and tests keep
working unchanged.
"""

from __future__ import annotations

import fnmatch
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibedft.analyzers.physics_models import PhysicsInsight


# ═══════════════════════════════════════════════════════════════════════════════
# Section result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SectionResult:
    """Unified output of one analyzer run.

    Fields mirror the section object shape from ROADMAP §3.
    """

    section_id: str
    status: str = "missing"  # pass | warn | fail | missing
    data: dict[str, Any] = field(default_factory=dict)
    insights: list[PhysicsInsight] = field(default_factory=list)
    plots: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "status": self.status,
            "data": _json_clean(self.data),
            "insights": [
                {
                    "id": i.id,
                    "category": i.category,
                    "level": i.level.value if hasattr(i.level, "value") else str(i.level),
                    "message": i.message,
                    "detail": i.detail,
                    "evidence": [
                        {
                            "source_file": e.source_file,
                            "parser": e.parser,
                            "key": e.key,
                            "value": str(e.value),
                        }
                        for e in i.evidence
                    ],
                }
                for i in self.insights
            ],
            "plots": _json_clean(self.plots),
            "provenance": _json_clean(self.provenance),
        }


def _json_clean(obj: Any) -> Any:
    """Recursively coerce non-JSON-native values to JSON-safe forms."""
    if isinstance(obj, dict):
        return {str(k): _json_clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_clean(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


# ═══════════════════════════════════════════════════════════════════════════════
# Analyzer ABC
# ═══════════════════════════════════════════════════════════════════════════════


class Analyzer(ABC):
    """Abstract base class for all physics analyzers.

    Concrete subclasses declare the file globs they consume and implement
    the six pipeline methods. ``run_analyzer`` orchestrates the calls.
    """

    id: str = ""
    label: str = ""
    required_patterns: list[str] = []
    optional_patterns: list[str] = []

    # Instance state populated by ``run_analyzer`` before the pipeline runs.
    case_dir: Path | None = None
    matched_files: list[Path] = []
    score: float = 0.0

    @abstractmethod
    def discover(self, files: list[Path]) -> list[Path]:
        """Filter ``files`` down to those this analyzer consumes."""

    @abstractmethod
    def parse(self) -> dict[str, Any]:
        """Parse matched files into a dict of key fields."""

    @abstractmethod
    def summarize(self) -> dict[str, Any]:
        """Return a short status + summary dict (``status``, ...)."""

    @abstractmethod
    def insights(self) -> list[PhysicsInsight]:
        """Produce physics insights for this section."""

    @abstractmethod
    def plots(self) -> list[dict[str, Any]]:
        """Return artifact dicts (id/type/data_ref). Empty until Sprint 3."""

    @abstractmethod
    def provenance(self) -> dict[str, Any]:
        """Return parser + source_files provenance for this section."""


# ═══════════════════════════════════════════════════════════════════════════════
# Pattern matching helper
# ═══════════════════════════════════════════════════════════════════════════════


def _match_files(files: list[Path], patterns: list[str]) -> list[Path]:
    """Return files matching any of the glob ``patterns`` (``**`` aware)."""
    matched: list[Path] = []
    for f in files:
        rel_name = f.name
        rel_str = str(f)
        for pat in patterns:
            if pat.startswith("**/"):
                if fnmatch.fnmatch(rel_name, pat[3:]):
                    matched.append(f)
                    break
            elif fnmatch.fnmatch(rel_str, pat) or fnmatch.fnmatch(rel_name, pat):
                matched.append(f)
                break
    return matched


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════


def run_analyzer(analyzer: Analyzer, case_dir: Path | str) -> SectionResult:
    """Run the full analyzer pipeline and assemble a ``SectionResult``."""
    case_dir = Path(case_dir)
    analyzer.case_dir = case_dir
    analyzer.matched_files = []

    files = sorted(p for p in case_dir.rglob("*") if p.is_file())
    matched = analyzer.discover(files)
    analyzer.matched_files = matched

    data = analyzer.parse()
    summary = analyzer.summarize()
    insights = analyzer.insights()
    plots = analyzer.plots()
    prov = analyzer.provenance()

    status = summary.get("status", "missing") if isinstance(summary, dict) else "missing"
    if not matched and status == "pass":
        status = "missing"

    return SectionResult(
        section_id=analyzer.id,
        status=status,
        data=data if isinstance(data, dict) else {},
        insights=insights if isinstance(insights, list) else [],
        plots=plots if isinstance(plots, list) else [],
        provenance=prov if isinstance(prov, dict) else {},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════════════


_ANALYZER_REGISTRY: list[type[Analyzer]] = []
_AUTO_DISCOVERED = False


def _auto_discover() -> None:
    """Import all analyzer modules so their @register_analyzer decorators run.

    Without this, ``get_all_analyzers()`` returns an empty list when the
    caller only imported ``base`` (the decorators run at import time of the
    subclass modules). We walk the ``analyzers`` package once and import any
    module whose name ends in ``_analyzer``.
    """
    global _AUTO_DISCOVERED
    if _AUTO_DISCOVERED:
        return
    _AUTO_DISCOVERED = True
    import importlib
    import pkgutil
    from vibedft import analyzers as _pkg
    for mod in pkgutil.iter_modules(_pkg.__path__):
        if mod.name == "base":
            continue
        if mod.name.endswith("_analyzer") or mod.name.endswith("_analyzers"):
            try:
                importlib.import_module(f"vibedft.analyzers.{mod.name}")
            except Exception:
                pass


def register_analyzer(cls: type[Analyzer]) -> type[Analyzer]:
    """Decorator: register an ``Analyzer`` subclass in the global registry."""
    if not isinstance(cls, type) or not issubclass(cls, Analyzer):
        raise TypeError("register_analyzer expects an Analyzer subclass")
    if cls not in _ANALYZER_REGISTRY:
        _ANALYZER_REGISTRY.append(cls)
    return cls


def get_all_analyzers() -> list[type[Analyzer]]:
    """Return a copy of the registered analyzer classes.

    Triggers auto-discovery on first call so that simply importing
    ``vibedft.analyzers.base`` is enough to see all registered analyzers.
    """
    _auto_discover()
    return list(_ANALYZER_REGISTRY)


__all__ = [
    "Analyzer",
    "SectionResult",
    "run_analyzer",
    "register_analyzer",
    "get_all_analyzers",
]