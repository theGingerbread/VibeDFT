#!/usr/bin/env python3
"""VibeDFT documentation/workflow health checks for the external reorg frame."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def collect_markdown_docs(docs_root: Path) -> set[str]:
    return {p.relative_to(docs_root).as_posix() for p in docs_root.rglob("*.md")}


def collect_index_entries(index_path: Path) -> set[str]:
    text = load_text(index_path)
    links = set()
    for match in re.finditer(r"\(([^)]+)\)", text):
        target = match.group(1).strip()
        if target.startswith("http://") or target.startswith("https://"):
            continue
        if target.startswith("#") or target.startswith("mailto:"):
            continue
        clean = target.split(":")[0] if target.startswith("file:") else target
        clean = clean.strip()
        if clean.startswith("<") and clean.endswith(">"):
            clean = clean[1:-1]
        if clean.endswith(":"):
            clean = clean[:-1]
        if clean.startswith("docs/"):
            clean = clean.removeprefix("docs/")
        if clean.startswith("./"):
            clean = clean.removeprefix("./")
        if clean.startswith("../"):
            continue
        if clean and not clean.endswith(".md"):
            continue
        if clean == "INDEX.md":
            continue
        links.add(clean)
    return links


def extract_stage_ids(text: str) -> set[str]:
    pattern = re.compile(r"(?<![\w])\d{2}_[a-z0-9_]+\b(?![\w])")
    return {m.group(0) for m in pattern.finditer(text)}


def read_stage_ids(stages_path: Path) -> set[str]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyYAML unavailable; cannot parse workflows/stages.yaml") from exc

    data = yaml.safe_load(load_text(stages_path))
    stage_ids = set()
    for stage in data.get("stages", []):
        sid = stage.get("stage_id")
        if sid:
            stage_ids.add(sid)
    return stage_ids


def audit_cases(cases_root: Path, stage_ids: set[str]) -> dict:
    """Audit case directory layouts outside the paper directory."""

    results = []
    canonical_cases = 0
    custom_layout_cases = 0

    for case_root in sorted((p for p in cases_root.iterdir() if p.is_dir() and not p.name.startswith(".")), key=lambda p: p.name):
        direct_stage_dirs = [p for p in case_root.iterdir() if p.is_dir() and p.name in stage_ids]
        nested_stage_dirs = [
            p
            for p in case_root.rglob("*")
            if p.is_dir() and p.name in stage_ids and p.parent != case_root
        ]
        stage_dirs_found = {p.name for p in direct_stage_dirs} | {p.name for p in nested_stage_dirs}
        missing_stages = sorted(stage_ids - stage_dirs_found)
        is_canonical_21 = len(direct_stage_dirs) == len(stage_ids) and not nested_stage_dirs
        layout = {
            "case": case_root.name,
            "direct_stage_count": len(direct_stage_dirs),
            "nested_stage_count": len(nested_stage_dirs),
            "covered_stages": len(stage_dirs_found),
            "missing_stages_count": len(missing_stages),
            "is_canonical_21": is_canonical_21,
        }

        if is_canonical_21:
            canonical_cases += 1
        else:
            custom_layout_cases += 1
            layout["sample_missing_stages"] = missing_stages[:6]

        results.append(layout)

    return {
        "total_cases": len(results),
        "canonical_full": canonical_cases,
        "noncanonical": custom_layout_cases,
        "cases": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VibeDFT reorg health checks.")
    parser.add_argument("--docs-root", default="docs", type=Path)
    parser.add_argument("--index", default="docs/INDEX.md", type=Path)
    parser.add_argument(
        "--stages",
        default="workflows/stages.yaml",
        type=Path,
        help="Canonical workflow definition file",
    )
    parser.add_argument(
        "--stage-map",
        default="docs/reference/physics_layer_stage_map_v2.md",
        type=Path,
        help="Physics-layer mapping document",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON summary",
    )
    parser.add_argument(
        "--skip-cases",
        action="store_true",
        help="Skip case-layout audit (docs/stage checks only)",
    )
    return parser.parse_args()


def run_checks(
    docs_root: Path,
    index_path: Path,
    stages_path: Path,
    stage_map_path: Path,
    skip_cases: bool = False,
) -> dict:
    docs = collect_markdown_docs(docs_root)
    index_entries = collect_index_entries(index_path)
    stage_ids = read_stage_ids(stages_path)
    stage_map_text = load_text(stage_map_path)
    mapped_ids = extract_stage_ids(stage_map_text)

    # exclude the root index itself and any potential docs-only artifacts
    docs_with_expected_index = {p for p in docs if p != "INDEX.md"}

    missing_in_index = sorted(docs_with_expected_index - index_entries)
    unknown_in_index = sorted(index_entries - docs_with_expected_index)

    missing_stages_in_map = sorted(stage_ids - mapped_ids)
    extra_map_stages = sorted(mapped_ids - stage_ids)
    case_audit = audit_cases(Path("cases"), stage_ids) if not skip_cases else None
    status = "PASS"
    if missing_in_index or missing_stages_in_map:
        status = "FAIL"

    unknown_in_index_set = set(unknown_in_index)

    return {
        "status": status,
        "docs": {
            "total": len(docs_with_expected_index),
            "indexed": len(index_entries - unknown_in_index_set),
            "missing_in_index": missing_in_index,
            "unknown_in_index": unknown_in_index,
        },
        "stages": {
            "canonical_count": len(stage_ids),
            "mapped_count": len(mapped_ids.intersection(stage_ids)),
            "missing_in_map": missing_stages_in_map,
            "extra_map_stages": extra_map_stages,
        },
        "cases": case_audit,
        "checks": {
            "docs_index_complete": not missing_in_index and not unknown_in_index,
            "stage_map_complete": not missing_stages_in_map,
            "case_layout_audit_enabled": not skip_cases,
        },
    }


def main() -> int:
    args = parse_args()
    summary = run_checks(
        docs_root=args.docs_root,
        index_path=args.index,
        stages_path=args.stages,
        stage_map_path=args.stage_map,
        skip_cases=args.skip_cases,
    )

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Status: {summary['status']}")
        print(
            "Docs indexed: "
            f"{summary['docs']['indexed']}/{summary['docs']['total']} "
            f"(missing={len(summary['docs']['missing_in_index'])}, "
            f"unknown={len(summary['docs']['unknown_in_index'])})"
        )
        print(
            "Stages mapped: "
            f"{summary['stages']['mapped_count']}/{summary['stages']['canonical_count']} "
            f"(missing={len(summary['stages']['missing_in_map'])}, "
            f"extra={len(summary['stages']['extra_map_stages'])})"
        )

        if summary["docs"]["missing_in_index"]:
            print("  Missing docs in INDEX.md:")
            for item in summary["docs"]["missing_in_index"]:
                print(f"   - {item}")
        if summary["docs"]["unknown_in_index"]:
            print("  Unknown docs listed in INDEX.md:")
            for item in summary["docs"]["unknown_in_index"]:
                print(f"   - {item}")

        if summary["stages"]["missing_in_map"]:
            print("  Stage IDs in stages.yaml not present in stage map:")
            for item in summary["stages"]["missing_in_map"]:
                print(f"   - {item}")
        if summary["stages"]["extra_map_stages"]:
            print("  Stage-like IDs in map not in stages.yaml:")
            for item in summary["stages"]["extra_map_stages"]:
                print(f"   - {item}")
        if not args.skip_cases:
            cases = summary["cases"] or {}
            print(
                "Case layouts: "
                f"{cases.get('canonical_full', 0)} canonical / "
                f"{cases.get('noncanonical', 0)} custom / "
                f"{cases.get('total_cases', 0)} total"
            )
            for item in cases.get("cases", []):
                if not item["is_canonical_21"]:
                    print(
                        "  - {case}: direct={direct}, nested={nested}, missing={missing}".format(
                            case=item["case"],
                            direct=item["direct_stage_count"],
                            nested=item["nested_stage_count"],
                            missing=item["missing_stages_count"],
                        )
                    )

    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
