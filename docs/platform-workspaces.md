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

需要相邻已提交的 Engine 0.5.1 和本轮 Assets。远程 Engine 锁定仍是旧 0.5.0，未执行远程推送／发布；依赖交付方式见 `local-engine-delivery-2026-10-16.md`。

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
