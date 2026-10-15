"""资产信息查询路由（读当前 SHA 快照）。"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from testplat_control.database.session import get_db
from testplat_control.services.asset_service import AssetService
from testplat_control.services.project_access import (
    ensure_snapshot_dirs,
    get_project,
    get_repos_config,
)

router = APIRouter(prefix="/repos/{repo}/projects/{project}", tags=["assets"])


class AssetNodeResponse(BaseModel):
    """资产树节点响应"""

    id: str = Field(..., description="唯一标识")
    name: str = Field(..., description="显示名称")
    type: str = Field(..., description="类型: directory 或 file")
    path: str = Field(..., description="相对路径")
    children: list["AssetNodeResponse"] | None = Field(None, description="子节点 (仅目录)")
    metadata: dict[str, Any] | None = Field(None, description="文件元数据 (仅文件)")

    model_config = ConfigDict(from_attributes=True)


AssetNodeResponse.model_rebuild()


class AssetDetailsResponse(BaseModel):
    """资产详情响应"""

    id: str = Field(..., description="唯一标识")
    name: str = Field(..., description="显示名称")
    type: str = Field(..., description="类型: directory 或 file")
    path: str = Field(..., description="相对路径")
    metadata: dict[str, Any] | None = Field(None, description="文件元数据")

    model_config = ConfigDict(from_attributes=True)


@router.get("/assets", response_model=AssetNodeResponse)
async def get_assets_tree(
    repo: str,
    project: str,
    request: Request,
    db: Session = Depends(get_db),
) -> AssetNodeResponse:
    """获取项目的资产树（当前 commit 快照）。"""
    row = get_project(db, repo, project)
    _, assets_root, _ = ensure_snapshot_dirs(get_repos_config(request), row)
    tree = AssetService(assets_root).scan_assets()
    return AssetNodeResponse.model_validate(tree)


@router.get("/assets/{asset_id}", response_model=AssetDetailsResponse)
async def get_asset_details(
    repo: str,
    project: str,
    asset_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> AssetDetailsResponse:
    """获取单个资产详情。"""
    row = get_project(db, repo, project)
    _, assets_root, _ = ensure_snapshot_dirs(get_repos_config(request), row)
    asset = AssetService(assets_root).get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetDetailsResponse.model_validate(asset)
