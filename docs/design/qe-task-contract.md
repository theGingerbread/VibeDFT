# VibeDFT QE Task Contract（阶段化任务契约）

## 0. 目的

本文件冻结 QE 任务 stage 的正式契约。目标是让任意 task 的 `params->prepare->run->monitor->parse->review->clean->schemas` 流程对外行为一致，防止 parse/review/analysis 边界混淆。

统一术语：

- `parse.py`：**事实抽取**。
- `review.py`：**科学可用性判定**。
- `clean.py`：**合同化输出**。

## 1. Stage 规范总览

每个 QE task package 建议具备以下阶段：

1. `params.py`
2. `prepare.py`
3. `run.py`
4. `monitor.py`
5. `parse.py`
6. `review.py`
7. `clean.py`
8. `schemas.py`
9. `policy.py`（可选，复杂任务可加）

该设计优于六阶段旧写法，因为 REVIEW 已在 SCF 与后续任务中被证实不可回避。

---

## 2. `params.py`

### 职责

- 定义任务输入参数模型。
- 校验参数类型、默认值、取值范围。
- 统一参数归一化（单位、别名、上下游兼容字段）。

### 输入

- 用户调用参数（CLI/API）
- task-local 运行上下文（计算目标、结构摘要）

### 输出

- `Params` dataclass
- `ValidationReport`
- `ParameterSet`

### 不允许

- 不得访问文件系统副作用。
- 不得读取 raw 输出。
- 不得进行“任务通过/失败”的科学判定。

### 是否强制

是。

### 测试

- 边界值测试
- 缺失参数异常
- 别名映射一致性

### Agent-facing

- 用于前置校验与错误早反馈。

---

## 3. `prepare.py`

### 职责

- 根据 params 组织输入文件、运行目录、artifact 清单。
- 准备可重放的 `RunBundle`：输入路径、输入文本、预期输出、环境。

### 输入

- 参数对象
- 上游 `Provenance`（可选）
- 结构上下文

### 输出

- `PreparedRun`
- `RunManifest`

### 不允许

- 不调用 QE 命令。
- 不进行 parser 语义解读。

### 是否强制

是。

### 测试

- 输入生成黄金文件测试
- dry-run 快照测试

### Agent-facing

- 可用于“是否可安全启动”确认。

---

## 4. `run.py`

### 职责

- 按 `prepare` 产物调用本地命令或调度器。
- 返回 run handle / exit status / 运行 artifact。

### 输入

- `PreparedRun`

### 输出

- `RunResult`

### 不允许

- 进行科学意义判定。
- 修改解析模型。

### 是否强制

是（除非任务当前仅离线清洗）。

### 测试

- 命令失败传播、错误码映射、环境变量注入。

### Agent-facing

- 主要提供执行状态给上层 orchestration，非直接给科学决策。

---

## 5. `monitor.py`

### 职责

- 提供运行中状态（运行中/阻塞/完成/失败）。
- 解析部分文本用于进度与异常预警。

### 输入

- stdout/stderr path 或流

### 输出

- `MonitorSnapshot`

### 不允许

- 不得做最终科学判定。
- 不得覆盖 parse/review 的职责。

### 是否强制

优先（长作业任务应强制，短作业可延后）。

### 测试

- 运行中和异常片段状态机测试。

### Agent-facing

- 供重试、看门狗、队列监视。

---

## 6. `parse.py`

### 职责

- 抽取 QE 计算器语义事实。
- 输出 parser 专用数据模型。
- 提取 `WorkflowReadiness` 的可复用基础指示（仅事实）。

### 输入

- 完整输出文本或 artifact。

### 输出

- Task-specific parsed model（如 `ScfOutput`）
- 行号和证据事件列表（用于审阅引用）。

### 不允许

- 不应做 PASS/WARN/BLOCK 判定。
- 不应“把警告解释成是否允许下游”。

### 是否强制

是。

### 测试

- 真实输出 fixture。
- 含 warning/error 的兼容性测试。

### Agent-facing

- 仅作为 clean/review 的上游输入，不直接对外暴露。

---

## 7. `review.py`

### 职责

- 根据 parsed model 计算 task 的科学判定：`PASS / WARN / BLOCK`。
- 输出 `ReviewResult`：
  - `status`
  - `reasons`
  - `evidence`
  - `allowed_downstream`
  - `blocked_downstream`
  - `recommendations`

### 输入

- parsed model + policy（可选）

### 输出

- `ReviewResult`

### 不允许

- 不读文件系统（除非仅 metadata）。
- 不做 parser 之外字段的重新解析。

### 是否强制

是。

### 测试

- pass/warn/block 三类规则测试
- 下游允许列表边界测试

### Agent-facing

- `qe.*.review` 命令可直接映射。

---

## 8. `clean.py`

### 职责

- 把 parsed + review 转换为统一 `CleanedResult`。
- 输出可 JSON 序列化的 `inputs/outputs/observables/diagnostics/readiness`。

### 输入

- parsed model
- `ReviewResult`

### 输出

- `CleanedResult`

### 不允许

- 不进行运行调度。
- 不隐去 review 关键字段。

### 是否强制

是。

### 测试

- 序列化测试
- `status` 映射测试
- 可选字段一致性

### Agent-facing

- CLI/analysis/未来 MCP/HTTP 的统一消费对象。

---

## 9. `schemas.py`

### 职责

- Task-local 模型、枚举、字段别名与 JSON schema 导出。
- 提供阶段输入/输出的形式化类型。

### 输入

- 同 task 的各 stage 需求

### 输出

- 本任务 schema 常量与类型
- 可复用的字段集合

### 不允许

- 不放置 review 策略。
- 不做文件 IO。

### 是否强制

是。

### 测试

- 类型/字段一致性测试

### Agent-facing

- 保证 schema 工具链可生成一致文档。

---

## 10. `policy.py`（可选）

### 职责

- 对复杂任务集中管理可读规则（如 phonon 子任务中的 q-grid/ASR/dielectric）。

### 输入

- parsed + config context

### 输出

- `DownstreamPolicy`

### 不允许

- 不替代 `review.py`。

### 是否强制

否。

### 测试

- 与 `review.py` 配合的策略覆盖。

### Agent-facing

- 可选，任务层内可见。

---

## 11. 任务清单与最小阶段要求

以下任务至少应具备以下字段：

- `review.py`
- `clean.py`
- `schemas.py`

任务：`scf`、`relax`、`vc_relax`、`nscf`、`bands`、`dos`、`pdos`、`phonon`（计划拆分后为 gamma/qgrid/dos/dielectric/debug）。

### 11.1 为何必须每个任务有 review/clean

- 下游决策必须统一。
- 单任务不一致会导致 agent 形成错误依赖。

---

## 12. 数据合同复用规则（关键）

- 所有 task 的审阅结果都要表达为 `ReviewResult`。
- 所有 task 的闭环最终都以 `CleanedResult` 收口。
- 所有 task 的 status 与 reason 必须可回传给 CLI envelope。

---

## 13. 迁移与验收标准

- 若 parser 已有但 no review/clean，任务视为“半结构化阶段”。
- 不允许将无 review/clean 的任务纳入生产 agent path。
- 任何 command 必须返回可审计 `CleanedResult`。
