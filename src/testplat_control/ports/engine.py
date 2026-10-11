"""Engine 执行端口。

Control 只依赖此 Protocol，路由与编排层不直接构造具体 Adapter。
请求/结果 DTO 与 Engine 包公开 Interface 对齐，保证 Fake 与真实适配器可互换。
"""

from __future__ import annotations

from typing import Protocol

from testplat_engine import ApiExecutionOutcome, ApiExecutionRequest


class EnginePort(Protocol):
    """单 API 执行 seam；实现方不得依赖 Control ORM 或 FastAPI。"""

    async def execute(self, request: ApiExecutionRequest) -> ApiExecutionOutcome:
        """执行单个 API，返回业务结果或抛出已分类的 EngineError。"""
        ...
