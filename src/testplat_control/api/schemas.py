"""Pydantic 请求/响应模型"""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


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


_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_result_json(raw: str | None) -> dict[str, Any] | None:
    """把执行记录里的 result_json 解析成字典。

    空字符串和 JSON ``null`` 视为没有结果。解析失败时不抛错，返回带
    ``parse_error`` 的字典。非对象 JSON 会包进 ``value``，保证结果始终是字典。

    Args:
        raw: 数据库中的 result_json。

    Returns:
        解析后的字典；没有结果时返回 None。
    """
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
    """把秒数格式化成可读耗时，例如 ``250ms``、``1.50s``、``1m 30.50s``。"""
    if seconds is None:
        return None
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}m {rest:.2f}s"


class ExecutionRecordListResponse(BaseModel):
    """执行记录列表项。"""

    id: str = Field(..., description="记录ID")
    asset_id: str = Field(..., description="资产ID")
    status: str = Field(..., description="执行状态")
    start_time: datetime = Field(..., description="开始时间")
    duration: float | None = Field(None, description="执行时长（秒）")

    @classmethod
    def from_model(cls, record: Any) -> "ExecutionRecordListResponse":
        """从 ExecutionRecord 构造列表项。

        Args:
            record: 数据库执行记录。

        Returns:
            列表响应。
        """
        duration = None if record.duration is None else float(record.duration)
        return cls(
            id=record.id,
            asset_id=record.asset_id,
            status=record.status,
            start_time=record.start_time,
            duration=duration,
        )

    @classmethod
    def from_orm(cls, record: Any) -> "ExecutionRecordListResponse":
        """``from_model`` 的别名，兼容旧的 from_orm 调用。"""
        return cls.from_model(record)


class ExecutionAuth(BaseModel):
    """一次 API 请求实际使用的身份（Phase 3.3a，Engine 0.3 公开 ``auth`` 字段，Q1）。

    只含身份名与 header **名**，永不含秘密值；匿名执行时整个字段为 null。
    ``extra="forbid"``：Engine 的公开 auth 恰好三个键，多出的键说明契约漂移，宁可解析失败。
    """

    model_config = ConfigDict(extra="forbid")

    identity: str = Field(..., description="身份名，例如 admin")
    header_names: list[str] = Field(..., description="注入的凭证 header 名（不含值）")
    overridden_headers: list[str] = Field(
        ..., description="被凭证覆盖的资产 header 名（资产里的原始写法）"
    )


def parse_execution_auth(result: dict[str, Any] | None) -> ExecutionAuth | None:
    """从结果字典中取出公开 ``auth``；缺失（旧记录）或形状不符时返回 None，不让详情 500。"""
    if not isinstance(result, dict):
        return None
    raw = result.get("auth")
    if raw is None:
        return None
    try:
        return ExecutionAuth.model_validate(raw)
    except ValidationError:
        return None


class ExecutionDisplay(BaseModel):
    """详情页使用的格式化时间与耗时。"""

    start_time: str = Field(..., description="开始时间，YYYY-MM-DD HH:MM:SS")
    end_time: str | None = Field(None, description="结束时间，YYYY-MM-DD HH:MM:SS")
    duration: str | None = Field(None, description="可读耗时")


class ExecutionRecordDetailResponse(BaseModel):
    """执行记录详情。``result`` 是解析后的结果，而不是原始 JSON 字符串。"""

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
        None, description="单 API 结果中的身份信息（Phase 3.3a）；匿名、Case 记录或旧记录为 null"
    )

    @classmethod
    def from_model(cls, record: Any) -> "ExecutionRecordDetailResponse":
        """从 ExecutionRecord 构造详情，并安全解析 result_json。

        Args:
            record: 数据库执行记录。

        Returns:
            详情响应。result_json 无法解析时，``result`` 含 ``parse_error``。
        """
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
            auth=parse_execution_auth(result),
        )

    @classmethod
    def from_orm(cls, record: Any) -> "ExecutionRecordDetailResponse":
        """``from_model`` 的别名，兼容旧的 from_orm 调用。"""
        return cls.from_model(record)
