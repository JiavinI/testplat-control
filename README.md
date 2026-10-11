# testplat-control

测试平台控制面（FastAPI）。

## Engine 依赖（Phase 2.5）

Control 通过 Python 包依赖调用 `testplat-engine`，**禁止**运行时 `sys.path` 注入。

- 兼容版本：`testplat-engine>=0.1.0,<0.2`（0.1.x）
- 启动时校验：包是否安装、版本是否兼容、Interface 符号齐全，并**实际调用**公开 `create_engine()`，验证返回对象具备 async `execute`；失败则 fail-fast（不再把无效 runtime 延迟到首次执行 503）
- 默认 DI 提供 `PackageEngineAdapter`（仅解析已安装包的官方 `create_engine()`）
- 测试 / 浏览器 Fake 门禁通过 `app.dependency_overrides[get_engine_port]` 或 `harness_fake` 注入 `FakeEngineAdapter`

### 本地开发安装（Agent 4 验收）

本集成分支用 uv path editable 指向 **Engine 集成 worktree**（相对路径，含 runtime）：

```toml
# pyproject.toml 中的 [tool.uv.sources]
testplat-engine = { path = "../phase2-5-integration", editable = true }
```

对应 Engine 候选：`codex/phase2-5-integration`（基于 Agent 2 `dfdec69`，并补充 `create_engine`）。

```bash
uv sync --extra dev
uv run uvicorn testplat_control.main:app --host 127.0.0.1 --port 8000
```

正式 git commit / tag 锁定为推送 Engine 远程后的 follow-up（**本修复阶段仍保持 path editable，不要求远程 tag lock；亦不宣称 clean-machine final**）。
在未推送前，换机验收需同时 checkout 两个 worktree 并保持上述相对路径。

### FakeEngine 门禁启动

```bash
# 后端（Fake，不打真实目标）
uv run uvicorn testplat_control.harness_fake:app --host 127.0.0.1 --port 8000

# 前端
cd frontend && pnpm install && pnpm dev

# 双视口门禁（需 5173 + 8000 已启动）
cd frontend && pnpm e2e:gate
```

### 真实 Engine 冒烟

1. 启动本地目标 HTTP（或使用测试里的 ThreadingHTTPServer 模式）。
2. 项目 `config/envs/{env}.yaml` 的 `api_hosts` 指向 `http://127.0.0.1:<port>`（不要写公网）。
3. 使用默认 `main:app`（PackageEngineAdapter）启动 Control。
4. 浏览器执行 → 历史详情应看到真实请求/响应快照。

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

## 故障排查

- **启动报未安装 / 版本不兼容 / 缺少 runtime**：按上方 uv sources 安装 Engine 集成 worktree，或等待正式 git 锁定。
- **启动即失败 / 不再延迟 503**：包只有 Interface、没有可用的 `create_engine()`，或返回值不是 EnginePort 时，lifespan 直接 fail-fast。
- **业务 failed 却不是 200**：不应发生；检查是否把断言失败误映射成系统错误。
- **e2e 打到真实网络**：门禁用 `harness_fake:app`；真实冒烟才用 `main:app` + 本地目标。
