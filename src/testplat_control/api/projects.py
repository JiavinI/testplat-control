"""项目管理路由"""

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from testplat_control.api.schemas import (
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
)
from testplat_control.database.models import Project
from testplat_control.database.session import get_db

router = APIRouter(prefix="/projects", tags=["projects"])

DUPLICATE_PROJECT_NAME = "项目名称已存在"
PROJECT_HAS_EXECUTION_RECORDS = "项目存在执行记录，无法删除"


def _integrity_text(exc: IntegrityError) -> str:
    """拼出约束错误原文，用来区分唯一约束和外键约束。"""
    parts = [str(exc)]
    orig = getattr(exc, "orig", None)
    if orig is not None:
        parts.append(str(orig))
    return " ".join(parts).lower()


def _commit_or_conflict(db: Session, *, deleting: bool = False) -> None:
    """提交项目变更，并把已知约束冲突映射为 409。

    名称唯一约束返回「项目名称已存在」。删除时若仍有执行记录引用该项目，
    外键约束返回「项目存在执行记录，无法删除」，不级联删除历史。
    无法归类的完整性错误在回滚后继续抛出。

    Args:
        db: 数据库会话
        deleting: 当前是否在删除项目

    Raises:
        HTTPException: 名称重复，或删除时仍有执行记录
        IntegrityError: 无法归类的约束错误
    """
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        text = _integrity_text(exc)
        if "unique" in text or "projects.name" in text:
            raise HTTPException(status_code=409, detail=DUPLICATE_PROJECT_NAME) from exc
        if deleting and ("foreign key" in text or "foreign_key" in text):
            raise HTTPException(
                status_code=409,
                detail=PROJECT_HAS_EXECUTION_RECORDS,
            ) from exc
        raise


@router.post("", response_model=ProjectResponse)
async def create_project(
    project: ProjectCreate,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    """创建新项目

    Args:
        project: 项目创建请求
        db: 数据库会话

    Returns:
        ProjectResponse: 创建的项目

    Raises:
        HTTPException: 项目名称已存在时返回 409
    """
    project_id = str(uuid4())
    now = datetime.utcnow()

    db_project = Project(
        id=project_id,
        name=project.name,
        env=project.env,
        assets_root=project.assets_root,
        config_root=project.config_root,
        created_at=now,
        updated_at=now,
    )

    db.add(db_project)
    _commit_or_conflict(db)
    db.refresh(db_project)

    return ProjectResponse.model_validate(db_project)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[ProjectResponse]:
    """列出所有项目 (分页)

    Args:
        skip: 跳过的项目数
        limit: 返回的最大项目数
        db: 数据库会话

    Returns:
        list[ProjectResponse]: 项目列表
    """
    projects = db.query(Project).offset(skip).limit(limit).all()
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    """获取项目详情

    Args:
        project_id: 项目ID
        db: 数据库会话

    Returns:
        ProjectResponse: 项目信息

    Raises:
        HTTPException: 项目不存在时返回 404
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return ProjectResponse.model_validate(project)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    project: ProjectUpdate,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    """更新项目

    Args:
        project_id: 项目ID
        project: 项目更新请求
        db: 数据库会话

    Returns:
        ProjectResponse: 更新后的项目

    Raises:
        HTTPException: 项目不存在时返回 404；名称与其他项目重复时返回 409
    """
    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")

    update_data = project.model_dump(exclude_unset=True)
    update_data["updated_at"] = datetime.utcnow()

    for key, value in update_data.items():
        setattr(db_project, key, value)

    _commit_or_conflict(db)
    db.refresh(db_project)

    return ProjectResponse.model_validate(db_project)


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """删除项目

    Args:
        project_id: 项目ID
        db: 数据库会话

    Returns:
        dict: 删除结果

    Raises:
        HTTPException: 项目不存在时返回 404；仍有执行记录时返回 409
    """
    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")

    db.delete(db_project)
    _commit_or_conflict(db, deleting=True)

    return {"message": "Project deleted successfully"}
