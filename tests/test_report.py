"""Tests for the interactive report module."""

import json
import subprocess
import sys
import os
from pathlib import Path

from vibedft.core.report import (
    CaseFileDiscovery,
    build_structure_section,
    build_overview_section,
    build_bands_section,
    build_dos_pdos_section,
    build_phonon_section,
    build_epc_section,
    build_superconductivity_section,
    build_report,
    render_report_html,
    ReportPayload,
    SectionData,
    Insight,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SAMPLE_SCF = """\
     Program PWSCF v.7.2 starts
     iteration #  1     total energy              =    -191.725651 Ry
     estimated scf accuracy    <       1.0E-12 Ry
     iteration #  2     total energy              =    -191.725600 Ry
     estimated scf accuracy    <       1.0E-13 Ry
     the Fermi energy is    -0.0583 ev
     convergence has been achieved in 9 iterations
     number of scf cycles    =   9
!    total energy              =    -191.725651 Ry
     PWSCF        :     29.90s CPU     32.70s WALL
   JOB DONE.
"""

SAMPLE_DOS_DATA = """\
#  E (eV)   dos(E)     Int dos(E) EFermi =   -0.009 eV
 -10.000  0.0000  0.0000
  -5.000  0.5000  0.2500
   0.000  0.0010  1.0000
   5.000  1.5000  5.0000
  10.000  0.0000  8.0000
"""

SAMPLE_DOS_MISMATCH_EF = """\
#  E (eV)   dos(E)     Int dos(E) EFermi =    0.250 eV
 -10.000  0.0000  0.0000
  -5.000  0.5000  0.2500
   0.000  0.0010  1.0000
   5.000  1.5000  5.0000
  10.000  0.0000  8.0000
"""

SAMPLE_BANDS = """\
 &plot nbnd=  2, nks=    3 /
            0.000000  0.000000  0.000000
  -10.000   -1.000
            0.250000  0.144338  0.000000
   -9.500   -0.500
            0.500000  0.000000  0.000000
   -9.000    0.000
"""

SAMPLE_COMPARE_BANDS = """\
 &plot nbnd=  2, nks=    3 /
            0.000000  0.000000  0.000000
  -9.800   -0.800
            0.250000  0.144338  0.000000
   -9.300   -0.300
            0.500000  0.000000  0.000000
   -8.800    0.200
"""

SAMPLE_MISMATCH_BANDS = """\
 &plot nbnd=  2, nks=    3 /
            0.000000  0.000000  0.000000
  -9.800   -0.800
            0.250000  0.144338  0.000000
   -9.300   -0.300
            0.500200  0.000000  0.000000
   -8.800    0.200
"""

SAMPLE_FREQ_GP = """\
   0.0000   0.0000  12.3456  25.6789
   0.1000  -0.1150  12.4000  25.7000
   0.2000   0.0000  12.5000  25.8000
"""


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "vibedft", *args],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_bands_case(case_dir: Path, bands_text: str, *, ef: float = 0.0) -> Path:
    out = case_dir / "output"
    out.mkdir(parents=True)
    (out / "scf.out").write_text(
        f"the Fermi energy is    {ef:.4f} ev\n"
        "convergence has been achieved in 4 iterations\n"
        "!    total energy              =    -10.000000 Ry\n"
        "JOB DONE.\n",
        encoding="utf-8",
    )
    (out / "material-a.bands.dat.gnu").write_text(bands_text, encoding="utf-8")
    return case_dir


# ── Data model tests ──


def test_report_payload_json_roundtrip():
    payload = ReportPayload(
        title="Test", case_id="test-1", material="HfBr2",
    )
    payload.sections.append(SectionData(
        section_id="overview", title="Overview", status="pass",
        data={"scf": {"total_energy_ry": -184.77}},
        insights=[Insight(section_id="overview", status="pass", message="All good")],
    ))
    js = payload.to_json()
    data = json.loads(js)
    assert data["title"] == "Test"
    assert data["case_id"] == "test-1"
    assert len(data["sections"]) == 1
    assert data["sections"][0]["status"] == "pass"


def test_section_data_defaults():
    s = SectionData(section_id="test", title="Test")
    assert s.status == "missing"
    assert s.data == {}
    assert s.insights == []
    assert s.evidence_files == []


# ── File discovery tests ──


def test_discover_finds_scf_dos_bands(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text(SAMPLE_SCF)
    (out / "hfi2.dos").write_text(SAMPLE_DOS_DATA)
    sub = out / "bands"
    sub.mkdir()
    (sub / "hfi2.bands.dat.gnu").write_text(SAMPLE_BANDS)

    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovered = discovery.discover()

    assert "scf" in discovered
    assert "dos" in discovered
    assert "bands" in discovered
    assert discovery.has_stage("scf")
    assert discovery.has_stage("dos")
    assert discovery.has_stage("bands")
    assert not discovery.has_stage("ph_disp")


def test_discover_recursive_finds_nested(tmp_path: Path):
    out = tmp_path / "output" / "ph64"
    out.mkdir(parents=True)
    (out / "test.freq.gp").write_text(SAMPLE_FREQ_GP)

    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovered = discovery.discover()

    assert "ph_disp" in discovered
    assert len(discovered["ph_disp"]) == 1


def test_discover_empty_case(tmp_path: Path):
    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovered = discovery.discover()
    assert discovered == {}
    assert not discovery.has_stage("scf")


# ── Overview section tests ──


def test_build_overview_with_scf(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text(SAMPLE_SCF)

    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovery.discover()
    section = build_overview_section(discovery)

    assert section.status == "pass"
    assert section.data["scf"]["scf_converged"] is True
    assert section.data["scf"]["scf_iterations"] >= 1  # parser uses last iteration # line
    assert abs(section.data["scf"]["total_energy_ry"] - (-191.725651)) < 0.001
    assert len(section.insights) == 1
    assert "converged" in section.insights[0].message.lower()


def test_build_overview_missing_scf(tmp_path: Path):
    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovery.discover()
    section = build_overview_section(discovery)

    assert section.status == "missing"
    assert any("No SCF" in i.message for i in section.insights)


# ── Bands section tests ──


def test_build_bands_with_data(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text(SAMPLE_SCF)
    (out / "hfi2.bands.dat.gnu").write_text(SAMPLE_BANDS)

    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovery.discover()
    section = build_bands_section(discovery)

    assert section.status == "pass"
    assert section.data["nbnd"] == 2
    assert section.data["nks"] == 3
    assert "band_gap" in section.data
    # With SCF EF=-0.0583 eV, gap should be detected (bands range -10 to 0)
    assert len(section.insights) >= 1


def test_build_bands_missing(tmp_path: Path):
    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovery.discover()
    section = build_bands_section(discovery)

    assert section.status == "missing"
    assert any("No bands" in i.message for i in section.insights)


# ── DOS/PDOS section tests ──


def test_build_dos_with_data(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "hfi2.dos").write_text(SAMPLE_DOS_DATA)

    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovery.discover()
    section = build_dos_pdos_section(discovery)

    assert section.status == "pass"
    assert "tdos" in section.data
    assert section.data["tdos"]["n_points"] == 5


# ── Phonon section tests ──


def test_build_phonon_with_imaginary(tmp_path: Path):
    out = tmp_path / "output" / "ph64"
    out.mkdir(parents=True)
    (out / "test.freq.gp").write_text(SAMPLE_FREQ_GP)

    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovery.discover()
    section = build_phonon_section(discovery)

    assert section.status == "warn"  # has imaginary mode
    assert "grids" in section.data
    assert "ph64" in section.data["grids"]
    gd = section.data["grids"]["ph64"]
    assert gd["n_imaginary"] == 1
    assert any("imaginary" in i.message.lower() for i in section.insights)


def test_build_phonon_missing(tmp_path: Path):
    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovery.discover()
    section = build_phonon_section(discovery)

    assert section.status == "missing"
    assert any("No freq.gp" in i.message for i in section.insights)


# ── EPC section tests ──


def test_build_epc_missing(tmp_path: Path):
    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovery.discover()
    section = build_epc_section(discovery)

    assert section.status == "missing"


# ── Superconductivity section tests ──


def test_build_tc_insufficient_grids(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "lambdax.out").write_text("lambda  omega_log  T_c\n")

    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovery.discover()
    section = build_superconductivity_section(discovery)

    assert section.status == "missing"
    assert "Need ≥2" in section.insights[0].message


# ── Structure section tests ──


def test_build_structure_from_qe_input(tmp_path: Path):
    """Build structure section from a QE-style scf.in."""
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "scf.in").write_text("""\
&CONTROL
  prefix = 'HfBr2'
/
&SYSTEM
  ibrav = 0
  nat = 3
  ntyp = 2
  ecutwfc = 60
/
CELL_PARAMETERS (angstrom)
   3.488143121  -0.000000000   0.000000000
  -1.744071561   3.020820555   0.000000000
   0.000000000   0.000000000  40.000000000
ATOMIC_POSITIONS (crystal)
Hf   -0.0000000000  -0.0000000000   0.5000000000
Br    0.6666666670   0.3333333330   0.5461764050
Br    0.6666666670   0.3333333330   0.4538235950
""")

    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovery.discover()
    section = build_structure_section(discovery)

    assert section.status == "pass"
    assert section.data["n_atoms"] == 3
    assert "Hf" in section.data["elements"]
    assert "Br" in section.data["elements"]
    assert section.data["lattice"]["c"] > 30  # 40 Å vacuum
    m = section.data["metrics_2d"]
    assert m["vacuum_thickness_ang"] > 10  # sufficient vacuum
    assert len(section.insights) >= 2


def test_build_structure_missing(tmp_path: Path):
    discovery = CaseFileDiscovery(case_dir=tmp_path)
    discovery.discover()
    section = build_structure_section(discovery)
    assert section.status == "missing"


# ── Full report assembly tests ──


def test_build_report_produces_all_sections(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text(SAMPLE_SCF)
    (out / "hfi2.dos").write_text(SAMPLE_DOS_DATA)
    (out / "hfi2.bands.dat.gnu").write_text(SAMPLE_BANDS)

    payload = build_report(tmp_path)
    assert len(payload.sections) == 9
    section_ids = [s.section_id for s in payload.sections]
    assert "overview" in section_ids
    assert "bands" in section_ids
    assert "dos_pdos" in section_ids


def test_build_report_empty_case(tmp_path: Path):
    payload = build_report(tmp_path)
    assert len(payload.sections) == 9
    # All sections should handle missing data gracefully (no crashes)
    for s in payload.sections:
        assert s.status in ("pass", "warn", "fail", "missing")


def test_render_report_html_produces_valid_file(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text(SAMPLE_SCF)

    payload = build_report(tmp_path)
    html_path = tmp_path / "report.html"
    html = render_report_html(payload, html_path)

    assert html_path.is_file()
    assert "Plotly" in html or "plotly" in html.lower()
    assert "VibeDFT" in html
    assert "SCF" in html or "scf" in html.lower()
    # Template has 3 legitimate </script> closings (Plotly CDN + 3Dmol CDN + inline block)
    assert html.count("</script>") == 3


# ── CLI tests ──


def test_cli_report_build_outputs_json(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text(SAMPLE_SCF)

    result = run_cli("report", "build", "--case-dir", str(tmp_path), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "sections" in data
    assert len(data["sections"]) == 9


def test_cli_report_html_generates_file(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text(SAMPLE_SCF)

    result = run_cli(
        "report", "html",
        "--case-dir", str(tmp_path),
        "--title", "Test Report",
        "--output", str(tmp_path / "out.html"),
    )
    assert result.returncode == 0
    assert (tmp_path / "out.html").is_file()
    content = (tmp_path / "out.html").read_text()
    assert "Test Report" in content


def test_cli_report_build_with_html_flag(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text(SAMPLE_SCF)

    result = run_cli(
        "report", "build",
        "--case-dir", str(tmp_path),
        "--html",
        "--output", str(tmp_path / "combined.html"),
    )
    assert result.returncode == 0
    assert (tmp_path / "combined.html").is_file()


def test_report_bands_advanced_surfaces_dos_scf_fermi_mismatch_with_evidence(tmp_path: Path):
    """EF mismatch must be a visible insight with source file evidence."""
    out = tmp_path / "output"
    out.mkdir()
    (out / "scf.out").write_text(SAMPLE_SCF)
    (out / "hfi2.dos").write_text(SAMPLE_DOS_MISMATCH_EF)
    (out / "hfi2.bands.dat.gnu").write_text(SAMPLE_BANDS)

    payload = build_report(tmp_path)
    section = next(s for s in payload.sections if s.section_id == "bands_advanced")
    mismatch = [
        insight for insight in section.insights
        if "DOS header EF" in insight.message and insight.status == "warn"
    ]

    assert mismatch, "expected visible DOS/SCF EF mismatch warning"
    files = [e.file for e in mismatch[0].evidence]
    assert "output/scf.out" in files
    assert "output/hfi2.dos" in files


def test_cli_report_build_accepts_repeatable_compare_dir(tmp_path: Path):
    main = write_bands_case(tmp_path / "case-a", SAMPLE_BANDS, ef=0.0)
    compare_b = write_bands_case(tmp_path / "case-b", SAMPLE_COMPARE_BANDS, ef=0.1)
    compare_c = write_bands_case(tmp_path / "case-c", SAMPLE_COMPARE_BANDS, ef=0.2)

    result = run_cli(
        "report", "build",
        "--case-dir", str(main),
        "--compare-dir", str(compare_b),
        "--compare-dir", str(compare_c),
        "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    overlay = next(s for s in data["sections"] if s["section_id"] == "bands_overlay")
    assert overlay["status"] == "pass"
    assert len(overlay["data"]["cases"]) == 3


def test_cli_report_html_accepts_compare_dir_and_renders_overlay(tmp_path: Path):
    main = write_bands_case(tmp_path / "case-a", SAMPLE_BANDS, ef=0.0)
    compare = write_bands_case(tmp_path / "case-b", SAMPLE_COMPARE_BANDS, ef=0.1)
    output = tmp_path / "overlay.html"

    result = run_cli(
        "report", "html",
        "--case-dir", str(main),
        "--compare-dir", str(compare),
        "--output", str(output),
    )

    assert result.returncode == 0, result.stderr
    html = output.read_text(encoding="utf-8")
    assert "Overlay Bands" in html
    assert "renderOverlayBands" in html
    assert "Delta-E" in html


def test_report_overlay_mismatch_warning_and_html_delta_panel(tmp_path: Path):
    main = write_bands_case(tmp_path / "case-a", SAMPLE_BANDS, ef=0.0)
    compare = write_bands_case(tmp_path / "case-b", SAMPLE_MISMATCH_BANDS, ef=0.1)

    payload = build_report(main, compare_dirs=[compare])
    overlay = next(s for s in payload.sections if s.section_id == "bands_overlay")

    assert overlay.status == "warn"
    assert any("k coordinate mismatch" in insight.message for insight in overlay.insights)
    html = render_report_html(payload)
    assert "Overlay Bands" in html
    assert "renderOverlayBands" in html
    assert "Delta-E" in html
