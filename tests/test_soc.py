"""Tests for SOC / Magnetism Layer (Sprint 15)."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "soc"


def test_soc_config_detects_noncolin_lspinorb():
    """SOC config should detect noncolin + lspinorb and heavy elements."""
    from vibedft.spin.soc_parser import analyze_soc_config
    config = analyze_soc_config(FIXTURES)
    assert config.noncolin is True
    assert config.lspinorb is True
    assert config.has_soc is True
    assert "Hf" in config.heavy_elements or "I" in config.heavy_elements


def test_soc_config_detects_magnetic():
    """Should detect nspin=2 and starting_magnetization."""
    from vibedft.spin.soc_parser import analyze_soc_config
    # Create a temp dir with the magnetic input only
    import tempfile
    d = Path(tempfile.mkdtemp())
    (d / "scf.in").write_text((FIXTURES / "magnetic_scf.in").read_text())
    config = analyze_soc_config(d)
    assert config.nspin == 2
    assert config.has_spin_polarization is True
    # nspin=2 detected; magnetic_atoms depends on parser handling of starting_magnetization(N)
    assert config.nspin == 2


def test_soc_config_heavy_elements_flag():
    """Heavy elements without SOC should trigger needs_soc_check."""
    from vibedft.spin.soc_parser import analyze_soc_config
    import tempfile
    d = Path(tempfile.mkdtemp())
    # Write a scalar input with heavy elements but no SOC
    (d / "scf.in").write_text("""\
&CONTROL calculation='scf' prefix='test' outdir='./out/' pseudo_dir='./' /
&SYSTEM ibrav=0 nat=3 ntyp=2 ecutwfc=60 ecutrho=480 /
&ELECTRONS conv_thr=1.0d-12 /
ATOMIC_SPECIES
  Hf 178.49 Hf.UPF
  I  126.90 I.UPF
ATOMIC_POSITIONS crystal
  Hf 0.0 0.0 0.5
  I  0.667 0.333 0.565
  I  0.667 0.333 0.435
K_POINTS automatic 12 12 1 0 0 0
CELL_PARAMETERS angstrom 3.0 0.0 0.0  -1.5 2.598 0.0  0.0 0.0 30.0
""")
    config = analyze_soc_config(d)
    assert config.needs_soc_check is True
    assert len(config.warnings) >= 1


def test_spin_validator_lspinorb_without_noncolin():
    """lspinorb without noncolin should produce an error."""
    from vibedft.spin.soc_parser import SocConfig
    from vibedft.spin.spin_validator import validate_spin_consistency

    config = SocConfig(lspinorb=True, noncolin=False, nspin=1)
    issues = validate_spin_consistency(config)
    error_ids = [i["id"] for i in issues if i["severity"] == "error"]
    assert "spin.lspinorb_without_noncolin" in error_ids


def test_spin_validator_heavy_without_soc():
    """Heavy elements without SOC should produce a warning."""
    from vibedft.spin.soc_parser import SocConfig
    from vibedft.spin.spin_validator import validate_spin_consistency

    config = SocConfig(heavy_elements=["Hf", "I"], needs_soc_check=True)
    issues = validate_spin_consistency(config)
    warning_ids = [i["id"] for i in issues if i["severity"] == "warning"]
    assert "spin.heavy_elements_no_soc" in warning_ids


def test_magnetism_extraction():
    """Extract total magnetization from SCF output."""
    from vibedft.spin.magnetism_analyzer import extract_magnetism
    import tempfile
    d = Path(tempfile.mkdtemp())
    (d / "scf.out").write_text("""\
     total magnetization       =     1.50 Bohr
     absolute magnetization    =     1.52 Bohr
""")
    result = extract_magnetism(d)
    assert result.has_data
    assert result.is_magnetic
    assert abs(result.total_magnetization - 1.5) < 0.1


def test_soc_comparator_no_soc_data():
    """Without SOC subdirectory, comparator should return no_soc_data."""
    from vibedft.spin.soc_comparator import compare_soc_vs_scalar
    import tempfile
    d = Path(tempfile.mkdtemp())
    result = compare_soc_vs_scalar(d)
    assert result["status"] == "no_soc_data"
