# testplat-control

测试平台控制面（FastAPI）。

## Engine 依赖（Phase 2.5）

Control 通过 Python 包依赖调用 `testplat-engine`，**禁止**运行时 `sys.path` 注入。

- 兼容版本：`testplat-engine>=0.1.0,<0.2`（0.1.x）
- 启动时会校验包是否安装、版本是否兼容、公开 Interface 符号是否齐全；失败则 fail-fast
- 默认 DI 提供 `PackageEngineAdapter`；测试/验收 harness 通过
  `app.dependency_overrides[get_engine_port]` 注入 `FakeEngineAdapter`

### 本地开发（Agent 3 worktree）

本分支用 uv path editable 指向已审查的 Interface worktree（仅本地开发覆盖，**不要**把绝对路径写进运行时 Python）：

```toml
# pyproject.toml 中的 [tool.uv.sources]
testplat-engine = { path = "../phase2-5-engine-interface", editable = true }
```

对应 Interface 提交：`bee429d`（`codex/phase2-5-engine-interface`）。
Agent 4 将把正式依赖锁定为 git commit；CI / 换机验收不得依赖开发者目录布局。

当前 Interface 已含契约，但 **runtime `create_engine` / `execute` 由 Agent 2 落地**。
在 runtime 合入前，真实 `PackageEngineAdapter.execute` 会抛出 `unavailable`（HTTP 503）；
业务与集成测试使用 Fake。

```bash
uv sync --extra dev
uv run uvicorn testplat_control.main:app --reload
```

## 项目接口错误

约束冲突返回 409，响应体为 `{"detail": "<可读说明>"}`，不会变成 500。

- 创建或重命名为已存在的项目名称：`detail` 为 `项目名称已存在`。
- 删除仍有执行记录的项目：`detail` 为 `项目存在执行记录，无法删除`。执行历史不会被级联删除。

## 执行错误映射（摘要）

| Engine kind | stage | HTTP | 执行记录 |
|---|---|---|---|
| asset_not_found | preflight | 404 | 不创建 |
| invalid_asset | preflight | 422 | 不创建 |
| invalid_environment | preflight | 422 | 不创建 |
| unavailable | preflight | 503 | 不创建 |
| timeout | execution | 504 | 创建 failed |
| transport | execution | 502 | 创建 failed |
| internal | preflight / execution | 500 | 仅 execution 创建 |
| 业务 failed | — | 200 | 创建 failed |
