# 依赖旧项目接口的 scripts（交给 Agent 4）

以下脚本仍使用 `POST /projects` + `assets_root` / `config_root`，以及旧的
`/projects/{id}/...` 运行路径，需迁到两段式路由 + `env` + 服务端仓库同步：

- `scripts/auth_real_engine_matrix.py`
- `scripts/login_real_engine_matrix.py`
- `scripts/login_cache_real_engine_matrix.py`
- `scripts/login_vcode_real_engine_matrix.py`
- `scripts/run_real_engine_matrix.sh`（若间接依赖上述脚本）

本 Agent 未修改这些脚本。
