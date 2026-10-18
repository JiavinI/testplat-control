# testplat-control

测试平台控制面（FastAPI）。

## 当前安装与开发（2026-10-18）

Control 通过远程精确提交安装 Engine **0.5.1**，已包含请求内容覆盖、登录凭据透传与脱敏扩展，不需要相邻 Engine 或 editable 覆盖：

```bash
uv sync --locked --extra dev
uv run --locked python -c 'from testplat_control.engine_bootstrap import ensure_engine_compatible; print(ensure_engine_compatible())'
uv run --locked --extra dev pytest -q
```

测试在导入应用前强制隔离内存库；服务启动读取调用者环境和 `.env`，请显式指定自己的数据库、仓库登记和对应主密钥，不要指向既有预览库。交付分支、复现证据及限制见 [本阶段交付](docs/stage-delivery-2026-10-18.md)。

需要同时修改 Engine 时，仍可显式使用本地开发入口：

```bash
bash scripts/dev.sh check
bash scripts/dev.sh pytest -q
bash scripts/verify-local-engine.sh
```

`dev.sh` 使用 `uv run --isolated --locked --with-editable`，验证相邻 Engine 来源及契约，不改变锁文件或加载预览私有配置。可用 `TESTPLAT_ENGINE_SOURCE=/绝对路径/testplat-engine` 指定源码目录。[历史本地交付记录](docs/local-engine-delivery-2026-10-16.md) 保留当时的依赖状态与证据。

## Engine 依赖（当前：Engine 0.5）

Control 通过 Python 包依赖调用 `testplat-engine`，**禁止**运行时 `sys.path` 注入。

- 兼容版本：`testplat-engine>=0.5.0,<0.6`
- 启动时校验：包是否安装、版本是否兼容、Interface 符号齐全、包含 `request_override` 契约，并**实际调用**公开 `create_engine()`，验证返回对象具备 async `execute`；失败则 fail-fast（不再把无效 runtime 延迟到首次执行 503）
- 默认 DI 提供 `PackageEngineAdapter`（仅解析已安装包的官方 `create_engine()`）
- 测试 / 浏览器 Fake 门禁通过 `app.dependency_overrides[get_engine_port]` 或 `harness_fake` 注入 `FakeEngineAdapter`

Phase 3 文档里的 `>=0.2.0,<0.3` 与 commit `4715c61` 是当时的基线，不是当前锁定。

### 当前远程精确锁定

`testplat-engine` 通过 `[tool.uv.sources]` **锁定到 GitHub 上的精确 commit**（非本地 path editable）：

```toml
# pyproject.toml 中的 [tool.uv.sources]
testplat-engine = { git = "https://github.com/JiavinI/testplat-engine.git", rev = "eb591d8879ec793f928500e5d7436648ef735309" }
```

> 该 rev 是已推送工作分支上的 Engine 0.5.1 提交，包含请求覆盖契约；未合并 main、打标签或发布包。安装按精确 SHA，不依赖分支移动。

- 版本约束：`>=0.5.0,<0.6`（与依赖声明一致）
- 安装以 **rev/commit** 为准，不依赖分支名漂移；禁止 `sys.path` 注入；本地开发通过上面的显式隔离 editable 入口

`uv sync --locked --extra dev` 直接安装上述远程 Engine。`uv.lock` 由 uv 生成；本轮 uv 将锁文件格式 revision 从 5 写为 3，其余依赖版本未变。

### 验证入口

```bash
bash scripts/dev.sh pytest -q
bash scripts/verify-local-engine.sh
```

当前独立脚本及历史入口状态见 [集成门禁](docs/phase4_1a/integration-gates.md)。历史 Phase 3 浏览器脚本依赖已退出的项目入口；`scripts/run_real_engine_matrix.sh` 仍使用旧安装命令，本轮不作为验收入口。假服务测试证明请求与登录行为；真实 GSB 业务结果需独立验收。

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
- 已有 Web 环境后，`api_hosts`、账号和启停只来自数据库；Git 同步不覆盖它们。默认缺少数据库环境时返回 422，引导到配置页面；不会读取 Git 环境、历史 auth 或服务器业务凭据。仅历史兼容需要 `TESTPLAT_LEGACY_GIT_CONFIG=true`，且项目完全没有数据库环境行，才允许读取 Git 环境和 `config/auth/{env}.yaml`。已有数据库环境的项目即使启用此开关也不得回退。pytest 只对 `legacy_git_config` 标记的用例开启该模式。
- HTTP 步骤超时：请求显式 `timeout_seconds` > 环境 `timeout_seconds` > 默认 30。省略和显式 30 不是同一件事。仍是每步超时，不是整个 Case 的总预算。
- 不使用 Alembic。启动发现不兼容表结构时提示显式删除数据库文件，不会自动清空。
- `DATABASE_URL` 决定实际库。未设置时默认 `sqlite:///:memory:`，进程退出后用户、环境和账号都会消失。需要留下数据时设为 `sqlite:///绝对路径/control.db`，并固定同一把 `TESTPLAT_MASTER_KEY`。请同时备份数据库文件和主密钥。表结构不兼容时程序只报错，不会自动删库；需要重建时由操作者显式删除该文件。团队使用前再决定是否把默认改成文件库，或在未配置时拒绝启动。本批不引入迁移工具。

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
| `GET /repos/{repo}/projects/{project}/cases/{case_id}` | Case 文件级元信息（不解析 YAML） |
| `POST /repos/{repo}/projects/{project}/cases/{case_id}/run` | 串行运行 Case，保存 `asset_type="case"` 记录 |
| `GET /repos/{repo}/projects/{project}/case-execution-records/{record_id}` | 历史详情，`result` 有明确 schema |
| `GET /repos/{repo}/projects/{project}/execution-records?asset_type=case` | 历史列表按类型筛选（可选参数） |

`GET /projects/{project_id}` 是扁平详情只读别名，已标 deprecated。新调用使用 `GET /repos/{repo}/projects/{project}`。`GET /projects` 列表仍然有效。该别名保留到 Phase 4.1a 集成验收确认没有仓外调用方后删除。

`timeout_seconds` 是 Engine 对**每个步骤**的 HTTP 超时，不是整个 Case 的总预算；
未显式指定时默认 30 秒（Phase 4.1a 起可被请求或环境覆盖）。Control 目前没有 Case 级总限时。

日志硬约束：不使用 `logger.exception` / `exc_info`，不记录 `EngineError.log_reason`、`__cause__` 或异常原文，
只记 kind、stage、ID 与异常类型名（`tests/test_log_redaction.py` 守护）。

## 故障排查

- **启动报未安装 / 版本不兼容 / 缺少 runtime**：执行 `bash scripts/dev.sh check` 核对本地 Engine 来源；远程锁定当前不含扩展，不能直接用于本轮启动。
- **启动即失败 / 不再延迟 503**：包只有 Interface、没有可用的 `create_engine()`，或返回值不是 EnginePort 时，lifespan 直接 fail-fast。
- **业务 failed 却不是 200**：不应发生；检查是否把断言失败误映射成系统错误。
- **e2e 打到真实网络**：门禁用 `harness_fake:app`；真实冒烟才用 `main:app` + 本地目标。
- **保存账号报 TESTPLAT_MASTER_KEY 未配置 / 无效**：用 `cryptography.fernet.Fernet.generate_key()` 生成密钥后写入环境变量。不要在密钥丢失后自动换一把新密钥，旧密文将无法解密。
- **启动提示表结构不兼容**：显式删除当前 SQLite 文件后再启动。程序不会清空数据库。
