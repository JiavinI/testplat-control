"""Engine provider / 启动诊断测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from testplat_control.adapters.fake_engine import FakeEngineAdapter
from testplat_control.adapters.package_engine import PackageEngineAdapter
from testplat_control.deps import create_default_engine_port, get_engine_port
from testplat_control.engine_bootstrap import EngineBootstrapError, ensure_engine_compatible
from testplat_control.main import app


def test_provider_defaults_to_package_adapter() -> None:
    """默认工厂返回真实 PackageEngineAdapter，而不是 Fake。"""
    engine = create_default_engine_port()
    assert isinstance(engine, PackageEngineAdapter)
    assert not isinstance(engine, FakeEngineAdapter)


def test_fake_injection_via_dependency_overrides_without_monkeypatch() -> None:
    """Fake 通过 dependency_overrides 注入，不 monkeypatch 路由全局符号。"""
    fake = FakeEngineAdapter()
    app.dependency_overrides[get_engine_port] = lambda: fake
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
        assert app.dependency_overrides[get_engine_port]() is fake
    finally:
        app.dependency_overrides.pop(get_engine_port, None)


def test_ensure_engine_compatible_succeeds_for_installed_0_2() -> None:
    """已安装 0.2.x Interface（含 Case DTO）时启动诊断通过。"""
    version = ensure_engine_compatible()
    assert version.startswith("0.2")


def test_ensure_engine_compatible_rejects_0_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 3 起 0.1.x 不再兼容：缺少 Case DTO，必须在启动期被拒绝。"""
    monkeypatch.setattr("testplat_control.engine_bootstrap.version", lambda _dist: "0.1.0")
    with pytest.raises(EngineBootstrapError, match="版本不兼容"):
        ensure_engine_compatible()


def test_ensure_engine_compatible_requires_case_interface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺少 Case 公开符号时 fail-fast，并点名缺失项。"""
    import testplat_engine as eng

    monkeypatch.delattr(eng, "CaseExecutionRequest", raising=False)
    with pytest.raises(EngineBootstrapError, match="CaseExecutionRequest"):
        ensure_engine_compatible()


def test_ensure_engine_compatible_fail_fast_on_missing_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺包时给出明确诊断。"""
    real_import = __import__

    def _guard(name: str, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name == "testplat_engine" or name.startswith("testplat_engine."):
            raise ImportError("simulated missing engine")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _guard)
    with pytest.raises(EngineBootstrapError, match="未安装 testplat-engine"):
        ensure_engine_compatible()


def test_ensure_engine_compatible_fail_fast_on_bad_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """版本不在 0.2.x 时 fail-fast。"""
    monkeypatch.setattr(
        "testplat_control.engine_bootstrap.version",
        lambda _dist: "9.0.0",
    )
    with pytest.raises(EngineBootstrapError, match="版本不兼容"):
        ensure_engine_compatible()


def test_lifespan_fail_fast_when_engine_incompatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """应用 lifespan 在 Engine 不兼容时拒绝启动。"""

    @asynccontextmanager
    async def broken_lifespan(application: FastAPI):
        ensure_engine_compatible()
        yield

    monkeypatch.setattr(
        "testplat_control.engine_bootstrap.version",
        lambda _dist: "9.0.0",
    )
    broken_app = FastAPI(lifespan=broken_lifespan)
    with pytest.raises(EngineBootstrapError, match="版本不兼容"):
        with TestClient(broken_app):
            pass


def test_ensure_engine_compatible_requires_callable_create_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺少 create_engine 时启动诊断 fail-fast。"""
    import testplat_engine as eng

    monkeypatch.delattr(eng, "create_engine", raising=False)
    with pytest.raises(EngineBootstrapError, match="create_engine"):
        ensure_engine_compatible()


def test_ensure_engine_compatible_fail_fast_on_bad_create_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_engine 返回无 async execute 的对象时启动失败。"""
    import testplat_engine as eng

    class _Bad:
        def execute(self, request):  # noqa: ANN001, ANN201
            return None

    monkeypatch.setattr(eng, "create_engine", lambda: _Bad())
    with pytest.raises(EngineBootstrapError, match="async"):
        ensure_engine_compatible()
