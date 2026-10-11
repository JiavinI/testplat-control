"""FastAPI 依赖注入。

路由通过 ``Depends(get_engine_port)`` 获取 EnginePort，禁止在路由内直接 new Adapter。
测试与验收 harness 使用 ``app.dependency_overrides[get_engine_port] = ...`` 注入 Fake，
无需 monkeypatch 路由模块全局符号。
"""

from __future__ import annotations

from fastapi import Request

from testplat_control.adapters.package_engine import PackageEngineAdapter
from testplat_control.ports.engine import EnginePort


def create_default_engine_port() -> EnginePort:
    """默认构造真实 PackageEngineAdapter（供 lifespan 与单测断言）。"""
    return PackageEngineAdapter()


def get_engine_port(request: Request) -> EnginePort:
    """从应用状态取 EnginePort；若尚未初始化则惰性创建默认真实适配器。"""
    engine = getattr(request.app.state, "engine_port", None)
    if engine is None:
        engine = create_default_engine_port()
        request.app.state.engine_port = engine
    return engine  # type: ignore[no-any-return]
