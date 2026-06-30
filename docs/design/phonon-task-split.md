# Phonon task split 设计

## 1. 设计前提与核心原则

VibeDFT 的 `phonon` 不应作为单一任务存在，核心原因不是工程风格偏好，而是科学链路和交付风险控制需要。

当前代码层已经具备 SCF / relax / nscf 等较清晰的阶段化模式，而 `phonon` 若继续当作单体，就会把彼此不同的输入卡、输出语义、收敛判断和下游可用性混在一起，导致以下问题不可避免：

1. review 规则不能统一：`dynmat` 阶段只关注振动态矩阵收敛，`matdyn` 阶段关注声子色散光滑性，`epsilon` 阶段关注 Born 有效电荷与偶极耦合证据。
2. 清洗 schema 漂移：不同阶段可记录的 observables（实空间矩阵、q 点群特征、负频率分类、介电张量）不同，若混到一个 `CleanedResult` 字段会丢失判定精度。
3. 失败归因不清：`ph.x` 失败可能是输入 q 点不当、FFT 大小不一致、或对称性不匹配；`matdyn.x` 失败常是 q-grid 后处理参数缺失；单体任务往往只有一个 `blocked` 原因，无法追踪到具体阶段。
4. 任务依赖不可分：`Gamma` 与 `q-grid` 的输入差异较大，不能共享同一 prepare/review/clean 接口而不引入大量条件分支。

因此本设计将 phonon 明确拆分成五类子任务，保持与 QE-Learning 的任务语义对齐。

---

## 2. 拆分范围与命名

推荐目录（与当前仓库风格和现有命名一致）：

```text
src/vibedft/calculator/qe/
  phonon_gamma/
  phonon_qgrid/
  phonon_dos/
  dielectric/
  phonon_debug/
```

### 推荐理由

- 保留 `phonon` 前缀，便于全局检索和命令层分类；
- 命名中显式写出主流程目标（`gamma / qgrid / dos / dielectric / debug`）；
- `dielectric` 与 `phonon` 解耦，可作为单独 `qe` 任务组，未来支持 `dielectric.x` 与 `post-processing`。

如果希望路径更贴近 QE-Learning 的文件名，也可选：

```text
calculator/qe/phonon/
  gamma/
  dispersion/
  dos/
  dielectric_born/
  debug/
```

二者本质等价。主决策是：**每个子任务必须有独立 stage、独立 schema 和独立 review policy**。

---

## 3. 各子任务边界

### 3.1 `phonon_gamma`

#### 目标

完成 Γ 点（`q=0`）的 DFPT 基础求解，得到力常数矩阵、原始动力学矩阵与声子频率、振幅、dielectric/Born 限制上下文（如果当前运行包含电场耦合参数）。

#### 输入

- 上游 SCF（`clean_scf_output`）可用产物：电荷密度、`convergence` 与结构参数；
- `ph.x` 的 `-nr1/-nr2/-nr3`、`ldisp = .false.`、`epsil` / `epsil = .true.` 等标记；
- 可选：nscf 波函数来源用于精细网格验证。

#### 输出

- `*.dynG` / `*.dyn0`；
- `f_ifc` / 振动模频率在 Γ 点列表；
- 若 `epsil=.true.`，`*.dmat`/`*.bvec` 与介电张量候选。

#### review policy

- `job_done` & `no severe issue` 基线必须成立；
- Γ 点频率必须可读；若存在虚频，依据振幅/模式符号标注；
- 输出文件可定位（存在 dyn 文件）且对应体系结构与 SCF 一致。

#### CleanedResult observables

- `gamma_frequencies_ev`（数组）
- `gamma_negative_modes_count`
- `asr_applied`（若能识别）
- `epsilon_from_gamma`（可选）
- `born_available`（可选布尔）

#### 负频率处理

`negative_frequency` 不直接阻塞任务执行本身，但应触发 review `WARN/BLOCK` 规则：
- `||freq|` 小于某阈值但为负：WARN（常见数值噪声）；
- 严重负频率（高幅值）或多模连续负：BLOCK（结构不稳定、超静态不可靠）；
- 需要记录证据：mode index、频率值、对应不可见坐标文件行号。

---

### 3.2 `phonon_qgrid`

#### 目标

对 q 网格进行 DFPT 扫描，获取全 Brillouin 区声子色散所需的网格动力学矩阵，并形成后续色散/声学修正所需输入。

#### 输入

- 上游 `phonon_gamma` clean 结果和/或 SCF clean 结果；
- `ph.x` 输入卡：`ldisp = .true.`、`nq1/nq2/nq3`；
- 晶格与原子类型一致性。

#### 输出

- 一组 `*.dyn` 文件（q 网格）
- `ifc` 或频率快照集合（q 点级别）
- q 网格元数据（`q-point count`, `qmesh`）。

#### review policy

- 所有网格点输出完整；
- 若 `sum q-points` 与预期不一致，降级 BLOCK；
- 存在明显 `convergence` 错误或重启残缺文件：BLOCK；
- 若存在极少数单点失败但全局覆盖完整：WARN + 记录 blocked downstream list（例如 `phonon_dos` 阶段优先降级）。

#### observables

- `q_grid_shape`
- `q_grid_point_count`
- `phonon_qpoint_failures`
- `ifc_raw_path`

---

### 3.3 `phonon_dos`

#### 目标

基于 q 网格和 IFCT / dyn 文件，使用 `q2r.x` + `matdyn.x` 路线输出 phonon DOS。

#### 输入

- `phonon_qgrid` 的 dyn 文件；
- `q2r.x` 输入；
- `matdyn.x` 输入（可指定 dos 参数）。

#### 输出

- 力常数实空间文件（若 q2r 成功）
- DOS 曲线文本（频率-强度）
- 阶段统计（总态数归一化等指标）

#### review policy

- q2r 成功，matdyn 成功，dos 文件可读；
- DOS 是否包含负频率区，若出现负频峰需结合 `phonon_qgrid` evidence；
- 与单位约定一致（`cm-1` or `THz` 明确记录）。

#### observables

- `phonon_dos_file`
- `dos_frequency_range`
- `dos_total_norm`
- `dos_area`（可作一致性诊断）

---

### 3.4 `dielectric`（dielectric/Born）

#### 目标

执行带电场微扰求解，产出介电常数、Born 有效电荷、极化方向相关系数，支持后续红外/拉曼/LO-TO 分析与极性材料修正。

#### 输入

- SCF 基态与 `phonon_gamma` 结果；
- `ph.x` 卡中 `epsil=.true.` / `lraman` / `lrpa` 等；
- 2D 材料边界可增加 `assume_isolated='2D'` 等额外边界标记。

#### 输出

- `epsilon` 张量；
- Born 电荷张量；
- `ifc` / 频率修正参数；
- 可选：LO-TO 分裂相关参数。

#### review policy

- 若 `epsil=True` 但缺失关键张量，标记 WARN；
- 若体系金属且错误开启了 `epsil`，应 BLOCK；
- 对 2D/金属体系给出更严格 WARN 规则（真空厚度与偶极矫正证据）。

#### observables

- `epsilon_tensor`
- `born_charges`
- `polar_material_detected`
- `asr_applied_for_dielectric`
- `lo_to_gap_signature`

---

### 3.5 `phonon_debug`

#### 目标

不作为常规流程任务，而是故障定位专用任务：检查 symmetry、q 点缺失、FFT 参数、收敛噪声来源和文件一致性。此任务不应与主科学判断耦合。

#### 输入

- 任意 phonon 子任务失败产物；
- 日志与 `prefix/*.xml` 等可读元文件；
- SCF 与原始输入指纹。

#### 输出

- 诊断报告（文本、JSON）
- 阶段级失败分类
- 推荐修复动作（例如增大 `tr2_ph`、重设 `q2r` 参数、修复超胞）

#### review policy

- 该任务仅输出诊断不建议写科学 PASS；
- 可输出 `warn` 作为可执行修复建议；
- 严重文件缺失为 BLOCK，并给出最小修复清单。

#### observables

- `diagnostic_notes`
- `replay_hints`
- `failed_stage`

---

## 4. 依赖与下游映射（command-level）

建议命令层映射：

```text
vibedft qe phonon gamma review
vibedft qe phonon qgrid review
vibedft qe phonon dos review
vibedft qe phonon dielectric review
vibedft qe phonon debug review
```

推荐 readiness 输出示例：

- `phonon_gamma` 允许 `phonon_dos`, `phonon_debug`
- `phonon_qgrid` 允许 `phonon_dos`, `phonon_debug`
- `phonon_dos` 允许 `phonon_debug`
- `dielectric` 允许 `phonon_debug`

关键点：所有 `readiness` 必须来自 explicit 下游能力标签，而不是任务完成字符串推断。

---

## 5. 与现有 code contract 的对齐

每个 phonon 子任务都必须有完整 stage 组成（即使某阶段仅占位）：

1. `params.py`：参数模型；
2. `prepare.py`：生成可复现输入；
3. `run.py`：任务启动与命令包装；
4. `monitor.py`：运行状态（running/blocked/no_data/completed）；
5. `parse.py`：QE 事实提取；
6. `review.py`：PASS/WARN/BLOCK；
7. `clean.py`：输出 `CleanedResult`；
8. `schemas.py`：任务常量/枚举；
9. `policy.py`（可选）：复杂边界策略（2D/metal/polar）。

`readiness` 与 `downstream` 字段必须写死为受控枚举集合，不允许自由拼接。

---

## 6. 特殊体系边界

### 2D 体系

- `assume_isolated`、真空厚度、偶极修正必须作为 evidential field 进入 diagnostics；
- 若缺少 2D correction 证据，默认 WARN；
- 不要在 `status=pass` 下放行需要精密 IR/LO-TO 的 workflow。

### 金属体系

- 对 `epsilon` 与 LO-TO 相关参数要求更严格；
- 若金属体系未明确禁用 polar 修正：BLOCK。

### 极性材料

- `born`/介电张量必须可追溯到 dyn/eigenvector 证据；
- 若缺失导致频率重整失败，BLOCK 下游 `analysis/phonon`.

---

## 7. 负频率与 ASR 的规范表达

在 `Diagnostics` 中至少应记录：

- `asr_status`：是否显式启用 ASR；
- `n_asr_modes`：数量及是否包含平移零模；
- `negative_mode_indices`：索引与频率；
- `negative_mode_confidence`：基于振幅/归一化幅值的估计；
- `negative_mode_action`：建议动作（优化/细化 q-grid / 重新 SCF）。

`negative_frequency` 不应简单阻断所有输出。它是用于科学风险分级的核心信号：可为 WARN，也可 BLOCK，必须保留证据。

---

## 8. 迁移计划（文档约束）

1. **阶段 1**：创建目录 + schema/stage 骨架；
2. **阶段 2**：先实现 `phonon_gamma` parse/review/clean 的最小闭环；
3. **阶段 3**：补充 `phonon_qgrid` 与 `phonon_dos`；
4. **阶段 4**：添加 `dielectric` 与 `phonon_debug`；
5. **阶段 5**：接入 command registry，逐步替代单体 `qe phonon` 命令；
6. **阶段 6**：保留旧命令兼容层，标记为废弃并给出迁移文档。

任何阶段不得出现“一个 review.py 同时判定 gamma 与 dos”的实现。

---

## 9. 决策与验收

### 决策

- phonon 必须拆分为独立子任务；
- 每个子任务必须具备 review + clean，输出统一 `CleanedResult`；
- `phonon_debug` 属于诊断增强，不与主任务混淆；
- 负频率和 ASR 由可追溯证据驱动，不能一票否决。

### 验收

- 分拆后 command registry 可独立路由；
- `readiness` 与下游依赖在各任务中一致；
- 至少一套 phonon 集成 fixture 验证每个子任务 evidence field；
- 旧 `phonon` 单体代码只保留 adapter，不作为新功能入口。

