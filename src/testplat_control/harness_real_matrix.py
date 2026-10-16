"""真实 Engine 浏览器/API 矩阵 harness。

挂载默认 PackageEngineAdapter（与 ``main:app`` 相同），但将 Case / API 的每步骤
``timeout_seconds`` 缩短为 0.5，以便本地 slow 目标触发 504 而不必等待 30 秒。

【仅限验收，禁止用于生产】
本模块只供 ``scripts/run_real_engine_matrix.sh`` 的真实 Engine 矩阵验收使用：
它在导入时 monkeypatch 服务层与路由层的 ``run_case`` / ``run_single_api``，
把每步骤超时强制改为 0.5 秒。这会改变执行语义，因此它**不是**生产入口，
生产请使用 ``testplat_control.main:app``。不改变公开 HTTP 契约。

Phase 3.3a：设置 ``MATRIX_SQLITE_PATH`` 时，把会话工厂改绑到该路径的文件型 SQLite
（默认是进程内存库，矩阵结束后无从检查），供泄密搜索直接读取执行记录的原始行（设计稿 §6-1）。
只改绑定，不改表结构、不新增表或迁移。

用法：
    uv run uvicorn testplat_control.harness_real_matrix:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import os
from typing import Any

import testplat_control.api.cases as cases_api
import testplat_control.api.run as run_api
from testplat_control.database import session as db_session
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

_sqlite_path = os.environ.get("MATRIX_SQLITE_PATH")
if _sqlite_path:
    # 矩阵专用：所有请求经 get_db -> SessionLocal，改绑同一个 sessionmaker 即全局生效。
    _file_engine = db_session.make_engine(f"sqlite:///{_sqlite_path}")
    db_session.init_engine_schema(_file_engine)
    db_session.SessionLocal.configure(bind=_file_engine)

__all__ = ["app"]
