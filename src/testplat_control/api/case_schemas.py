"""Case 相关的 HTTP 契约（OpenAPI 的权威来源）。

本模块只描述**形状**，不解释语义：

- 步骤 / Case 结果的字段与 Engine 0.2 的 ``StepOutcome`` / ``CaseExecutionOutcome.to_dict()``
  一一对应，``summary`` 由 Engine 计算，Control 不重算、不修正。
- Case 资产详情只含文件级元信息。Engine 0.2 没有公开的 Case 描述/摘要接口
  （loader 只在 Engine 内部子模块），而 Control 不得维护第二套 Case 语义解析器，
  所以这里**不**返回 name/tags/steps 等需要理解 YAML 语义才能得到的内容。
  Engine 将来公开描述接口后，应在这里新增显式的 ``definition`` 字段（而不是塞进 dict）。

``request`` / ``response`` / ``headers`` / ``body`` 来自被测系统，天然是自由 JSON，
这是契约中仅有的开放位置；其余字段全部是有类型的。这些值在 Engine 的 DTO 构造期
已递归脱敏，Control 原样转发，不再次加工。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from testplat_control.api.schemas import (
    ExecutionAuth,
    ExecutionDisplay,
    format_duration,
    format_time,
)

StepStatus = Literal["success", "failed", "skipped"]
CaseStatus = Literal["success", "failed"]


class CaseStepRequest(BaseModel):
    """步骤实际发出的请求快照（已脱敏）。变量解析失败的步骤没有请求（为 null）。

    Phase 3.3b：``body_type`` 默认 json（A8）；``query`` 类型请求的参数在 ``query`` 字段，
    不进 ``url``（Q8）。
    """

    model_config = ConfigDict(extra="allow")

    method: str = Field(..., description="HTTP 方法")
    url: str = Field(..., description="完整请求 URL")
    headers: dict[str, Any] = Field(default_factory=dict, description="已脱敏的请求头")
    body: Any | None = Field(None, description="已脱敏的请求体（自由 JSON）")
    body_type: str = Field(
        default="json",
        description="请求体类型 json/form/query/raw；未声明资产时仍为 json（A8）",
    )
    query: dict[str, Any] | None = Field(
        None, description="query 类型请求的参数对象（已脱敏）；其它类型为 null/缺省"
    )

    @model_serializer(mode="wrap")
    def _omit_null_query(self, handler):  # noqa: ANN001, ANN201
        """与 Engine 快照对齐：非 query 类型不输出 query 键（避免 API 多出 null）。"""
        data = handler(self)
        if isinstance(data, dict) and data.get("query") is None:
            data.pop("query", None)
        return data


class CaseStepResponse(BaseModel):
    """步骤收到的响应快照（已脱敏）。"""

    model_config = ConfigDict(extra="allow")

    status_code: int = Field(..., description="HTTP 状态码")
    headers: dict[str, Any] = Field(default_factory=dict, description="已脱敏的响应头")
    body: Any | None = Field(None, description="已安全化的响应体（自由 JSON）")


class CaseStepError(BaseModel):
    """步骤级业务错误（assertion / variable_resolution 等），或系统错误对应的步骤错误。

    ``kind`` 是开放字符串：业务错误的 kind 由 Engine 的步骤执行器定义
    （目前有 ``assertion``、``variable_resolution``，系统错误则为 timeout/transport/internal）。
    """

    model_config = ConfigDict(extra="allow")

    kind: str = Field(..., description="错误类别")
    message: str = Field(..., description="面向用户的安全说明，不含秘密")
    stage: Literal["preflight", "execution"] | None = Field(
        None, description="仅系统错误携带；Case 开始后的系统错误恒为 execution"
    )
    step_id: str | None = Field(None, description="variable_resolution：出错的步骤")
    path: str | None = Field(None, description="variable_resolution：无法解析的引用路径")


class CaseStepResult(BaseModel):
    """单个声明步骤的结果；顺序与 Case 资产 steps 声明顺序一一对应。"""

    step_id: str = Field(..., description="步骤 ID（Case 内唯一）")
    name: str | None = Field(None, description="步骤展示名；缺省时前端回退到 step_id")
    type: str = Field(..., description="步骤类型；第一批恒为 api")
    status: StepStatus = Field(..., description="success / failed / skipped")
    duration_seconds: float = Field(..., ge=0, description="步骤耗时（秒）；skipped 恒为 0")
    request: CaseStepRequest | None = Field(None, description="请求快照；skipped/变量失败为 null")
    response: CaseStepResponse | None = Field(None, description="响应快照；skipped/变量失败为 null")
    error: CaseStepError | None = Field(None, description="failed 步骤的安全错误；其余为 null")
    output: str | None = Field(None, description="成功步骤声明的 output alias 名（不含响应值）")
    skip_reason: Literal["fail_fast", "login_failed"] | None = Field(
        None,
        description=(
            "仅 skipped 步骤：fail_fast=前序业务/系统失败；login_failed=前序登录失败（H4）"
        ),
    )
    # H3：显式声明而不是改成 extra="allow"——本模型对未知字段静默丢弃，
    # 漏声明会让 Engine 0.3 的步骤 auth 在响应和历史详情里消失。
    auth: ExecutionAuth | None = Field(
        None,
        description=(
            "步骤实际使用的身份（Phase 3.3d 九键）；"
            "匿名、skipped、login_failed 步骤的 request/response 为 null 时仍可带 login_ref（A6）"
        ),
    )


class CaseSummary(BaseModel):
    """步骤计数汇总，由 Engine 根据步骤结果计算。"""

    total: int = Field(..., ge=0)
    success: int = Field(..., ge=0)
    failed: int = Field(..., ge=0)
    skipped: int = Field(..., ge=0)


class CaseSystemError(BaseModel):
    """Case 执行阶段系统错误（timeout / transport / internal）的外显信息。

    只出现在 execution 系统错误保存的历史记录里；``log_reason`` 永不进入此处。
    """

    kind: Literal["timeout", "transport", "internal"] = Field(..., description="系统错误类别")
    stage: Literal["execution"] = Field(..., description="恒为 execution：preflight 不保存记录")
    message: str = Field(..., description="安全的公开说明")


class CaseResult(BaseModel):
    """Case 完整结果：run 响应与历史详情共用同一形状。

    - 业务 success / failed：``error`` 为 null，``steps`` 来自 Engine 的 outcome。
    - execution 系统错误（只在历史里出现）：``status=failed``，``steps`` 来自异常携带的
      ``partial_outcome``（前序 success、当前 failed、其后 skipped），``error`` 说明系统错误。
    - Phase 3.3b：``logins`` 只在 Case / 单 API 结果顶层（A7）；无登录时仍为 ``[]``（A8）。
    """

    case_id: str = Field(..., description="Case ID")
    status: CaseStatus = Field(..., description="success 当且仅当全部步骤 success")
    duration_seconds: float = Field(..., ge=0, description="Engine 计时的 Case 总耗时（秒）")
    steps: list[CaseStepResult] = Field(..., description="按声明顺序的步骤结果")
    summary: CaseSummary = Field(..., description="步骤计数汇总")
    error: CaseSystemError | None = Field(None, description="仅 execution 系统错误记录非 null")
    logins: list[dict[str, Any]] = Field(
        default_factory=list,
        description="本次执行的登录记录（已脱敏）；无登录时为 []（A8）",
    )


class CaseRunRequest(BaseModel):
    """运行 Case 的请求体。

    ``env`` 必填且须在项目 ``envs`` 内。``params`` 覆盖 Case 默认参数。
    """

    env: str = Field(..., min_length=1, description="运行环境（须在项目 envs 内）")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="覆盖 Case 默认参数的顶层键值（自由 JSON；不得放秘密）",
    )


class CaseRunResponse(BaseModel):
    """Case 运行响应。业务 failed 同样是 HTTP 200，``status`` 为 failed。

    系统错误（timeout/transport/internal）与 preflight 错误不使用本响应，
    而是沿用 Phase 2.5 的 ``{"detail": "..."}`` 错误体与状态码映射。
    """

    record_id: str = Field(..., description="执行记录 ID，可用于历史详情")
    status: CaseStatus = Field(..., description="Case 状态")
    duration: float | None = Field(None, description="Control 侧测得的执行时长（秒）")
    result: CaseResult = Field(..., description="完整 Case / 步骤结果")
    commit_sha: str | None = Field(None, description="本次执行固定使用的 commit SHA")


class CaseAssetDetailResponse(BaseModel):
    """Case 资产详情：仅文件级元信息（见模块文档字符串关于摘要来源的说明）。"""

    case_id: str = Field(..., description="Case ID，由规范路径推导，例如 case.demo.login")
    path: str = Field(..., description="相对 assets_root 的路径（POSIX 分隔符）")
    file_name: str = Field(..., description="文件名，例如 login.case.yaml")
    size_bytes: int = Field(..., ge=0, description="文件大小（字节）")
    modified_at: datetime = Field(..., description="文件最后修改时间（UTC）")


class CaseExecutionRecordDetailResponse(BaseModel):
    """Case 历史详情：与通用执行记录详情同源，但 ``result`` 有明确 schema。

    通用端点 ``/projects/{id}/execution-records/{record_id}`` 对 Case 记录仍然可用且不变
    （``result`` 为未约束对象，``request``/``response`` 为 null）；本端点供前端稳定消费步骤数据。
    """

    id: str = Field(..., description="记录 ID")
    project_id: str = Field(..., description="项目 ID")
    asset_id: str = Field(..., description="Case ID")
    asset_type: Literal["case"] = Field(..., description="恒为 case")
    status: str = Field(..., description="执行状态：success / failed")
    start_time: datetime = Field(..., description="开始时间")
    end_time: datetime | None = Field(None, description="结束时间")
    duration: float | None = Field(None, description="执行时长（秒）")
    display: ExecutionDisplay = Field(..., description="格式化后的时间与耗时")
    result: CaseResult | None = Field(
        None, description="Case 结果；存档缺失或无法按 schema 解析时为 null"
    )
    env: str | None = Field(None, description="运行环境")
    commit_sha: str | None = Field(None, description="执行所用 commit SHA")
    repo: str | None = Field(None, description="仓库键")
    operator: str | None = Field(None, description="操作人；4.0 恒为 null")

    @classmethod
    def from_model(
        cls, record: Any, result: CaseResult | None
    ) -> CaseExecutionRecordDetailResponse:
        """由 ExecutionRecord 与已解析的 CaseResult 构造详情。"""
        duration = None if record.duration is None else float(record.duration)
        return cls(
            id=record.id,
            project_id=record.project_id,
            asset_id=record.asset_id,
            asset_type="case",
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
            env=getattr(record, "env", None),
            commit_sha=getattr(record, "commit_sha", None),
            repo=getattr(record, "repo", None),
            operator=getattr(record, "operator", None),
        )
