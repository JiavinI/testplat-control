# 本地 Engine 扩展交付方案

核对日期：2026-10-16（Asia/Shanghai）。本文件是可审查方案及本地验证说明，不代表已获准远程推送、合并或发布。

## 三仓实际基线

| 仓库 | 当前分支 / HEAD | 开始本轮时的状态 |
| --- | --- | --- |
| Control | `main` / `3e0d192fef01705dbadca14d00e6165d49f48ef0` | 34 个已跟踪文件有未提交修改，另有导航、账号引用等新增文件；保留用户 `PHASE2_3_REVIEW_REPORT.md` |
| Engine | `main` / `5231fb470dbb7a23b0d44489c49e2b8e88da7d36` | 12 个文件有未提交修改：162 行增加、42 行删除；本轮未修改 Engine |
| Assets | `codex/gsb-b2-auth` / `fd93f865e8bc84ce17dcd8e12b83e5717f60ab51` | 工作区干净；相对 main 有 3 个本地提交，本轮未修改 |

Control 现有改动包括被测凭据原样透传、完整账号引用、请求内容覆盖、功能导航和测试库隔离。本轮只在这些改动上叠加接口详情、环境 URL、响应优先展示、相关验证与本文。没有重置工作区、整理提交或改动分支。

Engine 已有改动包括：放宽被测输入凭据限制、短值按完整字段脱敏、登录缓存收集秘密、不可变 `request_override` 契约、JSON/Query/Form/Raw 覆盖及显式 JSON null 发送。Assets 本地提交分别为 `b4ade2b`、`3765345`、`fd93f86`，涉及分组账号引用、文档和删除空 auth 文件；不代表搜索接口与场景业务验收完成。

## 已证实的缺口

Control 的 `pyproject.toml` 与 `uv.lock` 仍精确锁定远程 Engine `5231fb4`（0.5.0）。只使用锁文件创建隔离环境后，`ApiExecutionRequest` 没有 `request_override` 字段。当前预览通过启动脚本的 `uv run --with-editable ../testplat-engine` 使用未提交的本地扩展，因此远程全新检出还不能复现当前能力。

本轮不把依赖锁定改为本地 path 或远程无法取得的 SHA，也不伪称该缺口已发布解决。两个 Engine 的包版本目前都仍是 0.5.0，单看版本号不能区分能力。

## 当前可复现的本地验证

前提：三个仓库及其当前工作区源码均已保留，已安装 uv 和前端锁定依赖。以下命令在 Control 仓库运行；不加载预览 `env.sh`，不需要实际业务凭据。

```sh
# 观察远程锁定包：supports_request_override 为 False。
uv run --isolated --locked python -c 'from dataclasses import fields; from testplat_engine import ApiExecutionRequest; print({"supports_request_override": "request_override" in {x.name for x in fields(ApiExecutionRequest)}})'

# 将当前本地 Engine 打成 wheel，在隔离环境中安装并校验契约，再跑假服务集成。
bash scripts/verify-local-engine.sh

# 完整 Control 回归；conftest 仍在导入应用前强制隔离测试库。
DATABASE_URL=sqlite:///:memory: uv run --isolated --locked --extra dev --with-editable ../testplat-engine pytest -q

# Engine 回归在 Engine 仓库运行。
# uv run --isolated --group dev pytest -q
```

`verify-local-engine.sh` 在私有临时目录构建 wheel，断言实际从隔离环境的 site-packages 导入且支持覆盖契约，执行 19 项假服务集成，退出后删除 wheel。可通过 `TESTPLAT_ENGINE_SOURCE` 指定其它本地 Engine 源目录。它不修改 Control 的锁文件、项目虚拟环境、预览数据库、账号或主密钥。此方式证明源码可打包集成；可复现所需源码仍包含未提交 diff，不能只分发三个 HEAD。

本轮结果：Engine 429 项、Control 379 项全量回归通过；构建 wheel 后的 19 项假服务集成通过，涵盖凭据、登录、缓存、覆盖、JSON null 与 Query/Form/Raw。

## 建议的提交与远程交付顺序

1. 在三个仓库分别保留当前 diff；以 `git diff`、`git diff --cached` 和 `git ls-files --others --exclude-standard` 核对提交范围。现有用户报告和预览私有文件不纳入提交。需要新分支时使用 `codex/` 前缀。
2. Engine 先整理凭据/脱敏及请求覆盖的实现与测试；审查公开契约和版本策略，再确定发布版本。本轮没有改版本。若保留 0.5 系列，需明确以新精确 SHA 区分，不能复用旧标签表示新能力。
3. Engine 的远程推送、合并、标签或发布须用户另行授权。获得可获取的最终 Engine commit 后，才修改 Control 的 `[tool.uv.sources]` 精确 rev；若 Engine 跨 minor，再同步依赖范围。不要用尚未推送的本地 SHA。
4. 执行 `uv lock --upgrade-package testplat-engine` 更新真实锁定结果并审查 diff，不手写锁文件中的来源或散列。随后在全新隔离环境中仅用 `--locked` 安装，检查覆盖字段、凭据行为、脱敏和全量 Control 回归，移除验证命令里的 editable/wheel 覆盖。
5. Control 的账号/运行契约、功能导航、接口工作区可分别作为可审查提交；测试库隔离必须随相关测试一并保留。Control 合并、部署仍需另行授权。
6. Assets 的三个本地提交单独审查后按授权推送。预览通过正常 Git 同步使用可获取的快照；不手改快照目录，不恢复已删除的 `auth/test.yaml`。

最终交付门禁：全新检出 + 锁定安装可启动，测试无需任何本地 Engine 覆盖；用隔离业务配置确认真实余额的 HTTP 状态和业务码；搜索商品与两步场景另行验收。当前本地 wheel 验证通过不等于这些远程门禁已通过。
