# Phase 3.3a 跨仓集成：真实 Engine 鉴权矩阵与泄密验收

日期：2026-10-12　基线：Engine `f631e2e`（0.3.0）+ Control `d80cf63`（file:// 临时锁定 Engine `f631e2e`）

## 运行

```bash
FRONTEND_PORT=5183 bash scripts/run_real_engine_matrix.sh   # 端口可用环境变量覆盖
```

脚本把资产（`tests/fixtures/assets` + `tests/fixtures/auth_matrix/assets`）、各 config root、
SQLite 全部写在临时目录，结束即删除；已跟踪 fixture 从不改写。假秘密只以环境变量注入 Control 进程。

| 段 | 内容 | 产物（`frontend/screenshots/phase3_3-real-engine/`） |
|---|---|---|
| 1 | HTTP 矩阵：设计稿 §6 全部 10 条 + B2 + Q2/Q3/Q5/Q7，target `/__inspect` 核对实际发出的凭证摘要 | `auth-matrix-report.json`、`auth-422-real-engine.json` |
| 2 | 身份展示截图（390/1440，无 route mock），逐张 DOM 秘密搜索 | `*-auth-*.png`、`dom-secret-search.json`、`auth-browser-report.json` |
| 3 | Phase 3 回归：无 auth 配置项目跑原浏览器矩阵（截图写临时目录） | `phase3-regression-report.json` |
| 4 | 泄密全文搜索：后端/Engine DEBUG 日志、target/前端日志、SQLite 文件字节与逐表原始行、报告、DOM 证据、docs | `leak-search-evidence.json` |

## 本地回显目标（`scripts/local_target_server.py`）

- `GET /echo/headers`：把 `Authorization`/`X-Api-Key`/`X-Tenant-Token` 回显到非敏感键 `echo.seen_*`。
- `GET /echo/error`：401，凭证写进错误正文。
- `GET /__inspect`、`POST /__inspect/reset`：只给出凭证头的 sha256 与出现次数，不暴露原值。

## 已知限制

- POSIX 环境变量值不能含 NUL，“变量值含 NUL → 不可用”无法在真实进程环境里构造，由 Control 单测覆盖；
  模板字面量含 NUL（`literal-nul`）在矩阵中覆盖。
- `harness_real_matrix` 仅限验收：缩短超时，并在设置 `MATRIX_SQLITE_PATH` 时改绑文件型 SQLite。
