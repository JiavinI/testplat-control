"""真实 Engine 包适配器。

把已安装的 ``testplat-engine`` 解析为 ``EnginePort``，供默认 DI 使用。
不修改 ``sys.path``；依赖必须通过包安装（正式 git 锁定或本地 editable 覆盖）。

仅认可官方公开入口 ``testplat_engine.create_engine()``，不再猜测
``application.create_engine`` / ``SingleApiEngine`` / 模块级 ``execute``。
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from testplat_engine import (
    ApiExecutionOutcome,
    ApiExecutionRequest,
    EngineUnavailableError,
)

from testplat_control.ports.engine import EnginePort

logger = logging.getLogger(__name__)


def resolve_package_engine() -> EnginePort:
    """从已安装的 testplat-engine 解析公开 EnginePort 实现。

    唯一入口：``testplat_engine.create_engine()``，返回值须具备 async ``execute``。

    Returns:
        可调用的 EnginePort。

    Raises:
        EngineUnavailableError: 包已安装但缺少或不符合公开 create_engine 契约。
    """
    import testplat_engine as eng

    factory = getattr(eng, "create_engine", None)
    if not callable(factory):
        raise EngineUnavailableError(
            public_message="执行引擎不可用：已安装包，但缺少公开 create_engine 入口",
            log_reason=(
                "testplat-engine 已安装且版本兼容，但未导出 create_engine；"
                "请安装含 runtime 的 0.1.x 包"
            ),
        )

    try:
        engine = factory()
    except Exception as exc:
        raise EngineUnavailableError(
            public_message="执行引擎不可用：create_engine 调用失败",
            log_reason=f"testplat_engine.create_engine() raised {type(exc).__name__}: {exc}",
        ) from exc

    _assert_engine_port(engine, "testplat_engine.create_engine()")
    return engine  # type: ignore[no-any-return]


def _assert_engine_port(engine: Any, source: str) -> None:
    """工厂返回值必须具备 async execute，否则视为分发不兼容。"""
    execute = getattr(engine, "execute", None)
    if execute is None or not callable(execute):
        raise EngineUnavailableError(
            public_message="执行引擎不可用：create_engine 返回值不是 EnginePort",
            log_reason=f"{source} 未提供可调用的 execute 方法",
        )
    if not inspect.iscoroutinefunction(execute):
        raise EngineUnavailableError(
            public_message="执行引擎不可用：create_engine 返回值不是 EnginePort",
            log_reason=f"{source} 的 execute 不是 async 协程函数",
        )


class PackageEngineAdapter:
    """默认真实适配器：委托已安装包的 EnginePort 实现。

    可通过 ``delegate`` 注入替身（单测 PackageEngineAdapter 自身时使用）；
    路由层不得直接 ``PackageEngineAdapter()``，应走 ``get_engine_port``。

    无 delegate 时构造即解析 ``create_engine()``；解析失败直接抛出，
    不再延迟到首次 execute 才以 503 暴露（启动期由 bootstrap fail-fast）。
    """

    def __init__(self, delegate: EnginePort | None = None) -> None:
        """初始化适配器。

        Args:
            delegate: 显式注入的 EnginePort；为 None 时从已安装包解析。

        Raises:
            EngineUnavailableError: 无法从包解析出合法 EnginePort。
        """
        if delegate is not None:
            self._delegate: EnginePort = delegate
        else:
            self._delegate = resolve_package_engine()

    async def execute(self, request: ApiExecutionRequest) -> ApiExecutionOutcome:
        """转发到包内 EnginePort。"""
        return await self._delegate.execute(request)
