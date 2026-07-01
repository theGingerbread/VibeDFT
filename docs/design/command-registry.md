# main command registry 设计

## 0. 设计目标

把 `main/` 从“入口脚本”升级为“命令边界层（command registry）”，统一：

- 命令定义与元数据。
- 参数校验。
- 调用 handler。
- 统一 JSON envelope。

当前 `src/vibedft/main/cli.py` 已通过 `main.commands` registry 支持 `qe scf review`，不再使用硬编码分发。

统一术语：

- `command`
- `handler`
- `metadata`
- `registry`

---

## 1. 为什么不能继续沿用 legacy_main fallback

`main/cli.py` fallback 到 `vibedft.cli.main` 的问题：

1. 行为漂移：新旧命令集合不一致。
2. 状态语义混杂：旧命令以 `analysis`/脚本风格输出。
3. 契约弱化：返回格式不是统一 JSON envelope。
4. 难以做 API/MCP 一致化。

短期策略：fallback 仅作为兼容桥，必须显式标注并逐步淘汰。

---

## 2. Command registry 模型

建议 `main/commands.py`（或 registry 模块）定义：

```python
@dataclass(frozen=True)
class CommandMeta:
    command_id: str
    path: str
    task: str
    description: str
    input_args_schema: dict
    output_schema: dict
    status_behavior: dict
    supports_pretty: bool = True
    supports_output_file: bool = True
    supports_fail_on_block: bool = True
    handler: Callable[..., CommandResult]
```

### 2.1 责任

- 全局命令发现。
- handler 到命令路径绑定。
- schema/权限/错误码元信息。

### 2.2 发现机制

- 静态字典注册（初期）。
- 之后按约定自动扫描 `calculator` 子命令目录可选。
- 不在用户运行前动态 import 旧模块。

---

## 3. handler 统一接口

建议统一签名：

```python
def handler(args: argparse.Namespace, context: CommandContext) -> CommandResult:
    ...
```

`CommandResult` 包含：

- `ok: bool`
- `result: dict | None`
- `error: ErrorPayload | None`
- `status_hint: str`

`context` 包含：

- `cwd`
- `user`
- `calculator`
- `dry_run`
- `trace_id`

---

## 4. 命令元数据样例

```text
command_id: qe.scf.review
path: qe scf review
task: qe.scf
description: Parse and review a QE SCF output file
input_args_schema:
  - output_file: str
  - pretty: bool
  - output: str?
  - fail_on_block: bool
output_schema:
  - command
  - ok
  - result/ error
status_behavior:
  - normal: exit 0
  - missing_file: exit 1
  - fail_on_block_block: exit 2
supports_pretty: true
supports_output_file: true
supports_fail_on_block: true
```

---

## 5. handler 与 library 函数绑定

- `main` 不直接实现 parse/review 清洗。
- `main` 只调用 `vibedft.calculator.qe.scf.clean.clean_scf_text(...)`（当前已实现）。
- handler 产物经过统一 envelope 序列化。

---

## 6. CLI 与未来 MCP / HTTP 的共享

- registry 生成命令描述 json（name、args、schema）。
- MCP wrapper 直接复用 registry，不再单独维护 command 列表。
- HTTP 层（后续）也复用同一 handler 与 schema。

---

## 7. 统一错误与输出行为

1. 默认 `ok: true` 且 `result` 为 `CleanedResult`。
2. 错误时 `ok: false` 且 `error` 显式类型。
3. `--pretty` 和 `--output` 仅影响展示，不影响语义。
4. `--fail-on-block` 为策略级退出码扩展。

---

## 8. 迁移要求（本阶段）

- 所有可暴露给 agent 的命令必须写入 registry。
- 不允许命令散落在 if/else 字符串匹配。
- 测试应覆盖命令发现和 handler 合同。

## 9. PR2.9 合同稳定性边界（与本阶段一致）

PR2.9 要求 command registry 与可运行任务完全分离：  

- registry 只能做 **命令寻址 + 参数接收 + 输出封装**。  
- scientific policy 只来自 task 的 `ReviewResult` 与 `CleanedResult.readiness`。  
- observability/decision logic 不能在 registry 层重新实现。  
- handler 必须只调用 task 层公开 API（例如 `clean_scf_text`）并返回标准 `CommandExecution`。  

反模式明确禁止：

- `qe.scf.review` handler 在 registry 内部硬写 SCF 下游规则。  
- `result` 字段不包含 `CleanedResult`。  
- 同一命令在 registry 与 legacy 路径维护两套策略。  
- 以 command id 命名替代任务版本化边界（必须保持 `qe.scf.review` 等明确定义）。  

与 v2 contract 的绑定：

- `result` 为 `CleanedResult` 时，`ok` 代表 transport 成功；科学成功由 `result.review.status` + `result.status` 表达。  
- 任何新命令注册时必须先检查其 `review/clean` 是否有 typed downstream。  
- PR2.9 之后 registry 改动只允许影响命令元数据与 transport，不允许变更科学判断语义。

---

## 10. 可执行示例（建议命令矩阵）

- `qe scf review`
- `qe relax review`（未来）
- `qe vc_relax review`（未来）
- `qe dos review`（未来）
- `qe bands review`（未来）
- `project init`（可选）
- `result clean`（后续分析入口）

---

## 11. 反模式清单

- handler 直接 `print(json.dumps(...))`。
- 每个命令各自自定义错误结构。
- 命令依赖 `vibedft.cli.main` 的旧结构。
- registry 中出现同名不同路径的 command。
