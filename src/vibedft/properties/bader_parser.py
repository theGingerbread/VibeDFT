"""Bader charge analyzer — parses ACF.dat from Bader analysis."""

from __future__ import annotations

from pathlib import Path

from vibedft.properties.base import PropertyResult


def analyze_bader(case_dir: Path) -> PropertyResult:
    """Parse Bader ACF.dat and compute charge transfer per atom.

    ACF.dat format (Henkelman Bader code)::

           #   X        Y        Z     CHARGE    MIN DIST   ATOMIC VOL
         ---- ------- ------- ------- ---------- ---------- -----------
            1  1.234   2.345   3.456    12.3456     1.2345    123.4567
           ...
        -------------------------------------------
          VACUUM CHARGE:    0.0123
          NUMBER OF ELECTRONS:   180.0000
    """
    result = PropertyResult(property_name="bader_charge")

    acf_files = list(case_dir.rglob("ACF.dat"))
    if not acf_files:
        result.status = "missing"
        result.insights.append("No ACF.dat found — run Bader analysis on charge density first.")
        return result

    for fp in acf_files[:1]:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        atoms: list[dict] = []
        in_table = False
        for line in text.splitlines():
            ls = line.strip()
            if ls.startswith("#") or ls.startswith("-"):
                in_table = True
                continue
            if not in_table or not ls:
                continue
            parts = ls.split()
            if len(parts) >= 5:
                try:
                    idx = int(parts[0])
                    charge = float(parts[4])
                    atoms.append({"index": idx, "bader_charge": charge})
                except (ValueError, IndexError):
                    continue

        if not atoms:
            continue

        # Compute charge transfer (reference: neutral atom charge = Z)
        # Without Z info, report raw charges
        total = sum(a["bader_charge"] for a in atoms)
        charges = [a["bader_charge"] for a in atoms]
        max_transfer = max(abs(c - (total / len(atoms))) for c in charges)

        result.status = "ok"
        result.data = {
            "n_atoms": len(atoms),
            "total_charge": round(total, 4),
            "max_charge_transfer": round(max_transfer, 3),
            "per_atom": atoms[:50],
        }
        result.source_files.append(str(fp))
        result.insights.append(
            f"Bader: {len(atoms)} atoms, total charge = {total:.3f}e, "
            f"max transfer = {max_transfer:.3f}e."
        )
        if max_transfer > 1.0:
            result.insights.append(
                f"Significant charge transfer detected ({max_transfer:.2f}e) — "
                "indicates ionic bonding character."
            )

    return result
