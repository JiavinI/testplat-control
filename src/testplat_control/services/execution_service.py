"""单 API 与 Case 的执行编排。

负责：环境加载、计时、调用 EnginePort、按 stage 写执行记录、映射 HTTP。
不拥有资产 YAML 参数表单校验（仍在路由层）；不直接构造 Adapter。

所有权边界（Phase 3）
---------------------
- **Case 语法与运行语义的权威是 Engine**：Case id 格式、文件路径映射、schema、引用
  校验、步骤执行与 fail-fast 全部发生在 ``EnginePort.execute(request)`` 之内。
  本模块不解析 Case YAML，只把 Engine 返回的 outcome / 异常原样落库和映射为 HTTP。
- Control 只负责：项目与环境（``load_project_environment``）、身份表
  （``load_auth``，Phase 3.3d 含 cache_scope）、调用与计时、
  ``ExecutionRecord`` 持久化、HTTP 状态码映射。

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
from testplat_control.services.env_loader import load_project_environment

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


def _load_environment(project: Project) -> dict[str, Any]:
    """加载项目环境；失败属 Control 侧 preflight，不写记录。"""
    try:
        return load_project_environment(project.config_root, project.env)
    except EngineError as exc:
        _log_engine_error(
            project=project,
            asset_id="-",
            exc=exc,
            what=f"环境配置 preflight 失败 env={project.env}",
        )
        raise HTTPException(
            status_code=map_engine_error_http_status(exc),
            detail=exc.public_message,
        ) from exc


def _load_auth(project: Project) -> AuthLoadResult | None:
    """加载项目环境的身份表与 login_plugins；失败属 Control 侧 preflight，不写记录。

    日志沿用 ``_log_engine_error`` 的安全字段；``public_message`` 由 auth_loader 保证
    只含身份名 / header 名 / 变量名 / 策略名。
    Phase 3.3d：传入 ``cache_scope=f"{project.id}:{project.env}"``，由 Engine 持有缓存；
    Control 不做缓存实现，也不把 scope 写入日志。
    """
    try:
        return load_auth(
            project.config_root,
            project.env,
            cache_scope=f"{project.id}:{project.env}",
        )
    except EngineError as exc:
        _log_engine_error(
            project=project,
            asset_id="-",
            exc=exc,
            what=f"鉴权配置 preflight 失败 env={project.env}",
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
            what=f"登录插件注册失败 env={project.env}",
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
    environment = _load_environment(project)
    loaded = _load_auth(project)
    auth = None if loaded is None else loaded.table
    engine = _engine_for_auth(engine, loaded, project)

    try:
        request = ApiExecutionRequest(
            api_id=asset_id,
            assets_root=Path(project.assets_root),
            environment=environment,
            params=params,
            timeout_seconds=timeout_seconds,
            auth=auth,
        )
    except (TypeError, ValueError) as exc:
        # 请求 DTO 构造失败视为 Control 侧参数/环境不合法；detail 用固定文案（M1）。
        _log_request_build_error(project=project, asset_id=asset_id, exc=exc)
        raise HTTPException(status_code=422, detail=_INVALID_REQUEST_DETAIL) from exc

    start_time = datetime.now(UTC)
    try:
        outcome = await engine.execute(request)
    except EngineError as exc:
        end_time = datetime.now(UTC)
        _log_engine_error(project=project, asset_id=asset_id, exc=exc)
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
        # 日志硬约束：只记类型名，不用 logger.exception（traceback 会带出异常原文）。
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
    )
    return _persist(db, record)


def case_result_payload(
    outcome: CaseExecutionOutcome, *, error: dict[str, Any] | None = None
) -> dict[str, Any]:
    """把 Engine 的 Case outcome 原样展开为持久化 / 响应共用的 result 载荷。

    ``result_json`` 的形状固定为 ``CaseExecutionOutcome.to_dict()`` + ``error``：

    - 业务 success/failed：``error`` 为 ``None``；
    - execution 系统错误：outcome 取自异常携带的 ``partial_outcome``，
      ``error`` 为 ``{kind, stage, message}``（不含 log_reason）。

    摘要（summary）完全由 Engine 计算，Control 不二次推导。
    """
    payload = outcome.to_dict()
    payload["error"] = error
    return payload


def _system_error_case_payload(
    exc: EngineError, *, case_id: str, elapsed_seconds: float
) -> dict[str, Any]:
    """execution 系统错误的 Case 结果：步骤证据只来自异常的安全 ``partial_outcome``。

    Engine 0.2 契约保证 Case 执行阶段的 timeout/transport/internal 都携带 partial；
    若缺失（Engine 缺陷），仍保存 failed 记录但步骤为空，绝不由 Control 伪造步骤。
    """
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
    timeout_seconds: float = 30.0,
) -> ExecutionRecord:
    """编排一次 Case 执行并返回已落库记录（``asset_type="case"``）。

    Control 不校验 Case 语法、不检查文件是否存在：``case_id`` 原样交给 Engine，
    由 Engine 负责路径映射与 schema 校验，并以 preflight 异常返回
    ``asset_not_found / invalid_asset / invalid_input / invalid_environment``。

    记录规则见模块文档字符串：业务 failed 与 execution 系统错误保存，preflight 不保存。

    Args:
        db: 数据库会话。
        project: 已存在的项目。
        case_id: Case ID，例如 ``case.demo.login_then_profile``。
        params: 覆盖 Case 默认参数的顶层键（浅层覆盖由 Engine 完成）。
        engine: 注入的 EnginePort（真实或 Fake）。
        timeout_seconds: **每步骤** HTTP 超时（不是整个 Case 预算）。

    Returns:
        已持久化的 ExecutionRecord。

    Raises:
        HTTPException: 按错误表映射的状态码；detail 仅含安全外显信息。
    """
    environment = _load_environment(project)
    loaded = _load_auth(project)
    auth = None if loaded is None else loaded.table
    engine = _engine_for_auth(engine, loaded, project)

    try:
        request = CaseExecutionRequest(
            case_id=case_id,
            assets_root=Path(project.assets_root),
            environment=environment,
            params=params,
            timeout_seconds=timeout_seconds,
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
    )
    return _persist(db, record)
