"""成功路径：经 create_engine 跑单 API，断言 inject、三步记录与脱敏。"""

from __future__ import annotations

import logging

import pytest
from testplat_engine import ApiExecutionRequest

from support import (
    CAPTCHA_4,
    CAPTCHA_6,
    ENV,
    FAKE_TOKEN,
    FAKE_USER_ID,
    FAKE_UUID,
    KEY_PREFIX,
    FakeTarget,
    assert_no_secrets,
    assets_root,
    engine_for,
    make_auth,
)


def _api(auth) -> ApiExecutionRequest:
    return ApiExecutionRequest(
        api_id="api.vcode.echo",
        assets_root=assets_root(),
        environment=ENV,
        params={},
        auth=auth,
    )


@pytest.mark.parametrize("captcha", [CAPTCHA_4, CAPTCHA_6])
async def test_success_inject_three_steps_and_redact(captcha: str, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    target = FakeTarget(captcha=captcha)
    auth, fake_redis = make_auth(captcha_in_redis=captcha)
    # 目标与 Redis 使用同一 captcha / uuid
    target.captcha = captcha
    outcome = await engine_for(target, fake_redis).execute(_api(auth))
    d = outcome.to_dict()
    assert d["status"] == "success"
    business = target.requests[-1]
    assert business.headers["X-TOKEN"] == FAKE_TOKEN
    assert business.headers["X-USER-ID"] == FAKE_USER_ID
    assert d["response"]["body"]["echo"]["x_token"] == "***"
    assert d["auth"]["identity"] == "df_admin"
    assert d["auth"]["login_ref"] == 0

    [record] = d["logins"]
    assert record["strategy"] == "vcode_redis"
    assert record["status"] == "success"
    names = [s["name"] for s in record["steps"]]
    assert names == ["create_vcode", "redis_get", "login"]

    create_step, redis_step, login_step = record["steps"]
    assert create_step["response"]["body"]["data"]["uuid"] == "***"
    assert redis_step["request"] == {
        "connection": "redis_main",
        "key_prefix": KEY_PREFIX,
        "found": True,
    }
    assert redis_step["response"] is None
    login_body = login_step["request"]["body"]
    assert login_body["code"] == "***"
    assert login_body["userKey"] == "***"
    assert login_body["password"] == "***"
    assert login_step["response"]["body"]["data"]["token"] == "***"

    assert fake_redis.calls == ["get", "aclose"]
    assert_no_secrets(target, d, caplog.text)
    # 短验证码本身也不出现
    assert captcha not in str(d)
    assert FAKE_UUID not in str(d)
