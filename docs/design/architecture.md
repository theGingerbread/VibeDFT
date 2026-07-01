# VibeDFT v2 架构设计（v2.0 架构收敛版）

## 0. 设计声明

本设计版本明确把 VibeDFT 定位为：

- **QE-first**：首要执行引擎是 Quantum ESPRESSO。
- **Python-first**：Python 负责任务阶段控制、解析、清洗与审阅。
- **Agent-facing**：接口输出面向自动化 agent 的结构化 JSON，而非交互式人类报告。
- **Schema-first**：`CleanedResult` / `ReviewResult` / `Evidence` 是所有下游决策的统一契约。
- **Calculator-neutral analysis**：analysis 层只能消费统一合同，不能读器后/原始输出。

当前状态：

- PR1/PR2/PR2.5/PR2.5.1 已完成。
- PR2.7（shared contract hardening）已完成。
- PR2.8（command registry + response envelope）已完成。
- PR2.8.1（observability contract alignment）已完成。
- PR2.9（contract stability documentation）已完成。
- SCF 已形成 `parse -> review -> clean -> CLI` 闭环。
- 下一步目标是把这条闭环升级为跨任务、跨下游、跨命令的一致协议。

统一术语（后续文档强制一致）：

- `CleanedResult`
- `ReviewResult`
- `Evidence`
- `Provenance`
- `Diagnostics`
- `PASS / WARN / BLOCK`
- `pass / warn / block`
- `readiness`
- `downstream`
- `command registry`
- `CLI JSON`
- `legacy inventory`

---

## 1. VibeDFT 与 QE-Learning 的关系

### 1.1 关系边界

- **QE-Learning**：方法论与流程学习仓库。负责“如何判定收敛、如何写记录、如何理解参数边界”。
- **VibeDFT**：实现仓库。负责把“可执行的解析/审阅/清洗契约”变成可复用接口。

因此两者边界必须是：

- QE-Learning 中的 checklist、理论最小模型、记录模板、教学页面，不直接提供运行时判定 API。
- VibeDFT 的 `review.py`、`clean.py`、`schemas.py` 把 QE-Learning 的标准变成机器可执行字段。
- 不允许在 VibeDFT 内把 QE-Learning 的“背景内容”原样复制为任务执行逻辑。

### 1.2 关系映射

1. QE-Learning 定义 **目标与检查项**。
2. VibeDFT 将检查项编码为 **ReviewResult + CleanedResult**。
3. Agent 或上层流水线依赖这些字段作决策，而不是手工解析原始 `.out`。
4. 当规则需要修订时先改 v2 契约，再逐步回填 QE-Learning 文档说明。

---

## 2. 五层架构：职责边界

### 2.1 架构图

```text
src/vibedft/
├── main/
│   ├── cli.py
│   ├── commands.py
│   ├── envelopes.py
│   ├── project.py
│   └── config.py
├── calculator/
│   └── qe/
│       ├── common/
│       ├── scf/   (+ review + clean + schemas)
│       ├── nscf/
│       ├── relax/
│       ├── vc_relax/
│       ├── bands/
│       ├── dos/
│       ├── pdos/
│       ├── workfunction/
│       ├── charge/
│       ├── bader/
│       └── phonon*(to be split)
├── structure/
│   ├── io.py
│   ├── normalize.py
│   └── provenance.py
├── analysis/
│   ├── ground_state.py
│   ├── electronic.py
│   ├── phonon.py
│   └── validators.py
└── _shared/
    ├── contracts.py
    └── serialization.py
```

### 2.2 main/

#### 职责（必须）

- 命令入口与路由。
- 解析参数、执行命令级校验、统一错误映射。
- 统一 envelope 生成并输出 JSON。
- 与 `calculator/*` 的调用边界。

#### 不允许

- 不允许实现科学判断。
- 不允许访问原始 `.out` 并自行决定 PASS/WARN/BLOCK。
- 不允许直接调用 legacy 分析模块形成分叉逻辑。

#### 禁用的耦合

- `main/` 不能在无版本说明情况下直接 import legacy `vibedft.cli.main`。
- 若存在 legacy fallback，必须标注为“迁移过渡期临时桥接”。

### 2.3 calculator/

#### 职责（必须）

- 每个任务封装计算器语义。
- 阶段实现：`params -> prepare -> run -> monitor -> parse -> review -> clean -> schemas`。
- `parse.py` 产出 parser 级结构化事实。
- `clean.py` 将 parser + review 融合为 `CleanedResult`。

#### 不允许

- 不允许给 analysis 生产专用逻辑。
- 不允许在 analysis 规则里解析 `.out`。

### 2.4 structure/

#### 职责（必须）

- 输入导入、坐标归一化、单位一致性、文件命名元信息。
- 结构体到下游任务的最小上下文打包。

#### 不允许

- 不做晶面重构、缺陷生成、异质结生成、slab/defect 全流程。
- 不承接深层“结构学习”或“材料设计”功能。

### 2.5 analysis/

#### 职责（必须）

- 基于 `CleanedResult` 做高层指标、结果整合、科学解释。
- 与任务具体 parser 解耦，只使用标准合同字段。

#### 不允许

- 不允许读取 raw QE output 或 `parse.py` 的数据结构。
- 不允许重复“是否可用于下游”判定。

### 2.6 _shared/

#### 职责（必须）

- 契约类型、通用诊断、序列化、跨层最小公共枚举。
- 仅保留公共模型，不直接放任务策略。

#### 不允许

- 不做计算器特定策略。
- 不充当逻辑分发层（`policy.py` 只允许在任务目录内）。

---

## 3. 跨层调用规则

### 3.1 规则总纲

- `main` -> `calculator` -> `_shared`。
- `analysis` -> `_shared` -> `CleanedResult`。
- `structure` 与各层共享 `Provenance` 字段语义。
- `analysis` 从不依赖 `calculator` raw parse。

### 3.2 禁止依赖矩阵

| 来源层 | 可依赖 | 不可依赖 |
|---|---|---|
| main | calculator/*, _shared/contracts | structure 内部 raw parser, legacy modules |
| calculator task | _shared/contracts, task own schemas | analysis 层、main 层 |
| structure | _shared/contracts, task-independent utilities | calculator/task parser |
| analysis | _shared/contracts, analysis local schemas | calculator/task parser, legacy解析器 |
| _shared | 无（仅工具） | 任何任务/analysis 领域逻辑 |

### 3.3 数据流（最小闭环）

```text
SCF output file
  -> parse_scf_output()
  -> review_scf_output()
  -> clean_scf_output()
  -> CleanedResult
  -> CLI JSON envelope
  -> Agent/Workflow
  -> analysis on CleanedResult
```

---

## 4. 为什么不能先扩展功能

### 4.1 先完成合同，再扩展任务

- 没有统一的 stage 合同与错误码，不同任务会产生不一致状态。
- 下游如果提前接入，就会出现“同一任务不同命名和判断标准”的冲突。
- 当前最小安全策略：把已有 SCF 机制固化为模板，再按顺序扩展。 

### 4.2 为什么不把 Phonon 写成单体

Phonon 在物理上含多个阶段（Gamma、q-grid、DOS、dielectric、debug）。
将其单任务化会导致：

- 下游 readiness 不可分辨。
- `ReviewResult` 的 `allowed/downstream` 无法精确。
- 错误恢复策略混淆（负频率在 debug 阶段处理方式和 gamma 响应张量不同）。

---

## 5. legacy inventory 的处理规则

### 5.1 原则

- `src/vibedft/` 现存目录中，除五层 + `calculator/qe` 外的部分默认是迁移库存。
- 任何 legacy 功能只有在被明确重写进 v2 boundary 后才能成为 canonical。
- migration 的临界条件：
  - stage 文件全部存在且非 placeholder。
  - 有任务级 `review.py`/`clean.py` 形成可复现合同。
  - 有 doc + test 覆盖（至少 clean/review 命令覆盖）。

### 5.2 迁移动作原则

- 先替换能力，不保留兼容影子实现。
- 不是“包裹旧逻辑”，而是“迁移到新 contracts”。

---

## 6. 为什么 analysis 只能消费 CleanedResult

### 6.1 因果性

- raw `.out` 解析存在多版本兼容与解析差异。
- agent 不应承担“不同任务不同 parser 细节”。
- analysis 若跨任务复用 raw 字段，几乎必然出现语义漂移。

### 6.2 合约价值

- `CleanedResult` 强制输出：
  - `status`
  - `provenance`
  - `outputs`
  - `observables`
  - `diagnostics`
  - `readiness`
- analysis 只用统一接口，便于测试与替代任务。

### 6.3 与“可复现”要求的关系

- Cleaned payload 可序列化、可追溯、可对账。
- 可做“禁止科学误入”：BLOCK 仍可返回 JSON，但应不作为下游最终依据。

---

## 7. 为什么 structure/ 保持窄边界

- 结构管理只做三件事：读取与单位规范化、结构溯源、与任务输入关联。
- QE-Learning 承担“如何设计/修改/优化结构方案”。
- `structure/` 不应接手：
  - 变形搜索
  - 缺陷掺杂生成
  - 晶面分裂与界面搭建
  - 自动推荐参数优化

---

## 8. 为什么现在不引入 MCP/HTTP

### 8.1 理由

- 现在尚未完成任务合同与 CLI envelope 的稳定性。
- MCP/HTTP 会增加消费者，迫使接口在 `review/clean/schemas` 不成熟时冻结。

### 8.2 推荐顺序

1. 完成任务合同和共享合同。
2. 稳定 CLI JSON + 命令注册。
3. 统一错误码。
4. 再引入 MCP/HTTP 作为薄封装层。

---

## 9. 八阶段任务合同为何必须冻结

### 9.1 推荐 stage

当前实践和审核结果一致：

- `params.py`
- `prepare.py`
- `run.py`
- `monitor.py`
- `parse.py`
- `review.py`
- `clean.py`
- `schemas.py`
- （可选）`policy.py`

### 9.2 规范要求

- `review.py` 与 `clean.py` 是对外可见阶段，`parse.py` 只保留语义事实。
- 每个任务须至少定义 `review` + `clean`。

---

## 10. v2-架构执行优先级结论

1. 锁定合同（本设计）
2. 整理 CleanedResult 与 Reviewschema
3. 命令 registry 与 envelope 稳定
4. 合同稳定性冻结（PR2.9）
5. SCF 复核（已完成）
6. relax + vc_relax + nscf/bands/dos/pdos
7. phonon 分拆
8. analysis 全链路只消费清洗结果

---

## 11. 本轮交付的直接产物（文档）

本轮不改功能实现，仅输出设计文档：

- `docs/design/architecture.md`（当前文件）
- `docs/design/qe-task-contract.md`
- `docs/design/cleaned-result-schema.md`
- `docs/design/command-registry.md`
- `docs/design/v2-contract-stability.md`
- `docs/design/agent-facing-cli-json.md`
- `docs/design/qe-learning-to-vibedft-map.md`
- `docs/design/module-synchronization-risk-matrix.md`
- `docs/design/phonon-task-split.md`
- `docs/design/language-and-tooling-policy.md`
- `docs/design/v2-pr-roadmap.md`
- `docs/design/human-decisions.md`

## 12. PR2.9 合同稳定性冻结条款（架构强制）

`docs/design/v2-contract-stability.md` 已将本轮关键边界固定为六条契约：  

1. `CleanedResult` 是唯一 agent-facing truth layer。  
2. `ReviewResult` 是单任务 scientific gate 且作为 `CleanedResult.review` 一等字段。  
3. `Readiness` 为 downstream DAG edge 的 typed 契约。  
4. Observability 只聚合 `CleanedResult`，不重算科学策略。  
5. CLI envelope 是 transport，不是结果合同。  
6. legacy parsed-output 桥接仅用于迁移/测试，不作为主路径。  

违反任一条均属于 v2 合同漂移，必须在提交前先补齐人类决策记录并冻结变更路径。
