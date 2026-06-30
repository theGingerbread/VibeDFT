"""Extract q-resolved EPC data from QE ``elph.inp_lambda.*`` files.

This is the alternative route when ``elph.gamma.*`` files are missing.
It reads the per-mode λ/γ values that lambda.x uses internally, and
optionally performs a closure check against ``lambda.dat``.

Migrated from ``~/Documents/DFT/scripts/extract_lambda_qv_from_elph_inputs.py``.
"""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path

RY_TO_THZ = 3289.841960


@dataclass
class Section:
    broadening_label: str
    dos: float
    lambdas: list[float]
    gammas: list[float]


@dataclass
class QPointData:
    q_index: int
    qx: float
    qy: float
    qz: float
    omega_thz: list[float]
    sections: list[Section]


SECTION_RE = re.compile(r"Gaussian Broadening:\s*([0-9Ee.+-]+)\s*Ry")
DOS_RE = re.compile(r"DOS\s*=\s*([0-9Ee.+-]+)")
MODE_RE = re.compile(
    r"lambda\(\s*(\d+)\s*\)\s*=\s*([0-9Ee.+-]+)\s+gamma=\s*([0-9Ee.+-]+)\s+GHz"
)


# ── public API ──


def sorted_elph_inputs(elph_dir: Path) -> list[Path]:
    files = sorted(
        elph_dir.glob("elph.inp_lambda.*"),
        key=lambda p: int(p.name.rsplit(".", 1)[-1]),
    )
    if not files:
        raise FileNotFoundError(f"No elph.inp_lambda.* files found in {elph_dir}")
    return files


def parse_elph_input(path: Path, q_index: int) -> QPointData:
    lines = [line.rstrip("\n") for line in path.read_text().splitlines() if line.strip()]
    header = lines[0].split()
    if len(header) < 5:
        raise ValueError(f"Malformed header in {path}")

    qx, qy, qz = map(float, header[:3])
    n_broad = int(header[3])
    n_mode = int(header[4])

    cursor = 1
    omega_sq: list[float] = []
    while len(omega_sq) < n_mode and cursor < len(lines):
        omega_sq.extend(float(tok) for tok in lines[cursor].split())
        cursor += 1
    if len(omega_sq) < n_mode:
        raise ValueError(f"Failed to read {n_mode} phonon frequencies from {path}")
    omega_sq = omega_sq[:n_mode]

    omega_thz = []
    for value in omega_sq:
        if value >= 0.0:
            omega_thz.append(math.sqrt(value) * RY_TO_THZ)
        else:
            omega_thz.append(-math.sqrt(abs(value)) * RY_TO_THZ)

    sections: list[Section] = []
    while cursor < len(lines):
        broad_match = SECTION_RE.search(lines[cursor])
        if not broad_match:
            cursor += 1
            continue
        broadening_label = broad_match.group(1)
        cursor += 1

        if cursor >= len(lines):
            raise ValueError(f"Unexpected EOF after broadening line in {path}")
        dos_match = DOS_RE.search(lines[cursor])
        if not dos_match:
            raise ValueError(f"Missing DOS line after broadening section in {path}")
        dos = float(dos_match.group(1))
        cursor += 1

        lambdas = [0.0] * n_mode
        gammas = [0.0] * n_mode
        seen_modes = 0
        while seen_modes < n_mode and cursor < len(lines):
            mode_match = MODE_RE.search(lines[cursor])
            if not mode_match:
                raise ValueError(f"Malformed mode line in {path}: {lines[cursor]}")
            mode_idx = int(mode_match.group(1)) - 1
            lambdas[mode_idx] = float(mode_match.group(2))
            gammas[mode_idx] = float(mode_match.group(3))
            seen_modes += 1
            cursor += 1

        sections.append(
            Section(
                broadening_label=broadening_label,
                dos=dos,
                lambdas=lambdas,
                gammas=gammas,
            )
        )

    if len(sections) != n_broad:
        raise ValueError(
            f"{path} declares {n_broad} broadenings but {len(sections)} were parsed"
        )

    return QPointData(
        q_index=q_index,
        qx=qx,
        qy=qy,
        qz=qz,
        omega_thz=omega_thz,
        sections=sections,
    )


def parse_lambda_dat(path: Path, row_index: int) -> dict[str, float]:
    rows: list[tuple[float, float, float, float, float]] = []
    for line in Path(path).read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        degauss, lambd, int_a2f, omega_log, nef = map(float, stripped.split())
        rows.append((degauss, lambd, int_a2f, omega_log, nef))
    if row_index < 1 or row_index > len(rows):
        raise ValueError(f"row-index {row_index} is outside lambda.dat row range 1..{len(rows)}")
    degauss, lambd, int_a2f, omega_log, nef = rows[row_index - 1]
    return {
        "degauss": degauss,
        "lambda": lambd,
        "int_alpha2F": int_a2f,
        "omega_log": omega_log,
        "nef": nef,
    }


def parse_lambdax_q_weights(path: Path) -> list[tuple[float, float, float, float]]:
    lines = [line.strip() for line in Path(path).read_text().splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError(f"Malformed lambdax.in: {path}")

    try:
        n_q = int(lines[1].split()[0])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"Failed to parse q-point count from {path}") from exc

    q_lines = lines[2 : 2 + n_q]
    if len(q_lines) != n_q:
        raise ValueError(f"{path} declares {n_q} q-points but only {len(q_lines)} were found")

    weights: list[tuple[float, float, float, float]] = []
    for line in q_lines:
        parts = line.split()
        if len(parts) < 4:
            raise ValueError(f"Malformed q-point line in {path}: {line}")
        qx, qy, qz, weight = map(float, parts[:4])
        weights.append((qx, qy, qz, weight))
    return weights


def compute_weighted_lambda_sum(
    qpoints: list[QPointData],
    row_index: int,
    lambdax_weights: list[tuple[float, float, float, float]],
    tol: float = 1e-6,
) -> dict[str, float]:
    if len(qpoints) != len(lambdax_weights):
        raise ValueError(
            f"Mismatch between elph q-point count ({len(qpoints)}) and lambdax.in q-point count ({len(lambdax_weights)})"
        )

    raw_weight_sum = sum(weight for _, _, _, weight in lambdax_weights)
    if raw_weight_sum <= 0.0:
        raise ValueError("lambdax.in q-point weights sum to zero")

    weighted_lambda_sum = 0.0
    for qpoint, (qx, qy, qz, weight) in zip(qpoints, lambdax_weights, strict=True):
        if any(
            abs(a - b) > tol for a, b in zip((qpoint.qx, qpoint.qy, qpoint.qz), (qx, qy, qz))
        ):
            raise ValueError(
                f"lambdax.in q-point order/coordinates do not match elph inputs: "
                f"elph=({qpoint.qx:.8f}, {qpoint.qy:.8f}, {qpoint.qz:.8f}) "
                f"vs lambdax=({qx:.8f}, {qy:.8f}, {qz:.8f})"
            )
        section = qpoint.sections[row_index - 1]
        weighted_lambda_sum += (weight / raw_weight_sum) * sum(section.lambdas)

    return {"weighted_lambda_sum": weighted_lambda_sum, "q_weight_sum": raw_weight_sum}


def write_outputs(
    qpoints: list[QPointData],
    row_index: int,
    wide_out: Path,
    gp_out: Path,
    lambda_meta: dict[str, float] | None = None,
    exact_broadening_ry: float | None = None,
    weighted_meta: dict[str, float] | None = None,
) -> None:
    sample_section = qpoints[0].sections[row_index - 1]
    dos_values = [q.sections[row_index - 1].dos for q in qpoints]
    dos_min = min(dos_values)
    dos_max = max(dos_values)

    wide_out.parent.mkdir(parents=True, exist_ok=True)
    gp_out.parent.mkdir(parents=True, exist_ok=True)

    with wide_out.open("w", encoding="utf-8") as fh:
        fh.write("# Extracted from elph.inp_lambda.*\n")
        fh.write(f"# row_index = {row_index}\n")
        fh.write(f"# broadening_label_ry = {sample_section.broadening_label}\n")
        if exact_broadening_ry is not None:
            fh.write(f"# broadening_exact_ry = {exact_broadening_ry:.7f}\n")
        fh.write(f"# dos_range = [{dos_min:.6f}, {dos_max:.6f}]\n")
        if lambda_meta is not None:
            fh.write(
                f"# lambda_dat_row = "
                f"degauss={lambda_meta['degauss']:.6f} "
                f"lambda={lambda_meta['lambda']:.6f} "
                f"omega_log={lambda_meta['omega_log']:.3f} "
                f"nef={lambda_meta['nef']:.6f}\n"
            )
        if weighted_meta is not None:
            fh.write(f"# q_weight_sum = {weighted_meta['q_weight_sum']:.12f}\n")
            fh.write(f"# weighted_lambda_sum = {weighted_meta['weighted_lambda_sum']:.12f}\n")
            if lambda_meta is not None:
                closure_ratio = weighted_meta["weighted_lambda_sum"] / lambda_meta["lambda"]
                fh.write(f"# closure_ratio_vs_lambda_dat = {closure_ratio:.12f}\n")
        fh.write(
            "# columns: q_index qx qy qz omega1_thz ... omegaN_thz lambda1 ... lambdaN gamma1_ghz ... gammaN_ghz\n"
        )
        for q in qpoints:
            section = q.sections[row_index - 1]
            row = [str(q.q_index), f"{q.qx:.8f}", f"{q.qy:.8f}", f"{q.qz:.8f}"]
            row.extend(f"{v:.12f}" for v in q.omega_thz)
            row.extend(f"{v:.12f}" for v in section.lambdas)
            row.extend(f"{v:.12f}" for v in section.gammas)
            fh.write(" ".join(row) + "\n")

    with gp_out.open("w", encoding="utf-8") as fh:
        fh.write("# Extracted from elph.inp_lambda.*\n")
        fh.write(f"# row_index = {row_index}\n")
        fh.write(f"# broadening_label_ry = {sample_section.broadening_label}\n")
        if exact_broadening_ry is not None:
            fh.write(f"# broadening_exact_ry = {exact_broadening_ry:.7f}\n")
        if lambda_meta is not None:
            fh.write(
                f"# lambda_dat_row = "
                f"degauss={lambda_meta['degauss']:.6f} "
                f"lambda={lambda_meta['lambda']:.6f} "
                f"omega_log={lambda_meta['omega_log']:.3f} "
                f"nef={lambda_meta['nef']:.6f}\n"
            )
        if weighted_meta is not None:
            fh.write(f"# q_weight_sum = {weighted_meta['q_weight_sum']:.12f}\n")
            fh.write(f"# weighted_lambda_sum = {weighted_meta['weighted_lambda_sum']:.12f}\n")
            if lambda_meta is not None:
                closure_ratio = weighted_meta["weighted_lambda_sum"] / lambda_meta["lambda"]
                fh.write(f"# closure_ratio_vs_lambda_dat = {closure_ratio:.12f}\n")
        fh.write("# columns: q_index qx qy qz mode omega_thz lambda_qv gamma_ghz\n")
        n_mode = len(qpoints[0].omega_thz)
        for mode in range(n_mode):
            for q in qpoints:
                section = q.sections[row_index - 1]
                omega = q.omega_thz[mode]
                lambd = section.lambdas[mode]
                gamma = section.gammas[mode]
                fh.write(
                    f"{q.q_index} {q.qx:.8f} {q.qy:.8f} {q.qz:.8f} "
                    f"{mode + 1} {omega:.12f} {lambd:.12f} {gamma:.12f}\n"
                )
            fh.write("\n")


# ── CLI (standalone usage) ──


def _main_cli() -> None:
    parser = argparse.ArgumentParser(
        description="Extract lambda_qv from elph.inp_lambda.* files at a selected smearing row."
    )
    parser.add_argument("--elph-dir", required=True, help="Directory containing elph.inp_lambda.* files.")
    parser.add_argument("--row-index", type=int, required=True, help="1-based smearing row index.")
    parser.add_argument("--lambda-dat", help="Optional lambda.dat for degauss, omega_log, N(Ef).")
    parser.add_argument("--lambdax-in", help="Optional lambdax.in for irreducible-q weight closure.")
    parser.add_argument("--a2fq2r-dir", help="Optional a2Fq2r.*.* directory for exact broadening.")
    parser.add_argument("--wide-out", required=True, help="Wide output: one row per q-point.")
    parser.add_argument("--gp-out", required=True, help="Long output for plotting.")
    args = parser.parse_args()

    elph_dir = Path(args.elph_dir)
    files = sorted_elph_inputs(elph_dir)
    qpoints = [parse_elph_input(path, idx) for idx, path in enumerate(files, start=1)]

    n_broad = len(qpoints[0].sections)
    if args.row_index < 1 or args.row_index > n_broad:
        raise ValueError(f"row-index {args.row_index} outside available range 1..{n_broad}")

    lambda_meta = parse_lambda_dat(Path(args.lambda_dat), args.row_index) if args.lambda_dat else None
    weighted_meta = None
    if args.lambdax_in:
        weights = parse_lambdax_q_weights(Path(args.lambdax_in))
        weighted_meta = compute_weighted_lambda_sum(qpoints, args.row_index, weights)

    write_outputs(
        qpoints=qpoints,
        row_index=args.row_index,
        wide_out=Path(args.wide_out),
        gp_out=Path(args.gp_out),
        lambda_meta=lambda_meta,
        weighted_meta=weighted_meta,
    )
    print(f"Wrote {args.wide_out} and {args.gp_out} from {len(qpoints)} q-points at row {args.row_index}")


if __name__ == "__main__":
    _main_cli()
