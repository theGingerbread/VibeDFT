# VibeDFT v2 语言与工具策略

## 1. 设计目标与约束

VibeDFT v2 的目标不是“给科研做一个通用平台”，而是构建一个**可供 agent 安全调用的任务合同系统**。这决定了语言与工具选择。

结论先行：核心系统采用 Python-first、CLI-first。所有高频逻辑（parse/review/clean/registry）都应在 Python 库内完成，输出标准化 JSON。其余接口（MCP、HTTP、GUI）全部排在后续，不得反向侵入核心。

此设计的核心不是技术名气，也不是生态时髦度，而是：
- 是否能保证 schema 可进化；
- 是否能稳定产出可验证证据链；
- 是否能让多任务并行和审稿式决策不依赖开发者直觉。

---

## 2. Python-first 的边界定义

### 必须使用 Python 的原因

1. **科学生态兼容性最高**：Quantum ESPRESSO 相关的文本解析、数值分析、Pydantic/dataclass 生态、测试和 CI 集成全部天然适配。
2. **类型与契约落地快**：dataclass、pydantic、json-schema 生态成熟。
3. **CLI 与任务脚本协作自然**：`argparse`/`subprocess`/`logging` 足够。
4. **复用现有库成本最低**：现有代码已大量使用 Python。

### 什么不该上 Python

- 不应把 Python 用于高性能数值核心（如大规模 FFT、矩阵求逆并行）；
- 不应把 Python 扩展到超高频 GUI event-loop；
- 不应把 Python 替代任务调度系统（这类应交给调度器/队列）。

---

## 3. 为什么不是 Rust / Go / TypeScript first

### Rust / Go

高性能和编译型优点成立，但会引入不必要迁移成本：
- 重构现有 parser/测试成本高；
- 与现有科学库衔接复杂；
- 加剧 schema 与 Python dataclass 的镜像维护。

### TypeScript

适合前端与 API 服务，不适合作为核心科学 contract 引擎：
- 生态不直接匹配 QE 文本解析；
- 生成的科学对象模型难保证与 Python 中的现有实现一致；
- 作为次级 SDK 层可以，但不应成为源模型。

### 结论

- 后端合同层不采用 Rust/Go/TS 重写；
- 可在后续按需补充轻量 CLI wrapper 或 API 框架，前提是共享 registry/schema 且不改变核心。

---

## 4. dataclasses vs Pydantic

### 当前基线

仓库已经使用 Python dataclasses 做主要 contract（`CleanedResult`, `ReviewResult`, `Evidence`, `Provenance`, `Diagnostics`），这一点应保留。

### 风险

- dataclass 缺失运行时字段校验；
- schema 版本演进时，历史兼容需手工处理；
- 错误字段会在运行时才泄露。

### 逐步策略

- **阶段 1（当前）**：保留 dataclass 作为主模型，重点在字段规范与清洗规则；
- **阶段 2**：新增 JSON schema 导出工具；
- **阶段 3**：对外暴露层（CLI/MCP）可引入 Pydantic 做输入校验；
- **阶段 4**：若复杂程度上升，再考虑 core 也引入 `BaseModel`，但只做结构增强，不替换 dataclass 核心。

这使得我们在“契约稳定”和“重构代价”之间取得平衡。

---

## 5. JSON Schema 策略

1. 所有 CleanedResult/ReviewResult 的 JSON shape 在 `_shared/contracts` 下版本化；
2. schema 首选集中输出为 `docs/schema/`（或 `src/vibedft/_shared/schema/`）；
3. `status`, `readiness`, `evidence` 等字段必须在 schema 层进行格式约束；
4. CLI 输出 envelope 需要严格对齐 schema 中 `command`、`ok`、`result` / `error` 约定；
5. schema 版本作为治理资产，在 PR 中必须同步更新并在文档中声明。

---

## 6. CLI、MCP、HTTP 的关系

### CLI：第一入口

CLI 是当前唯一稳定生产入口：它读取文件路径、调用 registry handler、输出 JSON。任何 agent-facing 任务优先走 CLI。

### MCP：预留但后置

MCP 可作为 registry 的消费者，不应改写 contract。即：
- handler 是 registry 中的同一函数；
- 输入输出均为相同 JSON envelope；
- MCP 只做参数透传，不做科学判断。

### HTTP：严格后置

HTTP 若引入，必须在 v2 末期作为远程访问层，复用同一命令/模型，不允许内部重复逻辑。

---

## 7. 外部工具的边界定位

### ASE / pymatgen

定位在 `structure/` 与 `calculator` 的输入/输出兼容层，不是科学判断层。

### AiiDA

- 仅可作为示例/参照；
- 不应作为核心依赖；
- 不应决定 VibeDFT 的任务模型。

### Phonopy / spglib

- 可作为对照或辅助校验；
- 不替代 QE DFPT 合同；
- `phonon` 系列主要依赖 QE 原生输出与任务 contract。

### Scheduler adapter（SLURM/PBS）

- run stage 及 monitor 可有 adapter；
- adapter 只负责启动命令/轮询日志，不应输出科学 `PASS/WARN/BLOCK`；
- 失败事件以标准 issue/evidence 形式回传到 diagnostics。

---

## 8. Notebook 与交互界面

Notebook（Jupyter）是分析验证和教学实验环境，不进入 core。

若未来要支持 notebook API：
- 调用 registry handler；
- 显示 JSON result 和证据；
- 不直接调用 parse 私有函数，避免 schema 越权。

GUI、Dashboard 在后续产品化阶段，默认不是本轮优先级。

---

## 9. 版本与演进原则

1. 工具栈变更必须兼容 `CleanedResult` 与 `ReviewResult`；
2. CLI 参数变更必须有退化兼容；
3. 所有新增工具不应增加对 raw output 的直接依赖点；
4. 工具引入必须经过 `command registry` 与 schema 同步。

---

## 10. 不允许的方向（本轮）

1. 不引入 MCP 作为唯一入口；
2. 不以 AiiDA 或数据库持久化模型替代 cleaned-result 合同；
3. 不在主分支引入 HTTP 路径；
4. 不把 structure/analysis 放大到 workflow 编排系统；
5. 不用多语言重复解析。

---

## 11. 技术与组织协同要求

每个子 agent 在新增功能前必须回答：
- 使用 dataclass / pydantic 的理由是什么？
- JSON schema 如何同步？
- 是否影响 `command registry`、CLI envelope；
- 是否在 `_shared/contracts` 层新增字段，是否需要 migration；
- 证据（Evidence）是否仍可追踪到 source line/path。

在未回答清楚前，不得进入实现阶段。

