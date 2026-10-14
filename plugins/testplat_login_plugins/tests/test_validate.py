"""validate()：缺必填、未知键、非法 body_type；消息不含参数值。"""

from __future__ import annotations

import pytest
from testplat_engine import LoginAuth, SecretStr

from support import FAKE_PASSWORD, KEY_PREFIX
from testplat_login_plugins.vcode_redis import VcodeRedisStrategy


def _auth(params: dict) -> LoginAuth:
    return LoginAuth(
        strategy="vcode_redis",
        host="daifa_admin",
        tier="plugin",
        params=params,
        secret_values=(SecretStr(FAKE_PASSWORD),),
        inject_headers={"X-TOKEN": "${login:token}"},
    )


BASE = {
    "redis_connection": "redis_main",
    "redis_key_prefix": KEY_PREFIX,
    "create_vcode.path": "/createVCode",
    "login.path": "/login",
    "extract.token": "$.data.token",
    "field.password": SecretStr(FAKE_PASSWORD),
}


def test_validate_ok() -> None:
    VcodeRedisStrategy().validate(_auth(BASE))


def test_validate_missing_required() -> None:
    params = dict(BASE)
    del params["redis_connection"]
    with pytest.raises(ValueError, match="redis_connection") as exc:
        VcodeRedisStrategy().validate(_auth(params))
    assert KEY_PREFIX not in str(exc.value)
    assert FAKE_PASSWORD not in str(exc.value)


def test_validate_unknown_key() -> None:
    params = dict(BASE)
    params["weird_secret_value"] = "should-not-appear-in-message"
    with pytest.raises(ValueError, match="weird_secret_value") as exc:
        VcodeRedisStrategy().validate(_auth(params))
    assert "should-not-appear-in-message" not in str(exc.value)


def test_validate_bad_create_body_type() -> None:
    params = dict(BASE)
    params["create_vcode.body_type"] = "multipart"
    with pytest.raises(ValueError, match="create_vcode.body_type") as exc:
        VcodeRedisStrategy().validate(_auth(params))
    assert "multipart" not in str(exc.value)


def test_validate_bad_login_body_type() -> None:
    params = dict(BASE)
    params["login.body_type"] = "query"
    with pytest.raises(ValueError, match="login.body_type") as exc:
        VcodeRedisStrategy().validate(_auth(params))
    assert "query" not in str(exc.value)
