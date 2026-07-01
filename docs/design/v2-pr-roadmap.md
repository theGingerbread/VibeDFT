# VibeDFT v2 后续 PR 路线图

## 0. 当前状态（已完成）

VibeDFT v2 当前基线已具备 SCF 主链路：

- PR1：`package identity + shared contracts + CLI entrypoint`
- PR2：`qe/scf schemas/review/clean`
- PR2.5：`vibedft qe scf review` CLI JSON 闭环
- PR2.5.1：`--output` 文件导出
- PR2.7：shared contract hardening 已完成
- PR2.8：command registry + envelope 已完成
- PR2.8.1：observability contract align 已完成
- PR2.9：contract stability documentation 已完成

这意味着本轮可执行的是“从闭环能力到任务扩展”的工程，不是“新功能补丁”。

---

## 1. PR2.6：v2 task contract documentation（文档冻结）

### 目标

把本轮之前的子 agent 设计文档正式定稿并作为代码契约依据。

### 范围

- 完成 `docs/design` 的 10+ 文档补齐；
- 制定统一术语和状态语义；
- 确定禁止项和人工决策点；
- 固化 `review.py` 与 `schemas.py` 为必需 stage。

### 文件

- `docs/design/*.md` 全量；
- `README.md`（仅文档同步，不变更架构定位）。

### 测试

- 文档自审（无模糊表达、无冲突）；
- 与当前代码路径一致性核对。

### 完成标准

- 每个文档明确引用同一术语；
- 所有任务 contract 章节能落地到现有 SCF 实现结构；
- v2 代码修改不应偏离文档。

### 禁止包含

- 提前添加 NSCF/Bands/DOS 的实现细节；
- 改变已完成 SCF 产物；
- 引入 MCP/HTTP 设计细则到功能实现层。

---

## 2. PR2.7：shared contract hardening（共享合同增强）

### 目标

强化 `_shared/contracts`，统一 `CleanedResult`/`ReviewResult`/`Evidence`/`Diagnostics`。

### 范围

- readiness 与 review 字段对齐；
- status 语义区分（monitor/review/result）；
- evidence 增加 `source`/`artifact`/`line` 映射；
- schema version 与向下兼容策略。

### 文件

- `src/vibedft/_shared/contracts.py`
- `src/vibedft/_shared/schema/` 或 docs schema 输出路径；
- `tests/contracts`。

### 测试

- 反序列化/序列化兼容；
- status 与 schema 校验。

### 完成标准

- 同一 `CleanedResult` 可被 CLI 与未来 MCP 一致消费；
- 文档与 schema 版本号一致。

### 风险

- schema 变化引发旧 fixture 破坏；
- `readiness` 从 dict 演化为结构体时迁移成本。

---

## 3. PR2.8：command registry and response envelope（命令注册与响应一致化）

### 目标

把 CLI 分发从临时 fallback 转为 registry 驱动，同时固定 JSON envelope。

### 范围

- `src/vibedft/main/` 增加 registry；
- handler metadata + 参数 schema；
- CLI 输出错误 envelope 与 success envelope 统一。

### 文件

- `src/vibedft/main/command_registry.py`
- `src/vibedft/main/agent_router.py`
- `src/vibedft/main/cli.py`
- `src/vibedft/main/run_context.py`（如必要）

### 测试

- `tests/main/test_cli_registry.py`
- `tests/main/test_cli_qe_scf_review.py` 兼容。

### 完成标准

- 新命令新增以 registry 注册，不写散落的 `if/elif`；
- handler 与命令映射可被未来 MCP 复用。

### 禁止包含

- 在 CLI 里写科学判断逻辑；
- 不经过 handler 的直接调用路径。

---

## 3.5 PR2.9：contract stability documentation（contract 稳定性文档）

### 目标

将 PR2.7/PR2.8/PR2.8.1 的结果收敛为一份可执行合同文档，并在架构主文档中固定约束。

### 范围

- 新增 `docs/design/v2-contract-stability.md`，定义六条冻结规则。  
- 更新 `docs/design/architecture.md`，加入 contract stability 条目与执行边界。  
- 更新 `docs/design/command-registry.md`，约束 transport 与 policy 的边界。  
- 更新 `docs/design/module-synchronization-risk-matrix.md`，加入 PR2.9 contract drift 风险。  
- 更新 `docs/design/v2-pr-roadmap.md`，将 PR2.9 作为 PR3 的前置门槛。

### 文件

- `docs/design/v2-contract-stability.md`（新增）
- `docs/design/architecture.md`
- `docs/design/command-registry.md`
- `docs/design/module-synchronization-risk-matrix.md`
- `docs/design/v2-pr-roadmap.md`

### 测试

- `tests/main/test_cli_qe_scf_review.py`（CLI 行为保持不变）
- `tests/main/test_command_registry.py`（命令发现不变）
- `tests/main/test_response_envelope.py`（envelope 形态不变）
- `tests/_shared/test_contracts.py`（typed 合同不变）
- `tests/qe/test_observability_from_cleaned_results.py`（observability 输入契约不变）

### 完成标准

- 六条冻结规则在文档体系内可检索、可引用。  
- 合同不引入 parsed-output policy 重算。  
- 下一步 PR3 不再以实验性 contract 讨论为前提即可启动。

### 禁止包含

- 重写 `SCF`、`relax`、`phonon` 科学逻辑。  
- 引入 MCP/HTTP/LSP 层实现。  
- 改变现有命令输出语义。  

---

## 4. PR3：relax clean/review（含 vc_relax）

### 目标

完成 relax 与 vc_relax 的 review/clean 闭环，形成从结构优化到 SCF/电子工作流入口的首个 Gate。

### 范围

- `calculator/qe/relax/{review,clean,schemas}`
- `calculator/qe/vc_relax/{review,clean,schemas}`
- 复用 SCF 的 readiness 与稳定性模型。

### 文件

- `src/vibedft/calculator/qe/relax/...`
- `src/vibedft/calculator/qe/vc_relax/...`
- `tests/qe/relax/`

### 测试

- `converged/no convergence/force high/truncated`
- `readiness` 到 `bands`、`dos`、`phonon` 的差异控制；
- `CleanedResult` JSON serialize。

### 完成标准

- relax/vc_relax 在 `analysis` 前形成 `PASS/WARN/BLOCK`；
- 不新增过度结构学习逻辑。

---

## 5. PR3.5：relax/vc_relax CLI review 接口

### 目标

将 PR3 的 cleaned result 纳入 CLI；

### 范围

- `vibedft qe relax review`
- `vibedft qe vc-relax review`
- 支持 `--pretty`, `--output`, `--fail-on-block`。

### 文件

- `src/vibedft/main/cli.py`
- `tests/main/test_cli_qe_relax_review.py`

### 测试

- pass/warn/block 三态；
- output 文件与 stdout 等价校验。

### 完成标准

- 与 SCF 一致的返回 envelope；
- 不影响 legacy compatibility。

---

## 6. PR4：NSCF task contract 实现（命令与清洗）

### 目标

在 SCF/relax 基础上完成 NSCF 任务合同与输出；为 Bands/DOS/PDOS 提供稳定前置。

### 范围

- `calculator/qe/nscf/{schemas,review,clean}`
- `main` 注册 `qe.nscf.review`

### 文件

- `src/vibedft/calculator/qe/nscf/...`
- `tests/qe/nscf`
- `tests/main/test_cli_qe_nscf_review.py`

### 风险

- nscf 参数与 NSCF-specific band mapping 语义易漂移；
- 不同 k-point 对后续 bands/dos 输出兼容性影响大。

---

## 7. PR5：DOS/PDOS 任务实现

### 目标

补齐 DOS 与 PDOS 的 parser/review/clean 并输出可分析 observables。

### 范围

- `calculator/qe/dos/...`
- `calculator/qe/pdos/...`

### 文件

- `tests/qe/dos`, `tests/qe/pdos`；
- CLI review 命令（可在 PR2.8 下集中引入）。

### 完成标准

- DOS 与 PDOS 的 `status` 不再依赖 raw parsing；
- 观测量包含能隙、费米能、DOS 近费米态密度等。

---

## 8. PR6：bands 实现

### 目标

实现 bands 的合同闭环，支持高层 analysis 的 band structure 解读。

### 范围

- `calculator/qe/bands/{schemas,review,clean}`
- `tests/qe/bands`

### 完成标准

- band gap / direct/indirect 判断以 evidence + citations；
- `readiness` 与 NSCF 耦合一致。

---

## 9. PR7：pp.x postprocessing scaffold

### 目标

按子任务拆分实现 pp 处理：charge density / electrostatic potential / ELF / work function 的最小闭环。

### 范围

- `calculator/qe/pp/{charge_density,electrostatic_potential,elf,work_function}/...`
- 通用 `pp` 输入/输出规范。

### 完成标准

- 每个子任务都能输出 `upstream_dependency`, `produced_files`, `units`, `next_action`。

---

## 10. PR8：analysis only consumes CleanedResult

### 目标

清理 analysis 层入口，禁止其直接读取 raw QE output。

### 范围

- `analysis/` 中所有入口；
- 只接受 `CleanedResult` + provenance；
- 增加 lint/测试防御 raw 读取。

### 文件

- `src/vibedft/analysis/*`
- 对应测试目录（mock + schema fixture）

### 完成标准

- analysis 代码路径中不存在 parse 的 direct import；
- 形成错误输出：缺少 cleaned result 时显式失败并建议重新运行命令。

---

## 11. PR9：phonon split scaffold（设计落地）

### 目标

创建拆分目录和任务 stage 框架（不要求一次实现全解析）。

### 文件

- `src/vibedft/calculator/qe/phonon_gamma/...`
- `src/vibedft/calculator/qe/phonon_qgrid/...`
- `src/vibedft/calculator/qe/phonon_dos/...`
- `src/vibedft/calculator/qe/dielectric/...`
- `src/vibedft/calculator/qe/phonon_debug/...`

### 完成标准

- 文档到目录映射完成；
- 各 task 的 `schemas.py` 与 `review.py` 已有最小骨架。

---

## 12. PR10：phonon family implementation

### 目标

按 PR9 骨架完成最小可运行链路（至少 gamma 与 dos）。

### 范围

- 解析器与 clean/review；
- 命令接入；
- 关键 negative mode/ASR 风险证据。

### 完成标准

- phonon 命令返回 `cleaned result`；
- 与 SCF/relax readiness 兼容。

---

## 13. PR11：JSON schema export and registry validation

### 目标

输出可验证 schema 与 registry 驱动验证（CI 门禁）。

### 文件

- `src/vibedft/_shared/schema/json_schema.py`
- `tests/schema/*`
- `tests/main/test_registry_schema.py`

### 完成标准

- 命令输出与 schema 通过 round-trip；
- schema 变更必须在 PR 中附版本说明。

---

## 14. PR12：MCP wrapper（后置）

### 目标

建立 MCP 服务器原型，复用 command registry。

### 文件

- `src/vibedft/mcp/`（新增）
- `tests/mcp`

### 完成标准

- MCP 调用链与 CLI 一致；
- 仅作外壳，不复写解析与判断逻辑。

---

## 15. 排序与依赖说明

按风险最小原则推荐顺序：

1. PR2.6 -> PR2.7 -> PR2.8 -> PR2.9（合同与治理优先）
2. PR3 -> PR3.5（几何任务闭环）
3. PR4 -> PR6 -> PR5（电子结构链路）
4. PR7（后处理）
5. PR8（analysis 收口）
6. PR9 -> PR10（phonon 拆分与实现）
7. PR11（门禁化）
8. PR12（外部协议）

若资源受限，可以将 PR3.5 合并到 PR4 前导时再补，不影响总体目标。

---

## 16. 本轮非目标

- 不引入 HTTP server；
- 不补充更多 MCP 功能；
- 不重构 legacy；
- 不开始 `structure` 方向的高层学习功能；
- 不把 analysis 变成 QE 细节解释器。

---

## 17. 交付定义（本路线图）

每个 PR 必须带：

1. 目标
2. 范围清单
3. 变更文件
4. 测试列表
5. 完成标准
6. 禁止包含项
7. 风险
8. 下一步依赖

本路线图可直接作为下轮 PR 评审模板。若偏离顺序，需在 PR 说明中说明原因与风险。
