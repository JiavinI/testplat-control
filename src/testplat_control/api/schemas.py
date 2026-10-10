"""Pydantic 请求/响应模型"""

from datetime import datetime
from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    """创建项目的请求模型"""

    name: str = Field(..., min_length=1, description="项目名称")
    env: str = Field(default="test", description="环境")
    assets_root: str = Field(..., min_length=1, description="资产目录")
    config_root: str = Field(..., min_length=1, description="配置目录")


class ProjectUpdate(BaseModel):
    """更新项目的请求模型"""

    name: str | None = Field(None, min_length=1, description="项目名称")
    env: str | None = Field(None, description="环境")
    assets_root: str | None = Field(None, min_length=1, description="资产目录")
    config_root: str | None = Field(None, min_length=1, description="配置目录")


class ProjectResponse(BaseModel):
    """项目响应模型"""

    id: str = Field(..., description="项目ID")
    name: str = Field(..., description="项目名称")
    env: str = Field(..., description="环境")
    assets_root: str = Field(..., description="资产目录")
    config_root: str = Field(..., description="配置目录")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    class Config:
        from_attributes = True


class ExecutionRecordResponse(BaseModel):
    """执行记录响应模型"""

    id: str = Field(..., description="记录ID")
    project_id: str = Field(..., description="项目ID")
    asset_type: str = Field(..., description="资产类型")
    asset_id: str = Field(..., description="资产ID")
    status: str = Field(..., description="执行状态")
    start_time: datetime = Field(..., description="开始时间")
    end_time: datetime | None = Field(None, description="结束时间")
    duration: float | None = Field(None, description="执行时长（秒）")
    result_json: str | None = Field(None, description="执行结果JSON")

    class Config:
        from_attributes = True
