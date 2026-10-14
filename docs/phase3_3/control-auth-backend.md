# Phase 3.3b Control 后端：登录鉴权

权威设计：`notes/phase3.3b-login-auth-design-draft.md`（已批准）。Engine 依赖：远程精确锁定 `https://github.com/JiavinI/testplat-engine.git` rev `f1a0c875`（main 合并提交，tag `v0.4.0` / PR #14）。

## 配置

`{config_root}/auth/{env}.yaml`（入 git，**不含秘密**）：

```yaml
identities:
  admin:                                    # 3.3a 静态 header
    headers:
      Authorization: "Bearer ${secret:TESTPLAT_ADMIN_TOKEN}"
  buyer:                                    # 第 1 档 generic
    login:
      host: main
      steps:
        - name: login
          method: POST
          path: /api/user/login
          body: { type: json, fields: { username: "buyer001", password: "${secret:TESTPLAT_BUYER_PASSWORD}" } }
          extract: [{ source: body_json, path: $.data.token, as: token }]
      inject:
        headers:
          X-TOKEN: "${login:token}"
default_identity: admin
connections:                                # 可选；插件用
  redis_main: { host: 10.0.0.5, port: 6379, password: "${secret:TESTPLAT_REDIS_MAIN_PASSWORD}" }
login_plugins: [vcode_redis]                # 可选；entry point ∩ 白名单才注册
```

占位符只允许 `${secret:NAME}`、`${login:名字}`、`${login_host}`。身份必须是 `headers` 或 `login` 之一（互斥）。

身份级 inject 约束（§12 Q1/Q2，handbook §5 已更正）：**至少一个 inject 值引用 `${login:}`，或声明 `session: cookie`**；`session: cookie` 时可省略 inject。字面量注入头同样按名遮蔽。

档位：`generic`（单步 + 单条 body_json/response_header 且 as=token + inject 只引用 token + 无 session/probe）/ `configured` / `plugin`。

### 连接秘密与身份阻断（Phase 3.3c §5）

- 某个 `connections` 条目的 `${secret:}` 不可用时：**该连接不进入** `AuthTable.connections`，并记入“不可用连接名”集合；**整次加载不再 422**。
- login 身份的 `params` 中任一**字符串值**（非 `SecretStr`）等于某个不可用连接名 → 该身份变为 `UnavailableAuth`，`public_reason` 只含连接名（形如 `连接 redis_main 不可用`）；同项目其它身份（静态 header、`generic_flow`、未引用该连接的插件身份）照常。
- 未被任何身份引用的不可用连接：不影响执行，只写警告日志（只含连接名与变量名，不含字段值）。
- **引用了不存在的连接名**（拼写错误、未在 `connections` 中声明）：Control **不**检查（不理解插件参数语义）；由插件在 `login()` 找不到连接时抛出自定义异常，公开面归为 `strategy_error`。
- 422 detail、日志与公开记录均不含连接字段值与秘密。

### Agent 1 交付说明（§13，写入配置文档）

1. **多步插件应自行拆分超时**：`LoginContext.timeout_seconds` 是每个请求的超时，插件 `login()` 整体另有一份总限时；多步插件不要依赖 Engine 再给一层总预算（A2）。
2. **短于 8 的附属命名值不会按值脱敏**：`token_too_short` 只约束名为 `token` 的值；其它命名值（如 `user_id`）长度不限，&lt; 8 的不进入按值替换。需要脱敏的附属值必须 ≥ 8（A3）。
3. **共享 `http_client` 仅限测试**：生产路径 `create_engine(login_strategies=...)` 必须走 `client_factory` 每次新建；注入共享 client 时 login 身份之间无 jar 隔离（A9）。

## 公开契约（相对 Phase 3）

- `ExecutionAuth` 七键：`{identity, kind, tier, header_names, overridden_headers, cookie_names, login_ref}`，`extra=forbid`。
- Case / 单 API 结果顶层 `logins`（默认 `[]`）；步骤请求快照含 `body_type`（默认 `"json"`）与可选 `query`。
- `skip_reason`：`fail_fast | login_failed`。
- `parse_execution_auth` 形状不符时记 warning（只含记录 id），不再静默丢身份而不留痕迹（H5）。
- 完整文档：`openapi-phase3_3.json`；示例见 `examples/`。

## 插件（E1）

`engine_bootstrap.resolve_login_strategies(whitelist)`：`entry_points(group=testplat_engine.login_strategies)` ∩ `login_plugins`。白名单列出但未安装 → `EngineBootstrapError`（只含策略名）；安装未列出 → info 日志并跳过。`ensure_engine_compatible` 与 `PackageEngineAdapter` 共用该解析（L1）。
