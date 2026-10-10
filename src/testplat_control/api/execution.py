"""执行记录路由"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement
from sqlalchemy.orm import Session

from testplat_control.api.schemas import (
    ExecutionRecordDetailResponse,
    ExecutionRecordListResponse,
)
from testplat_control.database.models import ExecutionRecord, Project
from testplat_control.database.session import get_db

router = APIRouter(tags=["execution"])

_ORDERABLE = {
    "start_time": ExecutionRecord.start_time,
    "end_time": ExecutionRecord.end_time,
    "duration": ExecutionRecord.duration,
    "status": ExecutionRecord.status,
    "asset_id": ExecutionRecord.asset_id,
}


def _get_project(db: Session, project_id: str) -> Project:
    """读取项目，不存在时返回 404。"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _resolve_order(order_by: str) -> ColumnElement:
    """把 order_by 解析成排序表达式。

    支持 ``-start_time``、``+duration``、``start_time_asc``、``start_time_desc``、
    ``start_time:asc`` 和 ``start_time desc``。单独写 ``start_time`` 时为降序，
    与默认排序一致。

    Args:
        order_by: 查询参数。

    Returns:
        SQLAlchemy 排序表达式。

    Raises:
        HTTPException: 字段或方向无法识别时返回 422。
    """
    raw = order_by.strip() or "-start_time"
    descending = False
    name = raw
    direction: str | None = None

    if " " in raw:
        name, direction = raw.split(None, 1)
    elif raw.startswith("-"):
        descending = True
        name = raw[1:]
    elif raw.startswith("+"):
        name = raw[1:]
    elif raw.endswith("_desc"):
        descending = True
        name = raw[: -len("_desc")]
    elif raw.endswith("_asc"):
        name = raw[: -len("_asc")]
    elif ":" in raw:
        name, direction = raw.split(":", 1)
    elif name == "start_time":
        descending = True

    if direction is not None:
        direction = direction.strip().lower()
        if direction not in {"asc", "desc"}:
            raise HTTPException(status_code=422, detail=f"Invalid order_by '{order_by}'")
        descending = direction == "desc"

    column = _ORDERABLE.get(name.strip())
    if column is None:
        raise HTTPException(status_code=422, detail=f"Invalid order_by '{order_by}'")
    return column.desc() if descending else column.asc()


@router.get(
    "/projects/{project_id}/execution-records",
    response_model=list[ExecutionRecordListResponse],
)
async def list_execution_records(
    project_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: str | None = None,
    asset_id: str | None = None,
    order_by: str = "-start_time",
    db: Session = Depends(get_db),
) -> list[ExecutionRecordListResponse]:
    """获取项目的执行记录。

    可按 ``status``、``asset_id`` 过滤。默认按 ``start_time`` 降序，并用
    ``skip`` / ``limit`` 分页。

    Args:
        project_id: 项目 ID。
        skip: 跳过的记录数。
        limit: 返回的最大记录数。
        status: 按执行状态精确过滤，例如 ``success``。
        asset_id: 按资产 ID 精确过滤。
        order_by: 排序，默认 ``-start_time``。
        db: 数据库会话。

    Returns:
        执行记录列表项。

    Raises:
        HTTPException: 项目不存在返回 404；``order_by`` 无法识别返回 422。
    """
    _get_project(db, project_id)
    query = db.query(ExecutionRecord).filter(ExecutionRecord.project_id == project_id)
    if status:
        query = query.filter(ExecutionRecord.status == status)
    if asset_id:
        query = query.filter(ExecutionRecord.asset_id == asset_id)

    records = query.order_by(_resolve_order(order_by)).offset(skip).limit(limit).all()
    return [ExecutionRecordListResponse.from_model(record) for record in records]


@router.get(
    "/projects/{project_id}/execution-records/{record_id}",
    response_model=ExecutionRecordDetailResponse,
)
async def get_execution_record(
    project_id: str,
    record_id: str,
    db: Session = Depends(get_db),
) -> ExecutionRecordDetailResponse:
    """获取执行记录详情。

    ``result`` 为解析后的对象。结果里若有 ``request`` / ``response``，会同时
    出现在对应字段。``display`` 提供格式化的起止时间和耗时。

    Args:
        project_id: 项目 ID。
        record_id: 记录 ID。
        db: 数据库会话。

    Returns:
        执行记录详情。

    Raises:
        HTTPException: 项目或记录不存在时返回 404。
    """
    _get_project(db, project_id)
    record = (
        db.query(ExecutionRecord)
        .filter(
            ExecutionRecord.id == record_id,
            ExecutionRecord.project_id == project_id,
        )
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Execution record not found")
    return ExecutionRecordDetailResponse.from_model(record)
