# Agent-facing CLI JSON 规范

## 0. 目标

VibeDFT 的 CLI 需要统一输出可被 agent 直接消费的 JSON envelope。任何命令都应在成功与失败时遵循同一外层形状。

建议 envelope：

```json
{ "command": "qe.scf.review", "ok": true, "result": {...} }
```

失败形式：

```json
{ "command": "qe.scf.review", "ok": false, "error": {...} }
```

---

## 1. 成功 envelope 必选字段

- `command`: 字符串，命令标识。
- `ok`: 布尔，成功时为 true。
- `result`: 结构化对象，一般为 `CleanedResult`。

可选字段：

- `meta`: `trace_id`, `elapsed_ms`, `command_version`。

---

## 2. 失败 envelope 必选字段

- `command`
- `ok: false`
- `error.type`
- `error.message`
- `error.detail`（可选）

---

## 3. 文件、终端与 stdout/stderr

### 3.1 建议

- 始终 stdout 输出 JSON。
- `--output <json-file>` 同步写同一 payload。
- 错误也写入同一 payload（含 ok:false）。

### 3.2 解析器容错

- `json.loads` 应可直接解析（包括 pretty 模式）。
- 对于不可 JSON 的异常，CLI 仍应返回 `ok:false`。

---

## 4. 退出码

- `0`：命令成功产出 JSON（即使科学 status=block）。
- `1`：运行时异常（文件不可读、参数错误、内部异常）。
- `2`：`--fail-on-block` 且 review 是 BLOCK。

---

## 5. `--pretty`

- 仅影响 formatting。
- 不改变字段。

---

## 6. `--output`

- 与 stdout 打印内容一致。
- 失败时同样写入。
- 目录不存在时自动 `mkdir -p`。
- 写入失败：返回 `1` 并在 stderr/ stdout 输出错误 payload。

---

## 7. `--fail-on-block`

- 仅改变退出码，不改变 payload。
- `result.status == "block"` 时返回 `2`。

### 理由

- Agent pipeline 能拿到结构化 BLOCK 决策。
- Shell 管道可通过 `$? == 2` 做分支。

---

## 8. output 与 payload 一致性

- `json.loads(stdout)` 与 `json.loads(output_file)` 必须字段级一致。
- 测试应比较：
  - `ok`
  - `result.task`
  - `result.status`

---

## 9. 与 API/MCP 的映射

- handler 输出始终是 `CommandEnvelope`。
- MCP 工具应直接复用同一 payload。
- HTTP 层应返回同 payload。

---

## 10. 流水线安全模式建议

1. 对单次任务：解析失败 => 直接失败；
2. 对科学失败（block）：保留 JSON 继续下游决策；
3. 对系统失败：退出 `1`。

---

## 11. 测试要求

- pretty 可 parse。
- output file 与 stdout 一致。
- block 场景：`
  - `ok==true`
  - `result.status==block`
  - `--fail-on-block` => exit 2。
- missing file => `ok:false`。
