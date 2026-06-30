from pathlib import Path

import yaml

from vibedft.core.registry import Registry
from vibedft.core.setup import build_setup_bundle
from vibedft.core.case import init_case


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dev_extra_installs_fastapi_testclient_dependency():
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"httpx>=' in pyproject
    assert "httpx2" not in pyproject


def test_build_setup_bundle_contains_workflow_steps_and_agent_prompts(tmp_path: Path):
    registry = Registry.from_project_root(PROJECT_ROOT)
    bundle = build_setup_bundle(
        registry=registry,
        software="qe",
        workflow="qe.scf_dos.v1",
        material="HfBr2",
        profile="qe-hfx2-test",
        output_dir=tmp_path,
    )

    assert bundle.html_path.exists()
    assert bundle.request_path.exists()
    assert "SCF" in bundle.html_path.read_text(encoding="utf-8")
    assert "参数表" in bundle.html_path.read_text(encoding="utf-8")
    assert "Agent 闭环交互" in bundle.html_path.read_text(encoding="utf-8")
    assert "收敛性测试" in bundle.html_path.read_text(encoding="utf-8")
    assert "来源链" in bundle.html_path.read_text(encoding="utf-8")

    request = yaml.safe_load(bundle.request_path.read_text(encoding="utf-8"))
    assert request["workflow"] == "qe.scf_dos.v1"
    assert request["material"] == "HfBr2"
    assert request["profile"] == "qe-hfx2-test"
    assert request["parameters"]["qe.pw.system.ecutwfc"]["recommended"] == 80
    assert request["parameters"]["qe.pw.system.ecutwfc"]["value"] == 60


def test_init_case_writes_slurm_first_log_and_metadata(tmp_path: Path):
    registry = Registry.from_project_root(PROJECT_ROOT)
    case_dir = init_case(
        registry=registry,
        software="qe",
        workflow="qe.scf_dos.v1",
        material="HfBr2",
        profile="qe-hfx2-test",
        case_id="HfBr2-test",
        output_dir=tmp_path,
    )

    log_path = case_dir / "logs" / "calculation.md"
    metadata_path = case_dir / "vibedft.case.yaml"
    assert log_path.exists()
    assert metadata_path.exists()
    assert "Slurm is required" in log_path.read_text(encoding="utf-8")
    assert "scp input bundle to server" in log_path.read_text(encoding="utf-8")
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    assert metadata["execution"]["scheduler"] == "slurm"
    assert metadata["execution"]["direct_remote_execution_allowed"] is False
