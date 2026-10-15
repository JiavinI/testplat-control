"""项目只读路由（Phase 4.0：不再提供 POST/PUT/DELETE）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from testplat_control.api.schemas import ProjectResponse
from testplat_control.database.models import Project
from testplat_control.database.session import get_db
from testplat_control.services.project_access import get_project

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[ProjectResponse]:
    """列出所有项目（含 archived）。"""
    projects = db.query(Project).offset(skip).limit(limit).all()
    return [ProjectResponse.from_model(p) for p in projects]


@router.get("/repos/{repo}/projects/{project}", response_model=ProjectResponse)
async def get_project_detail(
    repo: str,
    project: str,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    """获取单个项目详情。"""
    row = get_project(db, repo, project)
    return ProjectResponse.from_model(row)


@router.get("/projects/{project_id:path}", response_model=ProjectResponse)
async def get_project_by_id(
    project_id: str,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    """兼容扁平 ID ``{repo}/{project}`` 的详情读取。"""
    row = db.query(Project).filter(Project.id == project_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.from_model(row)
