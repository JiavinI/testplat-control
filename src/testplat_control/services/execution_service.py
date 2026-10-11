"""单 API 执行编排。

负责：环境加载、计时、调用 EnginePort、按 stage 写执行记录、映射 HTTP。
不拥有资产 YAML 参数表单校验（仍在路由层）；不直接构造 Adapter。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from testplat_engine import (
    ApiExecutionOutcome,
    ApiExecutionRequest,
    EngineError,
)

from testplat_control.database.models import ExecutionRecord, Project
from testplat_control.ports.engine import EnginePort
from testplat_control.services.env_loader import load_project_environment

logger = logging.getLogger(__name__)

# Engine kind -> HTTP 状态码（与 Phase 2.5 批准错误表一致）
_KIND_TO_HTTP: dict[str, int] = {
    "asset_not_found": 404,
    "invalid_asset": 422,
    "invalid_environment": 422,
    "timeout": 504,
    "transport": 502,
    "unavailable": 503,
    "internal": 500,
}


def map_engine_error_http_status(error: EngineError) -> int:
    """把 EngineError.kind 映射为 HTTP 状态码。"""
    return _KIND_TO_HTTP.get(error.kind, 500)


def _build_record(
    *,
    project: Project,
    asset_id: str,
    status: str,
    start_time: datetime,
    end_time: datetime,
    result_payload: dict[str, Any],
) -> ExecutionRecord:
    """构造尚未落库的执行记录。"""
    duration = (end_time - start_time).total_seconds()
    return ExecutionRecord(
        id=str(uuid4()),
        project_id=project.id,
        asset_type="api",
        asset_id=asset_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
        duration=duration,
        result_json=json.dumps(result_payload, ensure_ascii=False, default=str),
    )


def _persist(db: Session, record: ExecutionRecord) -> ExecutionRecord:
    """写入执行记录；失败时回滚并返回 500。"""
    try:
        db.add(record)
        db.commit()
        db.refresh(record)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Failed to persist execution record %s", getattr(record, "id", None))
        raise HTTPException(
            status_code=500,
            detail="Failed to persist execution record",
        ) from exc
    return record


async def run_single_api(
    *,
    db: Session,
    project: Project,
    asset_id: str,
    params: dict[str, Any],
    engine: EnginePort,
    timeout_seconds: float = 30.0,
) -> ExecutionRecord:
    """编排一次单 API 执行并返回已落库记录。

    记录规则（批准）：

    - ``preflight`` 系统错误：不创建记录，直接 HTTP 4xx/5xx。
    - ``execution`` 系统错误：创建 ``failed`` 记录，再返回 HTTP 5xx。
    - 业务 success/failed：创建记录，由路由包装为 HTTP 200 RunResponse。

    Args:
        db: 数据库会话。
        project: 已存在的项目。
        asset_id: API 资产 ID。
        params: 已通过表单校验的参数。
        engine: 注入的 EnginePort（真实或 Fake）。
        timeout_seconds: 传给 Engine 的超时。

    Returns:
        已持久化的 ExecutionRecord。

    Raises:
        HTTPException: 按错误表映射的状态码；detail 仅含安全外显信息。
    """
    # 环境加载属 Control 侧 preflight：失败不写记录。
    try:
        environment = load_project_environment(project.config_root, project.env)
    except EngineError as exc:
        logger.error(
            "环境配置 preflight 失败 project=%s env=%s: %s",
            project.id,
            project.env,
            exc.log_reason or exc.public_message,
        )
        raise HTTPException(
            status_code=map_engine_error_http_status(exc),
            detail=exc.public_message,
        ) from exc

    try:
        request = ApiExecutionRequest(
            api_id=asset_id,
            assets_root=Path(project.assets_root),
            environment=environment,
            params=params,
            timeout_seconds=timeout_seconds,
        )
    except (TypeError, ValueError) as exc:
        # 请求 DTO 构造失败视为 Control 侧参数/环境不合法。
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    start_time = datetime.now(UTC)
    try:
        outcome = await engine.execute(request)
    except EngineError as exc:
        end_time = datetime.now(UTC)
        logger.error(
            "Engine 系统错误 project=%s asset=%s kind=%s stage=%s: %s",
            project.id,
            asset_id,
            exc.kind,
            exc.stage,
            exc.log_reason or exc.public_message,
        )
        if exc.stage == "execution":
            # 已进入执行阶段：落 failed 记录，HTTP 仍为对应 5xx。
            payload = {
                "status": "failed",
                "request": None,
                "response": None,
                "error": exc.to_dict(),
            }
            record = _build_record(
                project=project,
                asset_id=asset_id,
                status="failed",
                start_time=start_time,
                end_time=end_time,
                result_payload=payload,
            )
            _persist(db, record)
        raise HTTPException(
            status_code=map_engine_error_http_status(exc),
            detail=exc.public_message,
        ) from exc
    except Exception as exc:
        # 未分类异常：不猜测 stage，不写记录，避免污染历史。
        logger.exception(
            "未预期执行异常 project=%s asset=%s",
            project.id,
            asset_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute API: {type(exc).__name__}",
        ) from exc

    end_time = datetime.now(UTC)
    if not isinstance(outcome, ApiExecutionOutcome):
        raise HTTPException(status_code=500, detail="Engine returned an invalid outcome")

    payload = outcome.to_dict()
    record = _build_record(
        project=project,
        asset_id=asset_id,
        status=outcome.status,
        start_time=start_time,
        end_time=end_time,
        result_payload=payload,
    )
    return _persist(db, record)
