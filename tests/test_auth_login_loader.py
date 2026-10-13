"""Phase 3.3b：auth_loader 登录身份、connections、login_plugins、档位判定。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from testplat_engine import (
    InvalidEnvironmentError,
    LoginAuth,
    SecretStr,
    StaticHeaderAuth,
    UnavailableAuth,
)

from testplat_control.services.auth_loader import load_auth, load_auth_table
from tests.auth_support import (
    FAKE_PARTNER,
    FAKE_SECRET,
    STANDARD_CONFIG,
    STANDARD_ENV,
    assert_no_secret,
    log_text,
    write_auth,
)

FAKE_PASSWORD = "tp-fake-buyer-pass-77"
LOGIN_ENV = {
    **STANDARD_ENV,
    "TESTPLAT_BUYER_PASSWORD": FAKE_PASSWORD,
    "TESTPLAT_REDIS_MAIN_PASSWORD": "tp-fake-redis-main-55",
}


def _generic_buyer() -> dict:
    return {
        "login": {
            "host": "main",
            "steps": [
                {
                    "name": "login",
                    "method": "POST",
                    "path": "/api/user/login",
                    "body": {
                        "type": "json",
                        "fields": {
                            "username": "buyer001",
                            "password": "${secret:TESTPLAT_BUYER_PASSWORD}",
                        },
                    },
                    "success": {"path": "$.code", "value": 0},
                    "extract": [{"source": "body_json", "path": "$.data.token", "as": "token"}],
                }
            ],
            "inject": {"headers": {"X-TOKEN": "${login:token}"}},
        }
    }


def _configured_cookie() -> dict:
    return {
        "login": {
            "host": "admin",
            "steps": [
                {
                    "name": "bootstrap",
                    "method": "GET",
                    "path": "/login",
                    "extract": [{"source": "html_meta", "name": "csrf-token", "as": "csrf"}],
                },
                {
                    "name": "submit",
                    "method": "POST",
                    "path": "/login",
                    "headers": {"Referer": "${login_host}/login"},
                    "body": {
                        "type": "form",
                        "fields": {
                            "_csrf": "${login:csrf}",
                            "username": "seller001",
                            "password": "${secret:TESTPLAT_BUYER_PASSWORD}",
                        },
                    },
                    "success": {"status_code": 302},
                },
            ],
            "session": "cookie",
            "probe": {
                "method": "GET",
                "path": "/nx/withdrawView",
                "success": {"status_code": 200},
            },
            "inject": {
                "headers": {
                    "X-CSRF-Token": "${login:csrf}",
                    "X-SOURCE": "web",
                }
            },
        }
    }


def test_standard_static_still_works_and_connections_always_present(tmp_path: Path) -> None:
    """U3：无 connections 时仍传空映射；静态 header 回归。"""
    write_auth(tmp_path, STANDARD_CONFIG)
    result = load_auth(tmp_path, "test", environ=STANDARD_ENV)
    assert result is not None
    assert result.login_plugins == ()
    assert dict(result.table.connections) == {}
    assert isinstance(result.table.identities["admin"], StaticHeaderAuth)


def test_generic_tier_single_step_token(tmp_path: Path) -> None:
    write_auth(
        tmp_path,
        {"identities": {"buyer": _generic_buyer()}, "default_identity": "buyer"},
    )
    result = load_auth(tmp_path, "test", environ=LOGIN_ENV)
    assert result is not None
    buyer = result.table.identities["buyer"]
    assert isinstance(buyer, LoginAuth)
    assert buyer.tier == "generic"
    assert buyer.strategy == "generic_flow"
    assert list(buyer.header_names) == ["X-TOKEN"]
    assert_no_secret([repr(buyer), str(buyer.to_dict()), repr(result.table)])


def test_configured_tier_with_cookie_and_literal_inject(tmp_path: Path) -> None:
    """Q1：字面量 inject 头允许；多步 + session + probe → configured。"""
    write_auth(tmp_path, {"identities": {"seller": _configured_cookie()}})
    result = load_auth(tmp_path, "test", environ=LOGIN_ENV)
    seller = result.table.identities["seller"]
    assert isinstance(seller, LoginAuth)
    assert seller.tier == "configured"
    assert seller.session_cookie is True
    assert "X-SOURCE" in seller.header_names
    assert_no_secret([repr(seller), repr(result.table)])


def test_session_cookie_may_omit_inject(tmp_path: Path) -> None:
    """Q2：session: cookie 时可省略 inject。"""
    cfg = _configured_cookie()
    del cfg["login"]["inject"]
    # 去掉 probe/多步以外仍保持 configured；此处只测省略 inject
    write_auth(tmp_path, {"identities": {"sess": cfg}})
    result = load_auth(tmp_path, "test", environ=LOGIN_ENV)
    material = result.table.identities["sess"]
    assert isinstance(material, LoginAuth)
    assert material.session_cookie is True
    assert list(material.header_names) == []


def test_plugin_tier_requires_whitelist(tmp_path: Path) -> None:
    write_auth(
        tmp_path,
        {
            "identities": {
                "df": {
                    "login": {
                        "strategy": "vcode_redis",
                        "host": "daifa_admin",
                        "params": {"username": "admin01"},
                        "inject": {"headers": {"X-TOKEN": "${login:token}"}},
                    }
                }
            },
            "login_plugins": ["vcode_redis"],
        },
    )
    result = load_auth(tmp_path, "test", environ=LOGIN_ENV)
    assert result.login_plugins == ("vcode_redis",)
    material = result.table.identities["df"]
    assert isinstance(material, LoginAuth)
    assert material.tier == "plugin"
    assert material.flow is None


def test_plugin_strategy_not_in_whitelist_is_schema_error(tmp_path: Path) -> None:
    write_auth(
        tmp_path,
        {
            "identities": {
                "df": {
                    "login": {
                        "strategy": "vcode_redis",
                        "host": "main",
                        "inject": {"headers": {"X-TOKEN": "${login:token}"}},
                    }
                }
            }
        },
    )
    with pytest.raises(InvalidEnvironmentError, match="login_plugins"):
        load_auth(tmp_path, "test", environ=LOGIN_ENV)


def test_headers_and_login_are_mutually_exclusive(tmp_path: Path) -> None:
    write_auth(
        tmp_path,
        {
            "identities": {
                "bad": {
                    "headers": {"Authorization": "Bearer ${secret:TESTPLAT_ADMIN_TOKEN}"},
                    "login": {
                        "host": "main",
                        "steps": [
                            {
                                "name": "login",
                                "method": "POST",
                                "path": "/x",
                                "extract": [{"source": "body_json", "path": "$.t", "as": "token"}],
                            }
                        ],
                        "inject": {"headers": {"X-TOKEN": "${login:token}"}},
                    },
                }
            }
        },
    )
    with pytest.raises(InvalidEnvironmentError, match="必须且只能是"):
        load_auth(tmp_path, "test", environ=LOGIN_ENV)


def test_inject_without_login_ref_and_without_session_rejected(tmp_path: Path) -> None:
    """Q1：身份级约束——无 ${login:} 且无 session: cookie → 422。"""
    write_auth(
        tmp_path,
        {
            "identities": {
                "bad": {
                    "login": {
                        "host": "main",
                        "steps": [
                            {
                                "name": "login",
                                "method": "POST",
                                "path": "/x",
                                "extract": [{"source": "body_json", "path": "$.t", "as": "token"}],
                            }
                        ],
                        "inject": {"headers": {"X-SOURCE": "web"}},
                    }
                }
            }
        },
    )
    with pytest.raises(InvalidEnvironmentError, match=r"\$\{login:\}"):
        load_auth(tmp_path, "test", environ=LOGIN_ENV)


def test_inject_ref_must_be_extracted(tmp_path: Path) -> None:
    write_auth(
        tmp_path,
        {
            "identities": {
                "bad": {
                    "login": {
                        "host": "main",
                        "steps": [
                            {
                                "name": "login",
                                "method": "POST",
                                "path": "/x",
                                "extract": [{"source": "body_json", "path": "$.t", "as": "token"}],
                            }
                        ],
                        "inject": {"headers": {"X-USER": "${login:user_id}"}},
                    }
                }
            }
        },
    )
    with pytest.raises(InvalidEnvironmentError, match="未提取的命名值"):
        load_auth(tmp_path, "test", environ=LOGIN_ENV)


def test_login_password_missing_becomes_unavailable(tmp_path: Path) -> None:
    write_auth(tmp_path, {"identities": {"buyer": _generic_buyer()}})
    table = load_auth_table(tmp_path, "test", environ={})
    assert isinstance(table.identities["buyer"], UnavailableAuth)
    assert "TESTPLAT_BUYER_PASSWORD" in table.identities["buyer"].public_reason
    assert FAKE_PASSWORD not in table.identities["buyer"].public_reason


def test_connections_password_rendered_and_never_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write_auth(
        tmp_path,
        {
            "identities": STANDARD_CONFIG["identities"],
            "default_identity": "admin",
            "connections": {
                "redis_main": {
                    "host": "10.0.0.5",
                    "port": 6379,
                    "password": "${secret:TESTPLAT_REDIS_MAIN_PASSWORD}",
                }
            },
        },
    )
    with caplog.at_level(logging.DEBUG, logger="testplat_control"):
        result = load_auth(tmp_path, "test", environ=LOGIN_ENV)
    assert result is not None
    conn = result.table.connections["redis_main"]
    assert conn["host"] == "10.0.0.5"
    assert isinstance(conn["password"], SecretStr)
    public = repr(result.table) + str(result.table.to_dict())
    assert "connection_names" in str(result.table.to_dict())
    assert_no_secret(
        [public, *log_text(caplog.records)],
        secrets=(
            FAKE_SECRET,
            FAKE_PARTNER,
            FAKE_PASSWORD,
            LOGIN_ENV["TESTPLAT_REDIS_MAIN_PASSWORD"],
        ),
    )


def test_connections_secret_missing_is_invalid_environment(tmp_path: Path) -> None:
    write_auth(
        tmp_path,
        {
            "identities": STANDARD_CONFIG["identities"],
            "connections": {"redis_main": {"password": "${secret:TESTPLAT_REDIS_MAIN_PASSWORD}"}},
        },
    )
    with pytest.raises(InvalidEnvironmentError, match="连接秘密不可用"):
        load_auth(tmp_path, "test", environ=STANDARD_ENV)


def test_unknown_root_and_login_fields_still_422(tmp_path: Path) -> None:
    write_auth(tmp_path, {**STANDARD_CONFIG, "extra": 1})
    with pytest.raises(InvalidEnvironmentError, match="未知字段"):
        load_auth(tmp_path, "test", environ=STANDARD_ENV)
    write_auth(
        tmp_path,
        {
            "identities": {
                "buyer": {
                    "login": {
                        "host": "main",
                        "weird": 1,
                        "steps": [
                            {
                                "name": "login",
                                "method": "POST",
                                "path": "/x",
                                "extract": [{"source": "body_json", "path": "$.t", "as": "token"}],
                            }
                        ],
                        "inject": {"headers": {"X-TOKEN": "${login:token}"}},
                    }
                }
            }
        },
    )
    with pytest.raises(InvalidEnvironmentError, match="未知字段"):
        load_auth(tmp_path, "test", environ=LOGIN_ENV)


def test_other_placeholder_in_login_rejected(tmp_path: Path) -> None:
    cfg = _generic_buyer()
    cfg["login"]["inject"]["headers"]["X-TOKEN"] = "${login:token}${env:HOME}"
    write_auth(tmp_path, {"identities": {"buyer": cfg}})
    with pytest.raises(InvalidEnvironmentError, match="只允许"):
        load_auth(tmp_path, "test", environ=LOGIN_ENV)
