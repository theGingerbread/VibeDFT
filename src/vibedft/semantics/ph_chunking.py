"""PH chunking analysis — detect parallel ph.x job splitting via start_q/last_q."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PhChunk:
    file: str
    start_q: int = 0
    last_q: int = 0


@dataclass
class PhChunkingPlan:
    chunks: list[PhChunk] = field(default_factory=list)
    total_q_points: int = 0
    is_chunked: bool = False
    chunk_count: int = 0
    coverage: str = "unknown"          # "complete" | "gaps" | "overlap" | "unknown"
    missing_q: list[int] = field(default_factory=list)
    overlap_q: list[int] = field(default_factory=list)
    summary: str = ""
    warnings: list[str] = field(default_factory=list)


def analyze_ph_chunking(case_dir: Path | str) -> PhChunkingPlan:
    """Detect parallel ph.x chunking from start_q/last_q across input files."""
    d = Path(case_dir)
    plan = PhChunkingPlan()

    from vibedft.parsers.qe_input_parser import parse_qe_input

    for in_file in sorted(d.rglob("*.in")):
        try:
            qe = parse_qe_input(in_file)
        except Exception:
            continue

        sq = qe.get_param("inputph", "start_q", None)
        lq = qe.get_param("inputph", "last_q", None)
        if sq is not None and lq is not None:
            try:
                plan.chunks.append(PhChunk(
                    file=str(in_file.relative_to(d)) if in_file.is_relative_to(d) else in_file.name,
                    start_q=int(sq), last_q=int(lq),
                ))
            except (ValueError, TypeError):
                pass

    if len(plan.chunks) <= 1:
        plan.is_chunked = False
        plan.summary = "Single ph.x job or no chunking detected."
        return plan

    plan.is_chunked = True
    plan.chunk_count = len(plan.chunks)
    plan.chunks.sort(key=lambda c: c.start_q)

    # Check for gaps and overlaps
    covered: set[int] = set()
    for c in plan.chunks:
        for q in range(c.start_q, c.last_q + 1):
            if q in covered:
                plan.overlap_q.append(q)
            covered.add(q)

    if plan.chunks:
        min_q = min(c.start_q for c in plan.chunks)
        max_q = max(c.last_q for c in plan.chunks)
        expected = set(range(min_q, max_q + 1))
        plan.missing_q = sorted(expected - covered)
        plan.total_q_points = max_q - min_q + 1

    if plan.missing_q:
        plan.coverage = "gaps"
        plan.warnings.append(f"Missing q-points: {plan.missing_q}")
    elif plan.overlap_q:
        plan.coverage = "overlap"
        plan.warnings.append(f"Overlapping q-points: {plan.overlap_q}")
    else:
        plan.coverage = "complete"

    # Summary
    parts = [f"{plan.chunk_count} ph.x chunks covering q={min_q}–{max_q} ({plan.total_q_points} irreducible points)"]
    if plan.coverage == "complete":
        parts.append("— complete coverage, no gaps.")
    elif plan.coverage == "gaps":
        parts.append(f"— MISSING q-points: {plan.missing_q}.")
    plan.summary = " ".join(parts)

    return plan
