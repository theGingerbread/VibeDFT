from importlib import import_module


def test_v2_platform_packages_are_importable():
    modules = [
        "vibedft.main",
        "vibedft.calculator",
        "vibedft.calculator.qe",
        "vibedft.structure",
        "vibedft.analysis",
        "vibedft._shared.contracts",
    ]

    for name in modules:
        assert import_module(name) is not None, f"expected module {name} to exist"


def test_qe_task_modules_follow_standard_pipeline_layout():
    task_modules = [
        "scf",
        "nscf",
        "relax",
        "vc_relax",
        "bands",
        "dos",
        "pdos",
        "phonon",
        "charge",
        "bader",
        "workfunction",
    ]
    stage_modules = ["params", "prepare", "run", "monitor", "parse", "clean"]

    for task_name in task_modules:
        for stage_name in stage_modules:
            module_name = f"vibedft.calculator.qe.{task_name}.{stage_name}"
            assert import_module(module_name) is not None, (
                f"expected QE task stage module {module_name} to exist"
            )


def test_cleaned_result_contract_exposes_platform_boundary_fields():
    contracts = import_module("vibedft._shared.contracts")
    cleaned = contracts.CleanedResult(
        calculator="qe",
        task="scf",
        schema_version="0.1",
        source_artifacts=["scf.out"],
        payload={"total_energy_ry": -100.0},
    )

    assert cleaned.calculator == "qe"
    assert cleaned.task == "scf"
    assert cleaned.schema_version == "0.1"
    assert cleaned.payload["total_energy_ry"] == -100.0


def test_platform_blueprint_doc_exists():
    from pathlib import Path

    doc = Path(__file__).resolve().parents[1] / "docs" / "reference" / "vibedft-v2-platform-blueprint.md"
    assert doc.is_file(), "expected the v2 platform blueprint to exist"


def test_legacy_modules_are_explicitly_marked():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    legacy_dirs = [
        "agent",
        "analyzers",
        "classifiers",
        "cli",
        "convergence",
        "core",
        "decision",
        "epw",
        "frontend",
        "generators",
        "knowledge_base",
        "models",
        "parsers",
        "postprocess",
        "properties",
        "research",
        "semantics",
        "server",
        "spin",
        "validators",
    ]

    for directory in legacy_dirs:
        marker = root / "src" / "vibedft" / directory / "LEGACY.md"
        assert marker.is_file(), f"expected legacy marker for {directory}"
