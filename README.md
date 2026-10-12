# testplat-control

测试平台控制面（FastAPI）。

## Engine 依赖（Phase 3：Engine 0.2）

Control 通过 Python 包依赖调用 `testplat-engine`，**禁止**运行时 `sys.path` 注入。

- 兼容版本：`testplat-engine>=0.2.0,<0.3`（0.2.x；0.1.x 不再支持，因为缺少 Case DTO 与 `invalid_input`）
- 启动时校验：包是否安装、版本是否兼容、Interface 符号齐全，并**实际调用**公开 `create_engine()`，验证返回对象具备 async `execute`；失败则 fail-fast（不再把无效 runtime 延迟到首次执行 503）
- 默认 DI 提供 `PackageEngineAdapter`（仅解析已安装包的官方 `create_engine()`）
- 测试 / 浏览器 Fake 门禁通过 `app.dependency_overrides[get_engine_port]` 或 `harness_fake` 注入 `FakeEngineAdapter`

### 安装（远程 git commit 精确锁定）

`testplat-engine` 通过 `[tool.uv.sources]` **锁定到 GitHub 上的精确 commit**（非本地 path editable）：

```toml
# pyproject.toml 中的 [tool.uv.sources]
testplat-engine = { git = "https://github.com/JiavinI/testplat-engine.git", rev = "4715c61be52ce4e071bde5114a57fbbcad959bf6" }
```

> 该 rev 是 Engine PR #12 合并后的 `main` commit（`4715c61`，merge commit）。
> 之前的本机 `file://` 临时锁定已移除，干净目录 / 干净缓存的远程安装已验证（见
> `frontend/screenshots/phase3-real-engine/CLEAN_INSTALL_EVIDENCE.txt`）。
>
> - 升级 Engine 时改为新的 main commit SHA，再执行 `uv lock`。

- 版本约束：`>=0.2.0,<0.3`（与依赖声明一致）
- 安装以 **rev/commit** 为准，不依赖分支名漂移；**禁止** `sys.path` 注入与 path editable

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

### 真实 Engine 冒烟 / 浏览器矩阵

失败 / 422 / 5xx / legacy **必须**走真实 Engine（`PackageEngineAdapter`），不能只靠前端
`e2e-gate.mjs` 的 `route.fulfill` mock。Fake 门禁只覆盖 UI 壳与横向溢出。

一键矩阵（本地 target + 短超时 harness + 前端，不访问公网）：

```bash
./scripts/run_real_engine_matrix.sh
# 截图与报告：frontend/screenshots/phase3-real-engine/
```

手动步骤：

1. `uv run python scripts/local_target_server.py --port 18099`
2. 确认 `tests/fixtures/config/envs/test.yaml` 的 `api_hosts.local` 指向该端口（`dead` 保持 `127.0.0.1:1`）。
3. `uv run uvicorn testplat_control.harness_real_matrix:app --host 127.0.0.1 --port 8000`
   （与 `main:app` 相同真实 Engine；仅将每步骤超时缩短为 0.5s 以便触发 504。）
4. `cd frontend && pnpm dev`
5. `cd frontend && pnpm e2e:real-engine`

API 层证据：`uv run pytest -q tests/integration/test_real_engine_case_flow.py`。

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
| invalid_input（Phase 3 新增，Case 参数缺失） | preflight | 422 | 不创建 |
| unavailable | preflight | 503 | 不创建 |
| timeout | execution | 504 | 创建 failed |
| transport | execution | 502 | 创建 failed |
| internal | preflight / execution | 500 | 仅 execution 创建 |
| 业务 failed | — | 200 | 创建 failed |

## Case（Phase 3）

Case 的语法校验与执行语义**归 Engine**；Control 只负责项目/环境、调用与计时、记录与 HTTP。
契约、示例 JSON 与 OpenAPI diff 见 `docs/phase3/`。

| 方法与路径 | 说明 |
|---|---|
| `GET /projects/{id}/cases/{case_id}` | Case 文件级元信息（不解析 YAML） |
| `POST /projects/{id}/cases/{case_id}/run` | 串行运行 Case，保存 `asset_type="case"` 记录 |
| `GET /projects/{id}/case-execution-records/{record_id}` | 历史详情，`result` 有明确 schema |
| `GET /projects/{id}/execution-records?asset_type=case` | 历史列表按类型筛选（可选参数） |

`timeout_seconds`（默认 30）是 Engine 对**每个步骤**的 HTTP 超时，不是整个 Case 的总预算；
Control 目前没有 Case 级总限时，N 步 Case 最坏约 `N × 30s`。

日志硬约束：不使用 `logger.exception` / `exc_info`，不记录 `EngineError.log_reason`、`__cause__` 或异常原文，
只记 kind、stage、ID 与异常类型名（`tests/test_log_redaction.py` 守护）。

## 故障排查

- **启动报未安装 / 版本不兼容 / 缺少 runtime**：执行 `uv sync --extra dev`，确认能拉取 `testplat-engine` 的锁定 commit；勿用 `sys.path` 或本地 sibling path 绕过。
- **启动即失败 / 不再延迟 503**：包只有 Interface、没有可用的 `create_engine()`，或返回值不是 EnginePort 时，lifespan 直接 fail-fast。
- **业务 failed 却不是 200**：不应发生；检查是否把断言失败误映射成系统错误。
- **e2e 打到真实网络**：门禁用 `harness_fake:app`；真实冒烟才用 `main:app` + 本地目标。
