# 平台＋项目工作区与安全配置导入

用户决定与业务关系以外层 `docs/requirements/platforms-and-projects.md` 为准。平台列表为 GO2 网站、E3E3 网站、GSB、代发后台、拿货端、GO2 管理后台。GSB 选择 GO2／E3E3 时明确显示各自归属；已有 `main/gsb` 路由、账号和历史保留。

## 数据和运行契约

资产清单的每个工作区可增加 `workspace: {platform, platform_name, project, project_name, configuration?}`。configuration 默认自身，指定时必须是同仓直接工作区，且双方 config 路径相同。同步只新增／更新 `workspace_bindings`，不修改旧表结构；旧清单仍可使用。GET 项目接口返回显式 workspace 坐标。

网站与自身 GSB 共用一套数据库环境／账号；独立后台的业务项目上下文共用各自后台配置。所有配置 CRUD、环境列表和运行解析通过同一归属服务；页面提示共享关系，保存时使相关缓存失效。执行历史与登录缓存仍属于实际运行工作区，执行摘要保存平台／项目和配置归属。

配置文件树按 manifest.config 显示，不能因复用 GSB 接口目录就展示另一个网站的登录流程。正常 Web 仍只从数据库读取 Host 和凭据，不因缺少环境或账号回退到 Git。

独立后台流程可使用完整字符串 `${workspace:project}` 作为登录参数，Control 只将其替换为绑定的业务项目键。不自动修改业务接口的过滤字段。GSB 登录 source 保持各自配置里的字面量 go2／e3e3。

`identities.<name>.unavailable` 用 `{reason, credentials}` 明确声明尚未适配的流程；credentials 只允许字段名到 `${secret:同字段名}` 的映射，便于 Web 维护。引用该流程在网络请求前失败，页面展示具体限制。代发后台验证码／Redis 使用此声明，不加载虚构插件或简化密码登录。

## 本地复现

在 Control 目录执行：

```sh
bash scripts/dev.sh check
bash scripts/dev.sh pytest -q
bash scripts/dev.sh python scripts/verify_platform_assets.py
bash scripts/dev.sh python ../testplat-assets/scripts/validate.py
```

需要本轮 Assets；Control 已远程精确锁定 Engine 0.5.1，可直接使用 `uv run --locked --extra dev`。相邻源码开发仍可用 `scripts/dev.sh`。交付分支和复现证据见 [阶段交付](stage-delivery-2026-10-18.md)，历史本地验证保留原记录。

真实 Assets 验收脚本创建临时文件库、虚构凭据和本机假服务，验证 10 个上下文请求、GO2／E3E3 登录来源、拿货端 token 和管理后台 Cookie。拿货端的受保护探测 API 只加到临时资产仓，不写回实际 Assets。报告只含状态和虚构执行标识，不读取真实 secrets 或预览 env.sh。

## 安全导入

先正常同步本轮 Assets。调用方在进程环境提供目标库原有 `TESTPLAT_MASTER_KEY`，不要在命令行、聊天或日志中传主密钥。显式指定数据库；默认仅预览：

```sh
bash scripts/dev.sh python -m testplat_control.platform_import \
  --source /path/to/old/config \
  --database-url sqlite:////absolute/path/to/control.db \
  --skip-e3e3-b2
```

确认审查结果、先在隔离库／副本验证后加 `--apply`。导入通过现有环境／账号服务加密、递增版本及记审计；只补缺失 Host 和账号，已有值全部保留。执行前检查所有配置归属和主密钥；每项使用服务原子提交，异常后可安全重跑，不自动回滚已完成的独立项目。

用户名按本次指定值，密码取旧 secrets 对应条目。E3E3 b2.primary 的旧用户名不一致时，默认停止；`--skip-e3e3-b2` 可先导入其它已明确配置；仅用户确认对应关系后使用 `--allow-e3e3-b2-rename`。二者互斥。工具不导入支付密码或退款凭据，也不输出任何凭据值。

网站入口资产仅匿名检查 SSO，未实现浏览器登录。代发后台匿名入口可执行，验证码登录待适配。上述限制不因假服务请求通过而视为真实登录通过。搜索商品及完整场景的真实验收继续保留为待办。

## 2026-10-18 配置可读性补充

账号列表／详情新增 `login_username`，从原加密凭据中仅投影 username；不会返回完整 credentials。此读取需要原主密钥，列表／详情 GET 禁止浏览器缓存。没有明文账号字段迁移，也不使用 display_name 冒充登录账号。环境维护先选环境，直接展示完整 Host，用途分组仅影响展示，共享配置中的其它服务和未知 Host 均保留。

本轮没有迁移 `case_params` 或新增公共配置开关。参数与配置的后续目标见工作区 `docs/requirements/configuration-workspace.md` 和 ADR-003，正常运行仍由数据库提供环境和账号。执行隔离浏览器验收（需要 Vite 已运行）：`cd frontend && node scripts/e2e-config-workspace.mjs`；应用 API 全部由假数据拦截，不读取预览数据库，不调用真实目标。

## 运行页参数来源切片

GET `/repos/{repo}/projects/{project}/assets/{id}/params` 新增 `asset_defaults`，取现有 inputs.default；旧参数表单字段保持兼容。接口页按声明键展示资产默认值、共享环境覆盖、本次输入、生效值及来源，输入框只提交本次覆盖。场景页使用已有资产树的 params，允许单次 JSON 对象覆盖，支持 null／false／0 和顶层对象整体替换。非法 JSON 禁止执行；切换工作区、资产、环境后清空草稿。预览敏感键及嵌套值隐藏，完整请求体模式隐藏模板参数预览。

预览是模板输入；既有单接口插值可能把数字／布尔转为字符串，场景步骤引用保留类型，最终请求以执行展示为准。本轮不改 Engine 语义、不写回 Assets、不迁移共享 case_params。持久化已接续实现，见下一节和工作区 `notes/asset-parameter-storage-design-2026-10-18.md`。

隔离浏览器验收：`cd frontend && node scripts/e2e-parameter-preview.mjs`。全部应用 API 由假数据拦截，不访问预览库。真实本地 Engine＋本机假目标集成：`bash scripts/dev.sh pytest -q tests/test_phase4_1a_fake_target.py -k parameter_preview`，分别验证传给 Engine 的类型与目标收到的渲染结果，不使用真实账号。

## 资产参数保存与运行冻结

接口／场景页面现有“维护默认值”和“维护当前环境覆盖”入口，以 JSON 对象保存本层差异；单次输入继续独立，保存不会写回 Git。参数集按实际工作区隔离，不随 Host／账号归属共享。优先级为 Git 默认值 < 页面默认值 < 兼容共享 case_params < 当前资产环境覆盖 < 单次输入。对象按顶层键整体替换，清空本层恢复下层，场景 null 是值。

新增 `parameter_sets` 表，启动 create_all 只增加表，无旧行迁移。GET `/parameter-sets/{api|case}/{asset_id}?env=...` 返回五层中的四个持久层、有效值与来源、SHA 和各 revision；PUT 再加 `/{asset_default|environment_override}`，提交 values、读取 revision（未创建为 0）和 commit_sha。环境覆盖需传 env，资产默认值不得传 env。保存接口限制当前声明的参数名和类型，场景完整语义继续由 Engine 校验。敏感键不能存入普通参数集，审计不存值。

SQLite 保存用 BEGIN IMMEDIATE＋条件 revision 更新，同一资产 SHA 校验也在事务内；冲突 409，页面保留草稿不重试。运行显式读取事务冻结环境、账号、参数集，进入 Engine 前释放；历史 `config_snapshot.parameters` 保存脱敏有效值、来源及参数 revision，后续修改不改历史。当前共享参数不搬迁；孤立资产参数行保留，尚无管理清单。

保护现有预览库：本轮不重启原后端，不给原库加表。旧服务明确缺新路由时，页面提示保存未启用并保留既有临时调试；资产／环境 404 或读取失败禁止带缺失参数运行，不自动回退。部署前审查加表并备份，禁止删库。

验证均为隔离数据（需要相邻 Engine 0.5.1）：

```sh
bash scripts/dev.sh pytest -q tests/test_parameter_sets.py
# 需 Vite 已运行；本脚本以独立内存库＋临时 Git＋本机假目标运行真实浏览器链路。
bash scripts/dev.sh python scripts/verify_parameter_workspace.py
```

第二条会拦截浏览器全部应用 API 到临时 Control 服务，不读取预览 env.sh 或真实凭据；结束销毁内存库、临时仓库和服务。截图在 `/tmp/testplat-parameter-preview/`，不代表真实搜索或完整业务场景通过。前端全假数据脚本另验证 409 草稿保留、刷新、环境切换、完整 body 模式与 390px 布局。

## 共享参数消费者与迁移影响盘点

运行只读工具（`--data-dir` 是登记配置的 data_dir，包含各仓库目录，不是某仓库子目录）：

```sh
bash scripts/dev.sh python scripts/audit_shared_case_params.py \
  --database /absolute/path/to/control.db \
  --data-dir /absolute/path/to/repos-data \
  --output /absolute/path/to/report.md
```

工具通过 SQLite `mode=ro`、`query_only` 和读取事务盘点项目、工作区绑定、环境参数及参数集，不读取账号或 Host，不导入启动时建表的数据库 session。只扫描当前 SHA 已存在的快照；不 fetch、同步或物化，不启动后端，不执行目标请求。旧库缺少 parameter_sets 表时正常报告；缺失／非法快照、Case schema 不通过、符号链接等记分析缺口，不据此推断无消费者。报告目标不能是输入数据库或快照目录。

API 表单规则抽到 `services/api_parameter_schema.py`，运行路由及离线工具复用；Case 规范化直接使用相邻 Engine 的既有 loader，引用只从已校验步骤投影。每个实际工作区单独分析：API 声明、Case 明确引用（含嵌套）及全部共享键对其它 Case 的注入；不把 API 保存参数隐式继承到 Case。报告比较五层合成后“移除共享键”的有效参数变化、当前资产覆盖的冲突及 revision，仅输出类型和相等关系，不输出值。bool／number 严格区分，null 是值。

实际预览盘点保存在 [审计清单](audits/shared-case-params-2026-10-18.md)：10 工作区、5 套环境，共享 case_params 均为空，分析缺口为 0，原库尚无参数表。没有数据需要迁移，保留原状。本轮不新增迁移写入入口；将来出现共享值时重跑清单、明确目标与保留／替换策略，再用隔离库验证。
