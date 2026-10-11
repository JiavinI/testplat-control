"""测试与显式验收 harness 用的 Fake Engine。

仅通过 DI / dependency_overrides 注入；默认 provider 不会选择本实现。
"""

from __future__ import annotations

from testplat_engine import (
    ApiExecutionOutcome,
    ApiExecutionRequest,
    EngineError,
)


class FakeEngineAdapter:
    """确定性 EnginePort 替身。

    - 默认返回 success。
    - ``fail_passwords`` 中的 password 触发业务 failed。
    - ``system_error`` 非空时直接抛出该系统异常（用于错误映射单测）。
    """

    def __init__(
        self,
        *,
        fail_passwords: frozenset[str] | None = None,
        system_error: EngineError | None = None,
        delay: float = 0.0,
    ) -> None:
        self.fail_passwords = fail_passwords or frozenset({"wrong-password"})
        self.system_error = system_error
        self.delay = delay
        self.calls: list[ApiExecutionRequest] = []

    async def execute(self, request: ApiExecutionRequest) -> ApiExecutionOutcome:
        """按配置返回业务结果或抛出系统错误。"""
        import asyncio

        self.calls.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.system_error is not None:
            raise self.system_error

        password = request.params.get("password")
        failed = isinstance(password, str) and password in self.fail_passwords
        if failed:
            return ApiExecutionOutcome(
                status="failed",
                request={"api_id": request.api_id, "params": dict(request.params)},
                response=None,
                error={"kind": "assertion", "message": "assertion failed"},
            )
        return ApiExecutionOutcome(
            status="success",
            request={"api_id": request.api_id, "params": dict(request.params)},
            response={"status_code": 200, "body": {"ok": True}},
            error=None,
        )
