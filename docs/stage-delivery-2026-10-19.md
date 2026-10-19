# GSB 迁移与调用身份主线交付

日期：2026-10-19（Asia/Shanghai）。用户确认隔离环境验收通过，并授权提交、推送及合并三仓至默认 main；不部署、不更新原预览、不打标签或发布包。

## 交付内容

- Assets：24 个 GSB API、1 份只读 checks；公共契约一份、项目专属按 projects 限制，89 处必填标记保留。旧余额/搜索 ID 兼容，接口不绑定账号，smoke 步骤选择身份。
- Engine 0.5.2：调用 identity、显式 structured 模板的 JSON 类型/必填/默认值/嵌套路径，以及业务项目预检；兼容旧 auth 与未标记模板。
- Control：调试选择当前环境账号或匿名、JSON 对象/数组编辑、跨项目过滤及空目录隐藏；切换上下文清选择。pyproject.toml/uv.lock 精确锁远程 Engine 功能提交，最低版本同步为 0.5.2。
- 三仓主线原本落后于已验收工作分支；本次同时接入此前的平台/项目与配置归属、参数保存/审计、请求体覆盖与凭据透传，以及已提交的前端样式整理。原阶段决定及证据见 2026-10-18 交付记录。

## 提交与合并记录

| 仓库 | 功能提交 | main 合并记录 |
| --- | --- | --- |
| Engine | 7ae2c013a976da62074d4f4d28b86e8220bbed6d | a4d9500c1fa41c80595e3b4812c92586b9864b0f |
| Assets | da3235d（迁移） | c41e987caaf5d85b7803eeefc17d35d250a11d25 |
| Control | 1bcb841（功能与远程锁定） | 本记录随工作分支合入 main；最终 SHA 以远程 main 为准 |

GitHub 当前令牌允许 Git 推送，但创建 PR 返回 `Resource not accessible by personal access token`。因此使用临时干净检出执行普通 `git merge --no-ff` 并非强制推送 main，保留两亲合并记录；未使用管理员绕过、force 或改写已有历史。

## 验证与安装

Engine 正式构建安装后 436 项测试通过。Assets 在包含 Control 的正确包环境下 6 项测试及完整静态校验通过；迁移模板/说明/success 逐项对照一致。

Control 干净检出使用 `uv run --isolated --locked --extra dev --no-editable`，不使用 PYTHONPATH 或相邻 editable。Engine 的 direct_url.json commit 与锁文件精确一致、模块来自 site-packages、版本 0.5.2，真实 create_engine 启动检查通过。

干净检出 Control 全量 **421 通过**（含新增旧版本拒绝和 identity 契约检查）；同一远程包环境下 Assets **6 通过**、完整静态校验 ALL PASSED。日志 /tmp/gsb-merge-control-clean.log、/tmp/gsb-merge-remote-runtime.log、/tmp/gsb-merge-assets-remote.log、/tmp/gsb-merge-assets-remote-validate.log；临时日志不入库，以上入口可复现。

```sh
uv sync --locked --extra dev
uv run --locked python -c 'from testplat_control.engine_bootstrap import ensure_engine_compatible; print(ensure_engine_compatible())'
uv run --locked --extra dev pytest -q --tb=short
```

运行测试前有内存库隔离；实际启动服务时必须显式指定自己的数据库、主密钥与仓库配置，不使用原预览私有 env.sh。假服务与单元/集成通过不代表真实订单或资金业务验收。

隔离浏览器验收使用真实 Control/Engine/当前 Assets、虚构账号和本机假目标：6 次业务请求与 1 次预期嵌套必填 422，页面异常 0，390px 无页面横向溢出，用户已确认验收通过。前端上一轮全量 194、lint/build 通过；本次依赖收尾未修改前端产品代码。注释核对完成。

## 数据与后续边界

原预览服务、数据库、账号与主密钥未修改；未执行真实订单、支付、提现或售后。用户 PHASE2_3_REVIEW_REPORT.md 保留，不纳入提交。隔离预览 5183/8013 可继续查看，内存数据随进程停止丢弃。

工作区权威文档仍在外层入口；本轮 CONTEXT、ADR-004、任务和交接的只读交付快照保存到 docs/workspace-records，不自动同步。原预览升级和真实业务验收另开明确切片，不因代码合并而自动执行。
