# 阶段交付：配置工作区与运行参数

日期：2026-10-18（Asia/Shanghai）。用户已授权本阶段提交和推送；不合并 main、不打标签、不发布、不部署原预览。

## 完成范围

- 六个平台、10 个平台＋项目工作区，以及数据库 Host／账号归属（前一提交已保存）。
- 账号列表展示实际登录用户名；选择环境查看完整服务地址，编辑保留未知 Host 和共享配置。
- 接口／场景运行页展示参数来源，显式维护当前资产默认值与环境覆盖；单次修改不自动保存，不写回 Assets。
- 参数版本和资产 SHA 冲突返回 409，保留草稿；历史冻结脱敏有效参数及来源。优先级：Git 默认 < 页面默认 < 兼容共享环境值 < 当前资产环境覆盖 < 本次输入。
- 只读共享参数盘点：实际预览 10 工作区、5 环境，共享参数为空，0 分析缺口，无需迁移。见 [盘点报告](audits/shared-case-params-2026-10-18.md)。
- 正常 Web 仅用数据库 Host／账号；历史 Git 兼容测试显式开启开关，登录流程仍来自 Git。

## 依赖与提交

| 仓库 | 工作分支 | 本阶段输入 |
| --- | --- | --- |
| Engine | codex/local-engine-delivery | eb591d8879ec793f928500e5d7436648ef735309，0.5.1，已推送 |
| Assets | codex/gsb-b2-auth | 7a2cc0bb393663bb15ac8573bddb167a90a6eef0，已推送 |
| Control | codex/local-engine-delivery | 本文随功能与依赖提交保存；最终验证另补记录 |

Engine 先推送，再由 `uv lock --upgrade-package testplat-engine` 更新 Control 的来源与锁文件。不再依赖本地扩展才能运行。只变化 Engine 版本／来源，以及当前 uv 自动生成的 lock revision（5 → 3），其它依赖版本未变。历史 [本地交付记录](local-engine-delivery-2026-10-16.md) 保留当时事实。

## 本轮验证

- 工作区 Control 全量 414 通过；前端 28 文件／191 通过，lint 和 build 通过（既有 bundle 提示）。
- Engine 全量 429 通过；Assets 静态校验全部通过，安全输出回归 3 通过。
- 干净 Control 检出、不带 editable／wheel 的远程锁定验证：提交后执行，最终证据将在本文件补充。

此前浏览器隔离验收、参数持久化并发与假目标请求证据见 [工作区实现说明](platform-workspaces.md)。本轮不重复执行真实业务请求。

## 从远程复现

需要 Git、uv、Python >=3.11 及仓库访问权限。三个仓库可相邻检出，但 Control 默认安装不读取相邻 Engine：

```sh
git clone --branch codex/local-engine-delivery git@github.com:JiavinI/testplat-control.git
git clone --branch codex/local-engine-delivery git@github.com:JiavinI/testplat-engine.git
git clone --branch codex/gsb-b2-auth git@github.com:JiavinI/testplat-assets.git
cd testplat-control
uv run --isolated --locked --extra dev python -c 'from testplat_control.engine_bootstrap import ensure_engine_compatible; print(ensure_engine_compatible())'
uv run --isolated --locked --extra dev pytest -q
uv run --isolated --locked --extra dev python ../testplat-assets/scripts/validate.py
cd frontend
npm ci
npm test -- --run
npm run lint
npm run build
```

测试在导入应用前强制隔离内存库，持久化测试自行创建临时文件库，假服务使用合成凭据。完整覆盖 JSON／Query／Form／Raw、显式 null、登录／缓存与默认 Web 配置边界由回归测试验证。需要修改 Engine 时可继续使用 `bash scripts/dev.sh check` 和 `bash scripts/dev.sh pytest -q`，该入口显式覆盖为相邻源码。

## 预览与后续边界

原预览后端仍为上一切片服务，未重启、未加 parameter_sets 表、未改账号或主密钥。本次原库文件校验保持不变。源码新功能已在隔离库验收；原预览尚未启用参数保存，不得直接重启误触原库。独立安全预览或备份加表需下一阶段另定范围。

代发后台验证码／Redis、网站浏览器登录、搜索商品与完整场景真实验收尚未完成。真实余额沿用历史证据，不据此宣称其它接口通过。公共运行策略与连接配置、Page、复杂编排、测试数据、套件、Assets 编辑继续延后。

外层工作区没有远程仓库；相关需求、决策及交接将在 docs/workspace-records 中作为本阶段交付快照保存，后续本地工作仍以外层入口文档为准。用户原有 PHASE2_3_REVIEW_REPORT.md 不纳入提交。
