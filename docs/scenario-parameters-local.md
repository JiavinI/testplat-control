# 场景参数与公共流程：交付与隔离验证

场景运行页沿用统一参数预览、页面默认值、资产环境覆盖和单次 JSON 输入。新版 Engine 详情提供步骤引用树；每次公共流程调用的输入、声明输出、变量来源及子步骤可在运行结果和历史中展开，失败节点逐层展开到内部步骤。参数保存沿用已有行为，不写回 Assets，不自动保存单次输入。

Engine 是 schema 0.3 定义和执行语义的唯一来源。详情路由通过公开 describe_case 能力读取递归定义；旧 0.2 保持文件详情；正式启动要求具备新版公开描述能力。新结果通过类型化 trace.children 递归传递，result_version=0.3，旧响应省略新增字段。

正式依赖锁定 Engine 0.6.0 的不可变提交 bddb200a7e21804db0a6032e35c635b977168caf，启动要求公开 describe_case 可调用。正常安装使用 uv sync --locked --extra dev，无需相邻源码；现有预览未在本次交付中更新。显式开发与隔离验收入口：

```sh
uv run --isolated --locked --extra dev pytest -q
uv run --isolated --locked --extra dev pytest -q ../testplat-assets/tests
cd frontend
npm test -- --run
npm run lint
npm run build
```

新增集成测试用隔离 Git 快照、数据库、本机假目标验证详情、重复调用隔离、输出类型、零请求拒绝、嵌套超时、脱敏及历史一致性。前端测试验证引用展示、递归历史解析和失败子步骤展开。新增集成测试保留公开能力探测；正常正式启动拒绝旧 Engine，不将跳过计为新版支持证据。

历史本地验证（2026-10-20，正式锁更新前）：Control 本地候选 426 项通过；前端全量首次 210 通过、1 个旧文案断言失败，同步按钮查询后该文件 4 项通过，新场景文件 16 项通过；lint/build、ruff 与 diff 检查通过。既有 Ant Design、Starlette、bundle 体积提示保留。此条记录为当时源码验证，正式交付结果见 scenario-0.3-delivery-2026-10-20.md；没有真实业务验收。

五种新节点的定义配置、JSON 输出和执行证据现可在目录、详情、结果与历史查看。静态 map 的子步骤是每项复用定义，实际运行树显示独立迭代编号；失败自动展开至内部节点。Engine 仍负责全部执行语义，Control 不重新计算金额、匹配或断言。

独立 GO2 浏览器验收：

```sh
uv run --isolated --locked --extra dev python scripts/verify_pending_workspace.py
# 可选 --serve 保留独立预览；默认验收后清理。
```

脚本依赖相邻 Assets 候选目录及其测试假服务，使用内存 SQLite、临时 Git 快照、临时密钥和虚构静态头账号，Engine 通过 MockTransport 拦截全部业务请求。端口 5293/8223 冲突时拒绝启动，不改既有预览。三个分支验证成功（8 次假请求）、第二项 SKU 缺失（2 次）、后端金额不符（8 次），包含刷新历史、嵌套请求/响应、失败证据与 390px 页面无横向溢出，页面异常 0。报告和截图默认在 `/tmp/testplat-pending-preview/`；不包含真实凭据。

Engine 已提交推送，Control 精确锁定其实际提交并验证无本地覆盖安装后，才启用 GO2 正式资产；实际交付状态与证据见 [交付记录](scenario-0.3-delivery-2026-10-20.md)。
