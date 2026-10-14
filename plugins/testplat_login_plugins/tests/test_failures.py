"""失败映射：设计稿 §6 第 25 条 + 预算超时。"""

from __future__ import annotations

import logging

import redis.exceptions as redis_exc
from testplat_engine import ApiExecutionRequest

from support import (
    ENV,
    FakeTarget,
    assert_no_secrets,
    assets_root,
    engine_for,
    make_auth,
)


def _api(auth, *, timeout_seconds: float | None = None) -> ApiExecutionRequest:
    kwargs = {
        "api_id": "api.vcode.echo",
        "assets_root": assets_root(),
        "environment": ENV,
        "params": {},
        "auth": auth,
    }
    if timeout_seconds is not None:
        kwargs["timeout_seconds"] = timeout_seconds
    return ApiExecutionRequest(**kwargs)


async def _run(target, auth, fake_redis, **api_kwargs):
    return (await engine_for(target, fake_redis).execute(_api(auth, **api_kwargs))).to_dict()


async def test_redis_unreachable_is_transport(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    target = FakeTarget()
    auth, fake_redis = make_auth()
    fake_redis.get_error = redis_exc.ConnectionError("boom")
    d = await _run(target, auth, fake_redis)
    assert d["status"] == "failed"
    assert d["error"]["kind"] == "login_failed"
    assert d["error"]["login"]["reason"] == "transport"
    assert "ConnectionError" in caplog.text
    assert_no_secrets(target, d, caplog.text)


async def test_redis_timeout_is_timeout(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    target = FakeTarget()
    auth, fake_redis = make_auth()
    fake_redis.get_error = redis_exc.TimeoutError("slow")
    d = await _run(target, auth, fake_redis)
    assert d["error"]["login"]["reason"] == "timeout"
    assert "TimeoutError" in caplog.text
    assert_no_secrets(target, d, caplog.text)


async def test_redis_auth_error_is_transport(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    target = FakeTarget()
    auth, fake_redis = make_auth()
    fake_redis.get_error = redis_exc.AuthenticationError("nope")
    d = await _run(target, auth, fake_redis)
    assert d["error"]["login"]["reason"] == "transport"
    assert "ConnectionError" in caplog.text
    assert_no_secrets(target, d, caplog.text)


async def test_code_missing_is_strategy_error(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    target = FakeTarget()
    auth, fake_redis = make_auth(captcha_in_redis=None, redis_store={})
    d = await _run(target, auth, fake_redis)
    assert d["error"]["login"]["reason"] == "strategy_error"
    assert "VcodeCodeMissing" in caplog.text
    assert_no_secrets(target, d, caplog.text)


async def test_create_vcode_failed(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    target = FakeTarget(create_status=500)
    auth, fake_redis = make_auth()
    d = await _run(target, auth, fake_redis)
    assert d["error"]["login"]["reason"] == "strategy_error"
    assert "VcodeCreateFailed" in caplog.text
    assert_no_secrets(target, d, caplog.text)


async def test_login_failed(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    target = FakeTarget(login_status=401)
    auth, fake_redis = make_auth()
    d = await _run(target, auth, fake_redis)
    assert d["error"]["login"]["reason"] == "strategy_error"
    assert "VcodeLoginFailed" in caplog.text
    assert_no_secrets(target, d, caplog.text)


async def test_token_missing(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    target = FakeTarget(omit_token=True)
    auth, fake_redis = make_auth()
    d = await _run(target, auth, fake_redis)
    assert d["error"]["login"]["reason"] == "strategy_error"
    assert "VcodeTokenMissing" in caplog.text
    assert_no_secrets(target, d, caplog.text)


async def test_budget_timeout(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    target = FakeTarget()
    auth, fake_redis = make_auth()
    # 预算极小：插件在第一步前或剩余检查时抛 TimeoutError
    d = await _run(target, auth, fake_redis, timeout_seconds=0.05)
    assert d["error"]["login"]["reason"] == "timeout"
    assert_no_secrets(target, d, caplog.text)


async def test_uuid_missing(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    target = FakeTarget(omit_uuid=True)
    auth, fake_redis = make_auth()
    d = await _run(target, auth, fake_redis)
    assert d["error"]["login"]["reason"] == "strategy_error"
    assert "VcodeUuidMissing" in caplog.text
    assert_no_secrets(target, d, caplog.text)
