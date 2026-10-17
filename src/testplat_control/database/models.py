"""数据库模型定义（Phase 4.0：Git 用例仓库为数据源）。

无 alembic 迁移：旧表结构（含 ``assets_root`` / ``config_root`` / ``env``）不兼容，
启动时由 ``database.schema_guard`` 检测并提示删除数据库文件。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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


class WorkspaceBinding(Base):
    """显式的平台 / 业务项目运行上下文；配置归属可共享，旧 Project ID 不变。"""

    __tablename__ = "workspace_bindings"

    project_id: str = Column(String(160), ForeignKey("projects.id"), primary_key=True)
    platform: str = Column(String(64), nullable=False)
    platform_name: str = Column(String(128), nullable=False)
    business_project: str = Column(String(64), nullable=False)
    business_project_name: str = Column(String(128), nullable=False)
    configuration_project_id: str = Column(String(160), ForeignKey("projects.id"), nullable=False)


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
    # 4.1a 起写入当前平台用户名；历史行可空。
    operator: str | None = Column(String(255), nullable=True)
    # 启动时冻结的环境 revision；无 Web 环境的历史/兼容路径为空。
    config_revision: int | None = Column(Integer, nullable=True)
    # {账号名: 该账号 revision}。不含凭据。
    account_revisions = Column(JSON, nullable=True)
    # 非秘密配置快照。历史详情只读此列，不回查当前环境。
    config_snapshot = Column(JSON, nullable=True)

    def __repr__(self) -> str:
        return (
            f"ExecutionRecord(id={self.id!r}, project_id={self.project_id!r}, "
            f"asset_type={self.asset_type!r}, status={self.status!r}, "
            f"env={self.env!r}, commit_sha={self.commit_sha!r})"
        )


class PlatformUser(Base):
    """平台操作人。只存密码哈希，没有权限角色字段。"""

    __tablename__ = "platform_users"

    id: str = Column(String(36), primary_key=True)
    username: str = Column(String(64), nullable=False, unique=True)
    password_hash: str = Column(String(255), nullable=False)
    created_at: datetime = Column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return f"PlatformUser(id={self.id!r}, username={self.username!r})"


class PlatformSession(Base):
    """会话只存 token 哈希。注销后 revoked_at 非空即失效。"""

    __tablename__ = "platform_sessions"

    id: str = Column(String(36), primary_key=True)
    token_hash: str = Column(String(64), nullable=False, unique=True)
    user_id: str = Column(String(36), ForeignKey("platform_users.id"), nullable=False)
    expires_at: datetime = Column(DateTime, nullable=False)
    created_at: datetime = Column(DateTime, nullable=False)
    revoked_at: datetime | None = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"PlatformSession(id={self.id!r}, user_id={self.user_id!r})"


class ProjectEnvironment(Base):
    """项目环境。标识 ``env`` 保存后不可改名；启停用 ``enabled``。"""

    __tablename__ = "project_environments"
    __table_args__ = (UniqueConstraint("project_id", "env", name="uq_project_environment"),)

    id: str = Column(String(36), primary_key=True)
    project_id: str = Column(String(160), ForeignKey("projects.id"), nullable=False)
    env: str = Column(String(64), nullable=False)
    enabled: bool = Column(Boolean, nullable=False, default=True)
    api_hosts = Column(JSON, nullable=False, default=dict)
    # None 表示运行时使用平台默认 30 秒，与显式 30 区分。
    timeout_seconds: float | None = Column(Float, nullable=True)
    case_params = Column(JSON, nullable=False, default=dict)
    revision: int = Column(Integer, nullable=False, default=1)
    updated_by: str | None = Column(String(64), nullable=True)
    created_at: datetime = Column(DateTime, nullable=False)
    updated_at: datetime = Column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return (
            f"ProjectEnvironment(project_id={self.project_id!r}, env={self.env!r}, "
            f"enabled={self.enabled!r}, revision={self.revision!r})"
        )


class TestAccount(Base):
    """测试账号。唯一键 (project_id, env, account_name)；凭据只存密文。"""

    __tablename__ = "test_accounts"
    __table_args__ = (
        UniqueConstraint("project_id", "env", "account_name", name="uq_project_env_account"),
    )

    id: str = Column(String(36), primary_key=True)
    project_id: str = Column(String(160), ForeignKey("projects.id"), nullable=False)
    env: str = Column(String(64), nullable=False)
    account_name: str = Column(String(64), nullable=False)
    display_name: str | None = Column(String(255), nullable=True)
    business_role: str | None = Column(String(255), nullable=True)
    login_profile: str = Column(String(128), nullable=False)
    encrypted_credentials: str = Column(Text, nullable=False)
    enabled: bool = Column(Boolean, nullable=False, default=True)
    revision: int = Column(Integer, nullable=False, default=1)
    updated_by: str | None = Column(String(64), nullable=True)
    created_at: datetime = Column(DateTime, nullable=False)
    updated_at: datetime = Column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return (
            f"TestAccount(project_id={self.project_id!r}, env={self.env!r}, "
            f"account_name={self.account_name!r}, enabled={self.enabled!r})"
        )


class ConfigChange(Base):
    """配置变更。凭据只记「已修改」，不落原值。"""

    __tablename__ = "config_changes"

    id: str = Column(String(36), primary_key=True)
    operator: str = Column(String(64), nullable=False)
    project_id: str = Column(String(160), nullable=False)
    env: str = Column(String(64), nullable=False)
    object_type: str = Column(String(32), nullable=False)  # environment | account
    object_name: str = Column(String(64), nullable=False)
    action: str = Column(String(32), nullable=False)  # create | update
    field_names = Column(JSON, nullable=False, default=list)
    # 凭据有变更时为「已修改」，否则为空。
    credential_note: str | None = Column(String(16), nullable=True)
    revision: int = Column(Integer, nullable=False)
    created_at: datetime = Column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return (
            f"ConfigChange(project_id={self.project_id!r}, env={self.env!r}, "
            f"object_name={self.object_name!r}, action={self.action!r})"
        )
