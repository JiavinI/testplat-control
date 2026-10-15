# Phase 4.1a：Control 后端

本批只改 Control。Engine v0.5.0 只读，不增加步骤 `account` 字段，也不改前端业务。

OpenAPI：`openapi-phase4_1a.json`。相对 Phase 4.0 的路径与 schema 摘要：`openapi-diff-vs-phase4_0.diff`。

## 注册与登录

| 方法 | 路径 | 会话 |
|---|---|---|
| POST | `/auth/register` | 不需要；成功后写入会话 cookie |
| POST | `/auth/login` | 不需要 |
| POST | `/auth/logout` | 注销当前 cookie，204 |
| GET | `/auth/me` | 需要 |
| GET | `/health` | 不需要 |

其余配置与执行接口未登录返回 401。已登录用户能力相同，用户表没有超管或角色字段。

- 用户名：`^[A-Za-z][A-Za-z0-9_]{2,31}$`。密码 8–128 位，不含 CR/LF/NUL。
- 登录失败统一为「用户名或密码错误」。
- Cookie 名 `testplat_session`：HttpOnly、SameSite=Lax。`TESTPLAT_COOKIE_SECURE=true` 或请求是 HTTPS 时带 Secure。
- 随机 token 只以 SHA-256 存入 `platform_sessions`。有效期 7 天，不滑动续期。注销写 `revoked_at`。
- 变更接口若带 `Origin`，必须与当前站点 `base_url` 一致，否则 403。未带 Origin 的非浏览器客户端可以调用。
- 平台会话不进入 Engine `AuthTable`。

## 环境与测试账号

路由前缀：`/repos/{repo}/projects/{project}`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `.../environments` | 列表 / 新增 |
| GET/PUT | `.../environments/{env}` | 查看 / 更新。PUT 带 `revision`，不一致 409 |
| GET | `.../login-profiles` | 当前资产 commit 的流程名与 `${secret:字段名}`，不含凭据 |
| GET/POST | `.../environments/{env}/accounts` | 账号列表 / 新增。列表不含凭据 |
| GET/PUT | `.../environments/{env}/accounts/{name}` | 查看 / 编辑。PUT 带账号自己的 `revision` |
| GET | `.../environments/{env}/accounts/{name}/credentials` | 显式查看凭据。`Cache-Control: no-store` |

- 环境唯一键 `(project_id, env)`。账号唯一键 `(project_id, env, account_name)`。
- 环境名：`^[a-z0-9][a-z0-9_-]{0,63}$`，且不能以 `_` 开头。账号名：`^[a-z][a-z0-9_]{0,63}$`，保留 `none`。展示名和业务角色可以是中文。保存后不能改名，用 `enabled` 停用。
- 凭据字段值至少 8 个字符。`api_hosts` 的值必须是不含用户信息的 http(s) URL。
- 环境 `timeout_seconds` 为空表示运行时用默认 30；写入 30 表示环境显式指定 30。
- 账号或环境的修改在同一事务里递增**环境** revision，账号另有自己的 revision。冲突文案：「配置版本冲突，请刷新后再保存」。
- `config_changes` 只记字段名。凭据变更的 `credential_note` 为「已修改」，不记原值。

项目响应里的 `envs` / `default_env`：该项目已有 Web 环境时，由启用中的数据库环境派生，停用的不出现。还没有任何 Web 环境时，仍返回 Git 同步写入的列。之后的 Git 同步不覆盖已有 Web 环境、账号和启停；也不会把新的 Git 环境文件自动建成数据库环境。

## 主密钥

`TESTPLAT_MASTER_KEY` 经 pydantic-settings 读取，应是 Fernet 密钥（urlsafe base64）。空字符串视为未配置。

- 未配置：`服务配置错误：TESTPLAT_MASTER_KEY 未配置`
- 不是合法 Fernet 密钥：`服务配置错误：TESTPLAT_MASTER_KEY 无效`
- 无法解密已保存密文：`服务配置错误：TESTPLAT_MASTER_KEY 无法解密已保存的凭据`

进程不会自动生成新密钥。平台密码用 Argon2id（`argon2-cffi` 默认参数）哈希。被测凭据用 Fernet（AES-128-CBC + HMAC-SHA256）加密后存 `encrypted_credentials`。日志只记异常类型，不记密码、token、密钥或异常原文。

## 登录流程与运行配置

解析入口：

- `testplat_control.services.login_profiles.load_profile_catalog`：读 `config/auth/_profiles.yaml`。文件不存在则空目录。
- `testplat_control.services.auth_loader.build_auth_from_document`：纯数据构造。`${secret:字段名}` 只查传入的凭据字典，不读 `os.environ`，也不把凭据写回环境变量。校验与 `SecretStr` 仍走原来的 auth_loader。
- `testplat_control.services.run_config.resolve_run_config`：项目 + 环境 + 已固定的 commit 目录 → Engine `environment`、`AuthTable`、有效超时 / 参数、非秘密摘要。

每个启用账号按自己的 `login_profile` 解析，AuthTable 的身份名是账号名（例如 `gsb`）。多个账号不合并成一个全局秘密字典。停用账号放进表中作为 `UnavailableAuth`，避免旧登录缓存绕过停用。未引用且未配全的账号不阻断本次运行；被引用的缺失或停用在预检失败，不回退 `TESTPLAT_GSB_*`。

参数在同一次冻结里合成，不再读第二次环境。单接口：请求 `params` > 该接口声明过的环境 `case_params` > 资产 `inputs.default`。环境里其他接口的默认键不会使本接口报未知参数；请求体显式给出的未知键仍然 422。环境默认值可以补上该接口的必填项。Case：请求 `params` > 环境 `case_params`，case 资产参数仍由 Engine 再往下叠。

`api_hosts` 在已有 Web 环境时只来自该环境行。`cache_scope` 仍是 `{repo}:{project}:{env}`。

尚无 Web 环境行时，`resolve_run_config` 继续调用 `load_project_environment` 与历史 `load_auth`，以便 Phase 4.0 夹具保持可用。这条路径会读取 `TESTPLAT_*`。一旦该项目写入过 Web 环境，运行不再进入这条路径。

## revision 与执行记录

一次运行在同一个数据库事务里读出环境、账号和版本，复制成普通值后结束该事务，再调用 Engine。执行记录在之后的单独事务写入。进行中的运行不再回库补配置。执行记录复用 `operator`（当前平台用户名），并写入：

- `config_revision`
- `account_revisions`（账号名 → 该账号 revision）
- `config_snapshot`（来源、host、超时、case_params、账号元数据与凭据字段名）

历史详情读这些列，不回查当前环境。快照和修改记录不含凭据原值。进行中的运行使用启动时的材料；保存只影响之后开始的运行。

## 表结构

`DATABASE_URL` 接到实际引擎。默认 `sqlite:///:memory:`（测试与未配置进程）。文件 URL 在进程重启后仍保留数据。内存库使用单连接；文件库允许多进程打开同一文件。

不引入 Alembic。`create_all` 只补空库。已有库若 `execution_records` 缺少 `config_revision` / `account_revisions` / `config_snapshot`，或仍是 Phase 4.0 之前的项目表，启动抛出 `IncompatibleSchemaError`，提示显式删除 SQLite 文件。程序不会自动清空。

环境 PUT 与账号 PUT 都用带预期 revision 的条件更新。没有更新到行则 409，并回滚这次的版本和修改记录。账号创建和账号更新成功时，同一事务用 `revision = revision + 1` 原子递增环境 revision，修改记录使用这次得到的版本，不复用、不倒退。

单接口在这一份冻结结果上合成参数并校验：请求 params > 本接口声明的环境 case_params > 资产 inputs.default。环境里的必填值可以补上省略的请求字段；合并后仍缺的必填项返回 422。其他接口的环境默认键不参与本接口校验。

请求体校验失败只返回 `type` / `loc` / `msg`，不返回 `input` 或 `ctx`。

| 表 | 要点 |
|---|---|
| `platform_users` | `username` 唯一，`password_hash` |
| `platform_sessions` | `token_hash` 唯一，`expires_at`，`revoked_at` |
| `project_environments` | 唯一 `(project_id, env)`，`revision` |
| `test_accounts` | 唯一 `(project_id, env, account_name)`，`encrypted_credentials` |
| `config_changes` | `field_names`，`credential_note` |
| `execution_records` | 增量三列见上 |

## 偏差

- 项目还没有 Web 环境时，运行配置仍来自 Git，而不是「api_hosts 只能来自数据库」。这是为了让 Phase 4.0 的既有测试和历史 auth 夹具继续通过。
- `_profiles.yaml` 里的 `connections` 目前不会并入合并后的 AuthTable。本批登录流程不依赖连接配置。
- 环境与账号更新用「预期 revision」条件 UPDATE。受影响行数不是 1 则 409，并回滚本次版本与修改记录。账号创建和更新都在同一事务里原子递增环境 revision。

## 数据库与兼容路径

未设置 `DATABASE_URL` 时使用 `sqlite:///:memory:`。进程退出后数据消失。要在重启后仍能读到用户、环境和账号，启动前设置 `sqlite:///绝对路径`，并固定 `TESTPLAT_MASTER_KEY`。备份时同时保留数据库文件和主密钥。不兼容的旧表只提示显式删除文件，程序不会自己清空。团队共用前再决定持久化默认值或未配置时拒绝启动；本批不引入迁移工具。

`GET /projects/{project_id}` 是扁平项目详情的只读别名，OpenAPI 已标 `deprecated`。替代路径是 `GET /repos/{repo}/projects/{project}`。`GET /projects` 列表继续保留。该别名保留到 Phase 4.1a 集成验收确认没有仓外调用方之后删除，新增调用不要使用它。

项目还没有 Web 环境时，运行配置来自 Git 环境文件和历史 `load_auth`（会读 `TESTPLAT_*`）。这是显式的兼容模式：判断条件只有「该项目是否已有 Web 环境行」，不是猜测。正常 Web 使用以数据库为准。`auth_loader.build_auth_from_document` 继续给 Web 登录流程用，不删除。退出条件：集成阶段的 Web 资产和新矩阵成为门禁后，把 Git 回退收成显式兼容开关或移除；在此之前不删这条路径。

`scripts/phase4_0_matrix.py`、`scripts/phase4_0_e2e_real_assets.py` 以及 auth / login 矩阵目前没有平台登录，直接运行会未登录。登录迁移不在本批。历史阶段的 OpenAPI 与文档保持原样，只代表当时的版本。
