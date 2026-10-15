"""Phase 3.3d / 4.0：cache_scope 拼接、旧 auth 七键兼容。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from testplat_control.api.schemas import ExecutionAuth, parse_execution_auth
from testplat_control.database.session import SessionLocal
from testplat_control.services.run_config import resolve_run_config


def test_legacy_resolve_passes_repo_project_env_as_cache_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有 Web 环境时，resolve_run_config 把 cache_scope 拼成 repo:project:env。"""
    captured: dict[str, object] = {}

    def fake_load_auth(config_root, env, *, environ=None, cache_scope=None):  # noqa: ANN001
        captured["config_root"] = str(config_root)
        captured["env"] = env
        captured["cache_scope"] = cache_scope
        return None

    def fake_environment(config_root, env):  # noqa: ANN001
        del config_root, env
        return {"api_hosts": {"local": "http://127.0.0.1:9"}}

    monkeypatch.setattr(
        "testplat_control.services.run_config.load_auth",
        fake_load_auth,
    )
    monkeypatch.setattr(
        "testplat_control.services.run_config.load_project_environment",
        fake_environment,
    )
    project = SimpleNamespace(id="cache-scope-only", repo="main", project_key="demo")
    with SessionLocal() as db:
        resolved = resolve_run_config(
            db,
            project,  # type: ignore[arg-type]
            "staging",
            Path("/tmp/cfg"),
            request_params={},
            request_timeout=None,
        )
    assert captured["cache_scope"] == "main:demo:staging"
    assert captured["env"] == "staging"
    assert captured["config_root"] == "/tmp/cfg"
    assert resolved.config_revision is None
    assert resolved.params == {}


def test_parse_old_seven_key_auth_defaults_new_fields() -> None:
    """旧七键记录缺 session_source / reauthenticated → null / false。"""
    auth = parse_execution_auth(
        {
            "auth": {
                "identity": "admin",
                "kind": "static_headers",
                "tier": None,
                "header_names": ["Authorization"],
                "overridden_headers": [],
                "cookie_names": [],
                "login_ref": None,
            }
        }
    )
    assert isinstance(auth, ExecutionAuth)
    assert auth.session_source is None
    assert auth.reauthenticated is False


def test_parse_nine_key_auth_cache_and_reauthenticated() -> None:
    """九键：cache 命中与重登重发均可解析。"""
    cache_auth = parse_execution_auth(
        {
            "auth": {
                "identity": "buyer",
                "kind": "login",
                "tier": "generic",
                "header_names": ["X-TOKEN"],
                "overridden_headers": [],
                "cookie_names": [],
                "login_ref": None,
                "session_source": "cache",
                "reauthenticated": False,
            }
        }
    )
    assert cache_auth is not None
    assert cache_auth.session_source == "cache"
    assert cache_auth.login_ref is None
    assert cache_auth.reauthenticated is False

    reauth = parse_execution_auth(
        {
            "auth": {
                "identity": "buyer",
                "kind": "login",
                "tier": "generic",
                "header_names": ["X-TOKEN"],
                "overridden_headers": [],
                "cookie_names": [],
                "login_ref": 0,
                "session_source": "login",
                "reauthenticated": True,
            }
        }
    )
    assert reauth is not None
    assert reauth.reauthenticated is True
    assert reauth.session_source == "login"
    assert reauth.login_ref == 0
