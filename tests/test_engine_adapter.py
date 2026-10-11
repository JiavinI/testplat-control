"""PackageEngineAdapter 与 Engine 解析单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from testplat_engine import (
    ApiExecutionOutcome,
    ApiExecutionRequest,
    EngineUnavailableError,
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


@pytest.mark.asyncio
async def test_package_adapter_raises_unavailable_when_runtime_missing() -> None:
    """bee429d 仅有 Interface 时，无 delegate 的真实适配器在 execute 时抛 unavailable。"""
    # 当前 Interface worktree 未导出 create_engine/execute
    with pytest.raises(EngineUnavailableError) as exc_info:
        resolve_package_engine()
    assert exc_info.value.kind == "unavailable"
    assert exc_info.value.stage == "preflight"

    adapter = PackageEngineAdapter()
    with pytest.raises(EngineUnavailableError) as raised:
        await adapter.execute(_request())
    assert raised.value.kind == "unavailable"


def test_package_adapter_is_default_concrete_type() -> None:
    """默认构造得到 PackageEngineAdapter 实例（供 provider 断言）。"""
    adapter = PackageEngineAdapter()
    assert isinstance(adapter, PackageEngineAdapter)
