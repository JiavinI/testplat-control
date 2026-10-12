"""Engine 执行端口。

Control 只依赖此 Protocol，路由与编排层不直接构造具体 Adapter。
请求/结果 DTO 直接取自 Engine 包的公开 Interface（0.2），保证 Fake 与真实适配器
共用同一契约；Control 不再定义第二份 Case DTO。

Engine 0.2 的唯一执行入口仍是 ``execute(request)``：按请求类型判别，
``ApiExecutionRequest`` → ``ApiExecutionOutcome``，``CaseExecutionRequest`` →
``CaseExecutionOutcome``。Control 不使用任何其他 Engine 入口（loader、runner 等）。
"""

from __future__ import annotations

from typing import Protocol, overload

from testplat_engine import (
    ApiExecutionOutcome,
    ApiExecutionRequest,
    CaseExecutionOutcome,
    CaseExecutionRequest,
)


class EnginePort(Protocol):
    """Engine 执行 seam；实现方不得依赖 Control ORM 或 FastAPI。"""

    @overload
    async def execute(self, request: ApiExecutionRequest) -> ApiExecutionOutcome: ...

    @overload
    async def execute(self, request: CaseExecutionRequest) -> CaseExecutionOutcome: ...

    async def execute(
        self, request: ApiExecutionRequest | CaseExecutionRequest
    ) -> ApiExecutionOutcome | CaseExecutionOutcome:
        """执行 API 或 Case，返回业务结果或抛出已分类的 EngineError。"""
        ...
