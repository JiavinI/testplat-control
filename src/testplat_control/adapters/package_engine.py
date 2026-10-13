"""真实 Engine 包适配器。

把已安装的 ``testplat-engine`` 解析为 ``EnginePort``，供默认 DI 使用。
不修改 ``sys.path``；依赖必须通过包安装（正式 git 锁定或本地 editable 覆盖）。

仅认可官方公开入口 ``testplat_engine.create_engine(login_strategies=...)``，
与 ``engine_bootstrap.create_engine_with_plugins`` 共用同一份插件解析（L1）。
生产路径不得注入共享 ``http_client``（A9）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import overload

from testplat_engine import (
    ApiExecutionOutcome,
    ApiExecutionRequest,
    CaseExecutionOutcome,
    CaseExecutionRequest,
    EngineUnavailableError,
)

from testplat_control.engine_bootstrap import (
    EngineBootstrapError,
    create_engine_with_plugins,
)
from testplat_control.ports.engine import EnginePort

logger = logging.getLogger(__name__)


def resolve_package_engine(login_plugins: Sequence[str] = ()) -> EnginePort:
    """从已安装的 testplat-engine 解析公开 EnginePort 实现。

    唯一入口：``create_engine(login_strategies=entry_point ∩ whitelist)``。

    Args:
        login_plugins: auth 配置白名单；默认空（仅内置 generic_flow）。

    Returns:
        可调用的 EnginePort。

    Raises:
        EngineUnavailableError: 包已安装但缺少或不符合公开 create_engine 契约。
    """
    try:
        engine = create_engine_with_plugins(login_plugins)
    except EngineBootstrapError as exc:
        raise EngineUnavailableError(
            public_message="执行引擎不可用：create_engine 调用失败",
            log_reason=f"create_engine_with_plugins: {type(exc).__name__}",
        ) from exc
    return engine  # type: ignore[no-any-return]


class PackageEngineAdapter:
    """默认真实适配器：按 ``login_plugins`` 白名单缓存 ``create_engine`` 实例。

    可通过 ``delegate`` 注入替身（单测 PackageEngineAdapter 自身时使用）；
    路由层不得直接 ``PackageEngineAdapter()``，应走 ``get_engine_port``。

    无 delegate 时构造即解析空白名单引擎；项目执行前调用
    :meth:`for_login_plugins` 切换到该项目 auth 配置的白名单交集。
    """

    def __init__(
        self,
        delegate: EnginePort | None = None,
        *,
        login_plugins: Sequence[str] = (),
    ) -> None:
        """初始化适配器。

        Args:
            delegate: 显式注入的 EnginePort；为 None 时从已安装包解析。
            login_plugins: 初始白名单（默认空）。

        Raises:
            EngineUnavailableError: 无法从包解析出合法 EnginePort。
        """
        self._cache: dict[tuple[str, ...], EnginePort] = {}
        self._plugins: tuple[str, ...] = tuple(login_plugins)
        if delegate is not None:
            self._delegate = delegate
            self._cache[self._plugins] = delegate
        else:
            self._delegate = resolve_package_engine(self._plugins)
            self._cache[self._plugins] = self._delegate

    def for_login_plugins(self, login_plugins: Sequence[str]) -> PackageEngineAdapter:
        """返回绑定指定白名单的适配器（同实例缓存，避免重复 create_engine）。"""
        key = tuple(login_plugins)
        if key == self._plugins:
            return self
        if key not in self._cache:
            self._cache[key] = resolve_package_engine(key)
        # 返回共享缓存的浅包装，避免调用方持有过期 delegate。
        wrapped = PackageEngineAdapter.__new__(PackageEngineAdapter)
        wrapped._cache = self._cache
        wrapped._plugins = key
        wrapped._delegate = self._cache[key]
        return wrapped

    @overload
    async def execute(self, request: ApiExecutionRequest) -> ApiExecutionOutcome: ...

    @overload
    async def execute(self, request: CaseExecutionRequest) -> CaseExecutionOutcome: ...

    async def execute(
        self, request: ApiExecutionRequest | CaseExecutionRequest
    ) -> ApiExecutionOutcome | CaseExecutionOutcome:
        """转发到包内 EnginePort 的唯一 ``execute`` 入口（API 与 Case 共用）。"""
        return await self._delegate.execute(request)  # type: ignore[call-overload,no-any-return]
