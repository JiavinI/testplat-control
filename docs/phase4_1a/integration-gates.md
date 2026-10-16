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

## 已知偏差

`frontend/vite.config.ts` 的开发代理设置了 `changeOrigin: true`。浏览器的 `Origin` 仍是 Vite 地址，后端 `assert_same_origin` 用改写后的 `Host` 比较，登录和注册返回 403，文案是「Origin 与当前站点不一致」。本批不改 `frontend/src` 和 `vite.config.ts`。截图使用 `frontend/scripts/vite.screenshot.mjs`，其中 `changeOrigin` 为 false，只为拍到登录后的页面。
