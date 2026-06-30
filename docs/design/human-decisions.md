# 人工决策清单（VibeDFT v2）

本文件用于标记目前无法通过文档/代码自动固化的决策点，避免后续实现偏离统一契约。每条决策都包含“问题—重要性—选项—推荐—风险”五段。

---

## 决策 1：任务命名是 `scf` 还是 `qe.scf`

### 问题

任务 ID 对外统一使用 `scf` 还是 `qe.scf`。CLI、registry 与 CleanedResult 的 `task` 字段目前可能出现混用。

### 为什么重要

任务名直接影响命令兼容性、下游读取脚本和 readiness 映射。一致性问题会让迁移和审计成本翻倍。

### 选项 A

统一用 `task="scf"`，CLI command 用 `qe scf`。

### 选项 B

统一用 `task="qe.scf"`，并在 registry 中强制全路径命名。

### 推荐

短期沿用 `task="scf"` 以兼容当前 SCF 实现；`command` 使用 `qe.scf`。在 registry 中补 `TASK_ID_MAP` 兼容两者输入。

### 不决策风险

若不及时统一，未来新增 NSCF、phonon 多任务时会出现 `bands` 依赖映射错位，产生错误放行。

---

## 决策 2：CleanedResult 是否保留 `running/failed/no_data`

### 问题

当前 status 常见值为 pass/warn/block。是否在 CleanedResult 里保留 monitor 风格的 running/failed/no_data。

### 为什么重要

运行时中间态是否直接给用户看到，决定系统可观测性和重试策略。

### 选项 A

保留三者，作为合法 `status`（例如 `failed` 表示程序失败，`no_data` 表示解析缺失）。

### 选项 B

仅在 monitor 层保留，CleanedResult 限于科学 result（三态）。

### 推荐

保留 `failed/no_data` 的信息，但在 CleanedResult 内分离为 `monitor_status` 和 `result_status`，避免语义混淆。

### 不决策风险

混用单字段 status 会让 agent 误把运行失败当作科学判断，并触发错误的自动分支。

---

## 决策 3：readiness 是强类型对象还是 dict

### 问题

`readiness` 当前常为 dict[str, bool]。是否升级为强类型结构体（例如 `downstream`, `blockers`, `warnings`）。

### 为什么重要

这是防误导下游决策的关键。宽松 dict 虽灵活，但易拼写漂移。

### 选项 A

沿用 dict 并通过测试约束关键 key。

### 选项 B

升级为 dataclass / pydantic 模型，key 为受控枚举。

### 推荐

分两层：对外 `dict[str, bool]` 保持兼容；内部新增 `Readiness` dataclass 并输出时标准化映射，兼顾稳定与进阶验证。

### 不决策风险

dict 漂移导致下游 `allowed_downstream` 与实际评估不一致。

---

## 决策 4：review 是否作为 CleanedResult 一等字段

### 问题

review 信息放在 `CleanedResult.result` 同级还是独立字段。

### 为什么重要

这是最核心的可解释性与 agent 稳定性约束：没有 review 即没有可审计原因链。

### 选项 A

把 `ReviewResult` 单独挂在 `CleanedResult.review`。

### 选项 B

只通过 `status` + `warnings` 表达，不保留详细 review 对象。

### 推荐

必须采用选项 A。`status` 只能表达三态结果，`review` 承载 allowed/blocked/evidence/reason。

### 不决策风险

失去 `allowed_downstream` / `recommendations` 机器可用信息，analysis 与调度层只能依赖人工规则。

---

## 决策 5：Pydantic 是否在 v2 早期引入

### 问题

当前 dataclass 是否足够，还是立即替换为 Pydantic 主模型。

### 为什么重要

直接影响开发速度、模型验证、schema 生成和兼容成本。

### 选项 A

当前阶段不引入，先做 docs 与 dataclass 强约束。

### 选项 B

早期引入 Pydantic 作为主模型。

### 推荐

选项 A。稳定性优先；后续在 CLI 层或 schema 输出层渐进式引入。

### 不决策风险

早引入可能带来迁移不稳定和生态依赖膨胀；晚引入可能降低早期验证强度。故采用“阶段性增强”。

---

## 决策 6：JSON Schema 是否作为 CI 门禁

### 问题

是否要求每次 PR 都在 CI 触发 schema 校验。

### 为什么重要

schema 漂移是最容易在多 agent 开发中被忽略的问题。

### 选项 A

立即加入 CI 门禁（schema generate + lint）。

### 选项 B

先不强制，作为 PR 人工检查。

### 推荐

三阶段推进：PR2.7 文档化，PR2.8 设计注册，PR2.9 引入 CI 门禁。

### 不决策风险

缺少门禁会产生“文档正确但契约未执行”的假性完成。

---

## 决策 7：phonon 拆分命名

### 问题

是否使用 `phonon_gamma/phonon_qgrid/phonon_dos/dielectric/phonon_debug`，或 `phonon/gamma/dispersion/dos/dielectric_born/debug`。

### 为什么重要

命名关系到后续代码组织和命令学习成本。

### 选项 A

第一种扁平目录。

### 选项 B

嵌套目录保持历史 `phonon/xxx` 风格。

### 推荐

阶段 1 用扁平目录（便于 grep + 权限控制），后续若命令层已稳定再过渡为嵌套统一目录也可，需兼容 map 表。

### 不决策风险

命名频繁变化会让 subagent 写文档和 registry 对不上，增加迁移测试成本。

---

## 决策 8：legacy CLI fallback 保留多久

### 问题

`vibedft.cli:main` 到 `vibedft.main.cli:main` 的迁移后，临时兼容多久。

### 为什么重要
 
兼容窗口影响用户可用与技术债务收敛速度。

### 选项 A

保留 2-3 个小版本后移除。

### 选项 B

仅保留到重大稳定版本发布。

### 推荐

保留到 PR2.8 完成且有告警文档后再评估，至少覆盖一次主路径新旧脚本对照验证。

### 不决策风险

提前移除导致脚本打断；过晚移除则延迟 registry 主导地位。

---

## 决策 9：AiiDA 是否永远只作为参考

### 问题

AiiDA 是否进入核心依赖或仅作为参考材料。

### 为什么重要

核心依赖决定了仓库复杂度和运维链路。

### 选项 A

仅保留文档/学习参考，不作为运行依赖。

### 选项 B

将 AiiDA 作为部分 task 的 adapter。

### 推荐

明确选项 A。所有任务合同都来自 VibeDFT own contracts，AiiDA 仅在研究层面参考。

### 不决策风险

把 AiiDA 引入会把本来轻量任务合同转换为重平台依赖，违背 v2 目标。

---

## 决策 10：structure 的最大边界

### 问题

`structure/` 是只处理输入/摘要，还是允许做高级结构学习（缺陷/异质结生成）？

### 为什么重要

避免结构领域越界吞噬任务 contract。

### 选项 A

窄边界：IO、标准化、摘要、约束映射、来源追踪。

### 选项 B

扩边界：缺陷引擎、异质结搭建、超胞/掺杂策略生成。

### 推荐

选项 A。structure 层只作为“可计算前处理边界”。

### 不决策风险

扩边界会与 QE-Learning 的 Structure-Learning 冲突，导致职责重叠。

---

## 决策 11：是否保留 `policy.py` 阶段

### 问题

是否所有 task 都需要 `policy.py`。

### 为什么重要

stage 数量影响开发一致性与复杂度。

### 选项 A

统一要求所有 task 有，可为空文件或占位符。

### 选项 B

只在复杂 task 使用，其他可省略。

### 推荐

不强制为所有 task 必须存在，但在复杂 task（phonon/relax）必须存在，并在文档中列明不使用场景。

### 不决策风险

强制化会增加模板噪音，省略会在复杂任务中导致策略分散到 clean/review。

---

## 决策 12：是否要求 `evidence` 包含行号/range

### 问题

ScfOutput 等对象通常缺行号；是否必须在 evidence 中保留行号信息。

### 为什么重要

追溯能力决定审计可信度。

### 选项 A

允许 line 为可空，不要求强制存在。

### 选项 B

要求每条 evidence 必须有 `line_start`+`line_end`。

### 推荐

A 作为过渡，结合 `source` + `section` + `artifact` 做定位；对高风险类型（BLOCK）逐步要求 line。

### 不决策风险

强制行号会让 parser 重构过慢；无约束又会降低复现性。采用分级策略。

---

## 决策 13：下游 readiness 的表达粒度

### 问题

`readiness` 是 bool map 还是带原因/证据的对象。

### 为什么重要

用于自动编排和阻断。

### 选项 A

保持当前 `dict[str, bool]`。

### 选项 B

改为对象 `downstream[{id, ready, reasons}]`。

### 推荐

内部改对象、外部兼容 map。先保证 `allowed_downstream` / `blocked_downstream` + `downstream_reasons` 分离。

### 不决策风险

仅 bool 会导致“能否继续”判断缺乏依据，后续自动化失真。

---

## 决策 14：如何处理 `severe issue` 与 `failed` 的界线

### 问题

是否将 `severe issue` 直接映射为 BLOCK 或 failed。

### 为什么重要

决定退出码、重试策略和自动分支。

### 选项 A

`severe issue` => scientific BLOCK，仍返回可读 JSON；

### 选项 B

`severe issue` => runtime failed，返回错误级别。

### 推荐

区分两级：科学失败（BLOCK）与运行失败（FAILED）。前者返回 JSON result，后者返回 error envelope。

### 不决策风险

无分界会导致自动执行器错过可恢复场景，或错误重试非科学问题。

---

## 说明

以上决策将在 PR 开始前由主 agent 汇总一次确认；未决项不应进入实现。每项决策至少给一次书面确认后才能进入 PR 代码层执行。

