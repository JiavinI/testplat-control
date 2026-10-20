"""场景描述与结果契约；流程规则由 Engine 公开描述和执行入口负责。"""

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


class ScenarioBinding(BaseModel):
    target_path: str
    reference: str
    source_node_id: str | None = None
    value: Any = None
    value_type: Literal["null", "boolean", "integer", "number", "string", "object", "array"]


class ScenarioTrace(BaseModel):
    node_id: str
    parent_id: str | None = None
    asset_id: str
    inputs: dict[str, Any]
    outputs: Any
    bindings: list[ScenarioBinding]
    children: list[CaseStepResult]
    iteration_index: int | None = Field(None, ge=0)
    extracts: list[dict[str, Any]] | None = None
    calculations: list[dict[str, Any]] | None = None
    assertions: list[dict[str, Any]] | None = None
    transforms: list[dict[str, Any]] | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_evidence(self, handler):
        data = handler(self)
        for key in ("iteration_index", "extracts", "calculations", "assertions", "transforms"):
            if key not in self.model_fields_set:
                data.pop(key, None)
        return data


class ScenarioStepDefinition(BaseModel):
    step_id: str
    type: Literal["api", "flow", "map", "extract", "decimal", "assert", "transform"]
    asset_id: str
    name: str | None = None
    params: dict[str, Any]
    output: str | None = None
    identity: str | None = None
    definition: ScenarioDefinition | None = None
    source: str | None = None
    selector: dict[str, Any] | None = None
    cardinality: str | None = None
    value_type: str | None = None
    nullable: bool | None = None
    operation: str | None = None
    operands: Any = None
    scale: int | None = None
    rounding: str | None = None
    path: list[str | int] | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_configuration(self, handler):
        data = handler(self)
        for key in (
            "source",
            "selector",
            "cardinality",
            "value_type",
            "nullable",
            "operation",
            "operands",
            "scale",
            "rounding",
            "path",
        ):
            if key not in self.model_fields_set:
                data.pop(key, None)
        return data


class ScenarioDefinition(BaseModel):
    schema_version: Literal["0.3"]
    id: str
    kind: Literal["case", "flow"]
    name: str | None = None
    params: dict[str, Any]
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    steps: list[ScenarioStepDefinition]


class CaseStepResult(BaseModel):
    """单个声明步骤的结果；顺序与 Case 资产 steps 声明顺序一一对应。"""

    trace: ScenarioTrace | None = None

    @model_serializer(mode="wrap")
    def _omit_legacy_trace(self, handler):
        data = handler(self)
        if self.trace is None:
            data.pop("trace", None)
        return data

    step_id: str = Field(..., description="步骤 ID（同一调用内唯一）")
    name: str | None = Field(None, description="步骤展示名；缺省时前端回退到 step_id")
    type: str = Field(
        ..., description="步骤类型：api / flow / map / extract / decimal / assert / transform"
    )
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

    result_version: Literal["0.3"] | None = None

    @model_serializer(mode="wrap")
    def _omit_legacy_version(self, handler):
        data = handler(self)
        if self.result_version is None:
            data.pop("result_version", None)
        return data

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
    timeout_seconds: float | None = Field(
        None,
        gt=0,
        le=300,
        description="每步 HTTP 超时（秒）。省略则使用环境或默认 30；显式 30 会覆盖环境值",
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
    operator: str | None = Field(None, description="操作人（平台用户名）")
    config_revision: int | None = Field(None, description="启动时冻结的环境 revision")


class CaseAssetDetailResponse(BaseModel):
    """文件元信息；支持描述能力的 Engine 额外提供新版定义。"""

    definition: ScenarioDefinition | None = None

    @model_serializer(mode="wrap")
    def _omit_unavailable_definition(self, handler):
        data = handler(self)
        if self.definition is None:
            data.pop("definition", None)
        return data

    case_id: str = Field(..., description="Case ID，由规范路径推导，例如 case.demo.login")
    path: str = Field(..., description="相对 assets_root 的路径（POSIX 分隔符）")
    file_name: str = Field(..., description="文件名，例如 login.case.yaml")
    size_bytes: int = Field(..., ge=0, description="文件大小（字节）")
    modified_at: datetime = Field(..., description="文件最后修改时间（UTC）")


class CaseExecutionRecordDetailResponse(BaseModel):
    """Case 历史详情：与通用执行记录详情同源，但 ``result`` 有明确 schema。

    通用端点是 ``GET /repos/{repo}/projects/{project}/execution-records/{record_id}``
    （``result`` 为未约束对象）。本端点 ``.../case-execution-records/{record_id}``
    供前端稳定消费步骤数据。旧的 ``/projects/{id}/execution-records/...`` 已移除。
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
    operator: str | None = Field(None, description="操作人（平台用户名）")
    config_revision: int | None = Field(None, description="启动时冻结的环境 revision")
    account_revisions: dict[str, int] | None = Field(
        None, description="本次实际账号名到 revision；不含凭据"
    )
    config_snapshot: dict[str, Any] | None = Field(
        None, description="非秘密配置快照；历史详情不回查当前环境"
    )

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
            config_revision=getattr(record, "config_revision", None),
            account_revisions=getattr(record, "account_revisions", None),
            config_snapshot=getattr(record, "config_snapshot", None),
        )


ScenarioTrace.model_rebuild()
ScenarioStepDefinition.model_rebuild()
