"""Archive bridge: VibeDFT case → DFT results structured archive.

Enforces light-file policy, preserves provenance, and maps output files to
the DFT-standard results directory layout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Archive file policy
# ---------------------------------------------------------------------------

# Files that must NEVER be archived (heavy intermediates)
ARCHIVE_EXCLUDES = {
    "out/", "out_scf/", "out_nscf/",
    "*.save/", "_ph0/",
    "*.wfc*", "*.igk*", "*.bfgs",
    "elph_dir/",
    "CHGCAR", "WAVECAR",
    "*.xml",
}

# Stage to subdirectory mapping
STAGE_DIRS = {
    "rx": "RX",
    "scf_dos": "Bands_dos",
    "bands": "Bands_dos",
    "ph": "PH",
    "tc": "Tc",
    "epc": "EPC",
    "fs": "Fermi",
}

# Lightweight files to archive per stage
STAGE_ARTIFACTS: dict[str, dict[str, list[tuple[str, str]]]] = {
    "rx": {
        "required": [
            ("rx.out", "data/"),
        ],
        "optional": [
            ("*_structure.block", "data/"),
        ],
    },
    "scf_dos": {
        "required": [
            ("scf.out", "data/"),
        ],
        "optional": [
            ("*.dos", "data/"),
            ("*pdos_tot", "data/"),
            ("*pdos_atm*", "data/"),
        ],
    },
    "bands": {
        "required": [],
        "optional": [
            ("*.bands*", "data/"),
            ("*.gnu", "data/"),
            ("*.png", "Plot/"),
        ],
    },
    "ph": {
        "required": [
            ("*.freq.gp", "data/"),
        ],
        "optional": [
            ("*.fc", "data/"),
            ("*.phdos*", "data/"),
            ("*.png", "Plot/"),
        ],
    },
    "tc": {
        "required": [
            ("lambdax.out", "data/"),
        ],
        "optional": [
            ("lambda.dat", "data/"),
            ("tc_*.png", "Plot/"),
        ],
    },
    "epc": {
        "required": [
            ("alpha2F.dat", "data/"),
        ],
        "optional": [
            ("lambda.dat", "data/"),
            ("lambda", "data/"),
            ("elph.gamma.*", "data/"),
            ("elph.inp_lambda.*", "data/"),
            ("*.png", "Plot/"),
        ],
    },
    "fs": {
        "required": [],
        "optional": [
            ("*.bxsf", "data/"),
            ("*.png", "Plot/"),
        ],
    },
}


# ---------------------------------------------------------------------------
# Archive plan model
# ---------------------------------------------------------------------------


@dataclass
class ArchiveAction:
    """Single archive action: copy a file from source to target."""

    source: Path
    target: Path
    stage: str
    reason: str = ""


@dataclass
class ArchivePlan:
    """A sequence of archive copy actions."""

    case_dir: Path
    target_root: Path
    system: str
    material: str
    route: str
    actions: list[ArchiveAction] = field(default_factory=list)
    excluded: list[Path] = field(default_factory=list)

    @property
    def n_files(self) -> int:
        return len(self.actions)

    def summary(self) -> str:
        lines = [
            f"Archive Plan: {self.case_dir.name}",
            f"  System:   {self.system}",
            f"  Material: {self.material}",
            f"  Route:    {self.route}",
            f"  Target:   {self.target_root / self.system / self.material / self.route}",
            f"",
            f"  Files to archive: {self.n_files}",
        ]
        for a in self.actions:
            lines.append(f"    {a.stage:12s} {a.source.name:30s} → {a.target}")

        # Completeness check: compare against STAGE_ARTIFACTS whitelist
        present_stages = set(a.stage for a in self.actions)
        missing_required = []
        missing_optional = []
        for stage_code, level_dict in STAGE_ARTIFACTS.items():
            if stage_code in present_stages:
                stage_actions = [a for a in self.actions if a.stage == stage_code]
                for level_name, patterns in [("required", level_dict.get("required", [])),
                                              ("optional", level_dict.get("optional", []))]:
                    for pat, _subdir in patterns:
                        if not pat.startswith("*"):
                            matched = any(a.source.name == pat for a in stage_actions)
                        else:
                            matched = any(a.source.match(pat) for a in stage_actions)
                        if not matched:
                            target_list = missing_required if level_name == "required" else missing_optional
                            target_list.append(f"{stage_code}/{pat}")

        if missing_required:
            lines.append(f"")
            lines.append(f"  ⚠ Missing required artifacts ({len(missing_required)}):")
            for m in missing_required[:8]:
                lines.append(f"    ❌ {m}")
            if len(missing_required) > 8:
                lines.append(f"    ... and {len(missing_required) - 8} more")
        if missing_optional:
            lines.append(f"")
            lines.append(f"  ℹ Optional artifacts not found ({len(missing_optional)}):")
            for m in missing_optional[:8]:
                lines.append(f"    ? {m}")
            if len(missing_optional) > 8:
                lines.append(f"    ... and {len(missing_optional) - 8} more")

        if self.excluded:
            lines.append(f"")
            lines.append(f"  Excluded (heavy): {len(self.excluded)}")
            for e in self.excluded[:5]:
                lines.append(f"    ✗ {e.name}")
            if len(self.excluded) > 5:
                lines.append(f"    ... and {len(self.excluded) - 5} more")
        return "\n".join(lines)


def build_archive_plan(
    case_dir: Path | str,
    *,
    system: str = "HfX2",
    material: str = "HfBr2",
    route: str = "dopping",
    target_root: Path | str = "<DFT_RESULTS_DIR>",  # Placeholder — override when calling
) -> ArchivePlan:
    """Build an archive plan mapping case outputs to DFT results layout."""
    d = Path(case_dir).resolve()
    target = Path(target_root) / system / material / route

    plan = ArchivePlan(
        case_dir=d,
        target_root=Path(target_root),
        system=system,
        material=material,
        route=route,
    )

    output_dir = d / "output"
    if not output_dir.is_dir():
        return plan

    # Scan output files recursively and classify by stage
    all_files = list(output_dir.rglob("*"))
    for f in all_files:
        if not f.is_file():
            continue

        # Preserve relative path from output/ for stage subdirectories
        rel = f.relative_to(output_dir)

        # Check excludes
        excluded = False
        for pat in ARCHIVE_EXCLUDES:
            if pat.startswith("*"):
                if f.match(pat):
                    excluded = True
                    break
            elif pat.endswith("/"):
                # Directory pattern — match only as a full path component
                dir_name = pat.strip("/")
                if dir_name in f.parts:
                    excluded = True
                    break
            elif f.name == pat or f.match(pat):
                excluded = True
                break

        if excluded:
            plan.excluded.append(f)
            continue

        # Classify by parent dir + filename — preserve relative subdirectory from output/
        rel_parent = str(rel.parent) if str(rel.parent) != "." else ""
        stage = _classify_file(f.name, rel_parent=rel_parent)
        if stage:
            subdir = STAGE_DIRS.get(stage, "misc")
            dest = target / subdir / "data" / rel_parent / f.name
            plan.actions.append(
                ArchiveAction(
                    source=f,
                    target=dest,
                    stage=stage,
                    reason=f"Stage: {stage}" + (f" (from {rel_parent})" if rel_parent else ""),
                )
            )
        else:
            # Unclassified lightweight file — archive to root data/
            dest = target / "data" / rel_parent / f.name
            plan.actions.append(
                ArchiveAction(
                    source=f,
                    target=dest,
                    stage="misc",
                    reason="Unclassified output" + (f" (from {rel_parent})" if rel_parent else ""),
                )
            )

    # Also archive vibedft.case.yaml and calculation log
    for meta_file in ["vibedft.case.yaml"]:
        mf = d / meta_file
        if mf.is_file():
            plan.actions.append(
                ArchiveAction(
                    source=mf,
                    target=target / "provenance" / meta_file,
                    stage="provenance",
                    reason="Case provenance",
                )
            )

    log_file = d / "logs" / "calculation.md"
    if log_file.is_file():
        plan.actions.append(
            ArchiveAction(
                source=log_file,
                target=target / "provenance" / "calculation.md",
                stage="provenance",
                reason="Calculation log",
            )
        )

    return plan


def _classify_file(filename: str, rel_parent: str = "") -> str | None:
    """Classify a file into an archive stage based on its parent directory and name.

    *rel_parent* is the relative path from the output/ root (e.g. "epc", "ph64").
    Parent directory takes priority over filename heuristics, since subdirectory
    organisation reflects the workflow stage that produced the file.
    """
    name = filename.lower()
    parent = rel_parent.lower().rstrip("/")

    # ── Parent-directory-based classification (highest priority) ──
    parent_stage_map = {
        "rx": "rx",
        "scf_dos": "scf_dos",
        "bands": "bands",
        "ph": "ph", "ph64": "ph", "ph96": "ph", "sc_ph48": "ph", "sc_ph64": "ph",
        "tc": "tc",
        "epc": "epc",
        "fs": "fs", "fermi": "fs",
    }
    # Check each path component
    for part in parent.split("/"):
        part_clean = part.strip()
        if part_clean in parent_stage_map:
            return parent_stage_map[part_clean]

    # ── Filename-based fallback ──
    if "rx" in name and ("out" in name or "structure" in name):
        return "rx"
    if "scf" in name and "out" in name:
        return "scf_dos"
    if name.endswith(".dos") or "pdos" in name:
        return "scf_dos"
    if "bands" in name or name.endswith(".gnu"):
        return "bands"
    if "freq" in name or name.endswith(".fc"):
        return "ph"
    if "matdyn" in name and "dos" in name:
        return "ph"
    # Only match "lambda" as tc when NOT in an epc/ph context (handled above)
    if "lambdax" in name:
        return "tc"
    if "lambda" in name and "alpha2f" not in name:
        return "tc"
    if "alpha2f" in name or "a2f" in name:
        return "epc"
    if "bxsf" in name or "fermi" in name:
        return "fs"
    if name.endswith(".png"):
        if "tc_" in name:
            return "tc"
        if "epc" in name or "lambda" in name:
            return "epc"
        if "phdisp" in name or "phdos" in name:
            return "ph"
        if "bands" in name or "dos" in name:
            return "bands"
        if "fermi" in name or "fs" in name:
            return "fs"

    return None


def apply_archive(
    case_dir: Path | str,
    *,
    target_root: Path | str,
    dry_run: bool = False,
    system: str = "HfX2",
    material: str = "HfBr2",
    route: str = "dopping",
) -> str:
    """Apply an archive plan (copy files to target).

    Returns a human-readable report.
    """
    plan = build_archive_plan(
        case_dir=case_dir,
        system=system,
        material=material,
        route=route,
        target_root=target_root,
    )

    lines = []
    copied = 0
    skipped = 0

    for action in plan.actions:
        if dry_run:
            lines.append(f"  [DRY-RUN] {action.source.name} → {action.target}")
            copied += 1
        else:
            action.target.parent.mkdir(parents=True, exist_ok=True)
            try:
                import shutil
                shutil.copy2(action.source, action.target)
                lines.append(f"  ✅ {action.source.name} → {action.target}")
                copied += 1
            except OSError as exc:
                lines.append(f"  ❌ {action.source.name}: {exc}")
                skipped += 1

    lines.insert(0, f"Archive {'(DRY-RUN) ' if dry_run else ''}Report:")
    lines.insert(1, f"  Copied: {copied}, Skipped: {skipped}, Excluded: {len(plan.excluded)}")
    lines.insert(2, "")

    # Write provenance
    provenance_path = Path(target_root) / system / material / route / "provenance" / "archive.provenance.yaml"
    if not dry_run:
        provenance_path.parent.mkdir(parents=True, exist_ok=True)
        import yaml
        from datetime import datetime, timezone
        prov = {
            "source_case": str(Path(case_dir).resolve()),
            "target": str(provenance_path.parent.parent),
            "system": system,
            "material": material,
            "route": route,
            "files_copied": copied,
            "files_skipped": skipped,
            "heavy_excluded": len(plan.excluded),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        provenance_path.write_text(
            yaml.safe_dump(prov, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        lines.append(f"  Provenance: {provenance_path}")

    return "\n".join(lines)
