"""资产信息查询路由"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from pathlib import Path

from testplat_control.database.models import Project
from testplat_control.database.session import get_db
from testplat_control.services.asset_service import AssetService

router = APIRouter(prefix="/projects", tags=["assets"])


class AssetNodeResponse(BaseModel):
    """资产树节点响应"""

    id: str = Field(..., description="唯一标识")
    name: str = Field(..., description="显示名称")
    type: str = Field(..., description="类型: directory 或 file")
    path: str = Field(..., description="相对路径")
    children: list["AssetNodeResponse"] | None = Field(
        None, description="子节点 (仅目录)"
    )
    metadata: dict[str, Any] | None = Field(None, description="文件元数据 (仅文件)")

    class Config:
        from_attributes = True


# 更新 forward reference
AssetNodeResponse.model_rebuild()


class AssetDetailsResponse(BaseModel):
    """资产详情响应"""

    id: str = Field(..., description="唯一标识")
    name: str = Field(..., description="显示名称")
    type: str = Field(..., description="类型: directory 或 file")
    path: str = Field(..., description="相对路径")
    metadata: dict[str, Any] | None = Field(None, description="文件元数据")

    class Config:
        from_attributes = True


@router.get("/{project_id}/assets", response_model=AssetNodeResponse)
async def get_assets_tree(
    project_id: str,
    db: Session = Depends(get_db),
) -> AssetNodeResponse:
    """获取项目的资产树

    Args:
        project_id: 项目ID
        db: 数据库会话

    Returns:
        AssetNodeResponse: 资产树根节点

    Raises:
        HTTPException: 项目不存在返回 404
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 创建资产服务并扫描
    service = AssetService(Path(project.assets_root))
    tree = service.scan_assets()

    return AssetNodeResponse.model_validate(tree)


@router.get("/{project_id}/assets/{asset_id}", response_model=AssetDetailsResponse)
async def get_asset_details(
    project_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
) -> AssetDetailsResponse:
    """获取单个资产详情

    Args:
        project_id: 项目ID
        asset_id: 资产ID (如 api.common.health_check)
        db: 数据库会话

    Returns:
        AssetDetailsResponse: 资产详情

    Raises:
        HTTPException: 项目或资产不存在返回 404
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    service = AssetService(Path(project.assets_root))
    asset = service.get_asset(asset_id)

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    return AssetDetailsResponse.model_validate(asset)
