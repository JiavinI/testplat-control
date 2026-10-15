"""单 API 与 Case 的执行编排。

负责：环境加载、计时、调用 EnginePort、按 stage 写执行记录、映射 HTTP。
不拥有资产 YAML 参数表单校验（仍在路由层）；不直接构造 Adapter。

所有权边界（Phase 3）
---------------------
- **Case 语法与运行语义的权威是 Engine**：Case id 格式、文件路径映射、schema、引用
  校验、步骤执行与 fail-fast 全部发生在 ``EnginePort.execute(request)`` 之内。
  本模块不解析 Case YAML，只把 Engine 返回的 outcome / 异常原样落库和映射为 HTTP。
- Control 只负责：运行配置解析（Web 环境存在时用数据库；否则 Git 文件）、身份表
  （cache_scope=``{repo}:{project}:{env}``；Engine 禁止 `/`）、调用与计时、
  ``ExecutionRecord`` 持久化、HTTP 状态码映射。
- 一次执行在调用 Engine 前冻结 environment / AuthTable / 超时 / 参数；之后不再读库补配置。

记录生命周期（单次写入）
------------------------
一次执行最多写入**一条**记录，且只在 Engine 返回或抛出之后写，没有 ``running`` 中间态：

| 场景                                       | 记录             | HTTP        |
|--------------------------------------------|------------------|-------------|
| 业务 success / 业务 failed（含断言、变量解析失败） | 写 success/failed | 200         |
| preflight 错误（含 invalid_input/invalid_asset）   | **不写**          | 按错误表 4xx/5xx |
| execution 阶段系统错误（timeout/transport/internal）| 写 failed        | 按错误表 5xx |
| 未分类异常（非 EngineError）                       | **不写**          | 500         |

错误映射沿用 Phase 2.5 错误表，Phase 3 仅新增 ``invalid_input → 422``。

日志硬约束
----------
Engine 异常的 ``log_reason``、``__cause__`` 与异常原文可能带有 password/token/Cookie 原值，
所以本模块**任何日志都不得**使用 ``logger.exception`` / ``exc_info``，也不得记录
``log_reason`` 或异常文本；只记 kind、stage、项目/资产/记录 ID 与异常**类型名**。
``log_reason`` 只留在异常对象上，供调用方做决策，不外显、不入库、不进日志。

鉴权（Phase 3.3a）
-----------------
- 身份表在环境之后加载；配置错误与环境错误同属 preflight ``invalid_environment``，不写记录。
- 没有 auth 配置文件时传 ``auth=None``（不是空表），行为与 Phase 3 一致（Q2）。
- 请求 DTO 构造失败时 422 detail 使用固定安全文案，不再回显 ``str(exc)``（M1）：
  异常消息可能含 params/environment 的值，Control 不对其内容做任何假设。

超时语义
--------
``timeout_seconds`` 是 Engine 对**每个步骤** HTTP 调用的超时，不是整个 Case 的总预算。
N 步 Case 的最坏耗时约为 ``N * timeout_seconds``。Control 目前没有 Case 级总限时：
在外层 ``wait_for`` 取消会丢掉 Engine 的 ``partial_outcome``，且本批不引入后台任务。
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
    CaseExecutionOutcome,
    CaseExecutionRequest,
    EngineError,
)

from testplat_control.database.models import ExecutionRecord, Project
from testplat_control.ports.engine import EnginePort
from testplat_control.services.auth_loader import AuthLoadResult, load_auth
from testplat_control.services.run_config import ResolvedRunConfig, resolve_run_config

logger = logging.getLogger(__name__)

# Engine kind -> HTTP 状态码（Phase 2.5 批准错误表 + Phase 3 新增 invalid_input）
_KIND_TO_HTTP: dict[str, int] = {
    "asset_not_found": 404,
    "invalid_asset": 422,
    "invalid_environment": 422,
    # Engine 0.2 新增：Case 参数在执行前可判定缺失；preflight，不写记录。
    "invalid_input": 422,
    "timeout": 504,
    "transport": 502,
    "unavailable": 503,
    "internal": 500,
}


def map_engine_error_http_status(error: EngineError) -> int:
    """把 EngineError.kind 映射为 HTTP 状态码。"""
    return _KIND_TO_HTTP.get(error.kind, 500)


def _log_engine_error(
    *, project: Project, asset_id: str, exc: EngineError, what: str = "Engine 系统错误"
) -> None:
    """记录 Engine 系统错误的**安全字段**。

    不得出现 ``log_reason``、异常原文、traceback 或 ``exc_info``；``__cause__`` 只取类型名。
    """
    cause = exc.__cause__
    logger.error(
        "%s project=%s asset=%s kind=%s stage=%s exc_type=%s cause_type=%s",
        what,
        project.id,
        asset_id,
        exc.kind,
        exc.stage,
        type(exc).__name__,
        None if cause is None else type(cause).__name__,
    )


def _build_record(
    *,
    project: Project,
    asset_id: str,
    status: str,
    start_time: datetime,
    end_time: datetime,
    result_payload: dict[str, Any],
    asset_type: str = "api",
    env: str | None = None,
    commit_sha: str | None = None,
    operator: str | None = None,
    resolved: ResolvedRunConfig | None = None,
) -> ExecutionRecord:
    """构造尚未落库的执行记录（复用同一张表，``asset_type`` 区分 api / case）。"""
    duration = (end_time - start_time).total_seconds()
    return ExecutionRecord(
        id=str(uuid4()),
        project_id=project.id,
        asset_type=asset_type,
        asset_id=asset_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
        duration=duration,
        result_json=json.dumps(result_payload, ensure_ascii=False, default=str),
        env=env,
        repo=project.repo,
        commit_sha=commit_sha,
        operator=operator,
        config_revision=None if resolved is None else resolved.config_revision,
        account_revisions=None if resolved is None else dict(resolved.account_revisions),
        config_snapshot=None if resolved is None else dict(resolved.snapshot),
    )


def _persist(db: Session, record: ExecutionRecord) -> ExecutionRecord:
    """写入执行记录；失败时回滚并返回 500。

    并发共享 SQLite（StaticPool）下 ``commit`` 后 ``refresh`` 易竞态失败；
    且默认 ``expire_on_commit`` 后再读 ORM 属性会触发隐式 SELECT。
    因此：提交前捕获 id；提交时关闭 expire；绝不在 except 中读已过期属性。

    日志只记记录 ID 与异常类型名：SQLAlchemy 异常文本含 SQL 参数（即 result_json），
    ``logger.exception`` 会把它连同 traceback 写进日志。
    """
    record_id = record.id
    try:
        db.add(record)
        # 保留内存中已赋值字段，避免 commit 后 refresh/lazy-load 竞态。
        previous_expire = db.expire_on_commit
        db.expire_on_commit = False
        try:
            db.commit()
        finally:
            db.expire_on_commit = previous_expire
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "Failed to persist execution record %s exc_type=%s", record_id, type(exc).__name__
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to persist execution record",
        ) from exc
    return record


def _load_auth(config_root: Path, env: str, project: Project) -> AuthLoadResult | None:
    """加载身份表；``cache_scope=f"{repo}/{project}:{env}"``（设计稿 §5.3）。"""
    cache_scope = f"{project.repo}:{project.project_key}:{env}"
    try:
        return load_auth(
            config_root,
            env,
            cache_scope=cache_scope,
        )
    except EngineError as exc:
        _log_engine_error(
            project=project,
            asset_id="-",
            exc=exc,
            what=f"鉴权配置 preflight 失败 env={env}",
        )
        raise HTTPException(
            status_code=map_engine_error_http_status(exc),
            detail=exc.public_message,
        ) from exc


def _engine_for_auth(
    engine: EnginePort, loaded: AuthLoadResult | None, project: Project
) -> EnginePort:
    """按项目白名单切换真实适配器上的插件注册（E1）；Fake 无此方法则原样返回。

    白名单列出但未安装的插件在此暴露（按项目切换，无法在启动期发现）；
    属 preflight 失败，按错误表映射状态码，不写记录。
    """
    plugins = () if loaded is None else loaded.login_plugins
    binder = getattr(engine, "for_login_plugins", None)
    if not callable(binder):
        return engine
    try:
        return binder(plugins)  # type: ignore[no-any-return]
    except EngineError as exc:
        _log_engine_error(
            project=project,
            asset_id="-",
            exc=exc,
            what="登录插件注册失败",
        )
        raise HTTPException(
            status_code=map_engine_error_http_status(exc),
            detail=exc.public_message,
        ) from exc


# 请求 DTO 构造失败的固定外显文案（M1：不回显 str(exc)）。
_INVALID_REQUEST_DETAIL = "执行请求无效：参数或环境配置不合法"


def _log_request_build_error(*, project: Project, asset_id: str, exc: Exception) -> None:
    """请求 DTO 构造失败：只记 ids 与异常类型名。"""
    logger.error(
        "执行请求构造失败 project=%s asset=%s exc_type=%s",
        project.id,
        asset_id,
        type(exc).__name__,
    )


async def run_single_api(
    *,
    db: Session,
    project: Project,
    asset_id: str,
    params: dict[str, Any],
    engine: EnginePort,
    env: str,
    commit_sha: str,
    assets_root: Path,
    config_root: Path,
    timeout_seconds: float | None = None,
    operator: str | None = None,
) -> ExecutionRecord:
    """编排一次单 API 执行；全程使用调用方给定的 ``commit_sha`` 快照目录。

    ``timeout_seconds is None`` 表示请求省略了超时，可回落到环境或默认 30。
    显式传入的数字（包括 30）优先于环境配置。
    """
    resolved = _resolve(
        db,
        project,
        env,
        config_root,
        params=params,
        timeout_seconds=timeout_seconds,
    )
    auth = None if resolved.auth is None else resolved.auth.table
    engine = _engine_for_auth(engine, resolved.auth, project)

    try:
        request = ApiExecutionRequest(
            api_id=asset_id,
            assets_root=Path(assets_root),
            environment=resolved.environment,
            params=resolved.params,
            timeout_seconds=resolved.timeout_seconds,
            auth=auth,
        )
    except (TypeError, ValueError) as exc:
        _log_request_build_error(project=project, asset_id=asset_id, exc=exc)
        raise HTTPException(status_code=422, detail=_INVALID_REQUEST_DETAIL) from exc

    start_time = datetime.now(UTC)
    try:
        outcome = await engine.execute(request)
    except EngineError as exc:
        end_time = datetime.now(UTC)
        _log_engine_error(project=project, asset_id=asset_id, exc=exc)
        if exc.stage == "execution":
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
                env=env,
                commit_sha=commit_sha,
                operator=operator,
                resolved=resolved,
            )
            _persist(db, record)
        raise HTTPException(
            status_code=map_engine_error_http_status(exc),
            detail=exc.public_message,
        ) from exc
    except Exception as exc:
        logger.error(
            "未预期执行异常 project=%s asset=%s exc_type=%s",
            project.id,
            asset_id,
            type(exc).__name__,
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
        env=env,
        commit_sha=commit_sha,
        operator=operator,
        resolved=resolved,
    )
    return _persist(db, record)


def case_result_payload(
    outcome: CaseExecutionOutcome, *, error: dict[str, Any] | None = None
) -> dict[str, Any]:
    """把 Engine 的 Case outcome 原样展开为持久化 / 响应共用的 result 载荷。"""
    payload = outcome.to_dict()
    payload["error"] = error
    return payload


def _system_error_case_payload(
    exc: EngineError, *, case_id: str, elapsed_seconds: float
) -> dict[str, Any]:
    """execution 系统错误的 Case 结果。"""
    error = {"kind": exc.kind, "stage": exc.stage, "message": exc.public_message}
    if exc.partial_outcome is not None:
        return case_result_payload(exc.partial_outcome, error=error)
    return {
        "case_id": case_id,
        "status": "failed",
        "duration_seconds": max(elapsed_seconds, 0.0),
        "steps": [],
        "summary": {"total": 0, "success": 0, "failed": 0, "skipped": 0},
        "error": error,
    }


async def run_case(
    *,
    db: Session,
    project: Project,
    case_id: str,
    params: dict[str, Any],
    engine: EnginePort,
    env: str,
    commit_sha: str,
    assets_root: Path,
    config_root: Path,
    timeout_seconds: float | None = None,
    operator: str | None = None,
) -> ExecutionRecord:
    """编排一次 Case 执行；全程使用调用方给定的 ``commit_sha`` 快照目录。"""
    resolved = _resolve(
        db,
        project,
        env,
        config_root,
        params=params,
        timeout_seconds=timeout_seconds,
    )
    auth = None if resolved.auth is None else resolved.auth.table
    engine = _engine_for_auth(engine, resolved.auth, project)

    try:
        request = CaseExecutionRequest(
            case_id=case_id,
            assets_root=Path(assets_root),
            environment=resolved.environment,
            params=resolved.params,
            timeout_seconds=resolved.timeout_seconds,
            auth=auth,
        )
    except (TypeError, ValueError) as exc:
        _log_request_build_error(project=project, asset_id=case_id, exc=exc)
        raise HTTPException(status_code=422, detail=_INVALID_REQUEST_DETAIL) from exc

    start_time = datetime.now(UTC)
    try:
        outcome = await engine.execute(request)
    except EngineError as exc:
        end_time = datetime.now(UTC)
        _log_engine_error(project=project, asset_id=case_id, exc=exc)
        if exc.stage == "execution":
            payload = _system_error_case_payload(
                exc, case_id=case_id, elapsed_seconds=(end_time - start_time).total_seconds()
            )
            record = _build_record(
                project=project,
                asset_id=case_id,
                status="failed",
                start_time=start_time,
                end_time=end_time,
                result_payload=payload,
                asset_type="case",
                env=env,
                commit_sha=commit_sha,
                operator=operator,
                resolved=resolved,
            )
            _persist(db, record)
        raise HTTPException(
            status_code=map_engine_error_http_status(exc),
            detail=exc.public_message,
        ) from exc
    except Exception as exc:
        logger.error(
            "未预期执行异常 project=%s case=%s exc_type=%s",
            project.id,
            case_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute Case: {type(exc).__name__}",
        ) from exc

    end_time = datetime.now(UTC)
    if not isinstance(outcome, CaseExecutionOutcome):
        raise HTTPException(status_code=500, detail="Engine returned an invalid outcome")

    record = _build_record(
        project=project,
        asset_id=case_id,
        status=outcome.status,
        start_time=start_time,
        end_time=end_time,
        result_payload=case_result_payload(outcome),
        asset_type="case",
        env=env,
        commit_sha=commit_sha,
        operator=operator,
        resolved=resolved,
    )
    return _persist(db, record)


def _resolve(
    db: Session,
    project: Project,
    env: str,
    config_root: Path,
    *,
    params: dict[str, Any],
    timeout_seconds: float | None,
) -> ResolvedRunConfig:
    """冻结本次运行材料。配置错误在进入 Engine 之前返回，不写记录。"""
    return resolve_run_config(
        db,
        project,
        env,
        config_root,
        request_params=params,
        request_timeout=timeout_seconds,
    )
