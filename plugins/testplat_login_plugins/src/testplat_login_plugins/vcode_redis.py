"""vcode_redis：createVCode → Redis GET 验证码 → 表单/JSON 登录。

遵守设计稿 §2 / §4.2 / §4.3：
- 参数扁平点号键；剩余预算拆到每一步 HTTP / Redis 超时；
- redis-py 异常转内置 ``ConnectionError`` / ``TimeoutError`` 且 ``from None``；
- 记录里验证码 / uuid / 密码写 ``***``；Redis 一步只记连接名、前缀、found；
- 只用 ``testplat_engine`` 顶层公开导出，不导入 Engine 内部模块。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urljoin

from testplat_engine import LoginAuth, LoginContext, LoginResult, SecretStr

from testplat_login_plugins._exceptions import (
    VcodeCodeMissing,
    VcodeConnectionMissing,
    VcodeCreateFailed,
    VcodeLoginFailed,
    VcodeTokenMissing,
    VcodeUuidMissing,
)
from testplat_login_plugins._secrets import reveal_value

logger = logging.getLogger(__name__)

# 剩余预算低于此值则直接抛超时，避免发出无意义的短超时请求。
_MIN_BUDGET_SECONDS = 0.1

_REQUIRED_KEYS = (
    "redis_connection",
    "redis_key_prefix",
    "create_vcode.path",
    "login.path",
    "extract.token",
)

_KNOWN_KEYS = frozenset(
    {
        "redis_connection",
        "redis_key_prefix",
        "create_vcode.path",
        "create_vcode.method",
        "create_vcode.body_type",
        "uuid_path",
        "login.path",
        "login.method",
        "login.body_type",
        "code_field",
        "user_key_field",
    }
)

_CREATE_BODY_TYPES = frozenset({"json", "form", "query"})
_LOGIN_BODY_TYPES = frozenset({"json", "form"})

RedisClientFactory = Callable[..., Any]


def _param_text(params: Mapping[str, object], key: str, default: str | None = None) -> str | None:
    if key not in params:
        return default
    return reveal_value(params[key])


def _require_param(params: Mapping[str, object], key: str) -> str:
    raw = _param_text(params, key)
    if raw is None or raw == "":
        raise ValueError(f"缺少必填参数 {key}")
    return raw


def _json_path(body: object, path: str) -> object | None:
    """简化 JSONPath：只支持 ``$.a.b.c`` 点分路径。"""
    if not path.startswith("$."):
        return None
    cur: object = body
    for part in path[2:].split("."):
        if not part or not isinstance(cur, Mapping) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _as_int(value: object, *, field: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"连接字段 {field} 必须是整数")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ValueError(f"连接字段 {field} 必须是整数")


def _mask_mapping(data: Mapping[str, object], secret_keys: set[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, item in data.items():
        name = str(key)
        if name in secret_keys:
            out[name] = "***"
        elif isinstance(item, Mapping):
            out[name] = _mask_mapping(item, secret_keys)
        else:
            out[name] = item
    return out


def _mask_body_tree(body: object, secret_values: set[str]) -> object:
    """按值遮蔽短验证码 / uuid（Engine 按值替换对 < 8 位无效，插件必须自己做）。"""
    if isinstance(body, str):
        return "***" if body in secret_values else body
    if isinstance(body, list):
        return [_mask_body_tree(item, secret_values) for item in body]
    if isinstance(body, Mapping):
        return {str(k): _mask_body_tree(v, secret_values) for k, v in body.items()}
    return body


def _public_headers(headers: Mapping[str, object] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (headers or {}).items():
        name = str(key)
        lowered = name.lower()
        if lowered in {"authorization", "cookie", "set-cookie", "x-token", "x-api-key"}:
            out[name] = "***"
        else:
            out[name] = str(value)
    return out


def _http_record(
    *,
    method: str,
    url: str,
    headers: Mapping[str, object] | None,
    body_type: str,
    body: object,
    secret_keys: set[str],
    secret_values: set[str],
) -> dict[str, object]:
    if body_type == "query" and isinstance(body, Mapping):
        query = _mask_mapping(body, secret_keys)
        query = {k: ("***" if str(v) in secret_values else v) for k, v in query.items()}
        return {
            "method": method,
            "url": url,
            "headers": _public_headers(headers),
            "body_type": body_type,
            "body": None,
            "query": query,
        }
    recorded_body: object
    if isinstance(body, Mapping):
        recorded_body = _mask_mapping(body, secret_keys)
        recorded_body = _mask_body_tree(recorded_body, secret_values)
    else:
        recorded_body = _mask_body_tree(body, secret_values)
    return {
        "method": method,
        "url": url,
        "headers": _public_headers(headers),
        "body_type": body_type,
        "body": recorded_body,
    }


def _response_record(response: object, secret_values: set[str]) -> dict[str, object]:
    status = getattr(response, "status_code", None)
    headers = getattr(response, "headers", {}) or {}
    body = getattr(response, "body", None)
    return {
        "status_code": status,
        "headers": _public_headers(headers if isinstance(headers, Mapping) else {}),
        "body": _mask_body_tree(body, secret_values),
    }


def _map_redis_exc(exc: BaseException) -> None:
    """把 redis-py 异常转成内置超时/连接错误；不带原消息（``from None``）。"""
    try:
        import redis.exceptions as redis_exc
    except ImportError:
        raise exc  # noqa: B904 — 无 redis 时原样抛出，由 validate 前置拦截
    if isinstance(exc, redis_exc.TimeoutError):
        raise TimeoutError("redis") from None
    if isinstance(exc, (redis_exc.ConnectionError, redis_exc.AuthenticationError)):
        raise ConnectionError("redis") from None
    raise exc


class VcodeRedisStrategy:
    """验证码 Redis 登录策略（entry point 名 ``vcode_redis``）。"""

    name = "vcode_redis"

    def __init__(self, *, redis_client_factory: RedisClientFactory | None = None) -> None:
        # 可注入：测试传 fake 客户端工厂；生产默认 ``redis.asyncio.Redis``。
        self._redis_client_factory = redis_client_factory

    def validate(self, auth: LoginAuth) -> None:
        """预检：不连 Redis、不发请求；消息只含参数键名。"""
        try:
            import redis  # noqa: F401
        except ImportError as exc:
            raise ValueError("需安装 testplat-login-plugins[redis]") from exc

        params = auth.params or {}
        for key in params:
            if key in _KNOWN_KEYS or key.startswith("field.") or key.startswith("extract."):
                continue
            raise ValueError(f"未知参数键 {key}")

        for key in _REQUIRED_KEYS:
            if key not in params:
                raise ValueError(f"缺少必填参数 {key}")
            text = reveal_value(params[key])
            if text == "":
                raise ValueError(f"缺少必填参数 {key}")

        create_body_type = _param_text(params, "create_vcode.body_type", "json") or "json"
        if create_body_type not in _CREATE_BODY_TYPES:
            raise ValueError("参数 create_vcode.body_type 必须是 json/form/query")

        login_body_type = _param_text(params, "login.body_type", "form") or "form"
        if login_body_type not in _LOGIN_BODY_TYPES:
            raise ValueError("参数 login.body_type 必须是 json/form")

        if not any(k.startswith("extract.") for k in params):
            raise ValueError("缺少必填参数 extract.token")

    async def login(self, ctx: LoginContext) -> LoginResult:
        started = time.monotonic()
        params = ctx.params

        def remaining() -> float:
            left = ctx.timeout_seconds - (time.monotonic() - started)
            if left < _MIN_BUDGET_SECONDS:
                raise TimeoutError("login budget")
            return left

        redis_connection = _require_param(params, "redis_connection")
        redis_key_prefix = _require_param(params, "redis_key_prefix")
        create_path = _require_param(params, "create_vcode.path")
        create_method = (_param_text(params, "create_vcode.method", "POST") or "POST").upper()
        create_body_type = _param_text(params, "create_vcode.body_type", "json") or "json"
        uuid_path = _param_text(params, "uuid_path", "$.data.uuid") or "$.data.uuid"
        login_path = _require_param(params, "login.path")
        login_method = (_param_text(params, "login.method", "POST") or "POST").upper()
        login_body_type = _param_text(params, "login.body_type", "form") or "form"
        code_field = _param_text(params, "code_field", "code") or "code"
        user_key_field = _param_text(params, "user_key_field", "userKey") or "userKey"

        field_values: dict[str, str] = {}
        password_keys: set[str] = set()
        for key, raw in params.items():
            if not key.startswith("field."):
                continue
            name = key[len("field.") :]
            if not name:
                continue
            field_values[name] = reveal_value(raw)
            if name.lower() == "password" or isinstance(raw, SecretStr):
                password_keys.add(name)

        extract_paths: dict[str, str] = {}
        for key, raw in params.items():
            if key.startswith("extract."):
                name = key[len("extract.") :]
                if name:
                    extract_paths[name] = reveal_value(raw)

        if "token" not in extract_paths:
            raise VcodeTokenMissing("extract.token")

        # ---- 1) createVCode ----
        create_url = urljoin(ctx.host_url.rstrip("/") + "/", create_path.lstrip("/"))
        # 与旧语义一致：默认空对象；不支持 create_vcode 自定义 body 字段（本批扁平参数未提供）。
        create_body: dict[str, object] = {}
        create_kwargs: dict[str, object] = {}
        if create_body_type == "json":
            create_kwargs["json"] = create_body
        elif create_body_type == "form":
            create_kwargs["data"] = create_body
        else:
            create_kwargs["params"] = create_body

        budget = remaining()
        try:
            create_resp = await ctx.http.request(  # type: ignore[attr-defined]
                create_method,
                create_url,
                timeout=budget,
                follow_redirects=False,
                **create_kwargs,
            )
        except Exception:
            logger.warning(
                "vcode_redis step=create_vcode identity=%s status=transport_or_timeout",
                ctx.identity,
            )
            raise

        # uuid 尚未知：先用空集合记请求；取到后再按值遮蔽响应里的 uuid。
        pending_secrets: set[str] = set()
        if create_resp.status_code >= 400:
            ctx.record(
                _http_record(
                    method=create_method,
                    url=create_url,
                    headers=None,
                    body_type=create_body_type,
                    body=create_body,
                    secret_keys=set(),
                    secret_values=pending_secrets,
                ),
                _response_record(create_resp, pending_secrets),
                name="create_vcode",
            )
            logger.warning(
                "vcode_redis step=create_vcode identity=%s exc_type=VcodeCreateFailed",
                ctx.identity,
            )
            raise VcodeCreateFailed("create_vcode")

        uuid_raw = _json_path(create_resp.body, uuid_path)
        if uuid_raw is None or str(uuid_raw) == "":
            ctx.record(
                _http_record(
                    method=create_method,
                    url=create_url,
                    headers=None,
                    body_type=create_body_type,
                    body=create_body,
                    secret_keys=set(),
                    secret_values=pending_secrets,
                ),
                _response_record(create_resp, pending_secrets),
                name="create_vcode",
            )
            logger.warning(
                "vcode_redis step=create_vcode identity=%s exc_type=VcodeUuidMissing",
                ctx.identity,
            )
            raise VcodeUuidMissing("uuid")

        uuid_value = str(uuid_raw)
        pending_secrets.add(uuid_value)
        ctx.record(
            _http_record(
                method=create_method,
                url=create_url,
                headers=None,
                body_type=create_body_type,
                body=create_body,
                secret_keys=set(),
                secret_values=pending_secrets,
            ),
            _response_record(create_resp, pending_secrets),
            name="create_vcode",
        )

        # ---- 2) Redis GET ----
        conn = ctx.connections.get(redis_connection)
        if conn is None:
            logger.warning(
                "vcode_redis step=redis_get identity=%s exc_type=VcodeConnectionMissing",
                ctx.identity,
            )
            raise VcodeConnectionMissing("redis_connection")

        client = None
        captcha: str | None = None
        found = False
        try:
            client = self._build_redis_client(conn, timeout=remaining())
            try:
                raw_code = await client.get(f"{redis_key_prefix}{uuid_value}")
            except Exception as exc:
                _map_redis_exc(exc)
                raise  # pragma: no cover — _map_redis_exc 要么转换要么再抛
            if raw_code is not None:
                if isinstance(raw_code, bytes):
                    captcha = raw_code.decode("utf-8", errors="replace")
                else:
                    captcha = str(raw_code)
                found = bool(captcha)
        finally:
            ctx.record(
                {
                    "connection": redis_connection,
                    "key_prefix": redis_key_prefix,
                    "found": found,
                },
                None,
                name="redis_get",
            )
            if client is not None:
                await self._close_redis(client)

        if not captcha:
            logger.warning(
                "vcode_redis step=redis_get identity=%s exc_type=VcodeCodeMissing",
                ctx.identity,
            )
            raise VcodeCodeMissing("code")

        pending_secrets.add(captcha)

        # ---- 3) login ----
        login_url = urljoin(ctx.host_url.rstrip("/") + "/", login_path.lstrip("/"))
        login_body: dict[str, str] = dict(field_values)
        login_body[code_field] = captcha
        login_body[user_key_field] = uuid_value
        secret_keys = set(password_keys) | {code_field, user_key_field}
        # 密码明文也加入按值遮蔽，防止回显到非敏感键。
        for name in password_keys:
            pending_secrets.add(login_body[name])

        login_kwargs: dict[str, object] = {}
        if login_body_type == "json":
            login_kwargs["json"] = login_body
        else:
            login_kwargs["data"] = login_body

        budget = remaining()
        try:
            login_resp = await ctx.http.request(  # type: ignore[attr-defined]
                login_method,
                login_url,
                timeout=budget,
                follow_redirects=False,
                **login_kwargs,
            )
        except Exception:
            ctx.record(
                _http_record(
                    method=login_method,
                    url=login_url,
                    headers=None,
                    body_type=login_body_type,
                    body=login_body,
                    secret_keys=secret_keys,
                    secret_values=pending_secrets,
                ),
                None,
                name="login",
            )
            raise

        # token 先提取再记记录，以便按值遮蔽响应里的 token。
        values: dict[str, str] = {"vcode_uuid": uuid_value}
        for name, path in extract_paths.items():
            extracted = _json_path(login_resp.body, path)
            if extracted is None or str(extracted) == "":
                if name == "token":
                    ctx.record(
                        _http_record(
                            method=login_method,
                            url=login_url,
                            headers=None,
                            body_type=login_body_type,
                            body=login_body,
                            secret_keys=secret_keys,
                            secret_values=pending_secrets,
                        ),
                        _response_record(login_resp, pending_secrets),
                        name="login",
                    )
                    if login_resp.status_code >= 400:
                        logger.warning(
                            "vcode_redis step=login identity=%s exc_type=VcodeLoginFailed",
                            ctx.identity,
                        )
                        raise VcodeLoginFailed("login")
                    logger.warning(
                        "vcode_redis step=login identity=%s exc_type=VcodeTokenMissing",
                        ctx.identity,
                    )
                    raise VcodeTokenMissing("token")
                continue
            text = str(extracted)
            values[name] = text
            pending_secrets.add(text)

        if login_resp.status_code >= 400:
            ctx.record(
                _http_record(
                    method=login_method,
                    url=login_url,
                    headers=None,
                    body_type=login_body_type,
                    body=login_body,
                    secret_keys=secret_keys,
                    secret_values=pending_secrets,
                ),
                _response_record(login_resp, pending_secrets),
                name="login",
            )
            logger.warning(
                "vcode_redis step=login identity=%s exc_type=VcodeLoginFailed",
                ctx.identity,
            )
            raise VcodeLoginFailed("login")

        if "token" not in values:
            ctx.record(
                _http_record(
                    method=login_method,
                    url=login_url,
                    headers=None,
                    body_type=login_body_type,
                    body=login_body,
                    secret_keys=secret_keys,
                    secret_values=pending_secrets,
                ),
                _response_record(login_resp, pending_secrets),
                name="login",
            )
            logger.warning(
                "vcode_redis step=login identity=%s exc_type=VcodeTokenMissing",
                ctx.identity,
            )
            raise VcodeTokenMissing("token")

        ctx.record(
            _http_record(
                method=login_method,
                url=login_url,
                headers=None,
                body_type=login_body_type,
                body=login_body,
                secret_keys=secret_keys,
                secret_values=pending_secrets,
            ),
            _response_record(login_resp, pending_secrets),
            name="login",
        )
        return LoginResult(values=values, expires_at=None)

    def _build_redis_client(self, conn: Mapping[str, object], *, timeout: float) -> Any:
        host = reveal_value(conn.get("host", "127.0.0.1")) or "127.0.0.1"
        port = _as_int(conn.get("port"), field="port", default=6379)
        database = _as_int(conn.get("database", conn.get("db")), field="database", default=0)
        password_raw = conn.get("password")
        password = reveal_value(password_raw) if password_raw is not None else None
        if password == "":
            password = None

        kwargs: dict[str, object] = {
            "host": host,
            "port": port,
            "db": database,
            "password": password,
            "socket_timeout": timeout,
            "socket_connect_timeout": timeout,
            "decode_responses": True,
        }
        factory = self._redis_client_factory
        if factory is None:
            import redis.asyncio as redis_async
            from redis.asyncio.retry import Retry
            from redis.backoff import NoBackoff

            # 默认重试会把「连接拒绝」拖成数秒，短 timeout_seconds 下被整体误判为 timeout。
            # 重试次数为 0：不可达应快速变为 ConnectionError → transport。
            kwargs["retry"] = Retry(NoBackoff(), 0)
            factory = redis_async.Redis
        return factory(**kwargs)

    @staticmethod
    async def _close_redis(client: Any) -> None:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close is None:
            return
        result = close()
        if hasattr(result, "__await__"):
            await result
