"""Phase 3.3b：login_plugins 白名单 ∩ entry point（E1 / L1）。"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from testplat_control.engine_bootstrap import (
    EngineBootstrapError,
    create_engine_with_plugins,
    resolve_login_strategies,
)


class _FakeStrategy:
    name = "fake_login"

    def validate(self, auth):  # noqa: ANN001, ANN201
        return None

    async def login(self, ctx):  # noqa: ANN001, ANN201
        raise NotImplementedError


def test_empty_whitelist_registers_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "testplat_control.engine_bootstrap.discover_installed_login_strategies",
        lambda: {"fake_login": _FakeStrategy()},
    )
    assert resolve_login_strategies([]) == []


def test_whitelist_intersection(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    installed = {"fake_login": _FakeStrategy(), "other": SimpleNamespace(name="other")}
    monkeypatch.setattr(
        "testplat_control.engine_bootstrap.discover_installed_login_strategies",
        lambda: installed,
    )
    with caplog.at_level(logging.INFO, logger="testplat_control.engine_bootstrap"):
        got = resolve_login_strategies(["fake_login"])
    assert len(got) == 1 and got[0].name == "fake_login"
    assert any(
        "other" in r.getMessage() and "未列入白名单" in r.getMessage() for r in caplog.records
    )


def test_whitelist_missing_plugin_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "testplat_control.engine_bootstrap.discover_installed_login_strategies",
        lambda: {},
    )
    with pytest.raises(EngineBootstrapError, match="fake_login"):
        resolve_login_strategies(["fake_login"])


def test_create_engine_with_plugins_uses_same_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L1：create_engine_with_plugins 走 resolve_login_strategies。"""
    calls: list[tuple] = []

    def fake_resolve(whitelist):  # noqa: ANN001, ANN201
        calls.append(tuple(whitelist))
        return []

    monkeypatch.setattr("testplat_control.engine_bootstrap.resolve_login_strategies", fake_resolve)

    class _Eng:
        async def execute(self, request):  # noqa: ANN001, ANN201
            return None

    import testplat_engine as eng

    monkeypatch.setattr(eng, "create_engine", lambda **kwargs: _Eng())
    create_engine_with_plugins(("fake_login",))
    assert calls == [("fake_login",)]


def test_whitelisted_plugin_not_installed_is_503_without_record(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """白名单列出但未安装：按项目切换引擎时失败 → 503 安全文案，不写记录，不是 500。"""
    import copy

    from fastapi.testclient import TestClient

    from testplat_control.adapters.fake_engine import FakeEngineAdapter
    from testplat_control.adapters.package_engine import PackageEngineAdapter
    from testplat_control.deps import get_engine_port
    from testplat_control.main import app
    from tests.auth_support import STANDARD_CONFIG, STANDARD_ENV, write_auth
    from tests.case_support import create_project, write_assets, write_env

    for key, value in STANDARD_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        "testplat_control.engine_bootstrap.discover_installed_login_strategies", lambda: {}
    )
    assets, config = tmp_path / "assets", tmp_path / "config"
    assets.mkdir()
    config.mkdir()
    write_assets(assets)
    write_env(config, "http://127.0.0.1:9")
    auth_config = copy.deepcopy(STANDARD_CONFIG)
    auth_config["login_plugins"] = ["not_installed"]
    write_auth(config, auth_config)

    client = TestClient(app, raise_server_exceptions=False)
    project_id = create_project(client, assets, config)
    app.dependency_overrides[get_engine_port] = lambda: PackageEngineAdapter(
        delegate=FakeEngineAdapter()
    )
    try:
        response = client.post(
            f"/projects/{project_id}/assets/api.demo.create/run", json={"params": {}}
        )
    finally:
        app.dependency_overrides.pop(get_engine_port, None)

    assert response.status_code == 503
    assert response.json()["detail"] == "执行引擎不可用：create_engine 调用失败"
    records = client.get(f"/projects/{project_id}/execution-records").json()
    assert records == []
