# 模块同步风险矩阵（Module Synchronization Risk Matrix）

## 0. 目标

本矩阵用于发现文档、代码、测试、schema、CLI 之间的同步风险。每项包含：

- 风险描述
- 当前信号
- 危害
- 架构规则
- 测试方式
- schema enforcement
- 文档 enforcement
- PR checklist

---

## 1. parse/review 边界不清

### 风险描述

`parse.py` 在提取可用性信号（如 suitability）时提前承担了审阅职责。

### 当前信号

SCF 已有 `workflow_readiness`，`suitable_for_followup` 等在解析层形成。

### 危害

- downsteam 判定分散。
- 不同 task 的 PASS/WARN/BLOCK 口径冲突。

### 架构规则

- parse 仅保留事实。
- review 负责 final gate。

### 测试方式

- 任务级 fixture：同一输出在不同规则下 review 状态一致。

### Schema Enforcement

- `review_required` 在 clean 输出中必显。

### 文档 Enforcement

- 每 task doc 明确 stage 职责。

### PR Checklist

- review.go/no_review.go 禁止提交。

---

## 2. CleanedResult.readiness 类型漂移

### 风险描述

`readiness` 在历史上既作为 bool dict 又承载复杂对象。

### 当前信号

SCF clean 已输出 `workflow_readiness` 对象式内容。

### 危害

- 下游解析失败。
- READY 逻辑不可预期。

### 架构规则

- `readiness` 定义为 typed downstream map。

### 测试方式

- 同一 task 的 readiness schema 验证。

### Schema Enforcement

- JSON schema 强校验 `readiness.downstream`。

### 文档 Enforcement

- 记录在 `docs/design/cleaned-result-schema.md`。

### PR Checklist

- 新增 task 必须附 `readiness` schema/fixture。

---

## 3. monitor.status / review.status / result.status 混淆

### 风险描述

三类状态语义不统一时，管道无法区分“运行失败”和“科学失败”。

### 当前信号

已有 `monitor` 使用 `running/completed/blocked/failed`，review 使用 `PASS/WARN/BLOCK`。

### 危害

- 误触发重算。
- BLOCK 任务被当作系统错误丢弃。

### 架构规则

- 明确三层状态。

### 测试方式

- exit_code 场景测试 + payload 状态测试。

### Schema Enforcement

- schema 中枚举分离。

### 文档 Enforcement

- 在命令与 schema 文档写明差异。

### PR Checklist

- 每条 handler 文档需解释状态映射。

---

## 4. CLI JSON 与 CleanedResult 漂移

### 风险描述

`cli` 若手工拼接 dict，不同命令字段不一致。

### 当前信号

目前 SCF 命令通过 `asdict`，但未全局标准。

### 危害

- agent 无法通用消费。

### 架构规则

- 全局 envelope schema。

### 测试方式

- CLI golden snapshot + schema 校验。

### Schema Enforcement

- `main` envelope schema 文档。

### 文档 Enforcement

- 命令文档明确输出字段。

---

## 5. package README 与实际代码不一致

### 风险描述

如 `calculator/qe/phonon/README.md` 仍写 placeholder。

### 当前信号

多个 package README 标注占位，实际已具备 parse/monitor。

### 危害

- 新人误判任务可用性。
- CI 不知道何时允许使用。

### 架构规则

- 文档与实现同步。

### 测试方式

- 文档一致性 checklist。

### Schema Enforcement

- 无。

### 文档 Enforcement

- 每个 task README 需与 task contract 一致。

---

## 6. legacy fallback 长期残留

### 风险描述

`main.cli` fallback old path 可能掩盖新接口断裂。

### 当前信号

未迁移命令仍交给 `legacy_main`。

### 危害

- 输入输出格式不统一。
- 难以断言迁移进度。

### 架构规则

- fallback 仅保留兼容入口，必须记录移除计划。

### 测试方式

- 新命令必须优先走 registry。

### Schema Enforcement

- main 输出 envelope 对所有新命令。

### 文档 Enforcement

- 迁移状态文档。

---

## 7. tests 仅用 toy fixture

### 风险描述

仅小文本，不覆盖真实 QE 输出结构。

### 当前信号

部分任务测试主要为合成文本。

### 危害

- 真实生产路径出现未覆盖错误。

### 架构规则

- 至少每 task 保留 1 份真实风格 fixture。

### 测试方式

- real-data smoke。 

### Schema Enforcement

- 实际 fixture 必须通过 schema。

### 文档 Enforcement

- 测试基线文档化。

---

## 8. 下游 readiness 过度乐观

### 风险描述

SCF 将太多 downstream 标为 true。

### 当前信号

部分情形 WARN 仍允许 phonon。

### 危害

- 无效链路进入高成本任务。

### 架构规则

- 每项 downstream 都要有最小可入门条件。

### 测试方式

- policy boundary tests。

### Schema Enforcement

- `allowed_downstream` 与 `blocked_downstream` 必须一致。

---

## 9. source/evidence 无法定位

### 风险描述

Evidence 没有跨文件、section 追踪。

### 当前信号

`line_number` 为单点。

### 危害

- 证据难审计。

### 架构规则

- evidence 含 artifact/line span/section。

### 测试方式

- fixture 中验证 evidence 可定位。

---

## 10. 结构边界扩大

### 风险描述

structure 开始承担材料设计逻辑。

### 当前信号

某些提案里结构处理与 workflow 判定混淆。

### 危害

- 任务职责不清，分析重叠。

### 架构规则

- structure 只做导入导出和 provenance。

### 测试方式

- import graph 审查。

### 文档 Enforcement

- 结构角色文档。

---

## 11. phonon 单体化

### 风险描述

未拆分 phonon 任务导致下游不明确。

### 当前信号

当前 `phonon/` 仍为单体。

### 危害

- gamma 与 q-grid 规则冲突。
- debugging 与响应张量混合。

### 架构规则

- 拆分：gamma / qgrid / dos / dielectric / debug。

### 测试方式

- 子任务 fixture。

---

## 12. 运行时状态与审阅状态混用导致重试错误

### 风险描述

monitor failed 与 review block 未区分。

### 当前信号

部分文档/命令仍未统一。

### 危害

- 重跑策略错误。

### 架构规则

- 只允许 monitor 控制重试，review 控制决策。

### 测试方式

- 端到端场景测试：missing output 与 incomplete output。

---

## 13. 风险闭环（执行建议）

每个风险进入 PR 前需要：

1. 明确一条测试。
2. 一条文档更新。
3. 一条 schema 或接口约束。
4. 若仍有遗留，必须在决策文件中登记。

---

## 14. PR 审核清单

- README 与行为同步。
- status 映射一致。
- envelope 一致。
- readiness typed。
- evidence 可追踪。
