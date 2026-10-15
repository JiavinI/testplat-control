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

## 仓库与项目（Phase 4.0）

项目不再由 Web 新建 / 编辑 / 删除。流程：

1. 服务端配置 `TESTPLAT_REPOS_FILE` 登记 Git 用例仓库（见 `docs/phase4_0/repos-and-snapshots.md`）。
2. 启动同步或调用 `POST /repos/{repo}/sync`。
3. `GET /projects` / `GET /repos/{repo}/projects/{project}` 浏览项目；选 `env` 后运行 api / case。

资产与登录流程来自当前 commit 快照，不再使用 `assets_root` / `config_root` 字段。
运行时的环境地址、超时、业务参数和测试账号以数据库为准，见下一节。

## 平台会话、环境与账号（Phase 4.1a）

说明与 OpenAPI：`docs/phase4_1a/`。

- `POST /auth/register`、`POST /auth/login`、`POST /auth/logout`、`GET /auth/me`。会话 cookie 名 `testplat_session`（HttpOnly、SameSite=Lax，库中只存 token 哈希，约 7 天）。`health`、注册、登录不要求会话；其余配置与执行接口未登录返回 401。
- 项目前缀 `/repos/{repo}/projects/{project}` 下维护环境与测试账号。环境名、账号名保存后不可改；可以新增、编辑、停用。PUT 必须带 `revision`，过期版本返回 409。
- 登录流程读当前快照的 `config/auth/_profiles.yaml`。`GET .../login-profiles` 只返回流程名和凭据字段名。
- 被测凭据用 `TESTPLAT_MASTER_KEY`（Fernet）加密。密钥缺失或无效时明确报配置错误，不自动生成新密钥。平台用户密码用 Argon2 哈希。
- 已有 Web 环境后，`api_hosts`、账号和启停只来自数据库；Git 同步不覆盖它们。项目还没有任何 Web 环境时，运行仍读取 Git 环境文件和历史 `config/auth/{env}.yaml`。
- HTTP 步骤超时：请求显式 `timeout_seconds` > 环境 `timeout_seconds` > 默认 30。省略和显式 30 不是同一件事。仍是每步超时，不是整个 Case 的总预算。
- 不使用 Alembic。启动发现不兼容表结构时提示显式删除数据库文件，不会自动清空。

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

`timeout_seconds` 是 Engine 对**每个步骤**的 HTTP 超时，不是整个 Case 的总预算；
未显式指定时默认 30 秒（Phase 4.1a 起可被请求或环境覆盖）。Control 目前没有 Case 级总限时。

日志硬约束：不使用 `logger.exception` / `exc_info`，不记录 `EngineError.log_reason`、`__cause__` 或异常原文，
只记 kind、stage、ID 与异常类型名（`tests/test_log_redaction.py` 守护）。

## 故障排查

- **启动报未安装 / 版本不兼容 / 缺少 runtime**：执行 `uv sync --extra dev`，确认能拉取 `testplat-engine` 的锁定 commit；勿用 `sys.path` 或本地 sibling path 绕过。
- **启动即失败 / 不再延迟 503**：包只有 Interface、没有可用的 `create_engine()`，或返回值不是 EnginePort 时，lifespan 直接 fail-fast。
- **业务 failed 却不是 200**：不应发生；检查是否把断言失败误映射成系统错误。
- **e2e 打到真实网络**：门禁用 `harness_fake:app`；真实冒烟才用 `main:app` + 本地目标。
- **保存账号报 TESTPLAT_MASTER_KEY 未配置 / 无效**：用 `cryptography.fernet.Fernet.generate_key()` 生成密钥后写入环境变量。不要在密钥丢失后自动换一把新密钥，旧密文将无法解密。
- **启动提示表结构不兼容**：显式删除当前 SQLite 文件后再启动。程序不会清空数据库。
