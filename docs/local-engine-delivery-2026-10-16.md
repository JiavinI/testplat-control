# 本地 Engine 扩展交付

更新：2026-10-17（Asia/Shanghai）。本轮采用明确的本地开发方式完成可复现交付；未远程推送、合并、打标签或发布。

## 三仓成果

| 仓库 | 分支 | 本地提交 / 范围 |
| --- | --- | --- |
| Control | `codex/local-engine-delivery` | `5b37e74` 保存此前账号、请求内容覆盖、四菜单、接口工作区及测试隔离；后续提交提供本地入口、依赖诊断和数据库配置边界 |
| Engine | `codex/local-engine-delivery` | `bcef2e4` 保存凭据 / 脱敏 / 登录缓存秘密收集及请求覆盖；`eb591d8` 将本地候选标为 0.5.1，元数据、导出版本及 lock 一致 |
| Assets | `codex/gsb-b2-auth` | `b4ade2b`、`3765345`、`fd93f86` 三个已有提交保持原样，工作区干净 |

原 main 分支未改：Control `3e0d192`、Engine `5231fb4`。用户未跟踪的 `PHASE2_3_REVIEW_REPORT.md` 未纳入提交。未读取 / 更换预览主密钥、账号凭据，也未操作原预览数据库或重启预览服务。

Engine 扩展包括不可变 `request_override`、JSON（含显式 null）/Query/Form/Raw 整体覆盖，以及被测输入凭据原样透传和脱敏。Assets 的 GSB API 引用 `gsb.b2.primary`，登录流程在 `_profiles.yaml`，空 `auth/test.yaml` 已删除。搜索商品与完整场景仍未完成真实业务验收。

## 依赖来源与启动诊断

Control 的 `pyproject.toml` / `uv.lock` 仍锁定可获取的远程 Engine `5231fb470dbb7a23b0d44489c49e2b8e88da7d36`（0.5.0）。该包缺少请求覆盖契约；当前启动诊断会在创建 runtime 前明确拒绝它，并提示本地开发入口。保留旧远程锁定不等于当前能力已经发布。

`bash scripts/dev.sh ...` 在隔离 uv 环境中显式安装相邻 Engine，验证实际导入路径、版本、`request_override` 契约和公开 runtime，再执行指定命令。不会依赖当前 `.venv`，不修改远程锁定，不读取预览 `env.sh`。Engine 可以通过 `TESTPLAT_ENGINE_SOURCE=/绝对路径/testplat-engine` 指定。需要 uv、Python >=3.11 和依赖下载 / 缓存；隔离环境不表示离线安装。

`bash scripts/verify-local-engine.sh` 将 Engine 构建成临时 wheel，在独立环境确认从 site-packages 导入，执行实际启动诊断及假服务 / 配置边界 / 兼容测试；结束后删除 wheel。它不依赖 editable 安装，也不保留构建产物。

## 从干净本地克隆复现

以下从工作区已有本地分支复制提交与 Git 历史，不复制 `.env`、`.venv`、预览数据库、私有脚本或用户报告。路径可按实际保存位置调整；三个仓库放在相邻目录。

```sh
source_workspace=/Users/jiavin/Developer/products/testplat1
repro_root="$(mktemp -d /tmp/testplat-clean-repro.XXXXXX)"
git clone --no-hardlinks --branch codex/local-engine-delivery "$source_workspace/testplat-control" "$repro_root/testplat-control"
git clone --no-hardlinks --branch codex/local-engine-delivery "$source_workspace/testplat-engine" "$repro_root/testplat-engine"
git clone --no-hardlinks --branch codex/gsb-b2-auth "$source_workspace/testplat-assets" "$repro_root/testplat-assets"
cd "$repro_root/testplat-control"
bash scripts/dev.sh check
bash scripts/dev.sh pytest -q
bash scripts/verify-local-engine.sh
bash scripts/dev.sh python ../testplat-assets/scripts/validate.py
cd "$repro_root/testplat-engine"
uv run --isolated --locked --group dev pytest -q
```

Control 测试在导入应用前强制内存库；文件库测试和独立脚本自己创建临时库。假服务运行于回环地址、使用合成凭据，验证完整请求内容覆盖、登录、缓存与脱敏，不需要真实账号。Assets 校验只检查定义，不发起业务请求。干净检出的证据另记下方。

如需启动自己的开发服务，在 Control 运行 `bash scripts/dev.sh uvicorn testplat_control.main:app --host 127.0.0.1 --port 8000`。它读取调用者环境和 Control `.env`；文件数据库、仓库登记及原有主密钥由操作者显式指定。不要让测试或新的主密钥指向现有预览库。

## Web 配置边界与历史测试

正常 Web 默认只用数据库项目环境、host、参数、账号与启停。没有数据库环境时不展示 Git 模板环境，运行返回 422 引导配置；缺失 / 停用环境、账号、host 不读取 Git 或 `TESTPLAT_*` 业务凭据。登录流程仍从 Git `_profiles.yaml` 读取，这不属于凭据回退。

历史 Git 加载入口保留，但必须显式设置 `TESTPLAT_LEGACY_GIT_CONFIG=true`，且该项目完全没有数据库环境行。已有任何数据库环境行的项目不允许回退，直接调用配置解析服务也遵循这一规则。正常开发启动不要设置此开关。

pytest 通过 `legacy_git_config` 标记逐项启用历史模式，其余测试强制关闭；不是整套测试全局启用兼容。历史 Phase 4.0 独立矩阵在脚本中显式声明兼容模式。现代 Web 门禁先创建数据库环境和账号，再运行接口。

## 后续远程交付（待授权）

1. 审查 Engine 两个本地提交，获授权后推送 / 合并，再按项目版本策略发布 0.5.1 或明确的最终版本；不复用旧标签代表新能力。
2. 获得远程可获取的最终 Engine SHA 后，更新 Control `[tool.uv.sources]`，运行 `uv lock --upgrade-package testplat-engine` 并审查 lock diff。不要填入尚未推送的本地 SHA，也不手写 lock 的来源 / 哈希。
3. 在干净 Control 检出中仅用 `uv run --isolated --locked --extra dev` 验证启动、全量回归，不带 editable / wheel 覆盖。
4. Control 和 Assets 远程交付分别按授权执行。资产更新通过正常 Git 同步进入快照，不直接编辑快照目录。

本地复现通过不等于远程依赖更新完成。既有真实余额证据见 [接口工作区验收](api-workspace-2026-10-16.md)；本轮没有新增搜索商品或完整场景的真实验收结论。
