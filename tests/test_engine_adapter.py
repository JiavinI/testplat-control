"""PackageEngineAdapter 与 Engine 解析单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from testplat_engine import (
    ApiExecutionOutcome,
    ApiExecutionRequest,
    EngineUnavailableError,
    SingleApiEngine,
)

from testplat_control.adapters.package_engine import PackageEngineAdapter, resolve_package_engine


class _StubEngine:
    """可注入的 EnginePort 替身。"""

    def __init__(
        self,
        outcome: ApiExecutionOutcome | None = None,
        error: Exception | None = None,
    ) -> None:
        self.outcome = outcome or ApiExecutionOutcome(status="success", response={"ok": True})
        self.error = error
        self.calls: list[ApiExecutionRequest] = []

    async def execute(self, request: ApiExecutionRequest) -> ApiExecutionOutcome:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.outcome


def _request() -> ApiExecutionRequest:
    return ApiExecutionRequest(
        api_id="api.common.health_check",
        assets_root=Path("/assets"),
        environment={"api_hosts": {"main": "http://127.0.0.1"}},
        params={},
    )


@pytest.mark.asyncio
async def test_package_adapter_delegates_to_injected_engine() -> None:
    """显式 delegate 时直接转发，不依赖包内 runtime。"""
    stub = _StubEngine()
    adapter = PackageEngineAdapter(delegate=stub)

    outcome = await adapter.execute(_request())

    assert outcome.status == "success"
    assert len(stub.calls) == 1
    assert stub.calls[0].api_id == "api.common.health_check"


def test_resolve_package_engine_returns_runtime() -> None:
    """已安装 runtime 时仅通过 create_engine 解析出可执行的 EnginePort。"""
    engine = resolve_package_engine()
    assert callable(engine.execute)
    assert isinstance(engine, SingleApiEngine)


@pytest.mark.asyncio
async def test_package_adapter_uses_resolved_runtime() -> None:
    """无 delegate 时默认适配器委托已安装 runtime（构造即解析成功）。"""
    adapter = PackageEngineAdapter()
    assert adapter._delegate is not None  # noqa: SLF001


def test_package_adapter_raises_unavailable_when_runtime_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模拟缺少 create_engine 时，构造期即抛 unavailable（不再延迟到 execute）。"""

    def _boom() -> None:
        raise EngineUnavailableError(
            public_message="执行引擎不可用：已安装包，但缺少公开 create_engine 入口",
            log_reason="simulated missing runtime",
        )

    monkeypatch.setattr(
        "testplat_control.adapters.package_engine.resolve_package_engine",
        _boom,
    )
    with pytest.raises(EngineUnavailableError) as raised:
        PackageEngineAdapter()
    assert raised.value.kind == "unavailable"
    assert raised.value.stage == "preflight"


def test_resolve_rejects_non_create_engine_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """即使存在 SingleApiEngine / execute，缺少 create_engine 也必须失败。"""
    import testplat_engine as eng

    monkeypatch.delattr(eng, "create_engine", raising=False)
    assert hasattr(eng, "SingleApiEngine")
    with pytest.raises(EngineUnavailableError, match="create_engine"):
        resolve_package_engine()


def test_package_adapter_is_default_concrete_type() -> None:
    """默认构造得到 PackageEngineAdapter 实例（供 provider 断言）。"""
    adapter = PackageEngineAdapter()
    assert isinstance(adapter, PackageEngineAdapter)
