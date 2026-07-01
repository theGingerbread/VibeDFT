# VibeDFT v2 Contract Stability 指南（PR2.9）

## 1. 目标与适用范围

本文件用于冻结 PR2.9 后的核心合同边界，限定后续所有任务扩展与命令接入的行为边界。  
本文件直接绑定以下实现路径：

- `src/vibedft/_shared/contracts.py`
- `src/vibedft/calculator/qe/scf/clean.py`
- `src/vibedft/calculator/qe/scf/review.py`
- `src/vibedft/main/cli.py`
- `src/vibedft/main/commands.py`
- `src/vibedft/main/envelopes.py`
- `tests/qe/scf/*`
- `tests/main/*`
- `tests/_shared/*`
- `tests/qe/test_observability_from_cleaned_results.py`

PR2.9 不新增任何新科学功能，不更改任务算法，不改观测算法。  
本文件的作用是阻断 contract drift，确保 PR3 及以后任务按同一规则扩展。

## 2. 六条冻结规则（必须长期生效）

### 2.1 规则 A：`CleanedResult` 是 agent-facing 唯一 truth layer

`CleanedResult` 是 agent 对外读取的单一科学摘要结构；任何 task 的 downstream 决策与报告都必须从它衍生。  
`scf.parse` 或任何其他 `parse` 层产物不得被 agent 或上层命令作为 primary 判定来源。  

强制：

- `main` 与 `analysis` 只能消费 `CleanedResult` 或其子结构（如 `ReviewResult`）。  
- 如果某条能力需要新增输出，必须先扩展 `CleanedResult` 字段映射策略。  
- 各 task 的命令输出必须包含完整 `result` 对象，不允许只回传裸字段。  

测试与证据：

- `tests/_shared/test_contracts.py` 必须验证 `asdict(CleanedResult(...))` 的 JSON 可序列化。  
- `tests/qe/scf/test_scf_clean.py`、`tests/main/test_cli_qe_scf_review.py` 必须验证 `result` 存在且可解析。  

---

### 2.2 规则 B：`ReviewResult` 是单任务 scientific gate

`ReviewResult` 只表达单个任务在该任务范围内的 `PASS / WARN / BLOCK`。  
它不能替代 `monitor.status`，不能替代 `readiness`。  

强制：

- `clean_scf_output()`（以及未来 task clean）必须将 `review` 写入 `CleanedResult.review`。  
- `CleanedResult.status` 仍保留任务生命周期状态，不与 `review.status` 混用。  
- `Readiness.downstream` 的可入门状态由 `review.allowed_downstream/blocked_downstream` 派生。  

禁止：

- 在 `analysis` 或 `observability` 从 raw parse 重新计算 `PASS / WARN / BLOCK`。  
- 命令层直接判断是否可继续到下游（如 `if converged`）。  

测试与证据：

- `tests/qe/scf/test_scf_review.py` 应显式覆盖 converged + JOB DONE + 可追责 blocked/downstream。  
- `tests/qe/test_observability_from_cleaned_results.py` 必须以 `CleanedResult` 为输入。  

---

### 2.3 规则 C：`Readiness` 是 downstream DAG edge contract

`Readiness` 不再是自由 dict；它是 downstream 邻接门控的 typed contract。  
当前实现采用 `Readiness(downstream: Dict[str, DownstreamReadiness])`。  

强制：

- `downstream` 的 key 一定为 task 名（如 `bands`, `dos`, `phonon`）并显式表达 `allowed`。  
- 每条边必须可追踪 `reason`/`evidence_refs`，至少保留拒绝理由。  
- `clean` 流程不得直接写混合 dict（如 `{"bands": True, ...}`）。  

测试与证据：

- `tests/_shared/test_contracts.py` 覆盖 `Readiness` 与 `DownstreamReadiness` 的结构化构造。  
- `tests/main/test_cli_qe_scf_review.py` 覆盖 CLI JSON 中 `result.readiness.downstream` 可读。  

---

### 2.4 规则 D：Observability 只聚合 CleanedResult，不重算科学策略

`observability` 负责聚合多个 task 的 `CleanedResult`，不允许直接读取 `ScfOutput/PhononOutput` 做 downstream gate。  
可行策略是：若缺少 `CleanedResult` 输入则进入兼容桥接路径并显式标记，不参与主路径。  

强制：

- `build_workflow_readiness_graph` 主路径输入为任务级 `CleanedResult`。  
- `build_workflow_readiness_graph_from_parsed` 必须标记为 migration/legacy 并只用于过渡测试。  
- `epc/tc` 派生仅依赖 cleaned `readiness` 与对应任务 review 的完整状态。  

测试与证据：

- `tests/qe/test_observability_from_cleaned_results.py` 覆盖 SCF/CleanedResult -> graph。  
- 对负频、phonon 可用性与 EPC/Tc 入口，必须只在 cleaned readiness 判定后放通。  

---

### 2.5 规则 E：CLI envelope 是 transport，不是结果合同

`CommandEnvelope` 的职责是 transport 结构稳定：只承载成功/失败包裹。  
科学内容仍由 `CleanedResult` 和 `ReviewResult` 表达。  

强制：

- `cli` 与 `commands` 输出必须统一为 `{"command","ok", "result"/"error"}` 形态。  
- 任何错误类型都以 `CommandError` 回传，不篡改科学判断。  
- `stdout` 与 `--output` 文件内容在字段级一致（除格式化空白）。  

测试与证据：

- `tests/main/test_response_envelope.py` 覆盖 error/success 序列化。  
- `tests/main/test_cli_qe_scf_review.py` 覆盖 `--pretty` 与 `--output`。  

---

### 2.6 规则 F：legacy parsed-output bridge 只用于迁移与测试，不是主路径

`ScfOutput`、`PhononOutput` 等 parsed 对象仍保留于内部历史兼容；  
主路径必须使用 `CleanedResult`。  

强制：

- 任何新特性实现不得新增从 parsed output 直推的 downstream policy。  
- `_from_parsed` 桥接函数禁止从上层命令路径导入。  
- 文档必须注明 legacy 桥接使用边界与终止条件。  

测试与证据：

- 搜索与代码审查禁止从 `main`、`analysis`、`observability` 新增 parsed 入口。  
- 若必须保留历史兼容，需有独立测试覆盖兼容路径且不影响主路径。  

## 3. 冻结范围与变更流程

所有规则均为 PR2.9 冻结边界。  
后续若要修改规则，必须遵循以下步骤：

1. 在 `docs/design/human-decisions.md` 中新增一条决策项并提交确认。  
2. 在 `docs/design/v2-pr-roadmap.md` 新增/修改对应 PR 条目。  
3. 新增至少一条契约级别测试（共享测试）与一条端到端测试。  
4. 更新本文档说明生效日期与受影响规则。  

### 3.1 变更不能越权

以下变更不得直接通过代码 PR：

- 修改 `CleanedResult` 结构但不更新文档。  
- 在 `main` 重写任务科学规则。  
- 在 `observability` 重建策略树。  
- 在 `analysis` 读 raw QE output。  

## 4. 与 PR2.9 交付标准

PR2.9 完成条件：

- 在 `docs/design` 下新增并提交 `v2-contract-stability.md`。  
- `docs/design/architecture.md`、`docs/design/command-registry.md`、`docs/design/module-synchronization-risk-matrix.md`、`docs/design/v2-pr-roadmap.md` 均包含 rule lock 的显式引用。  
- 不新增 `analysis/scf`、`main`、`parser` 科学判断。  
- `SCF` 现有闭环保持可运行，`--output/--pretty/--fail-on-block` 行为不变。  

完成后，`PR3` 进入前提为：

- 任务扩展以 `review + clean + schemas` 路线执行；
- 任何新增 task 的 contract 完全继承 `CleanedResult / ReviewResult / Readiness`；
- `analysis` 与 `observability` 均只消费 `cleaned result`。  

该文档用于制止“已知正确路径被后续实现绕过”问题，是 PR2.9 的核心约束文本。
