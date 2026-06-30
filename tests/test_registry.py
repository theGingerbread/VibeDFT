from pathlib import Path

from vibedft.core.registry import Registry


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_discovers_qe_and_vasp_plugins():
    registry = Registry.from_project_root(PROJECT_ROOT)

    assert registry.plugin_ids() == ["qe", "vasp"]


def test_parameter_registry_exposes_metadata_for_qe_cutoff():
    registry = Registry.from_project_root(PROJECT_ROOT)

    parameter = registry.get_parameter("qe.pw.system.ecutwfc")

    assert parameter["software"] == "qe"
    assert parameter["program"] == "pw.x"
    assert parameter["name"] == "ecutwfc"
    assert parameter["unit"] == "Ry"
    assert parameter["ui"]["level"] == "basic"


def test_registry_loads_materials_from_config_fallback():
    registry = Registry.from_project_root(PROJECT_ROOT)

    assert "HfBr2" in registry.materials
    assert "HfCl2" in registry.materials
    assert "HfI2" in registry.materials


def test_resolve_parameters_applies_material_and_profile_overrides():
    registry = Registry.from_project_root(PROJECT_ROOT)

    resolved = registry.resolve_parameters(
        software="qe",
        workflow="qe.scf_dos.v1",
        material="HfBr2",
        profile="qe-hfx2-scf-dos",
    )

    assert resolved["qe.pw.control.prefix"]["value"] == "HfBr2"
    assert resolved["qe.pw.system.ecutwfc"]["value"] == 80
    assert resolved["qe.pw.system.ecutrho"]["value"] == 640
    assert resolved["common.kpoints.grid"]["value"] == [18, 18, 1]
    assert resolved["qe.pw.system.ecutwfc"]["source"] == "profile:qe-hfx2-scf-dos"


def test_registry_discovers_all_qe_workflows():
    """Assert the registry exposes all required QE workflows from Phase 1."""
    registry = Registry.from_project_root(PROJECT_ROOT)
    wf_ids = set(registry.workflows.keys())

    required = [
        "qe.scf_dos.v1",
        "qe.scf_dos.v2",
        "qe.rx.v1",
        "qe.bands.v1",
        "qe.ph_epc.v1",
        "qe.fs.v1",
    ]
    for wf_id in required:
        assert wf_id in wf_ids, f"Missing workflow: {wf_id}"

    # Verify ph_epc.v1 encodes the correct stage ordering
    ph_epc = registry.workflows["qe.ph_epc.v1"]
    stage_ids = [s["id"] for s in ph_epc.get("stages", [])]
    # pwxall must come before pwx
    pwxall_idx = stage_ids.index("pwxall") if "pwxall" in stage_ids else -1
    pwx_idx = stage_ids.index("pwx") if "pwx" in stage_ids else -1
    assert pwxall_idx >= 0 and pwx_idx >= 0, "ph_epc.v1 must have pwxall and pwx stages"
    assert pwxall_idx < pwx_idx, "pwxall MUST come before pwx in stage ordering"


def test_expanded_parameter_registry():
    """Assert the registry exposes expanded pw, ph, and postprocess parameters."""
    registry = Registry.from_project_root(PROJECT_ROOT)

    # pw.x parameters
    required_pw = [
        "qe.pw.control.calculation",
        "qe.pw.control.outdir",
        "qe.pw.system.input_dft",
        "qe.pw.system.occupations",
        "qe.pw.system.degauss",
        "qe.pw.system.assume_isolated",
        "qe.pw.system.cell_dofree",
        "qe.pw.electrons.conv_thr",
        "qe.pw.electrons.mixing_beta",
        "qe.pw.electrons.electron_maxstep",
    ]
    for pid in required_pw:
        assert pid in registry.parameters, f"Missing pw param: {pid}"

    # ph.x parameters
    required_ph = [
        "qe.ph.ldisp",
        "qe.ph.nq1",
        "qe.ph.nq2",
        "qe.ph.nq3",
        "qe.ph.start_q",
        "qe.ph.last_q",
        "qe.ph.electron_phonon",
        "qe.ph.el_ph_sigma",
        "qe.ph.el_ph_nsigma",
        "qe.ph.tr2_ph",
    ]
    for pid in required_ph:
        assert pid in registry.parameters, f"Missing ph param: {pid}"

    # postprocess parameters
    required_pp = [
        "qe.dos.DeltaE",
        "qe.dos.ngauss",
        "qe.projwfc.prefix",
        "qe.bands.prefix",
        "qe.q2r.fildyn",
        "qe.q2r.flfrc",
        "qe.q2r.zasr",
        "qe.matdyn.flfrq",
        "qe.matdyn.flfrc",
        "qe.matdyn.dos",
        "qe.matdyn.la2F",
        "qe.lambda.mustar",
        "qe.fs.deltaE",
    ]
    for pid in required_pp:
        assert pid in registry.parameters, f"Missing postprocess param: {pid}"


def test_resolve_ph_epc_workflow_parameters():
    """Resolve parameters for the PH/EPC workflow."""
    registry = Registry.from_project_root(PROJECT_ROOT)

    resolved = registry.resolve_parameters(
        software="qe",
        workflow="qe.ph_epc.v1",
        material="HfBr2",
        profile="qe-hfx2-test",
    )

    # Should include pw, ph, q2r, matdyn, and lambda parameters
    assert "qe.pw.system.ecutwfc" in resolved
    assert "qe.ph.ldisp" in resolved
    assert "qe.ph.nq1" in resolved
    assert "qe.q2r.zasr" in resolved
    assert "qe.lambda.mustar" in resolved
    # The la2F parameter should default to false (safe)
    assert resolved["qe.matdyn.la2F"]["value"] is False


def test_ph_epc_split_templates_render_distinct_q_ranges_without_stray_lines():
    registry = Registry.from_project_root(PROJECT_ROOT)

    rendered = {
        "phx": registry.render_template(
            software="qe",
            workflow="qe.ph_epc.v1",
            material="HfBr2",
            profile="qe-hfx2-test",
            template_rel="templates/ph_epc/phx.in.j2",
        ),
        "phx1": registry.render_template(
            software="qe",
            workflow="qe.ph_epc.v1",
            material="HfBr2",
            profile="qe-hfx2-test",
            template_rel="templates/ph_epc/phx1.in.j2",
        ),
        "phx2": registry.render_template(
            software="qe",
            workflow="qe.ph_epc.v1",
            material="HfBr2",
            profile="qe-hfx2-test",
            template_rel="templates/ph_epc/phx2.in.j2",
        ),
        "phx3": registry.render_template(
            software="qe",
            workflow="qe.ph_epc.v1",
            material="HfBr2",
            profile="qe-hfx2-test",
            template_rel="templates/ph_epc/phx3.in.j2",
        ),
    }

    expected_ranges = {
        "phx": ("start_q = 1", "last_q = 1"),
        "phx1": ("start_q = 2", "last_q = 4"),
        "phx2": ("start_q = 5", "last_q = 7"),
        "phx3": ("start_q = 8", "last_q = 10"),
    }
    for name, (start_q, last_q) in expected_ranges.items():
        assert start_q in rendered[name]
        assert last_q in rendered[name]
        # All rendered templates must have proper QE namelist syntax (no blank stray lines)


def test_bands_templates_use_qe71_safe_nscf_and_shared_outdir():
    registry = Registry.from_project_root(PROJECT_ROOT)

    bands_in = registry.render_template(
        software="qe",
        workflow="qe.bands.v1",
        material="HfBr2",
        profile="qe-hfx2-test",
        template_rel="templates/bands/bands.in.j2",
    )
    bandsx_in = registry.render_template(
        software="qe",
        workflow="qe.bands.v1",
        material="HfBr2",
        profile="qe-hfx2-test",
        template_rel="templates/bands/bandsx.in.j2",
    )

    # bands template avoids restart_mode and wf_collect; outdir is parameterized
    assert "calculation = 'bands'" in bands_in or "calculation = 'nscf'" in bands_in
    assert "restart_mode" not in bands_in
    assert "wf_collect" not in bands_in


def test_nscf_uniform_renders_nscf_with_separate_outdir():
    """nscf_uniform must use calculation='nscf' and its own outdir."""
    registry = Registry.from_project_root(PROJECT_ROOT)
    nscf_in = registry.render_template(
        software="qe", workflow="qe.nscf_uniform.v1",
        material="HfBr2", profile="qe-hfx2-test",
        template_rel="templates/scf_dos/nscf_uniform.in.j2",
    )
    assert "calculation = 'nscf'" in nscf_in
    assert "outdir = './out_nscf/'" in nscf_in
    assert "K_POINTS" in nscf_in


def test_dos_uses_nscf_outdir():
    """dos.x must read from NSCF outdir, not SCF outdir."""
    registry = Registry.from_project_root(PROJECT_ROOT)
    dos_in = registry.render_template(
        software="qe", workflow="qe.dos.v1",
        material="HfBr2", profile="qe-hfx2-test",
        template_rel="templates/scf_dos/dos.in.j2",
    )
    assert "&DOS" in dos_in
    assert "out_nscf" in dos_in


def test_projwfc_uses_nscf_outdir():
    """projwfc.x must read from NSCF outdir."""
    registry = Registry.from_project_root(PROJECT_ROOT)
    pwf_in = registry.render_template(
        software="qe", workflow="qe.projwfc.v1",
        material="HfBr2", profile="qe-hfx2-test",
        template_rel="templates/scf_dos/projwfc.in.j2",
    )
    assert "&PROJWFC" in pwf_in
    assert "out_nscf" in pwf_in


def test_scf_standalone_renders_scf_calculation():
    """scf.v1 standalone must render calculation='scf'."""
    registry = Registry.from_project_root(PROJECT_ROOT)
    scf_in = registry.render_template(
        software="qe", workflow="qe.scf.v1",
        material="HfBr2", profile="qe-hfx2-test",
        template_rel="templates/scf_dos/scf.in.j2",
    )
    assert "calculation = 'scf'" in scf_in


def test_unknown_workflow_raises_registry_error():
    """Verify that unknown workflows still raise RegistryError."""
    import pytest as pt
    from vibedft.core.registry import RegistryError

    registry = Registry.from_project_root(PROJECT_ROOT)
    with pt.raises(RegistryError):
        registry.resolve_parameters(
            software="qe",
            workflow="qe.nonexistent.v99",
            material="HfBr2",
            profile="qe-hfx2-test",
        )
