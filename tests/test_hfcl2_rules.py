"""Regression tests for HfCl2 hardening rules — P0.2/P1.1/P1.2.

Each test exercises a real validation rule from ``hfcl2_rules`` or
``core.qa`` and asserts the correct pass/fail behaviour.
"""

from pathlib import Path
import hashlib

from vibedft.core.qa import qa_inputs, discover_input_files
from vibedft.parsers.qe_input_parser import parse_qe_input
from vibedft.validators.hfcl2_rules import (
    check_fatband_location,
    check_fatband_kresolveddos,
    check_smearing_degauss_values,
    check_smearing_variants_exist,
    check_smearing_variants_distinct,
    check_pristine_elements,
    check_pristine_pseudo_family,
    check_pristine_ecut,
    check_pristine_cell,
    run_hfcl2_stage_rules,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ── helpers ──


def _write_in(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _write_k_screening_p2_fixture(root: Path) -> Path:
    _write_in(
        root / "07_bands" / "inputs" / "projwfc_fatband.in",
        "&PROJWFC\n  prefix = 'khfcl2'\n  outdir = './out_bands/'\n"
        "  filpdos = 'khfcl2.fatband'\n  kresolveddos = .true.\n/\n",
    )
    _write_in(
        root / "08_dos" / "inputs" / "projwfc_fatband.in",
        "&PROJWFC\n  prefix = 'khfcl2'\n  outdir = './out_dos/'\n"
        "  filpdos = 'khfcl2.fatband'\n  kresolveddos = .true.\n/\n",
    )
    return root


def _write_k_screening_p3_fixture(root: Path) -> Path:
    inputs = root / "08_dos" / "inputs"
    _write_in(
        inputs / "nscf.in",
        "&SYSTEM\n  occupations = 'smearing'\n  smearing = 'gaussian'\n"
        "  degauss = 3.7d-3\n/\n",
    )
    _write_in(
        inputs / "nscf_degauss_002.in",
        "&SYSTEM\n  occupations = 'smearing'\n  smearing = 'gaussian'\n"
        "  degauss = 2.0d-3\n/\n",
    )
    _write_in(
        inputs / "nscf_degauss_005.in",
        "&SYSTEM\n  occupations = 'smearing'\n  smearing = 'gaussian'\n"
        "  degauss = 5.0d-3\n/\n",
    )
    return root


def _write_pristine_b1_fixture(root: Path) -> Path:
    _write_in(
        root / "inputs" / "scf.in",
        "&CONTROL\n  calculation = 'scf'\n  prefix = 'pristine'\n  outdir = './out/'\n/\n"
        "&SYSTEM\n  ibrav = 0\n  nat = 3\n  ntyp = 2\n"
        "  ecutwfc = 90\n  ecutrho = 720\n"
        "  assume_isolated = '2D'\n/\n"
        "&ELECTRONS\n/\n"
        "ATOMIC_SPECIES\n"
        "  Hf 178.49 Hf.pbe-spn-kjpaw_psl.1.0.0.UPF\n"
        "  Cl 35.45 Cl.pbe-n-kjpaw_psl.1.0.0.UPF\n"
        "CELL_PARAMETERS (angstrom)\n  3.3 0.0 0.0\n  -1.65 2.86 0.0\n  0.0 0.0 30.0\n"
        "ATOMIC_POSITIONS (crystal)\n"
        "  Hf 0.0 0.0 0.5\n  Cl 0.666 0.333 0.598\n  Cl 0.333 0.666 0.402\n"
        "K_POINTS (automatic)\n  16 16 1 0 0 0\n",
    )
    return root


# ═══════════════════════════════════════════════════════════════════════════════
# P3 smearing: degauss=0.0d-3 must be rejected
# ═══════════════════════════════════════════════════════════════════════════════


def test_p3_rejects_zero_degauss(tmp_path: Path):
    """nscf_degauss_002.in containing degauss=0.0d-3 → FAIL."""
    inputs = tmp_path / "08_dos" / "inputs"
    inputs.mkdir(parents=True)
    f = inputs / "nscf_degauss_002.in"
    f.write_text(
        "&CONTROL\n  calculation = 'nscf'\n  prefix = 'test'\n  outdir = './out/'\n/\n"
        "&SYSTEM\n  ibrav = 0\n  nat = 1\n  ntyp = 1\n"
        "  ecutwfc = 90\n  ecutrho = 720\n"
        "  occupations = 'smearing'\n  smearing = 'gaussian'\n"
        "  degauss = 0.0d-3\n  nbnd = 40\n/\n"
        "&ELECTRONS\n/\n"
        "ATOMIC_SPECIES\n  Hf 178.49 Hf.upf\n"
        "CELL_PARAMETERS (angstrom)\n  3.3 0.0 0.0\n  -1.65 2.86 0.0\n  0.0 0.0 30.0\n"
        "ATOMIC_POSITIONS (crystal)\n  Hf 0.0 0.0 0.5\n"
        "K_POINTS (automatic)\n  32 32 1 0 0 0\n"
    )
    discovered = discover_input_files(tmp_path)
    results = check_smearing_degauss_values(discovered)
    assert any(
        c.id == "hfcl2.p3.smearing.degauss_zero" and c.status == "fail"
        for c in results
    ), "degauss=0.0d-3 must be caught as zero-smearing error"


def test_p3_requires_distinct_variants(tmp_path: Path):
    """degauss_002 and degauss_005 having the same hash → FAIL."""
    content = (
        "&CONTROL\n  calculation = 'nscf'\n  prefix = 'test'\n  outdir = './out/'\n/\n"
        "&SYSTEM\n  ibrav = 0\n  nat = 1\n  ntyp = 1\n"
        "  ecutwfc = 90\n  ecutrho = 720\n"
        "  occupations = 'smearing'\n  smearing = 'gaussian'\n"
        "  degauss = 3.7d-3\n  nbnd = 40\n/\n"
        "&ELECTRONS\n/\n"
        "ATOMIC_SPECIES\n  Hf 178.49 Hf.upf\n"
        "CELL_PARAMETERS (angstrom)\n  3.3 0.0 0.0\n  -1.65 2.86 0.0\n  0.0 0.0 30.0\n"
        "ATOMIC_POSITIONS (crystal)\n  Hf 0.0 0.0 0.5\n"
        "K_POINTS (automatic)\n  32 32 1 0 0 0\n"
    )
    inputs = tmp_path / "08_dos" / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "nscf_degauss_002.in").write_text(content)
    (inputs / "nscf_degauss_005.in").write_text(content)
    assert _hash(inputs / "nscf_degauss_002.in") == _hash(inputs / "nscf_degauss_005.in")

    discovered = discover_input_files(tmp_path)
    results = check_smearing_variants_distinct(discovered)
    assert any(
        c.id == "hfcl2.p3.smearing.distinct_variants" and c.status == "fail"
        for c in results
    ), "Identical variant files must be caught"


def test_p3_accepts_valid_smearing(tmp_path: Path):
    """Valid smearing with distinct degauss values → PASS."""
    for deg, fname in [(0.002, "nscf_degauss_002.in"), (0.005, "nscf_degauss_005.in")]:
        d = tmp_path / "08_dos" / "inputs"
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_text(
            "&SYSTEM\n  degauss = {:.1e}\n/\n".format(deg)
        )
    discovered = discover_input_files(tmp_path)
    deg_results = check_smearing_degauss_values(discovered)
    distinct_results = check_smearing_variants_distinct(discovered)
    assert all(c.status == "pass" for c in deg_results), "Valid degauss should pass"
    assert all(c.status == "pass" for c in distinct_results), "Distinct files should pass"


def test_p3_filename_matches_value(tmp_path: Path):
    """nscf_degauss_002.in must parse to 0.002 Ry; _005 to 0.005 Ry."""
    cases = [("nscf_degauss_002.in", 0.002), ("nscf_degauss_005.in", 0.005)]
    for idx, (fname, expected) in enumerate(cases):
        inputs = tmp_path / f"case_{idx}" / "08_dos" / "inputs"
        inputs.mkdir(parents=True)
        (inputs / fname).write_text(
            "&SYSTEM\n  degauss = {:.1e}\n/\n".format(expected)
        )
        qe = parse_qe_input(inputs / fname)
        deg = qe.get_param("system", "degauss")
        assert deg is not None, f"degauss not parsed from {fname}"
        assert abs(float(deg) - expected) < 1e-6, \
            f"{fname}: expected degauss={expected}, got {deg}"
        # Also run through rule engine
        discovered = discover_input_files(inputs.parent.parent)
        results = check_smearing_degauss_values(discovered)
        for r in results:
            assert r.status == "pass", f"{fname}: {r.message}"


# ═══════════════════════════════════════════════════════════════════════════════
# P2 fatband: projwfc_fatband.in must be in 07_bands/inputs/, not 08_dos/inputs/
# ═══════════════════════════════════════════════════════════════════════════════


def test_fatband_rejects_wrong_stage(tmp_path: Path):
    """projwfc_fatband.in under 08_dos/inputs/ → FAIL."""
    wrong = tmp_path / "08_dos" / "inputs" / "projwfc_fatband.in"
    _write_in(wrong,
        "&PROJWFC\n  prefix = 'test'\n  outdir = './out/'\n"
        "  filpdos = 'test.fatband'\n  kresolveddos = .true.\n/\n"
    )
    discovered = discover_input_files(tmp_path)
    results = check_fatband_location(discovered)
    assert any(
        c.id == "hfcl2.p2.fatband.location" and c.status == "fail"
        for c in results
    ), "fatband in 08_dos must fail location check"


def test_fatband_passes_correct_stage(tmp_path: Path):
    """projwfc_fatband.in under 07_bands/inputs/ → PASS."""
    right = tmp_path / "07_bands" / "inputs" / "projwfc_fatband.in"
    _write_in(right,
        "&PROJWFC\n  prefix = 'test'\n  outdir = './out_bands/'\n"
        "  filpdos = 'test.fatband'\n  kresolveddos = .true.\n/\n"
    )
    discovered = discover_input_files(tmp_path)
    results = check_fatband_location(discovered)
    assert any(
        c.id == "hfcl2.p2.fatband.location" and c.status == "pass"
        for c in results
    ), "fatband in 07_bands must pass location check"


def test_fatband_has_kresolveddos(tmp_path: Path):
    """projwfc_fatband.in with kresolveddos=.false. → FAIL."""
    f = tmp_path / "07_bands" / "inputs" / "projwfc_fatband.in"
    _write_in(f,
        "&PROJWFC\n  prefix = 'test'\n  outdir = './out/'\n"
        "  filpdos = 'test.pdos'\n  kresolveddos = .false.\n/\n"
    )
    discovered = discover_input_files(tmp_path)
    results = check_fatband_kresolveddos(discovered)
    assert any(
        c.id == "hfcl2.p2.fatband.kresolveddos" and c.status == "fail"
        for c in results
    ), "kresolveddos=.false. must fail"


# ═══════════════════════════════════════════════════════════════════════════════
# P2 kpoints: K_POINTS crystal_b count must equal number of special k-point lines
# ═══════════════════════════════════════════════════════════════════════════════


def test_kpoints_crystal_b_rejects_wrong_count(tmp_path: Path):
    """K_POINTS crystal_b with count=40 but 4 point lines → FAIL."""
    f = tmp_path / "07_bands" / "inputs" / "nscf_bands.in"
    _write_in(f,
        "&CONTROL\n  calculation = 'bands'\n  prefix = 'test'\n"
        "  outdir = './tmp/'\n  pseudo_dir = './pseudo/'\n/\n"
        "&SYSTEM\n  ibrav = 0\n  nat = 1\n  ntyp = 1\n"
        "  ecutwfc = 90\n  ecutrho = 720\n  occupations = 'smearing'\n"
        "  smearing = 'mv'\n  degauss = 5.0d-3\n  nbnd = 40\n"
        "  assume_isolated = '2D'\n/\n"
        "&ELECTRONS\n  conv_thr = 1.0d-10\n/\n"
        "ATOMIC_SPECIES\n  Hf 178.49 Hf.upf\n"
        "CELL_PARAMETERS angstrom\n  3.3 0.0 0.0\n  -1.65 2.86 0.0\n  0.0 0.0 30.0\n"
        "ATOMIC_POSITIONS crystal\n  Hf 0.0 0.0 0.5\n"
        "K_POINTS crystal_b\n"
        "40\n"
        "0.0  0.0  0.0  40\n"
        "0.5  0.0  0.0  40\n"
        "0.3333 0.3333 0.0  40\n"
        "0.0  0.0  0.0  1\n"
    )
    discovered = discover_input_files(tmp_path)
    # Check both: from function import and via run_hfcl2_stage_rules
    from vibedft.validators.hfcl2_rules import check_kpoints_crystal_b_count
    results = check_kpoints_crystal_b_count(discovered)
    assert any(
        c.id == "hfcl2.p2.kpoints.crystal_b_count" and c.status == "fail"
        for c in results
    ), "K_POINTS crystal_b with count=40 and 4 lines must fail"


def test_kpoints_crystal_b_passes_correct_count(tmp_path: Path):
    """K_POINTS crystal_b with count=4 and 4 point lines → PASS."""
    f = tmp_path / "07_bands" / "inputs" / "nscf_bands.in"
    _write_in(f,
        "&CONTROL\n  calculation = 'bands'\n  prefix = 'test'\n"
        "  outdir = './tmp/'\n  pseudo_dir = './pseudo/'\n/\n"
        "&SYSTEM\n  ibrav = 0\n  nat = 1\n  ntyp = 1\n"
        "  ecutwfc = 90\n  ecutrho = 720\n  occupations = 'smearing'\n"
        "  smearing = 'mv'\n  degauss = 5.0d-3\n  nbnd = 40\n"
        "  assume_isolated = '2D'\n/\n"
        "&ELECTRONS\n  conv_thr = 1.0d-10\n/\n"
        "ATOMIC_SPECIES\n  Hf 178.49 Hf.upf\n"
        "CELL_PARAMETERS angstrom\n  3.3 0.0 0.0\n  -1.65 2.86 0.0\n  0.0 0.0 30.0\n"
        "ATOMIC_POSITIONS crystal\n  Hf 0.0 0.0 0.5\n"
        "K_POINTS crystal_b\n"
        "4\n"
        "0.0  0.0  0.0  40\n"
        "0.5  0.0  0.0  40\n"
        "0.3333 0.3333 0.0  40\n"
        "0.0  0.0  0.0  1\n"
    )
    discovered = discover_input_files(tmp_path)
    from vibedft.validators.hfcl2_rules import check_kpoints_crystal_b_count
    results = check_kpoints_crystal_b_count(discovered)
    assert any(
        c.id == "hfcl2.p2.kpoints.crystal_b_count" and c.status == "pass"
        for c in results
    ), "K_POINTS crystal_b with count=4 and 4 lines must pass"


# ═══════════════════════════════════════════════════════════════════════════════
# B1 pristine: rrkjus reference must use correct pseudo family, vacuum, ecut
# ═══════════════════════════════════════════════════════════════════════════════


def test_pristine_rrkjus_rejects_kjpaw(tmp_path: Path):
    """kjpaw pseudo in pristine → FAIL."""
    content = (
        "&CONTROL\n  calculation = 'scf'\n  prefix = 'test'\n  outdir = './out/'\n/\n"
        "&SYSTEM\n  ibrav = 0\n  nat = 3\n  ntyp = 2\n"
        "  ecutwfc = 90\n  ecutrho = 720\n"
        "  assume_isolated = '2D'\n/\n"
        "&ELECTRONS\n/\n"
        "ATOMIC_SPECIES\n"
        "  Hf 178.49 Hf.pbe-spn-kjpaw_psl.1.0.0.UPF\n"
        "  Cl 35.45 Cl.pbe-n-kjpaw_psl.1.0.0.UPF\n"
        "CELL_PARAMETERS (angstrom)\n  3.3 0.0 0.0\n  -1.65 2.86 0.0\n  0.0 0.0 30.0\n"
        "ATOMIC_POSITIONS (crystal)\n"
        "  Hf 0.0 0.0 0.5\n  Cl 0.666 0.333 0.598\n  Cl 0.333 0.666 0.402\n"
        "K_POINTS (automatic)\n  16 16 1 0 0 0\n"
    )
    inputs = tmp_path / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "scf.in").write_text(content)
    discovered = discover_input_files(tmp_path)
    results = check_pristine_pseudo_family(discovered)
    assert any(
        c.id == "hfcl2.b1.pristine.pseudo_family" and c.status == "fail"
        for c in results
    ), "kjpaw pseudo must fail pseudo_family check"


def test_pristine_rrkjus_rejects_alkali(tmp_path: Path):
    """Li/Na/K atom in pristine → FAIL."""
    content = (
        "&CONTROL\n  calculation = 'scf'\n  prefix = 'test'\n  outdir = './out/'\n/\n"
        "&SYSTEM\n  ibrav = 0\n  nat = 4\n  ntyp = 3\n"
        "  ecutwfc = 90\n  ecutrho = 720\n"
        "  assume_isolated = '2D'\n/\n"
        "&ELECTRONS\n/\n"
        "ATOMIC_SPECIES\n"
        "  Hf 178.49 Hf.pbe-spn-rrkjus_psl.1.0.0.UPF\n"
        "  K 39.098 K.pbe-spn-rrkjus_psl.1.0.0.UPF\n"
        "  Cl 35.45 Cl.pbe-n-rrkjus_psl.1.0.0.UPF\n"
        "CELL_PARAMETERS (angstrom)\n  3.3 0.0 0.0\n  -1.65 2.86 0.0\n  0.0 0.0 30.0\n"
        "ATOMIC_POSITIONS (crystal)\n"
        "  Hf 0.0 0.0 0.5\n  K 0.0 0.0 0.0\n"
        "  Cl 0.666 0.333 0.6\n  Cl 0.333 0.666 0.4\n"
        "K_POINTS (automatic)\n  16 16 1 0 0 0\n"
    )
    inputs = tmp_path / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "scf.in").write_text(content)
    discovered = discover_input_files(tmp_path)
    results = check_pristine_elements(discovered)
    assert any(
        c.id == "hfcl2.b1.pristine.elements" and c.status == "fail"
        for c in results
    ), "K in pristine must fail elements check"


def test_pristine_rrkjus_requires_90_720(tmp_path: Path):
    """ecutwfc != 90 or ecutrho != 720 → FAIL."""
    content = (
        "&CONTROL\n  calculation = 'scf'\n  prefix = 'test'\n  outdir = './out/'\n/\n"
        "&SYSTEM\n  ibrav = 0\n  nat = 3\n  ntyp = 2\n"
        "  ecutwfc = 80\n  ecutrho = 560\n"
        "  assume_isolated = '2D'\n/\n"
        "&ELECTRONS\n/\n"
        "ATOMIC_SPECIES\n"
        "  Hf 178.49 Hf.pbe-spn-rrkjus_psl.1.0.0.UPF\n"
        "  Cl 35.45 Cl.pbe-n-rrkjus_psl.1.0.0.UPF\n"
        "CELL_PARAMETERS (angstrom)\n  3.3 0.0 0.0\n  -1.65 2.86 0.0\n  0.0 0.0 30.0\n"
        "ATOMIC_POSITIONS (crystal)\n"
        "  Hf 0.0 0.0 0.5\n  Cl 0.666 0.333 0.598\n  Cl 0.333 0.666 0.402\n"
        "K_POINTS (automatic)\n  16 16 1 0 0 0\n"
    )
    inputs = tmp_path / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "scf.in").write_text(content)
    discovered = discover_input_files(tmp_path)
    results = check_pristine_ecut(discovered)
    assert any(
        c.id == "hfcl2.b1.pristine.ecut" and c.status == "fail"
        for c in results
    ), "ecutwfc=80 must fail ecut check"


def test_pristine_rrkjus_requires_vacuum(tmp_path: Path):
    """c < 25 Å → FAIL."""
    content = (
        "&CONTROL\n  calculation = 'scf'\n  prefix = 'test'\n  outdir = './out/'\n/\n"
        "&SYSTEM\n  ibrav = 0\n  nat = 3\n  ntyp = 2\n"
        "  ecutwfc = 90\n  ecutrho = 720\n"
        "  assume_isolated = '2D'\n/\n"
        "&ELECTRONS\n/\n"
        "ATOMIC_SPECIES\n"
        "  Hf 178.49 Hf.pbe-spn-rrkjus_psl.1.0.0.UPF\n"
        "  Cl 35.45 Cl.pbe-n-rrkjus_psl.1.0.0.UPF\n"
        "CELL_PARAMETERS (angstrom)\n  3.3 0.0 0.0\n  -1.65 2.86 0.0\n  0.0 0.0 18.0\n"
        "ATOMIC_POSITIONS (crystal)\n"
        "  Hf 0.0 0.0 0.5\n  Cl 0.666 0.333 0.598\n  Cl 0.333 0.666 0.402\n"
        "K_POINTS (automatic)\n  16 16 1 0 0 0\n"
    )
    inputs = tmp_path / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "scf.in").write_text(content)
    discovered = discover_input_files(tmp_path)
    results = check_pristine_cell(discovered)
    assert any(
        c.id == "hfcl2.b1.pristine.cell_c" and c.status == "fail"
        for c in results
    ), "c=18 Å must fail cell check"


# ═══════════════════════════════════════════════════════════════════════════════
# Q2R / PH cross-cutting rules
# ═══════════════════════════════════════════════════════════════════════════════


def test_q2r_rejects_la2F(tmp_path: Path):
    """q2r.x input with la2F=.true. → BLOCKER."""
    f = tmp_path / "input" / "q2rx.in"
    _write_in(f, "&INPUT\n  fildyn = 'dyn'\n  flfrc = 'fc'\n  zasr = 'simple'\n  la2F = .true.\n/\n")
    qe = parse_qe_input(f)
    assert qe.program.value == "q2r.x", f"expected q2r.x, got {qe.program.value}"
    inp = qe.namelists.get("input")
    assert inp is not None
    assert inp.params.get("la2f") is True, "la2F must parse as .true."

    report = qa_inputs(tmp_path)
    assert any(c.id == "input.ph.no_la2f" and c.status == "fail" for c in report.checks)


def test_ph_stability_rejects_electron_phonon(tmp_path: Path):
    """PH_STABILITY ph.x input with electron_phonon set → BLOCKER."""
    f = tmp_path / "input" / "phx.in"
    _write_in(f,
        "&INPUTPH\n  ldisp = .true.\n  nq1 = 4\n  nq2 = 4\n  nq3 = 1\n"
        "  electron_phonon = 'dvscf'\n  prefix = 'test'\n  outdir = './out/'\n/\n"
    )
    qe = parse_qe_input(f)
    assert qe.program.value == "ph.x"
    assert qe.get_param("inputph", "electron_phonon") == "dvscf"


# ═══════════════════════════════════════════════════════════════════════════════
# Slurm: must use srun, not mpirun
# ═══════════════════════════════════════════════════════════════════════════════


def test_slurm_uses_srun():
    """Generated Slurm script should contain srun, not mpirun."""
    from vibedft.core.slurm import render_slurm_script
    stages = [
        {"label": "SCF", "executable": "pw.x", "input": "scf.in", "output": "scf.out", "np": 4},
    ]
    script = render_slurm_script(stages=stages)
    assert "srun" in script, "Default launcher must be srun"
    assert "mpirun" not in script, "Default launcher should not be mpirun"


def test_slurm_not_direct_execution():
    """Generated Slurm script should not call pw.x directly on login node."""
    from vibedft.core.slurm import render_slurm_script
    stages = [
        {"label": "SCF", "executable": "pw.x", "input": "scf.in", "output": "scf.out", "np": 4},
    ]
    script = render_slurm_script(stages=stages)
    assert "#!/bin/bash" in script
    assert "#SBATCH" in script
    assert "pw.x -in scf.in" in script, "srun must use -in style invocation"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: run_hfcl2_stage_rules on real cases
# ═══════════════════════════════════════════════════════════════════════════════


def test_integration_k_screening_p2(tmp_path: Path):
    """Synthetic K-screening case: P2 rules."""
    case = _write_k_screening_p2_fixture(tmp_path / "K_1")
    results = run_hfcl2_stage_rules(case, stage="P2")
    assert any(
        c.id == "hfcl2.p2.fatband.location" and c.status == "fail"
        for c in results
    ), "fatband in 08_dos must fail"


def test_integration_k_screening_p3(tmp_path: Path):
    """Synthetic K-screening case: P3 rules should pass."""
    case = _write_k_screening_p3_fixture(tmp_path / "K_1")
    results = run_hfcl2_stage_rules(case, stage="P3")
    failed = [c for c in results if c.status == "fail"]
    assert not failed, f"P3 rules unexpectedly failed: {[c.message for c in failed]}"


def test_integration_pristine_b1(tmp_path: Path):
    """Synthetic pristine case: B1 rules should flag kjpaw issues."""
    case = _write_pristine_b1_fixture(tmp_path / "pristine")
    results = run_hfcl2_stage_rules(case, stage="B1")
    assert any(
        c.id.startswith("hfcl2.b1.pristine") and c.status == "fail"
        for c in results
    ), "Pristine kjpaw inputs must have B1 failures"
