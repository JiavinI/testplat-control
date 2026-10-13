# testplat-login-plugins

独立登录策略插件包（本批提供 `vcode_redis`）。**不**加入 Control 的 `pyproject.toml` / `uv.lock`；由部署方按需安装，并由 Control 白名单 `login_plugins` 决定是否注册。

## 安装

在 Control 运行环境中（与 Control 同一 venv）：

```bash
uv pip install './plugins/testplat_login_plugins[redis]'
```

Engine 需为 `testplat-engine>=0.4.0,<0.5`。extras `redis` 精确锁定 `redis==8.1.0`（官方 redis-py，使用 `redis.asyncio`）。

## Control 白名单

环境 / 配置中声明：

```yaml
login_plugins: [vcode_redis]
```

未列入白名单时即使已安装也不会注册；使用该策略的身份会在预检期 422，且无出站请求。

## 配置样例（等价旧项目 `df_admin_api`）

```yaml
login_plugins: [vcode_redis]
connections:
  redis_main:
    driver: redis
    host: 127.0.0.1
    port: 6379
    database: 0
    password: ${secret:TESTPLAT_REDIS_MAIN_PASSWORD}   # 可省略（无密码 Redis）
identities:
  df_admin:
    login:
      strategy: vcode_redis
      host: daifa_admin
      params:
        redis_connection: redis_main
        redis_key_prefix: "gsb:vcode:prefix:"
        create_vcode.path: /createVCode
        create_vcode.method: POST            # 可选，默认 POST
        create_vcode.body_type: json         # json | form | query，默认 json（空对象）
        uuid_path: $.data.uuid               # 可选，默认 $.data.uuid
        login.path: /login
        login.method: POST                   # 可选，默认 POST
        login.body_type: form                # json | form，默认 form
        field.username: admin_user
        field.password: ${secret:TESTPLAT_DF_ADMIN_PASSWORD}
        field.source: daifa
        field.userType: "1"
        code_field: code                     # 可选，默认 code
        user_key_field: userKey              # 可选，默认 userKey
        extract.token: $.data.token          # 必填
        extract.user_id: $.data.userId       # 可选
      validity: { ttl_seconds: 72000 }
      inject:
        headers:
          X-TOKEN: ${login:token}
          X-USER-ID: ${login:user_id}
```

引用了**不存在**的连接名时，插件在 `login()` 抛 `VcodeConnectionMissing`（归类 `strategy_error`）；Control 不解析插件参数，不在加载期检查连接名拼写。

## 失败原因对照

| 场景 | `error.login.reason` | 异常类型名（日志） |
|---|---|---|
| Redis 不可达 / 认证失败 | `transport` | `ConnectionError` |
| Redis 超时或登录预算耗尽 | `timeout` | `TimeoutError` |
| Redis key 不存在或值为空 | `strategy_error` | `VcodeCodeMissing` |
| createVCode 状态码 ≥ 400 | `strategy_error` | `VcodeCreateFailed` |
| createVCode 缺少 uuid | `strategy_error` | `VcodeUuidMissing` |
| 登录状态码 ≥ 400 | `strategy_error` | `VcodeLoginFailed` |
| 登录响应缺少 token | `strategy_error` | `VcodeTokenMissing` |
| 连接名不存在 | `strategy_error` | `VcodeConnectionMissing` |

全部为业务失败：HTTP 200 + 保存执行，后续步骤 `skipped(login_failed)`。

## 短值不按值替换

Engine 的执行级按值替换只收录长度 ≥ 8 的命名值。验证码通常 4–6 位、部分 `user_id` 也可能 < 8。本插件在调用 `ctx.record` **之前**把验证码、uuid、密码写成 `***`，因此短值不会以原样出现在 `logins` 记录里。`vcode_uuid` 仍作为命名值返回，便于 Engine 把它加入替换集合（uuid 通常足够长）。

## 只读

插件对 Redis **只**调用 `GET`（以及客户端关闭）。连接握手的 `AUTH` / `SELECT` / `HELLO` 由 redis-py 发出，允许。
