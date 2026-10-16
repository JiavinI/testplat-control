# Phase 4.1a 集成门禁

本文件只说明当前怎么跑、哪些入口已经退出。历史版本文档保持原样。

## 当前门禁

这些入口要么已经改成正常注册 / 登录，要么本来就不依赖平台会话覆盖。

| 入口 | 作用 |
|---|---|
| `uv run ruff check .` / `uv run ruff format --check .` | 风格 |
| `uv run pytest` | 单元与集成测试。pytest 仍会注入平台用户；这不能代替下面的独立脚本 |
| `cd frontend && npm run lint` / `npm test -- --run` / `npm run build` | 前端 |
| `uv run python scripts/phase4_1a_matrix.py` | 设计稿 §8.1 A1–A13。本地假服务证明 host、入参、凭据进入请求。真实 GSB 返回 502/504 仍算编排通过，不把业务成功写成必过 |
| `uv run python scripts/phase4_0_e2e_real_assets.py` | 用资产仓 `f226b4a` 建 `test` / `pre`、账号 `gsb`、`login_profile=gsb_login`，再同步回归 |
| `uv run python scripts/phase4_0_matrix.py` | Phase 4.0 HTTP 矩阵。截图前会登录并写入数据库环境。`PHASE4_SKIP_SCREENSHOTS=1` 只跳过截图 |
| `uv run python scripts/phase4_1a_screenshots.py` | 390 与 1440：登录、环境、账号、运行选环境、历史中的操作人与配置版本 |
| `scripts/auth_real_engine_matrix.py` | 3.3a HTTP。脚本内注册或登录 |
| `scripts/login_real_engine_matrix.py` | 3.3b HTTP。同上 |
| `scripts/login_vcode_real_engine_matrix.py` | 3.3c HTTP。需要本机 Redis |
| `scripts/login_cache_real_engine_matrix.py` | 3.3d HTTP。并发客户端显式复制 cookie，不共享 CookieJar |
| `./scripts/run_real_engine_matrix.sh` | 串起上面四段 HTTP 矩阵。浏览器步骤跳过，见下一节 |

独立脚本的会话在 `tests/platform_gate.py`：`establish` 注册，用户名已存在则登录；`inherit_cookies` / `inherit_httpx` 按 domain 和 path 复制 `testplat_session`。

## 已退出当前运行指南的历史入口

这些文件保留，用来对照 Phase 3 / 3.3 的浏览器证据。4.1a 不再运行它们。

| 文件 | 原因 |
|---|---|
| `frontend/scripts/e2e-gate.mjs` | 依赖已删除的项目新建 / 编辑，以及 Fake 路由回放 |
| `frontend/scripts/e2e-auth-real-engine.mjs` | 运行环境下拉只列出数据库环境。给项目补 Web 环境后，Git `config/auth` 不再参与这次运行 |
| `frontend/scripts/e2e-login-real-engine.mjs` | 同上 |
| `frontend/scripts/e2e-login-vcode-real-engine.mjs` | 同上 |
| `frontend/scripts/e2e-login-cache-real-engine.mjs` | 同上 |
| `frontend/scripts/e2e-real-engine-matrix.mjs` | Phase 3 无鉴权浏览器回归，同样依赖旧的项目与环境入口 |

`scripts/run_real_engine_matrix.sh` 的第 3、4、4b、4c、5 步因此只打印跳过原因。缺少 `phase3-regression-report.json` 不再使 L45 失败。HTTP 矩阵报告仍要齐全。

## D6：Git 环境与数据库环境

正常使用以数据库为准。项目只要有任意一行 Web 环境，运行就使用数据库里的 host、账号和启停，Git 同步不覆盖这些行。

项目还没有任何 Web 环境行时，运行仍读取 Git 环境文件和历史 `config/auth/{env}.yaml`。这是唯一的兼容层：有没有 Web 行可以直接查库，不是按请求临时猜测。`auth_loader` 继续负责 profile 校验和 `SecretStr` 构造，本批不删除。

4.1a 矩阵在创建 Web 环境后断言请求使用数据库凭据，不读取 `TESTPLAT_GSB_*`。后续批次应把「无 Web 行则读 Git」改成显式兼容开关，或在确认没有调用方之后删除该分支。

## 开发代理

`frontend/vite.config.ts` 的 `/api` 代理 `changeOrigin` 为 false，转发时保留浏览器的 Host。后端 `assert_same_origin` 不改：带了 Origin 的变更请求必须和 Host 对应的站点一致；没有 Origin 的脚本客户端仍可调用。截图直接启动这份默认配置（`pnpm exec vite`，不再另写代理），并用 `VITE_DEV_PROXY_TARGET` 指向临时后端。

`uv run python scripts/phase4_1a_vite_login_check.py` 用默认 `npm run dev` 走注册、登录、保存环境和注销。报告在 `frontend/screenshots/phase4_1a/vite-login-check.json`，只记状态码。

## 脚本数据库隔离

`scripts/phase4_0_e2e_real_assets.py` 在导入 Control 之前创建临时 SQLite，并设置 `DATABASE_URL` 与只属于该库的 `TESTPLAT_MASTER_KEY`。调用者传入的文件库和原密钥不会被这把临时密钥覆盖。`PHASE4_E2E_HOST_OVERRIDE` 可把模板地址换成不可达回环，只给隔离回归用；默认仍读资产模板。

`scripts/phase4_0_matrix.py` 同样在导入前把 `DATABASE_URL` 指到临时文件，避免注册用户写入调用者的库。它不更换主密钥。

`scripts/phase4_1a_matrix.py` 原本就先设置临时库再生成主密钥。截图脚本只在子进程环境里同时设置这两项，父进程不导入 Control。HTTP 矩阵只导入 `engine_bootstrap`，不打开数据库，也不更换主密钥。

## 泄密扫描

矩阵收集假服务实际签发的业务 token，以及注册和注销后重新登录得到的平台会话 cookie。LEAK 检查响应正文、监听日志和 SQLite。凭据接口可以回显账号密码，但不能出现这些 token 或会话。报告落盘前会脱敏。

`PHASE4_1A_INJECT_LEAK=1` 会把业务 token 和最新会话写进 `testplat_engine` 日志，LEAK 必须失败。默认不打开。

## 已知偏差

真实 GSB 业务成功不是自动门禁。传输失败或超时可以留下执行记录，记录里要有 operator、env、commit、config_revision。不要把 `live_http=200` 写成业务通过。
