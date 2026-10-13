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
