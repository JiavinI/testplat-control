"""Pydantic 请求/响应模型（Phase 4.0）。"""

import json
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)


class ProjectResponse(BaseModel):
    """项目响应（只读；来自 Git 清单）。"""

    id: str = Field(..., description="项目 ID，形如 {repo}/{project}")
    repo: str = Field(..., description="仓库键")
    project: str = Field(..., description="项目键（清单内）")
    name: str = Field(..., description="显示名称")
    envs: list[str] = Field(default_factory=list, description="可选环境列表")
    default_env: str | None = Field(None, description="默认环境")
    archived: bool = Field(False, description="清单中已消失时为 true")
    commit_sha: str | None = Field(None, description="当前同步的 commit SHA")
    created_at: datetime = Field(..., description="首次同步时间")
    updated_at: datetime = Field(..., description="最近同步更新时间")

    @classmethod
    def from_model(cls, project: Any) -> "ProjectResponse":
        return cls(
            id=project.id,
            repo=project.repo,
            project=project.project_key,
            name=project.name,
            envs=list(project.envs or []),
            default_env=project.default_env,
            archived=bool(project.archived),
            commit_sha=project.commit_sha,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class RepoResponse(BaseModel):
    """仓库状态（不含 URL）。"""

    key: str = Field(..., description="仓库键")
    branch: str = Field(..., description="跟踪分支")
    current_sha: str | None = Field(None, description="当前 commit SHA")
    last_sync_at: datetime | None = Field(None, description="最近同步时间")
    last_sync_result: str | None = Field(
        None, description="最近同步结果：ok|network|auth|invalid_manifest|timeout"
    )


class SyncResponse(BaseModel):
    """同步结果（失败时只含类别，不含 git 原文）。"""

    repo: str = Field(..., description="仓库键")
    ok: bool = Field(..., description="是否成功")
    category: str = Field(..., description="ok|network|auth|invalid_manifest|timeout")
    commit_sha: str | None = Field(None, description="成功时为新 SHA；失败时为保留的旧 SHA")


_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_result_json(raw: str | None) -> dict[str, Any] | None:
    """把执行记录里的 result_json 解析成字典。"""
    if raw is None or raw == "":
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"parse_error": "invalid JSON", "raw": raw}
    if parsed is None:
        return None
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


def format_time(value: datetime | None) -> str | None:
    """把时间格式化成 ``YYYY-MM-DD HH:MM:SS``。"""
    if value is None:
        return None
    return value.strftime(_TIME_FORMAT)


def format_duration(seconds: float | None) -> str | None:
    """把秒数格式化成可读耗时。"""
    if seconds is None:
        return None
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}m {rest:.2f}s"


def derive_login_failed(result_json: str | None) -> bool:
    """从 result_json 判断列表项是否应标记 login_failed。"""
    try:
        result = parse_result_json(result_json)
        if not isinstance(result, dict):
            return False
        error = result.get("error")
        if isinstance(error, dict) and error.get("kind") == "login_failed":
            return True
        steps = result.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                step_error = step.get("error")
                if isinstance(step_error, dict) and step_error.get("kind") == "login_failed":
                    return True
        return False
    except Exception:
        return False


class ExecutionRecordListResponse(BaseModel):
    """执行记录列表项。"""

    id: str = Field(..., description="记录ID")
    asset_id: str = Field(..., description="资产ID")
    status: str = Field(..., description="执行状态")
    start_time: datetime = Field(..., description="开始时间")
    duration: float | None = Field(None, description="执行时长（秒）")
    login_failed: bool = Field(
        False,
        description="结果中是否含 login_failed",
    )
    env: str | None = Field(None, description="运行时选择的环境")
    commit_sha: str | None = Field(None, description="执行所用 commit SHA")
    repo: str | None = Field(None, description="仓库键")
    operator: str | None = Field(None, description="操作人（平台用户名）")
    config_revision: int | None = Field(None, description="启动时冻结的环境 revision")

    @classmethod
    def from_model(cls, record: Any) -> "ExecutionRecordListResponse":
        duration = None if record.duration is None else float(record.duration)
        return cls(
            id=record.id,
            asset_id=record.asset_id,
            status=record.status,
            start_time=record.start_time,
            duration=duration,
            login_failed=derive_login_failed(getattr(record, "result_json", None)),
            env=getattr(record, "env", None),
            commit_sha=getattr(record, "commit_sha", None),
            repo=getattr(record, "repo", None),
            operator=getattr(record, "operator", None),
            config_revision=getattr(record, "config_revision", None),
        )

    @classmethod
    def from_orm(cls, record: Any) -> "ExecutionRecordListResponse":
        return cls.from_model(record)


class ExecutionAuth(BaseModel):
    """一次 API / 步骤实际使用的身份（Phase 3.3d）。"""

    model_config = ConfigDict(extra="forbid")

    identity: str = Field(..., description="身份名，例如 admin")
    kind: str = Field(..., description="凭证 kind：static_headers 或 login")
    tier: str | None = Field(
        None, description="登录档位 generic/configured/plugin；静态 header 为 null"
    )
    header_names: list[str] = Field(..., description="注入的凭证 header 名（不含值）")
    overridden_headers: list[str] = Field(..., description="被凭证覆盖的资产 header 名")
    cookie_names: list[str] = Field(..., description="本次携带的 Cookie 名（不含值）")
    login_ref: int | None = Field(None, description="指向结果顶层 logins 的下标")
    session_source: str | None = Field(
        None,
        description="会话来源：login / execution / cache",
    )
    reauthenticated: bool = Field(
        False,
        description="本步是否触发了 401 重登重发",
    )


def parse_execution_auth(
    result: dict[str, Any] | None, *, record_id: str | None = None
) -> ExecutionAuth | None:
    """从结果字典中取出公开 ``auth``；缺失返回 None。"""
    if not isinstance(result, dict):
        return None
    raw = result.get("auth")
    if raw is None:
        return None
    try:
        return ExecutionAuth.model_validate(raw)
    except ValidationError:
        logger.warning(
            "公开 auth 字段无法解析 record_id=%s",
            record_id if record_id is not None else "-",
        )
        return None


class ExecutionDisplay(BaseModel):
    """详情页使用的格式化时间与耗时。"""

    start_time: str = Field(..., description="开始时间，YYYY-MM-DD HH:MM:SS")
    end_time: str | None = Field(None, description="结束时间，YYYY-MM-DD HH:MM:SS")
    duration: str | None = Field(None, description="可读耗时")


class ExecutionRecordDetailResponse(BaseModel):
    """执行记录详情。"""

    id: str = Field(..., description="记录ID")
    project_id: str = Field(..., description="项目ID")
    asset_id: str = Field(..., description="资产ID")
    asset_type: str = Field(..., description="资产类型")
    status: str = Field(..., description="执行状态")
    start_time: datetime = Field(..., description="开始时间")
    end_time: datetime | None = Field(None, description="结束时间")
    duration: float | None = Field(None, description="执行时长（秒）")
    display: ExecutionDisplay = Field(..., description="格式化后的时间与耗时")
    result: dict[str, Any] | None = Field(None, description="解析后的执行结果")
    request: Any | None = Field(None, description="结果中的请求详情")
    response: Any | None = Field(None, description="结果中的响应详情")
    auth: ExecutionAuth | None = Field(
        None,
        description="单 API 身份；匿名/Case/旧记录为 null",
    )
    env: str | None = Field(None, description="运行时选择的环境")
    commit_sha: str | None = Field(None, description="执行所用 commit SHA")
    repo: str | None = Field(None, description="仓库键")
    operator: str | None = Field(None, description="操作人（平台用户名）")
    config_revision: int | None = Field(None, description="启动时冻结的环境 revision")
    account_revisions: dict[str, int] | None = Field(
        None, description="本次实际账号名到 revision；不含凭据"
    )
    config_snapshot: dict[str, Any] | None = Field(
        None, description="非秘密配置快照；不回查当前环境补全"
    )

    @classmethod
    def from_model(cls, record: Any) -> "ExecutionRecordDetailResponse":
        result = parse_result_json(record.result_json)
        duration = None if record.duration is None else float(record.duration)
        return cls(
            id=record.id,
            project_id=record.project_id,
            asset_id=record.asset_id,
            asset_type=record.asset_type,
            status=record.status,
            start_time=record.start_time,
            end_time=record.end_time,
            duration=duration,
            display=ExecutionDisplay(
                start_time=format_time(record.start_time) or "",
                end_time=format_time(record.end_time),
                duration=format_duration(duration),
            ),
            result=result,
            request=None if result is None else result.get("request"),
            response=None if result is None else result.get("response"),
            auth=parse_execution_auth(result, record_id=getattr(record, "id", None)),
            env=getattr(record, "env", None),
            commit_sha=getattr(record, "commit_sha", None),
            repo=getattr(record, "repo", None),
            operator=getattr(record, "operator", None),
            config_revision=getattr(record, "config_revision", None),
            account_revisions=getattr(record, "account_revisions", None),
            config_snapshot=getattr(record, "config_snapshot", None),
        )

    @classmethod
    def from_orm(cls, record: Any) -> "ExecutionRecordDetailResponse":
        return cls.from_model(record)
