# testplat-control

测试平台控制面（FastAPI）。

## Engine 依赖（Phase 2.5）

Control 通过 Python 包依赖调用 `testplat-engine`，**禁止**运行时 `sys.path` 注入。

- 兼容版本：`testplat-engine>=0.1.0,<0.2`（0.1.x）
- 启动时校验：包是否安装、版本是否兼容、Interface 符号齐全，并**实际调用**公开 `create_engine()`，验证返回对象具备 async `execute`；失败则 fail-fast（不再把无效 runtime 延迟到首次执行 503）
- 默认 DI 提供 `PackageEngineAdapter`（仅解析已安装包的官方 `create_engine()`）
- 测试 / 浏览器 Fake 门禁通过 `app.dependency_overrides[get_engine_port]` 或 `harness_fake` 注入 `FakeEngineAdapter`

### 安装（git commit 锁定）

`testplat-engine` 通过 `[tool.uv.sources]` **锁定到远程 git commit**（非本地 path editable）：

```toml
# pyproject.toml 中的 [tool.uv.sources]
testplat-engine = { git = "https://github.com/JiavinI/testplat-engine.git", rev = "942a66dd127de3647deab88611ada2a9bcc06c90" }
```

- 版本约束：`>=0.1.0,<0.2`（与依赖声明一致）
- 对应远程分支：`codex/phase2-5-integration`（安装以 **rev/commit** 为准，不依赖分支名漂移）
- 换机 / clean-machine：只需能访问该仓库与 commit；**不需要** sibling Engine worktree，也**禁止** `sys.path` 注入

```bash
uv sync --extra dev
uv run uvicorn testplat_control.main:app --host 127.0.0.1 --port 8000
```

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

- **启动报未安装 / 版本不兼容 / 缺少 runtime**：执行 `uv sync --extra dev`，确认能拉取 `testplat-engine` 的锁定 commit；勿用 `sys.path` 或本地 sibling path 绕过。
- **启动即失败 / 不再延迟 503**：包只有 Interface、没有可用的 `create_engine()`，或返回值不是 EnginePort 时，lifespan 直接 fail-fast。
- **业务 failed 却不是 200**：不应发生；检查是否把断言失败误映射成系统错误。
- **e2e 打到真实网络**：门禁用 `harness_fake:app`；真实冒烟才用 `main:app` + 本地目标。
