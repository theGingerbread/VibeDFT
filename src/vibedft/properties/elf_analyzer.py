"""ELF (Electron Localization Function) analyzer — 2D visualization."""

from __future__ import annotations

from pathlib import Path

from vibedft.properties.base import PropertyResult


def analyze_elf(case_dir: Path) -> PropertyResult:
    """Analyze ELF output from pp.x.

    Expected files:
      - *.elf (3D ELF on grid, XCrySDen format)
      - *.elf2d (2D slice — preferred for 2D materials)
    """
    result = PropertyResult(property_name="elf")

    elf_files = list(case_dir.rglob("*.elf2d")) + list(case_dir.rglob("*.elf"))
    if not elf_files:
        result.status = "missing"
        result.insights.append("No .elf or .elf2d file found — run pp.x with plot_num=8.")
        return result

    for fp in elf_files[:1]:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        elf_values: list[float] = []
        nx, ny, nz = 0, 0, 0
        for line in text.splitlines():
            ls = line.strip()
            if not ls or ls.startswith("#") or ls.startswith("BEGIN") or ls.startswith("END"):
                continue
            # Grid dimensions line
            parts = ls.split()
            if len(parts) == 3 and nx == 0:
                try:
                    nx, ny, nz = int(parts[0]), int(parts[1]), int(parts[2])
                except ValueError:
                    pass
                continue
            # Data lines
            for val in parts:
                try:
                    elf_values.append(float(val))
                except ValueError:
                    continue

        if not elf_values:
            continue

        elf_min = min(elf_values)
        elf_max = max(elf_values)
        elf_mean = sum(elf_values) / len(elf_values)

        # ELF interpretation
        # ELF ≈ 1.0 → strongly localized (covalent bonds, lone pairs)
        # ELF ≈ 0.5 → electron-gas-like (metallic)
        # ELF ≈ 0.0 → very low density (vacuum, interstitial)
        n_localized = sum(1 for v in elf_values if v > 0.8)
        fraction_localized = n_localized / len(elf_values) if elf_values else 0.0

        result.status = "ok"
        result.data = {
            "grid": f"{nx}×{ny}×{nz}" if nx else "unknown",
            "elf_min": round(elf_min, 4),
            "elf_max": round(elf_max, 4),
            "elf_mean": round(elf_mean, 4),
            "fraction_localized": round(fraction_localized, 3),
            "n_points": len(elf_values),
        }
        result.source_files.append(str(fp))

        if fraction_localized > 0.3:
            result.insights.append(
                f"Strong covalent character: {fraction_localized*100:.0f}% of grid points "
                "show ELF > 0.8 (high localization)."
            )
        elif fraction_localized > 0.1:
            result.insights.append(
                f"Mixed bonding: {fraction_localized*100:.0f}% localized regions. "
                "Typical for polar-covalent 2D materials."
            )
        else:
            result.insights.append(
                "Predominantly metallic/ionic bonding — low electron localization."
            )

    return result
