"""真实 Engine 浏览器/API 矩阵 harness。

挂载默认 PackageEngineAdapter（与 ``main:app`` 相同），但将 Case / API 的每步骤
``timeout_seconds`` 缩短为 0.5，以便本地 slow 目标触发 504 而不必等待 30 秒。

本模块仅供矩阵验收；不改变公开 HTTP 契约，也不作为生产入口。

用法：
    uv run uvicorn testplat_control.harness_real_matrix:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

from typing import Any

import testplat_control.api.cases as cases_api
import testplat_control.api.run as run_api
from testplat_control.main import app
from testplat_control.services import execution_service

_SHORT_TIMEOUT = 0.5
_original_run_case = execution_service.run_case
_original_run_api = execution_service.run_single_api


async def _run_case_short(**kwargs: Any):
    """矩阵专用：强制短步骤超时。"""
    kwargs["timeout_seconds"] = _SHORT_TIMEOUT
    return await _original_run_case(**kwargs)


async def _run_api_short(**kwargs: Any):
    """矩阵专用：强制短步骤超时。"""
    kwargs["timeout_seconds"] = _SHORT_TIMEOUT
    return await _original_run_api(**kwargs)


# 服务层与路由层各有一份绑定，需同时替换。
execution_service.run_case = _run_case_short  # type: ignore[assignment]
execution_service.run_single_api = _run_api_short  # type: ignore[assignment]
cases_api.run_case = _run_case_short  # type: ignore[assignment]
run_api.run_single_api = _run_api_short  # type: ignore[assignment]

__all__ = ["app"]
