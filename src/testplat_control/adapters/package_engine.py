"""真实 Engine 包适配器。

把已安装的 ``testplat-engine`` 解析为 ``EnginePort``，供默认 DI 使用。
不修改 ``sys.path``；依赖必须通过包安装（正式 git 锁定或本地 editable 覆盖）。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from testplat_engine import (
    ApiExecutionOutcome,
    ApiExecutionRequest,
    EngineUnavailableError,
)

from testplat_control.ports.engine import EnginePort

logger = logging.getLogger(__name__)

_ExecuteFn = Callable[[ApiExecutionRequest], Awaitable[ApiExecutionOutcome]]


class _CallableEngine:
    """把模块级 ``async def execute(request)`` 包装成 EnginePort。"""

    def __init__(self, execute_fn: _ExecuteFn) -> None:
        self._execute_fn = execute_fn

    async def execute(self, request: ApiExecutionRequest) -> ApiExecutionOutcome:
        return await self._execute_fn(request)


def resolve_package_engine() -> EnginePort:
    """从已安装的 testplat-engine 解析公开 EnginePort 实现。

    解析顺序：

    1. ``testplat_engine.create_engine()``
    2. ``testplat_engine.application.create_engine()``
    3. ``testplat_engine.SingleApiEngine()``
    4. 模块级 ``testplat_engine.execute(request)``

    Returns:
        可调用的 EnginePort。

    Raises:
        EngineUnavailableError: 包已安装但缺少公开 execute 入口。
    """
    import testplat_engine as eng

    factory = getattr(eng, "create_engine", None)
    if callable(factory):
        engine = factory()
        _assert_engine_port(engine, "testplat_engine.create_engine()")
        return engine  # type: ignore[no-any-return]

    try:
        from testplat_engine.application import create_engine as app_factory
    except ImportError:
        app_factory = None
    if callable(app_factory):
        engine = app_factory()
        _assert_engine_port(engine, "testplat_engine.application.create_engine()")
        return engine  # type: ignore[no-any-return]

    single_cls = getattr(eng, "SingleApiEngine", None)
    if callable(single_cls):
        engine = single_cls()
        _assert_engine_port(engine, "testplat_engine.SingleApiEngine()")
        return engine  # type: ignore[no-any-return]

    execute_fn = getattr(eng, "execute", None)
    if callable(execute_fn):
        return _CallableEngine(execute_fn)

    raise EngineUnavailableError(
        public_message="执行引擎不可用：已安装包，但缺少公开 execute 入口",
        log_reason=(
            "testplat-engine 已安装且版本兼容，但未导出 create_engine/"
            "SingleApiEngine/execute；请安装含 runtime 的 0.1.x 包"
        ),
    )


def _assert_engine_port(engine: Any, source: str) -> None:
    """工厂返回值必须具备 async execute，否则视为分发不兼容。"""
    execute = getattr(engine, "execute", None)
    if execute is None or not callable(execute):
        raise EngineUnavailableError(
            public_message="执行引擎不可用：create_engine 返回值不是 EnginePort",
            log_reason=f"{source} 未提供可调用的 execute 方法",
        )


class PackageEngineAdapter:
    """默认真实适配器：委托已安装包的 EnginePort 实现。

    可通过 ``delegate`` 注入替身（单测 PackageEngineAdapter 自身时使用）；
    路由层不得直接 ``PackageEngineAdapter()``，应走 ``get_engine_port``。
    """

    def __init__(self, delegate: EnginePort | None = None) -> None:
        """初始化适配器。

        Args:
            delegate: 显式注入的 EnginePort；为 None 时从已安装包解析。
        """
        self._delegate: EnginePort | None = delegate
        self._resolve_error: EngineUnavailableError | None = None
        if self._delegate is None:
            try:
                self._delegate = resolve_package_engine()
            except EngineUnavailableError as exc:
                # 延迟到 execute：provider 默认仍能返回本适配器实例，便于类型断言；
                # 真正执行时再以 unavailable 系统错误暴露，映射为 503。
                logger.warning("PackageEngineAdapter 未能解析 runtime：%s", exc.log_reason)
                self._resolve_error = exc

    async def execute(self, request: ApiExecutionRequest) -> ApiExecutionOutcome:
        """转发到包内 EnginePort；解析失败时抛出 unavailable。"""
        if self._delegate is None:
            assert self._resolve_error is not None
            raise self._resolve_error
        return await self._delegate.execute(request)
