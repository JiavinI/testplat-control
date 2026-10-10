"""执行记录路由"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from testplat_control.api.schemas import ExecutionRecordResponse
from testplat_control.database.session import get_db
from testplat_control.database.models import ExecutionRecord, Project


router = APIRouter(tags=["execution"])


@router.get("/projects/{project_id}/execution-records", response_model=list[ExecutionRecordResponse])
async def list_execution_records(
    project_id: str,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[ExecutionRecordResponse]:
    """获取项目的执行记录 (分页)

    Args:
        project_id: 项目ID
        skip: 跳过的记录数
        limit: 返回的最大记录数
        db: 数据库会话

    Returns:
        list[ExecutionRecordResponse]: 执行记录列表

    Raises:
        HTTPException: 项目不存在时返回 404
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    records = (
        db.query(ExecutionRecord)
        .filter(ExecutionRecord.project_id == project_id)
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [ExecutionRecordResponse.model_validate(r) for r in records]


@router.get("/projects/{project_id}/execution-records/{record_id}", response_model=ExecutionRecordResponse)
async def get_execution_record(
    project_id: str,
    record_id: str,
    db: Session = Depends(get_db),
) -> ExecutionRecordResponse:
    """获取执行记录详情

    Args:
        project_id: 项目ID
        record_id: 记录ID
        db: 数据库会话

    Returns:
        ExecutionRecordResponse: 执行记录

    Raises:
        HTTPException: 记录不存在时返回 404
    """
    record = db.query(ExecutionRecord).filter(ExecutionRecord.id == record_id).first()

    if not record or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Execution record not found")

    return ExecutionRecordResponse.model_validate(record)
