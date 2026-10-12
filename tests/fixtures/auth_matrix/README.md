# Phase 3.3a 真实 Engine 鉴权矩阵 fixture

只供 `scripts/run_real_engine_matrix.sh` 使用：脚本把 `tests/fixtures/assets` 与本目录 `assets/`
合并复制到临时目录，再把 `auth/*.yaml` 写入各临时 config root。已跟踪的 fixture 从不被改写。

- 不含任何秘密值：auth 配置只写 `${secret:NAME}` 占位，假秘密由脚本以环境变量注入 Control 进程。
- `auth/main.yaml`：主身份表（正常 / 多秘密 / 不可用 / 白名单外 / 含 CR、LF 的变量值）。
- `auth/bad-yaml.yaml`、`auth/literal-*.yaml`：整份配置非法 → 加载即 422。
