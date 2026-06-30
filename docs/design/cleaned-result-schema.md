# CleanedResult / ReviewResult / Evidence / Diagnostics 设计文档

## 0. 目标

本文件定义 VibeDFT v2 的统一结果合同，作为所有 task 清洗后的唯一结构化入口。该合同需满足：

- 给 agent 稳定消费。
- 给 CLI/MCP/HTTP 提供一致 JSON。
- 保留证据可追溯（line/evidence/artifact）。
- 显式区分 runtime 状态与科学审阅状态。

统一术语：

- `CleanedResult`：任务级统一输出。
- `ReviewResult`：任务级审阅决策。
- `Evidence`：证据片段。
- `Diagnostics`：诊断分组（parser/消息/数值/流程）。

---

## 1. 现状问题（PR2 之后的同步点）

### 1.1 readiness 过于松散

当前 `readiness: dict[str, bool]` 在 SCF 中用于存放 allowed/blocked 列表，导致语义不固定。后续会遇到：

- 同一字段在不同任务含义不一致。
- 无法记录“为何可/不可用”。
- 无法提供证据引用（evidence id）。

### 1.2 review 藏在 diagnostics 内

`CleanedResult` 的关键审阅决策若完全嵌入 `diagnostics`，会让下游难以直接判断 scientific gate。

### 1.3 Evidence 信息不足

当前 Evidence 最低字段有 `source/field/value/interpretation/line_number`。
在多文件任务（phonon、nscf链、postprocessing）中还缺少：

- artifact 标识
- 行段范围
- section 标识（如“ph.x convergence block”）

### 1.4 Diagnostics 混杂

目前诊断通常混在一个扁平列表，难以区分：

- 解析器异常
- QE 输出警告
- 数值风险
- 工作流风险

### 1.5 schema_version 与兼容

当前 `schema_version` 缺省较低，且缺乏正式版本演进策略。

---

## 2. 推荐标准结果形态

建议结构（建议字段）：

```json
{
  "schema_version": "1.0.0",
  "calculator": "qe",
  "task": "qe.scf",
  "status": "pass",
  "review": {
    "status": "PASS",
    "reasons": [...],
    "allowed_downstream": ["relax", "nscf", "bands"],
    "blocked_downstream": ["phonon"],
    "recommendations": ["rerun with stricter q-grid"],
    "evidence_refs": ["ev:scf:1", "ev:scf:2"]
  },
  "source_files": ["pw.scf.HfBr2.out"],
  "provenance": {...},
  "inputs": {...},
  "outputs": {...},
  "observables": {...},
  "diagnostics": {
    "parser": {...},
    "qe_messages": {...},
    "numerical_risk": {...},
    "workflow_risk": {...},
    "evidence": []
  },
  "readiness": {
    "downstream": {
      "dos": {"allowed": true, "reason": "passed", "evidence_refs": ["ev:scf:3"]},
      "phonon": {"allowed": false, "reason": "convergence not strict enough", "evidence_refs": ["ev:scf:8"]}
    },
    "overall": "pass"
  },
  "warnings": ["..."],
  "next_actions": ["..."],
  "artifacts": [
    {"role": "stdout", "path": "pw.scf.HfBr2.out", "hash": "sha256:..."}
  ]
}
```

---

## 3. dataclass 与 Pydantic 边界

### 3.1 dataclass 为默认

- 当前工程已使用 dataclass。
- 保留 dataclass 作为运行时主力，便于轻量序列化。

### 3.2 Pydantic 的引入时机

- 建议放在 `schema_version >= 1.0.0` + `json-schema` 导出完成后。
- 迁移方式：
  - 现有 `dataclasses` 保持输出兼容。
  - 新增 `v1` 验证层可在 API 边界使用 pydantic。

---

## 4. Evidence 建议扩展

建议 Evidence 支持：

- `source`
- `artifact`
- `field`
- `value`
- `interpretation`
- `line_number`
- `line_start`
- `line_end`
- `section`

### 4.1 证据语义

- `field` 不仅是名称，也可是证据路径（如 `workflow_readiness.dos`）。
- `interpretation` 固定是可读文本，不要塞长段 JSON。
- `artifact` 对多文件任务必填（如 dynmat/matdyn/fdos）。

---

## 5. Diagnostics 四分区建议

### 5.1 parser

- 解析器错误、丢字段、字段降级。

### 5.2 qe_messages

- 原始 QE 错误/警告的归类信息。

### 5.3 numerical_risk

- 收敛振荡、能量跳变、cutoff 过低等数值风险。

### 5.4 workflow_risk

- 与下游依赖相关的风险和 blocked 决策前置条件。

---

## 6. 状态三分法

## 6.1 monitor.status

- 来源：`monitor.py`
- 关注运行态
- 示例：`running / blocked / completed / failed / no_data`

## 6.2 review.status

- 来源：`review.py`
- 科学判定：`PASS / WARN / BLOCK`
- 决定可否进入下游。

## 6.3 result.status

- 来源：`clean.py`
- 与结果生命周期一致：
  - `pass / warn / block / failed / running / no_data`
- `block` 通常映射自 review BLOCK。

### 建议

- 不要混合使用字符串语义。
- 保留小写 lifecycle，保持 review 大写。

---

## 7. 错误 JSON 与 result JSON 的区别

### 7.1 成功结果

- `ok: true` 且存在 `result`。
- `result.status` 始终存在。

### 7.2 运行失败

- `ok: false` 且存在 `error`。
- 保留 `error.type` 与 `error.message`。

### 7.3 科学 BLOCK

- `ok: true`。
- `result.status = block`。
- 避免让 pipeline 丢失可读证据。

---

## 8. schema_version 策略

- 建议 `schema_version` 语义化版本：
  - `1.0.0`：冻结 v2 的核心字段。
  - 小修订向后兼容：`1.0.x`。
  - 字段语义变更：`1.1.0+`。

### 回退策略

- 兼容老字段：
  - `task="scf"` 与 `task="qe.scf"` 同时接受（但不再新增）。
  - `payload` 与新字段映射。

---

## 9. JSON Schema 输出策略

### 9.1 输出目录

- 推荐 `docs/schemas/json/`。
- 每个 task 产出 schema 与命令 envelope schema。

### 9.2 CI 校验

- 每个测试路径生成 payload 都要通过 schema 校验。
- CLI 与 library 共同复用 schema。

### 9.3 向后兼容

- `schema_version` 与 `compatibility_version` 可在 payload 中同时携带。
- 文档列出每次字段新增/移除兼容矩阵。

---

## 10. CLI/API/MCP 复用

- CLI output envelope 应以 `CleanedResult` 为 `result`。
- MCP handler 输出同 envelope，HTTP 返回同 payload。
- 不允许命令各自自定义字段。

---

## 11. 设计决议（本仓库执行）

1. `review` 必须提升为 `CleanedResult.review` 的一等字段。
2. `readiness` 升级为含 reason/evidence 的 typed object。
3. Evidence 增加 artifact 与 span。
4. Diagnostics 分区：parser/qe_messages/numerical/workflow。
5. 保留 dataclass 主体，Pydantic 可作为边界验证层。

---

## 12. 迁移到 1.0 草案清单

- 增加 `review` 字段。
- 保留 `status` 映射。
- 引入 `readiness.downstream` typed schema。
- 增加 artifact 证据并保持 JSON 可读。
