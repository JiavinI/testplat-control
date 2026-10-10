"""数据库模型定义"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Project(Base):
    """项目配置表"""

    __tablename__ = "projects"

    id: str = Column(String(36), primary_key=True)
    name: str = Column(String(255), nullable=False, unique=True)
    env: str = Column(String(50), nullable=False)  # test/staging/prod
    assets_root: str = Column(String(500), nullable=False)
    config_root: str = Column(String(500), nullable=False)
    created_at: datetime = Column(DateTime, nullable=False)
    updated_at: datetime = Column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return (
            f"Project(id={self.id!r}, name={self.name!r}, env={self.env!r}, "
            f"created_at={self.created_at!r}, updated_at={self.updated_at!r})"
        )


class ExecutionRecord(Base):
    """执行记录表"""

    __tablename__ = "execution_records"

    id: str = Column(String(36), primary_key=True)
    project_id: str = Column(String(36), ForeignKey("projects.id"), nullable=False)
    asset_type: str = Column(String(50), nullable=False)  # "api" or "case"
    asset_id: str = Column(String(255), nullable=False)
    status: str = Column(String(50), nullable=False)  # "running"/"success"/"failed"
    start_time: datetime = Column(DateTime, nullable=False)
    end_time: datetime = Column(DateTime, nullable=True)
    duration: float = Column(Float, nullable=True)
    result_json: str = Column(String(65535), nullable=True)  # 完整的执行结果 JSON

    def __repr__(self) -> str:
        return (
            f"ExecutionRecord(id={self.id!r}, project_id={self.project_id!r}, "
            f"asset_type={self.asset_type!r}, status={self.status!r}, "
            f"start_time={self.start_time!r}, end_time={self.end_time!r})"
        )
