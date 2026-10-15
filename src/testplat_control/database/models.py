"""数据库模型定义（Phase 4.0：Git 用例仓库为数据源）。

无 alembic 迁移：旧表结构（含 ``assets_root`` / ``config_root`` / ``env``）不兼容，
启动时由 ``database.schema_guard`` 检测并提示删除数据库文件。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Repo(Base):
    """已同步的仓库状态（键来自服务端配置，不含 URL）。"""

    __tablename__ = "repos"

    key: str = Column(String(64), primary_key=True)
    branch: str = Column(String(255), nullable=False)
    current_sha: str | None = Column(String(40), nullable=True)
    last_sync_at: datetime | None = Column(DateTime, nullable=True)
    # ok|network|auth|invalid_manifest|timeout
    last_sync_result: str | None = Column(String(32), nullable=True)

    def __repr__(self) -> str:
        return (
            f"Repo(key={self.key!r}, branch={self.branch!r}, "
            f"current_sha={self.current_sha!r}, last_sync_result={self.last_sync_result!r})"
        )


class Project(Base):
    """项目来自清单 upsert；主键 ``{repo}/{project}``。"""

    __tablename__ = "projects"

    id: str = Column(String(160), primary_key=True)  # "{repo}/{project}"
    repo: str = Column(String(64), ForeignKey("repos.key"), nullable=False)
    project_key: str = Column(String(64), nullable=False)
    name: str = Column(String(255), nullable=False)
    envs = Column(JSON, nullable=False, default=list)  # list[str]
    default_env: str | None = Column(String(64), nullable=True)
    archived: bool = Column(Boolean, nullable=False, default=False)
    commit_sha: str | None = Column(String(40), nullable=True)
    created_at: datetime = Column(DateTime, nullable=False)
    updated_at: datetime = Column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return (
            f"Project(id={self.id!r}, name={self.name!r}, repo={self.repo!r}, "
            f"archived={self.archived!r}, commit_sha={self.commit_sha!r})"
        )


class ExecutionRecord(Base):
    """执行记录表；Phase 4.0 增加 env / repo / commit_sha / operator。"""

    __tablename__ = "execution_records"

    id: str = Column(String(36), primary_key=True)
    project_id: str = Column(String(160), ForeignKey("projects.id"), nullable=False)
    asset_type: str = Column(String(50), nullable=False)  # "api" or "case"
    asset_id: str = Column(String(255), nullable=False)
    status: str = Column(String(50), nullable=False)  # "running"/"success"/"failed"
    start_time: datetime = Column(DateTime, nullable=False)
    end_time: datetime = Column(DateTime, nullable=True)
    duration: float = Column(Float, nullable=True)
    result_json: str = Column(String(65535), nullable=True)
    env: str | None = Column(String(64), nullable=True)
    repo: str | None = Column(String(64), nullable=True)
    commit_sha: str | None = Column(String(40), nullable=True)
    # 4.0 恒为 null；4.1 平台登录后填写
    operator: str | None = Column(String(255), nullable=True)

    def __repr__(self) -> str:
        return (
            f"ExecutionRecord(id={self.id!r}, project_id={self.project_id!r}, "
            f"asset_type={self.asset_type!r}, status={self.status!r}, "
            f"env={self.env!r}, commit_sha={self.commit_sha!r})"
        )
