"""执行记录路由（两段式 + env 过滤）。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement
from sqlalchemy.orm import Session

from testplat_control.api.schemas import (
    ExecutionRecordDetailResponse,
    ExecutionRecordListResponse,
)
from testplat_control.database.models import ExecutionRecord
from testplat_control.database.session import get_db
from testplat_control.services.project_access import get_project

router = APIRouter(prefix="/repos/{repo}/projects/{project}", tags=["execution"])

_ORDERABLE = {
    "start_time": ExecutionRecord.start_time,
    "end_time": ExecutionRecord.end_time,
    "duration": ExecutionRecord.duration,
    "status": ExecutionRecord.status,
    "asset_id": ExecutionRecord.asset_id,
}


def _resolve_order(order_by: str) -> ColumnElement:
    """把 order_by 解析成排序表达式。"""
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
    "/execution-records",
    response_model=list[ExecutionRecordListResponse],
)
async def list_execution_records(
    repo: str,
    project: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: str | None = None,
    asset_id: str | None = None,
    asset_type: Literal["api", "case"] | None = None,
    env: str | None = None,
    order_by: str = "-start_time",
    db: Session = Depends(get_db),
) -> list[ExecutionRecordListResponse]:
    """获取项目的执行记录；可按 status / asset_id / asset_type / env 过滤。"""
    row = get_project(db, repo, project)
    query = db.query(ExecutionRecord).filter(ExecutionRecord.project_id == row.id)
    if status:
        query = query.filter(ExecutionRecord.status == status)
    if asset_id:
        query = query.filter(ExecutionRecord.asset_id == asset_id)
    if asset_type:
        query = query.filter(ExecutionRecord.asset_type == asset_type)
    if env:
        query = query.filter(ExecutionRecord.env == env)

    records = query.order_by(_resolve_order(order_by)).offset(skip).limit(limit).all()
    return [ExecutionRecordListResponse.from_model(record) for record in records]


@router.get(
    "/execution-records/{record_id}",
    response_model=ExecutionRecordDetailResponse,
)
async def get_execution_record(
    repo: str,
    project: str,
    record_id: str,
    db: Session = Depends(get_db),
) -> ExecutionRecordDetailResponse:
    """获取执行记录详情。"""
    row = get_project(db, repo, project)
    record = (
        db.query(ExecutionRecord)
        .filter(
            ExecutionRecord.id == record_id,
            ExecutionRecord.project_id == row.id,
        )
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Execution record not found")
    return ExecutionRecordDetailResponse.from_model(record)
