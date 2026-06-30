# QE-Learning 与 VibeDFT 映射（执行版）

## 0. 目标

把学习规范转成可执行合同。映射不是一一抄录，而是“是否进入 VibeDFT 合同”的判定。

统一原则：

- QE-Learning 中能指导人类判断的内容分为两类：
  - **Contract**：写入 `_shared/contracts.py` / task contracts。
  - **Documentation-only**：仅作为背景，不进入运行时。

---

## 1. 对齐路径

| QE-Learning | VibeDFT 映射 | 状态 |
|---|---|---|
| workflow order（ground-state / electronic / phonon） | `calculator/qe/*` stage 排列 | Contract |
| PASS/WARN/BLOCK | `ReviewResult.status` | Contract |
| output review checklist | `review.py` + Evidence references | Contract |
| calculation record template | `Provenance` + task manifest + CLI metadata | Contract + Documentation |
| theory-minimum | 可放宽解释，保留在 QE-Learning | Documentation |
| sources policy | `docs/design` 与引用入口说明 | Documentation |
| structure boundary | `structure/` scope 说明 | Contract |

---

## 2. 核心映射：task -> 任务实现

### 2.1 ground-state/scf

- 映射到：`calculator/qe/scf/*`
- 合同：
  - `params` / `prepare` / `run` / `monitor` / `parse` / `review` / `clean` / `schemas`
- 结果消费：`CleanedResult`

### 2.2 ground-state/nscf

- 映射到：`calculator/qe/nscf/*`
- 读取条件：SCF 准入 + proper prefix/outdir。

### 2.3 relax / vc-relax

- 映射到：`calculator/qe/relax`, `calculator/qe/vc_relax`
- 下游允许：先 static SCF，再 NSCF/Bands/DOS/PDOS。

### 2.4 electronic/bands/dos/pdos/charge-density/elf/work-function

- 对应任务包：`bands`, `dos`, `pdos`, `charge`, `workfunction`。
- 统一依赖：SCF + (NSCF) + 参数一致。

### 2.5 phonon 系列

- 映射到：`phonon_gamma`, `phonon_qgrid`, `phonon_dos`, `dielectric`, `phonon_debug`（待拆分）。

---

## 3. 下游规则映射

QE-Learning 的 “Allowed/Blocked” 应变为：

- `review.py` 的 `allowed_downstream`。
- `blocked_downstream`。
- `clean_scf_output` 内的 `readiness`。

优势：

- 自动化流程可不再依赖人工文本。
- 规则可回放。

---

## 4. 证据映射

- QE-Learning 要求“从 output 抓证据”，在 VibeDFT 映射为：
  - Evidence `source`
  - Evidence `field`
  - Evidence `value`
  - Evidence `line_number`
  - Evidence `artifact`
  - Evidence `section`

同时建议保持 `Provenance` 的：

- `input files`
- `command`
- `version`
- `started_at / completed_at`

---

## 5. 研究记录映射

`standards/calculation-record-template.md` 映射：

- 目标与上下游 => `review` 的 reason/recommendation。
- 输入/输出摘要 => `inputs/outputs`。
- 证据 => `evidence`。
- Downstream => `readiness`。

这不是替代记录，而是把记录字段化。

---

## 6. 不是合同的内容

- 理论推导和学习注释。
- 教程式参数建议。
- 环境经验（需要在 VibeDFT 中标注来源并转成测试 fixtures）。

---

## 7. 迁移路径（推荐）

1. 固化 SCF 合同（已完成）。
2. 扩展 relax/vc_relax contract。
3. 加入 NSCF -> DOS/PDOS/Bands。
4. phonon 拆分。
5. 让 `command registry` 与 `main` 完整消费。 

---

## 8. 与 `sources` 的关系

所有 contract 决策不能直接引用“未核对来源”。

- QE 输入输出字段：优先官方文档。
- workflow 判定规则：优先 QE-Learning + 官方交叉验证。

---

## 9. 映射结果

- `docs/reference/vibedft-v2-platform-blueprint.md` 保留架构声明。
- `docs/design/qe-task-contract.md` 承担 contract 的正式文本。
- `docs/design/phonon-task-split.md` 约束 phonon 拆分。
