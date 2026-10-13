# Phase 3.3b 登录矩阵 fixtures

供 `scripts/run_real_engine_matrix.sh` / `scripts/login_real_engine_matrix.py` 使用。

- `auth/`：登录身份配置（占位符 `${secret:...}`，假秘密由矩阵脚本注入进程环境）
- `assets/`：对本地 target 的 API / Case 资产（host=`local`）
- 假插件包：`tests/plugins/testplat_login_fake/`（本地 path 安装，不发布）

覆盖设计稿 §6 第 11–21 条与旧项目五个 profile 的等价配置。
