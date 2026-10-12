"""Case 资产详情、运行与历史详情路由。

分工（与 ``services/execution_service.py`` 的模块文档一致）：

- Case 语法校验与执行语义归 Engine；本路由不解析 Case YAML。
- 详情只返回文件级元信息；运行经 ``EnginePort.execute(CaseExecutionRequest)`` 完成；
  记录生命周期与错误映射见 ``execution_service.run_case``。
- 路由与既有 API 资产路由（``/assets/{id}/run``）并列、互不改变：Case 使用 ``/cases/...``。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from testplat_control.api.case_schemas import (
    CaseAssetDetailResponse,
    CaseExecutionRecordDetailResponse,
    CaseResult,
    CaseRunRequest,
    CaseRunResponse,
)
from testplat_control.database.models import ExecutionRecord, Project
from testplat_control.database.session import get_db
from testplat_control.deps import get_engine_port
from testplat_control.ports.engine import EnginePort
from testplat_control.services.case_asset_service import find_case_file
from testplat_control.services.execution_service import run_case

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["cases"])


def _get_project(db: Session, project_id: str) -> Project:
    """读取项目，不存在时返回 404。"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _load_case_result(record: ExecutionRecord) -> CaseResult | None:
    """把 ``result_json`` 解析为 CaseResult；缺失或不符合 schema 返回 None。

    日志只记记录 ID 与异常类型名：``ValidationError`` / ``JSONDecodeError`` 的文本会回显
    存档内容，不得写日志。
    """
    if not record.result_json:
        return None
    try:
        return CaseResult.model_validate(json.loads(record.result_json))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning(
            "Case 执行记录 %s 的 result_json 无法按 CaseResult 解析 exc_type=%s",
            record.id,
            type(exc).__name__,
        )
        return None


@router.get("/{project_id}/cases/{case_id}", response_model=CaseAssetDetailResponse)
async def get_case_detail(
    project_id: str,
    case_id: str,
    db: Session = Depends(get_db),
) -> CaseAssetDetailResponse:
    """获取 Case 资产的文件级元信息。

    不解析 YAML：Engine 0.2 没有公开的 Case 摘要接口，Control 也不维护第二套 Case 解析器。
    只有 ``scenarios`` 下真实存在的 ``.case.yaml`` 文件才会匹配；其他一律 404。

    Raises:
        HTTPException: 项目或 Case 文件不存在返回 404。
    """
    project = _get_project(db, project_id)
    info = find_case_file(Path(project.assets_root), case_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseAssetDetailResponse(
        case_id=info.case_id,
        path=info.path,
        file_name=info.file_name,
        size_bytes=info.size_bytes,
        modified_at=info.modified_at,
    )


@router.post("/{project_id}/cases/{case_id}/run", response_model=CaseRunResponse)
async def run_case_asset(
    project_id: str,
    case_id: str,
    body: CaseRunRequest,
    db: Session = Depends(get_db),
    engine: EnginePort = Depends(get_engine_port),
) -> CaseRunResponse:
    """串行运行一个 Case，并保存执行记录。

    业务成功与业务失败（断言失败、变量解析失败）都返回 HTTP 200 并保存记录，
    失败时后续步骤为 ``skipped``。Engine 的 preflight 错误
    （asset_not_found 404 / invalid_asset、invalid_input、invalid_environment 422）
    不保存记录；execution 阶段系统错误保存 ``failed`` 记录后返回
    504（timeout）/ 502（transport）/ 500（internal）。

    注意：同步请求，会占用连接直到 Case 跑完。Engine 的超时是每步骤超时而非总预算。

    Raises:
        HTTPException: 项目不存在 404；其余按上述错误表映射。
    """
    project = _get_project(db, project_id)
    record = await run_case(
        db=db,
        project=project,
        case_id=case_id,
        params=body.params,
        engine=engine,
    )
    result = _load_case_result(record)
    if result is None or not record.id:
        raise HTTPException(status_code=500, detail="Execution result is not valid")
    duration = None if record.duration is None else float(record.duration)
    return CaseRunResponse(
        record_id=record.id,
        status=result.status,
        duration=duration,
        result=result,
    )


@router.get(
    "/{project_id}/case-execution-records/{record_id}",
    response_model=CaseExecutionRecordDetailResponse,
)
async def get_case_execution_record(
    project_id: str,
    record_id: str,
    db: Session = Depends(get_db),
) -> CaseExecutionRecordDetailResponse:
    """获取 Case 执行记录详情（``result`` 有明确 schema）。

    只匹配 ``asset_type="case"`` 的记录；API 记录请用通用的
    ``/projects/{id}/execution-records/{record_id}``。通用端点对 Case 记录依然可用。

    Raises:
        HTTPException: 项目、记录不存在，或记录不是 Case 记录时返回 404。
    """
    _get_project(db, project_id)
    record = (
        db.query(ExecutionRecord)
        .filter(
            ExecutionRecord.id == record_id,
            ExecutionRecord.project_id == project_id,
            ExecutionRecord.asset_type == "case",
        )
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Execution record not found")
    return CaseExecutionRecordDetailResponse.from_model(record, _load_case_result(record))
