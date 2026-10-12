# Phase 3 Control Case backend 契约（供前端固定）

基线：Control `main @ da5e26f`；Engine `0.2.0 @ aff3ca6`。机器可读来源：
`docs/phase3/openapi-phase3.json`（当前完整 OpenAPI）、`docs/phase3/openapi-diff-vs-phase2_5.diff`（相对基线的 diff）、
`docs/phase3/examples/*.json`（真实 Engine + 本地 127.0.0.1 服务生成，规整了 ID/时间/端口；
`tests/test_case_examples.py` 保证它们始终符合当前 schema）。

## 所有权

- Case 语法校验、路径映射、引用解析、步骤执行、fail-fast、summary：**Engine**。
- Control：项目/环境加载、调用 `EnginePort.execute(CaseExecutionRequest)`（唯一入口）、计时、
  `ExecutionRecord(asset_type="case")` 持久化、HTTP 映射。**无 Case YAML 解析器**
  （旧 `YamlParser.parse_case_yaml` 已删除）。
- Engine 0.2 **没有公开的 Case 描述/摘要接口**（loader 只在内部子模块，不在 `interface.py`/包顶层导出），
  所以资产详情只返回文件级元信息；**没有 name/tags/params/steps 摘要，也无法判断“旧格式”**。
  前端在 Case 运行前拿不到步骤列表；步骤信息来自运行结果/历史详情。

## 端点

| 方法 | 路径 | 成功响应 | 说明 |
|---|---|---|---|
| GET | `/projects/{project_id}/cases/{case_id}` | `CaseAssetDetailResponse` | 文件元信息；不存在/非法/旧格式文件/符号链接逃逸 → 404 |
| POST | `/projects/{project_id}/cases/{case_id}/run` | `CaseRunResponse` | body `{"params": {...}}`；不接受 fail_fast/timeout 覆盖（多余字段被忽略） |
| GET | `/projects/{project_id}/case-execution-records/{record_id}` | `CaseExecutionRecordDetailResponse` | 只匹配 `asset_type="case"`，否则 404 |
| GET | `/projects/{project_id}/execution-records?asset_type=api\|case` | 既有列表（项不变） | 新增**可选**查询参数 `asset_type`；`status`/`asset_id`/`skip`/`limit`/`order_by` 不变 |
| GET | `/projects/{project_id}/execution-records/{record_id}` | 既有详情（不变） | 对 Case 记录依旧可用：`result` 为完整 Case 结果，`request`/`response` 为 `null` |

Case ID 来自资产树：`scenarios/**/*.case.yaml` 的树节点 id 现在是 `case.<...>`（修正了 `.case` 双后缀，契约 §8.3），
可直接用于上面的 `{case_id}`。

## 运行结果与 HTTP 映射

| 情形 | HTTP | 记录 | `record.status` | 响应体 |
|---|---|---|---|---|
| 全部步骤 success | 200 | 创建 | success | `CaseRunResponse` |
| 业务 failed（断言失败、变量解析失败） | 200 | 创建 | failed | `CaseRunResponse`；后续步骤 `skipped` |
| preflight：asset_not_found | 404 | 不创建 | — | `{"detail": 公开说明}` |
| preflight：invalid_asset / invalid_input / invalid_environment | 422 | 不创建 | — | `{"detail": …}` |
| preflight：unavailable | 503 | 不创建 | — | `{"detail": …}` |
| execution：timeout | 504 | 创建 | failed | `{"detail": …}` |
| execution：transport | 502 | 创建 | failed | `{"detail": …}` |
| execution：internal | 500 | 创建 | failed | `{"detail": …}` |
| preflight 阶段 internal / 未分类异常 | 500 | 不创建 | — | `{"detail": …}` |
| 项目不存在 | 404 | 不创建 | — | `{"detail": "Project not found"}` |

注意：系统错误（5xx）的响应体**不含 record_id**（沿用 Phase 2.5 错误体）；前端要看到失败步骤，需刷新历史列表
（`?asset_type=case&status=failed`）再打开类型化详情。

## `CaseResult`（run 响应与历史详情共用）

`{case_id, status, duration_seconds, steps[], summary{total,success,failed,skipped}, error|null}`

- `status`：`success` 当且仅当全部步骤 success。`summary` 由 Engine 计算。
- `steps[]` 顺序与资产声明一致；每项 `{step_id, name|null, type, status, duration_seconds, request|null,
  response|null, error|null, output|null, skip_reason|null}`。
  - `skipped`：`duration_seconds=0`，request/response/error 为 null，`skip_reason="fail_fast"`。
  - `failed`：`error.kind` 为 `assertion`（含 message）、`variable_resolution`（含 `step_id`、`path`，此时
    request/response 为 null），或系统错误的 `timeout|transport|internal`（`stage="execution"`）。
  - `request` = `{method,url,headers,body}`，`response` = `{status_code,headers,body}`，均已由 Engine 脱敏；
    `headers`/`body` 是被测系统的自由 JSON（契约里仅有的开放位置）。
  - `output` 只回显 alias 名，不含响应值。
- `error`（顶层）：仅 **execution 系统错误**的历史记录非 null：`{kind: timeout|transport|internal, stage:"execution", message}`；
  此时 `steps` 来自 Engine 异常携带的 `partial_outcome`（前序 success、当前 failed、其后 skipped）。
  业务 success/failed 的 `error` 恒为 null。
- 历史类型化详情的 `result` 在存档缺失/损坏/形状不符时为 `null`（不会 500）。

## 与 Phase 2.5 的兼容性

- 既有路径与既有 component schema 逐字节不变（`tests/test_case_openapi.py` 对基线快照逐项比对）。
- 唯一对既有操作的改动：`GET …/execution-records` 增加可选参数 `asset_type`（及说明文字）。
- 行为差异（非 OpenAPI）：Engine 0.2 的 DTO 在构造期递归脱敏，单 API 记录里的 `request.params.password` 现在保存为 `"***"`
  （此前明文），`tests/integration/test_api_execution_flow.py` 已相应更新。

## 超时语义

`timeout_seconds`（Control 固定 30 秒，不对外暴露）= Engine 对**每个步骤**的 HTTP 超时，**不是** Case 总预算。
N 步最坏约 `N × 30s`；同步请求会占住连接直到 Case 结束。Control 没有 Case 级总限时：外层 `wait_for` 取消会丢掉
`partial_outcome`，且本批不引入后台任务。是否需要总限时由主线程决策。
