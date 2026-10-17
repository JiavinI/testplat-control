"""平台 / 项目坐标和配置归属；所有配置入口与运行统一解析。"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from testplat_control.database.models import Project, WorkspaceBinding


def binding_for(db: Session, project: Project) -> WorkspaceBinding | None:
    return db.get(WorkspaceBinding, project.id)


def configuration_project(db: Session, project: Project) -> Project:
    binding = binding_for(db, project)
    if binding is None or binding.configuration_project_id == project.id:
        return project
    owner = db.get(Project, binding.configuration_project_id)
    if owner is None or (owner.archived and not project.archived) or owner.repo != project.repo:
        raise HTTPException(status_code=422, detail="平台配置归属不可用，请同步仓库")
    owner_binding = binding_for(db, owner)
    if owner_binding and owner_binding.configuration_project_id != owner.id:
        raise HTTPException(status_code=422, detail="不支持多层配置归属")
    return owner


def workspace_response(db: Session, project: Project) -> dict[str, str] | None:
    binding = binding_for(db, project)
    if binding is None:
        return None
    return {
        "platform": binding.platform,
        "platform_name": binding.platform_name,
        "project": binding.business_project,
        "project_name": binding.business_project_name,
        "configuration_project_id": binding.configuration_project_id,
    }
