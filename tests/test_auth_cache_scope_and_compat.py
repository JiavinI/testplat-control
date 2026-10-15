"""Phase 3.3d / 4.0：cache_scope 拼接、旧 auth 七键兼容。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from testplat_control.api.schemas import ExecutionAuth, parse_execution_auth
from testplat_control.services import execution_service


def test_load_auth_passes_repo_project_env_as_cache_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """execution_service._load_auth 拼 f"{repo}:{project}:{env}"。"""
    captured: dict[str, object] = {}

    def fake_load_auth(config_root, env, *, environ=None, cache_scope=None):  # noqa: ANN001
        captured["config_root"] = str(config_root)
        captured["env"] = env
        captured["cache_scope"] = cache_scope
        return None

    monkeypatch.setattr(execution_service, "load_auth", fake_load_auth)
    project = SimpleNamespace(id="main/demo", repo="main", project_key="demo")
    assert execution_service._load_auth(Path("/tmp/cfg"), "staging", project) is None  # noqa: SLF001
    assert captured["cache_scope"] == "main:demo:staging"
    assert captured["env"] == "staging"
    assert captured["config_root"] == "/tmp/cfg"


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
