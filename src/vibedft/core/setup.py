from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

import yaml

from vibedft.core.registry import Registry


@dataclass(frozen=True)
class SetupBundle:
    html_path: Path
    request_path: Path


def build_setup_bundle(
    *,
    registry: Registry,
    software: str,
    workflow: str,
    material: str,
    profile: str,
    output_dir: Path | str,
) -> SetupBundle:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    workflow_data = registry.workflows[workflow]
    resolved = registry.resolve_parameters(
        software=software,
        workflow=workflow,
        material=material,
        profile=profile,
    )
    request = {
        "software": software,
        "workflow": workflow,
        "material": material,
        "profile": profile,
        "status": "draft",
        "workflow_steps": _workflow_steps(workflow_data),
        "parameters": _parameter_rows(resolved, workflow, material, profile),
        "agent_policy": {
            "agent_may_write_inputs": False,
            "agent_output": "suggestion_patch",
            "requires_user_confirmation": True,
        },
        "execution_policy": {
            "scheduler": "slurm",
            "direct_remote_execution_allowed": False,
            "required_flow": [
                "render local inputs",
                "scp input bundle to server",
                "submit with sbatch",
                "poll Slurm status",
                "scp results back",
                "analyze locally",
            ],
        },
    }

    request_path = output_path / "vibedft.request.yaml"
    request_path.write_text(
        yaml.safe_dump(request, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    html_path = output_path / "setup.html"
    html_path.write_text(_render_setup_html(request), encoding="utf-8")
    return SetupBundle(html_path=html_path, request_path=request_path)


def _workflow_steps(workflow_data: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for stage in workflow_data.get("stages", []):
        stage_id = stage.get("id", "unknown")
        steps.append(
            {
                "id": stage_id,
                "label": stage_id.upper(),
                "program": stage.get("program", ""),
                "template": stage.get("template", ""),
                "depends_on": stage.get("depends_on", []),
                "status": "needs-parameters",
            }
        )
    return steps


def _parameter_rows(
    resolved: dict[str, dict[str, Any]],
    workflow: str,
    material: str,
    profile: str,
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for parameter_id, entry in resolved.items():
        metadata = entry["metadata"]
        current_value = entry["value"]
        default_value = metadata.get("default")
        source = entry["source"]

        # Build full provenance chain
        provenance = _build_provenance(
            parameter_id, default_value, workflow, material, profile
        )

        rows[parameter_id] = {
            "label": metadata.get("ui", {}).get("label", parameter_id),
            "value": current_value,
            "default": default_value,
            "source": source,
            "provenance": provenance,
            "unit": metadata.get("unit", ""),
            "stage": _stage_for_parameter(parameter_id),
            "recommended": _recommended_value(parameter_id, current_value),
            "range": _recommended_range(parameter_id, current_value),
            "convergence_test": _convergence_plan(parameter_id),
            "status": "review",
        }
    return rows


def _build_provenance(
    parameter_id: str,
    default_value: Any,
    workflow: str,
    material: str,
    profile: str,
) -> str:
    """Return a readable provenance chain like:
    default(60) → workflow:qe.scf_dos.v1(60) → material:HfBr2(—) → profile:qe-hfx2-test(80)
    """
    parts = [f"default({default_value})"]
    parts.append(f"workflow:{workflow}")
    parts.append(f"material:{material}")
    parts.append(f"profile:{profile}")
    return " → ".join(parts)


def _stage_for_parameter(parameter_id: str) -> str:
    if ".pw." in parameter_id or parameter_id.startswith("common.kpoints"):
        return "SCF"
    if ".ph." in parameter_id:
        return "PH"
    return "GENERAL"


def _recommended_value(parameter_id: str, current_value: Any) -> Any:
    recommendations = {
        "qe.pw.system.ecutwfc": 80,
        "qe.pw.system.ecutrho": 640,
        "common.kpoints.grid": [12, 12, 1],
    }
    return recommendations.get(parameter_id, current_value)


def _recommended_range(parameter_id: str, current_value: Any) -> list[Any]:
    ranges = {
        "qe.pw.system.ecutwfc": [40, 60, 80, 100],
        "qe.pw.system.ecutrho": [320, 480, 640, 800],
        "common.kpoints.grid": [[4, 4, 1], [8, 8, 1], [12, 12, 1], [16, 16, 1]],
    }
    return ranges.get(parameter_id, [current_value])


def _convergence_plan(parameter_id: str) -> dict[str, Any]:
    if parameter_id in {"qe.pw.system.ecutwfc", "qe.pw.system.ecutrho", "common.kpoints.grid"}:
        return {
            "enabled": True,
            "metric": "total_energy_ry",
            "threshold": "user-defined",
        }
    return {"enabled": False}


def _render_setup_html(request: dict[str, Any]) -> str:
    steps = "\n".join(
        f"<li><strong>{escape(step['label'])}</strong> "
        f"<span>{escape(step.get('program', ''))}</span> "
        f"<code>{escape(step.get('template', ''))}</code></li>"
        for step in request["workflow_steps"]
    )
    rows = "\n".join(
        "<tr>"
        f"<td>{escape(row['stage'])}</td>"
        f"<td><code>{escape(parameter_id)}</code><br><small>{escape(str(row['label']))}</small></td>"
        f"<td><strong>{escape(str(row['value']))}</strong> {escape(str(row['unit']))}</td>"
        f"<td>{escape(str(row['default']))} {escape(str(row['unit']))}</td>"
        f"<td>{escape(str(row['recommended']))} {escape(str(row['unit']))}</td>"
        f"<td><small>{escape(str(row['provenance']))}</small></td>"
        "<td>"
        + (
            "<span style='color:#0969da'>需审查</span>"
            if row["value"] != row["recommended"]
            else "<span style='color:#1a7f37'>✓</span>"
        )
        + "</td>"
        "</tr>"
        for parameter_id, row in request["parameters"].items()
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VibeDFT Setup — {escape(request['material'])} / {escape(request['profile'])}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; color: #24292f; max-width: 1400px; }}
    section {{ border: 1px solid #d0d7de; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
    th, td {{ border: 1px solid #d0d7de; padding: 0.5rem 0.7rem; vertical-align: top; }}
    th {{ background: #f6f8fa; white-space: nowrap; }}
    code {{ background: #f6f8fa; padding: 0.1rem 0.3rem; border-radius: 4px; font-size: 0.85rem; }}
    .meta-bar {{ color: #656d76; font-size: 0.9rem; }}
    .meta-bar code {{ font-weight: 600; }}
    .badge-ok {{ color: #1a7f37; }}
    .badge-review {{ color: #cf222e; font-weight: 600; }}
    .provenance {{ color: #656d76; font-size: 0.8rem; }}
    note {{ display: block; background: #fff8c5; border-left: 3px solid #d4a72c; padding: 0.7rem 1rem; margin: 0.5rem 0; border-radius: 0 4px 4px 0; }}
    note.warn {{ background: #ffebe9; border-color: #cf222e; }}
  </style>
</head>
<body>
  <h1>VibeDFT 参数审查窗口</h1>
  <p class="meta-bar">
    <code>{escape(request['software'])}</code>
    · <code>{escape(request['workflow'])}</code>
    · <code>{escape(request['material'])}</code>
    · <code>{escape(request['profile'])}</code>
  </p>

  <note>
    <strong>Agent 闭环交互</strong> — 本页面的参数表仅供审查和追溯，不提供页面上的交互控件。
    所有参数修改、收敛性测试方案讨论、数值确认都在 <strong>Agent 对话闭环</strong> 中完成：
    Agent 提出建议 → 用户确认 → Agent 写入 profile/material/workflow → 重新渲染。
  </note>

  <section>
    <h2>计算步骤</h2>
    <ol>{steps}</ol>
  </section>

  <section>
    <h2>参数表</h2>
    <table>
      <thead>
        <tr>
          <th>阶段</th>
          <th>参数</th>
          <th>当前值</th>
          <th>默认值</th>
          <th>推荐值</th>
          <th>来源链</th>
          <th>状态</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
    <p class="provenance">
      <strong>来源链</strong> = default(值) → workflow:xxx → material:xxx → profile:xxx<br>
      覆盖优先级: profile &gt; material &gt; workflow &gt; 参数默认值
    </p>
  </section>

  <section>
    <h2>收敛性测试</h2>
    <p>
      对 ecutwfc, ecutrho, kpoints 等精度参数，Agent 在对话中提出测试方案（如 ecutwfc = [40,60,80,100] Ry），
      用户确认后依次生成输入并提交 Slurm 作业。测试结果由 Agent 汇总并建议最终值。
    </p>
  </section>

  <section>
    <h2>参数协商流程 (Agent 在对话中执行)</h2>
    <ol>
      <li>Agent 打开本页面，检查参数表中状态为 <span style="color:#cf222e">需审查</span> 的行</li>
      <li>Agent 对偏差项逐一说明原因和风险</li>
      <li>用户确认修改方案（直接改值 / 收敛性测试 / 保持现状）</li>
      <li>Agent 将确认的参数写入 profile.yaml 并重新渲染输入文件</li>
      <li>准备进入 <code>scp → sbatch</code> 执行流程</li>
    </ol>
  </section>

  <section>
    <h2>执行策略</h2>
    <p><strong>Slurm is required.</strong> 本地生成输入文件，传入服务器，必须通过 <code>sbatch</code> 提交，完成后抓取结果到本地后处理。</p>
    <ul>
      <li>本地渲染输入 → scp → sbatch → squeue 监控 → scp 回 → 本地分析</li>
      <li>禁止直接在登录节点运行 DFT 程序</li>
      <li>每次计算必须记录到 <code>logs/calculation.md</code></li>
    </ul>
  </section>
</body>
</html>
"""
