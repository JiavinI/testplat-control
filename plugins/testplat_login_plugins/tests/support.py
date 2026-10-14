"""插件包测试公共夹具：假目标、假 Redis、Engine 入口。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from testplat_engine import (
    AuthTable,
    LoginAuth,
    SecretStr,
    Validity,
    create_engine,
)
from testplat_engine.plugins.httpx_client import HttpxClient

from testplat_login_plugins.vcode_redis import VcodeRedisStrategy

FIXTURES = Path(__file__).parent / "fixtures"
HOST = "http://target.test"
ENV = {"api_hosts": {"daifa_admin": HOST, "target": HOST}}

# 明显假值，同时作为泄密搜索目标。
FAKE_PASSWORD = "tp-fake-df-admin-pass-9f3a"
FAKE_REDIS_PASSWORD = "tp-fake-redis-pass-5e0d"
FAKE_TOKEN = "tok-vcode-0001-a8f3e2c1d0"
FAKE_USER_ID = "10001"
# 短验证码：专门覆盖「短值不按值替换」路径。
CAPTCHA_4 = "4281"
CAPTCHA_6 = "739204"
FAKE_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
KEY_PREFIX = "gsb:vcode:prefix:"


@dataclass
class FakeRedisClient:
    """记录方法名的假 Redis；只实现 get / aclose。"""

    store: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    get_delay: float = 0.0
    get_error: BaseException | None = None

    async def get(self, key: str) -> str | None:
        self.calls.append("get")
        if self.get_error is not None:
            raise self.get_error
        if self.get_delay:
            import asyncio

            await asyncio.sleep(self.get_delay)
        return self.store.get(key)

    async def aclose(self) -> None:
        self.calls.append("aclose")


@dataclass
class FakeTarget:
    """假 createVCode / login / 业务回显；零网络。"""

    requests: list[httpx.Request] = field(default_factory=list)
    captcha: str = CAPTCHA_4
    uuid: str = FAKE_UUID
    token: str = FAKE_TOKEN
    user_id: str = FAKE_USER_ID
    create_status: int = 200
    login_status: int = 200
    omit_uuid: bool = False
    omit_token: bool = False
    issued: list[str] = field(default_factory=list)

    def secrets(self) -> tuple[str, ...]:
        return (
            FAKE_PASSWORD,
            FAKE_REDIS_PASSWORD,
            self.token,
            self.uuid,
            self.captcha,
            *self.issued,
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        _body = request.content.decode() if request.content else ""
        if path == "/createVCode":
            if self.create_status >= 400:
                return httpx.Response(self.create_status, json={"msg": "create failed"})
            data: dict[str, Any] = {}
            if not self.omit_uuid:
                data["uuid"] = self.uuid
            return httpx.Response(200, json={"code": 0, "data": data})
        if path == "/login":
            if self.login_status >= 400:
                return httpx.Response(self.login_status, json={"msg": "login failed"})
            data = {"userId": self.user_id}
            if not self.omit_token:
                data["token"] = self.token
                self.issued.append(self.token)
            return httpx.Response(200, json={"code": 0, "data": data})
        if path == "/echo/token":
            return httpx.Response(
                200,
                json={
                    "echo": {
                        "x_token": request.headers.get("X-TOKEN"),
                        "x_user_id": request.headers.get("X-USER-ID"),
                    }
                },
            )
        return httpx.Response(404, json={"path": path})

    def factory(self) -> HttpxClient:
        return HttpxClient(transport=httpx.MockTransport(self.handler))


def make_auth(
    *,
    captcha_in_redis: str | None = CAPTCHA_4,
    extra_params: dict[str, Any] | None = None,
    redis_store: dict[str, str] | None = None,
) -> tuple[AuthTable, FakeRedisClient]:
    params: dict[str, Any] = {
        "redis_connection": "redis_main",
        "redis_key_prefix": KEY_PREFIX,
        "create_vcode.path": "/createVCode",
        "create_vcode.method": "POST",
        "create_vcode.body_type": "json",
        "uuid_path": "$.data.uuid",
        "login.path": "/login",
        "login.method": "POST",
        "login.body_type": "form",
        "field.username": "admin_user",
        "field.password": SecretStr(FAKE_PASSWORD),
        "field.source": "daifa",
        "field.userType": "1",
        "code_field": "code",
        "user_key_field": "userKey",
        "extract.token": "$.data.token",
        "extract.user_id": "$.data.userId",
    }
    if extra_params:
        params.update(extra_params)

    store = dict(redis_store or {})
    if captcha_in_redis is not None:
        store[f"{KEY_PREFIX}{FAKE_UUID}"] = captcha_in_redis
    fake_redis = FakeRedisClient(store=store)

    material = LoginAuth(
        strategy="vcode_redis",
        host="daifa_admin",
        tier="plugin",
        params=params,
        secret_values=(SecretStr(FAKE_PASSWORD), SecretStr(FAKE_REDIS_PASSWORD)),
        validity=Validity(ttl_seconds=72000),
        inject_headers={
            "X-TOKEN": "${login:token}",
            "X-USER-ID": "${login:user_id}",
        },
    )
    auth = AuthTable(
        identities={"df_admin": material},
        default_identity=None,
        connections={
            "redis_main": {
                "host": "127.0.0.1",
                "port": 6379,
                "database": 0,
                "password": SecretStr(FAKE_REDIS_PASSWORD),
            }
        },
    )
    return auth, fake_redis


def strategy_for(fake_redis: FakeRedisClient) -> VcodeRedisStrategy:
    def factory(**_kwargs: Any) -> FakeRedisClient:
        return fake_redis

    return VcodeRedisStrategy(redis_client_factory=factory)


def engine_for(target: FakeTarget, fake_redis: FakeRedisClient):
    """公开入口 create_engine；测试 seam 注入 MockTransport（与 Engine 自测一致）。"""
    engine = create_engine(login_strategies=[strategy_for(fake_redis)])
    engine._client_factory = target.factory  # noqa: SLF001 — 测试 seam
    return engine


def dump(payload: Any) -> str:
    if hasattr(payload, "to_dict"):
        payload = payload.to_dict()
    return payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)


def assert_no_secrets(target: FakeTarget, *payloads: Any) -> None:
    for payload in payloads:
        text = dump(payload)
        for secret in target.secrets():
            assert secret not in text, f"泄漏秘密前缀 {secret[:6]}"


def assets_root() -> Path:
    """最小资产树：单 API 回显 inject 头。"""
    return FIXTURES
