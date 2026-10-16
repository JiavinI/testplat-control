"""单次 API 参数表单与执行路由。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from testplat_control.api.platform_session import require_user
from testplat_control.api.schemas import ExecutionAuth, parse_execution_auth
from testplat_control.database.models import ExecutionRecord
from testplat_control.database.session import get_db
from testplat_control.deps import get_engine_port
from testplat_control.parsers.yaml_parser import YamlParser
from testplat_control.ports.engine import EnginePort
from testplat_control.services.asset_service import AssetNode, AssetService
from testplat_control.services.execution_service import run_single_api
from testplat_control.services.platform_auth import PlatformPrincipal
from testplat_control.services.project_access import (
    ensure_snapshot_dirs,
    get_project,
    get_repos_config,
    require_env,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repos/{repo}/projects/{project}", tags=["run"])

ParamType = Literal["string", "number", "boolean"]
RunStatus = Literal["success", "failed"]

_TYPE_ALIASES: dict[str, ParamType] = {
    "string": "string",
    "str": "string",
    "text": "string",
    "number": "number",
    "int": "number",
    "integer": "number",
    "float": "number",
    "double": "number",
    "long": "number",
    "boolean": "boolean",
    "bool": "boolean",
}

_SPEC_KEYS = {"type", "schema", "required", "description", "desc", "name", "default"}

_REQUIRED_MARKERS = ("(required)", "（required）", "(必填)", "（必填）")


class ParamInfo(BaseModel):
    """从 YAML inputs 提取的单个参数。"""

    name: str = Field(..., description="参数名")
    type: ParamType = Field(..., description="参数类型：string、number 或 boolean")
    required: bool = Field(..., description="是否必填")
    description: str | None = Field(None, description="参数说明")


class ParamsResponse(BaseModel):
    """API 参数表单。"""

    asset_id: str = Field(..., description="资产 ID")
    params: list[ParamInfo] = Field(..., description="参数列表，顺序与 YAML inputs 一致")


class RunRequest(BaseModel):
    """单次 API 执行请求。

    ``timeout_seconds`` 省略时不覆盖环境超时；显式 30 与省略不是同一件事。
    """

    env: str = Field(..., min_length=1, description="运行环境（须在项目 envs 内）")
    params: dict[str, Any] = Field(default_factory=dict, description="执行参数")
    request_override: dict[str, Any] | None = Field(
        None, description="临时请求覆盖，仅支持 body；整体替换，不写回 Assets、不渲染占位符"
    )
    timeout_seconds: float | None = Field(
        None,
        gt=0,
        le=300,
        description="每步 HTTP 超时（秒）。省略则使用环境或默认 30",
    )


class RunResponse(BaseModel):
    """单次 API 执行结果。"""

    record_id: str = Field(..., description="执行记录 ID")
    status: RunStatus = Field(..., description="执行状态：success 或 failed")
    duration: float | None = Field(None, description="执行时长（秒）")
    result: Any = Field(None, description="执行结果")
    # H3（单 API 同理）：result 是自由 JSON，auth 在其中原样保留；这里再显式声明一份
    # 有类型的副本，让 OpenAPI 与前端有稳定契约。
    auth: ExecutionAuth | None = Field(
        None, description="本次请求使用的身份（Phase 3.3d 九键）；匿名为 null，与 result.auth 相同"
    )
    commit_sha: str | None = Field(None, description="本次执行固定使用的 commit SHA")
    operator: str | None = Field(None, description="操作人（平台用户名）")
    config_revision: int | None = Field(None, description="启动时冻结的环境 revision")


def build_param_infos(inputs: Any) -> list[ParamInfo]:
    """把 YAML ``inputs`` 转成参数表单。

    支持两种写法：

    - 映射：``username: 用户名`` 或 ``username: {type, required, description}``
    - 列表：``[{name, type, required, description}, ...]``

    字符串值视为说明。说明中带 ``(required)`` / ``(必填)`` 时该参数必填，类型为
    string。数字、布尔值会据此推断类型。``integer`` / ``bool`` 等别名会归一成
    string、number、boolean。

    Args:
        inputs: ``request.inputs`` 的原始值。``None`` 视为没有参数。

    Returns:
        参数表单。没有 inputs 时返回空列表。

    Raises:
        ValueError: inputs 结构无法识别，或类型不在 string/number/boolean 中。
        ValidationError: 字段无法构成 ParamInfo。
    """
    if inputs is None:
        return []
    if isinstance(inputs, dict):
        params = [_param_from_spec(str(name), spec) for name, spec in inputs.items()]
    elif isinstance(inputs, list):
        params = [_param_from_entry(entry) for entry in inputs]
    else:
        raise ValueError("inputs must be a mapping or a list")

    names = [item.name for item in params]
    if len(names) != len(set(names)):
        raise ValueError("duplicate input names")
    return params


def _param_from_entry(entry: Any) -> ParamInfo:
    """解析列表形式的单个 input。"""
    if not isinstance(entry, dict) or "name" not in entry:
        raise ValueError("each input must be a mapping with a name")
    name = str(entry["name"]).strip()
    if not name:
        raise ValueError("input name must not be empty")
    return _param_from_spec(name, entry)


def _param_from_spec(name: str, spec: Any) -> ParamInfo:
    """按值的形态生成 ParamInfo。"""
    name = name.strip()
    if not name:
        raise ValueError("input name must not be empty")

    if spec is None or spec == "":
        return ParamInfo(name=name, type="string", required=False, description=None)
    if isinstance(spec, bool):
        return ParamInfo(name=name, type="boolean", required=False, description=None)
    if isinstance(spec, (int, float)):
        return ParamInfo(name=name, type="number", required=False, description=None)
    if isinstance(spec, str):
        return _param_from_description(name, spec)
    if isinstance(spec, dict):
        return _param_from_mapping(name, spec)
    raise ValueError(f"unsupported input spec for '{name}'")


def _param_from_description(name: str, text: str) -> ParamInfo:
    """把说明字符串解析为 string 参数，并识别必填标记。"""
    description = text.strip()
    required = False
    for marker in _REQUIRED_MARKERS:
        lowered = description.lower()
        index = lowered.find(marker.lower())
        if index == -1:
            continue
        required = True
        description = (description[:index] + description[index + len(marker) :]).strip()
    description = description.strip(" -\t")
    return ParamInfo(
        name=name,
        type="string",
        required=required,
        description=description or None,
    )


def _param_from_mapping(name: str, spec: dict[str, Any]) -> ParamInfo:
    """解析带 type/required/description 的映射。"""
    unknown = set(spec) - _SPEC_KEYS
    if unknown and not (set(spec) & _SPEC_KEYS):
        raise ValueError(f"unsupported input spec for '{name}'")

    raw_type = spec.get("type", spec.get("schema", "string"))
    description = spec.get("description", spec.get("desc"))
    return ParamInfo(
        name=name,
        type=_normalize_type(raw_type),
        required=_as_bool(spec.get("required", False)),
        description=None if description is None else str(description),
    )


def _normalize_type(raw: Any) -> ParamType:
    """把 YAML 中的类型名归一成 string、number 或 boolean。"""
    if raw is None:
        return "string"
    key = str(raw).strip().lower()
    if key not in _TYPE_ALIASES:
        raise ValueError(f"unsupported param type: {raw}")
    return _TYPE_ALIASES[key]


def _as_bool(value: Any) -> bool:
    """解析 required 字段。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "required"}:
            return True
        if lowered in {"false", "no", "0", "optional"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    raise ValueError(f"invalid required flag: {value!r}")


def _matches_type(expected: ParamType, value: Any) -> bool:
    """判断运行时参数是否符合表单类型。布尔值不是 number。"""
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return False


def asset_default_params(inputs: Any) -> dict[str, Any]:
    """从 inputs 的 ``default`` 取出资产默认值。没有默认值时为空。"""
    found: dict[str, Any] = {}
    pairs: list[tuple[str, Any]] = []
    if isinstance(inputs, dict):
        pairs = [(str(name), spec) for name, spec in inputs.items()]
    elif isinstance(inputs, list):
        for entry in inputs:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                pairs.append((entry["name"], entry))
    for name, spec in pairs:
        if isinstance(spec, dict) and "default" in spec:
            found[name] = spec["default"]
    return found


def _validate_run_params(form: list[ParamInfo], params: dict[str, Any]) -> None:
    """按参数表单校验已经合并后的运行参数。

    Args:
        form: 从 YAML 提取的参数表单。
        params: 调用方传入的参数。

    Raises:
        HTTPException: 缺必填、类型不匹配或出现未声明参数时返回 422。
    """
    errors: list[str] = []
    by_name = {item.name: item for item in form}

    for item in form:
        if item.required and (item.name not in params or params[item.name] is None):
            errors.append(f"missing required param '{item.name}'")

    for key, value in params.items():
        if key not in by_name:
            errors.append(f"unknown param '{key}'")
            continue
        if value is None:
            errors.append(f"param '{key}' must not be null")
            continue
        expected = by_name[key].type
        if not _matches_type(expected, value):
            errors.append(f"param '{key}' expects {expected}, got {type(value).__name__}")

    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))


def _asset_file(assets_root: Path, asset: AssetNode) -> Path:
    """定位资产文件，并限制在 assets_root 内（resolve + 前缀校验）。"""
    root = assets_root.resolve()
    file_path = (root / asset.path).resolve()
    if not file_path.is_relative_to(root):
        raise HTTPException(status_code=404, detail="Asset not found")
    return file_path


def _load_api_document(assets_root: Path, asset_id: str) -> dict[str, Any]:
    """定位 API YAML 并返回解析结果。错误不含文件原文以外的 YAML 异常文本。"""
    asset = AssetService(assets_root).get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.type != "file":
        raise HTTPException(status_code=422, detail="Asset is not a file")

    file_path = _asset_file(assets_root, asset)
    if file_path.suffix.lower() not in {".yaml", ".yml"}:
        raise HTTPException(status_code=422, detail="Asset is not a YAML file")

    try:
        parsed = YamlParser.parse_yaml(file_path)
        api = YamlParser.parse_api_yaml(file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Asset file not found") from exc
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid YAML: {exc}") from exc
    except OSError as exc:
        # 日志硬约束：不用 logger.exception，只记资产 ID 与异常类型名。
        logger.error("Failed to read asset %s exc_type=%s", asset_id, type(exc).__name__)
        raise HTTPException(status_code=500, detail="Failed to read asset file") from exc

    if parsed.get("type") != "api":
        raise HTTPException(status_code=422, detail="Asset is not an API")
    return api


def _load_param_form(assets_root: Path, asset_id: str) -> list[ParamInfo]:
    """用 AssetService 定位资产，再用 YamlParser 提取 inputs。"""
    api = _load_api_document(assets_root, asset_id)
    try:
        return build_param_infos(api.get("inputs"))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _run_response(record: ExecutionRecord) -> RunResponse:
    """把执行记录转成响应。结果 JSON 无法解析时返回 500。"""
    if record.status not in ("success", "failed"):
        raise HTTPException(status_code=500, detail="Unexpected execution status")
    if not record.id:
        raise HTTPException(status_code=500, detail="Execution record is missing an id")

    result: Any = None
    if record.result_json:
        try:
            result = json.loads(record.result_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=500,
                detail="Execution result is not valid JSON",
            ) from exc

    duration = None if record.duration is None else float(record.duration)
    return RunResponse(
        record_id=record.id,
        status=record.status,
        duration=duration,
        result=result,
        auth=parse_execution_auth(
            result if isinstance(result, dict) else None, record_id=record.id
        ),
        commit_sha=getattr(record, "commit_sha", None),
        operator=getattr(record, "operator", None),
        config_revision=getattr(record, "config_revision", None),
    )


@router.get("/assets/{asset_id}/params", response_model=ParamsResponse)
async def get_asset_params(
    repo: str,
    project: str,
    asset_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> ParamsResponse:
    """从 API YAML 的 inputs 提取参数表单（当前 SHA 快照）。"""
    row = get_project(db, repo, project)
    _, assets_root, _ = ensure_snapshot_dirs(get_repos_config(request), row)
    params = _load_param_form(assets_root, asset_id)
    return ParamsResponse(asset_id=asset_id, params=params)


@router.post("/assets/{asset_id}/run", response_model=RunResponse)
async def run_asset(
    repo: str,
    project: str,
    asset_id: str,
    body: RunRequest,
    request: Request,
    db: Session = Depends(get_db),
    engine: EnginePort = Depends(get_engine_port),
    user: PlatformPrincipal = Depends(require_user),
) -> RunResponse:
    """执行单个 API，并保存执行记录。请求体必填 ``env``。"""
    row = get_project(db, repo, project)
    env = require_env(db, row, body.env)
    commit_sha, assets_root, config_root = ensure_snapshot_dirs(get_repos_config(request), row)
    api = _load_api_document(assets_root, asset_id)
    try:
        form = build_param_infos(api.get("inputs"))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    declared_names = {item.name for item in form}
    if body.request_override is not None:
        if set(body.request_override) != {"body"}:
            raise HTTPException(status_code=422, detail="request_override 必须且只能包含 body")
        # 实际请求体已完整提供，原模板输入无需必填；显式参数仍校验名称和类型。
        form = [item.model_copy(update={"required": False}) for item in form]

    record = await run_single_api(
        db=db,
        project=row,
        asset_id=asset_id,
        params=body.params,
        engine=engine,
        env=env,
        commit_sha=commit_sha,
        assets_root=assets_root,
        config_root=config_root,
        timeout_seconds=body.timeout_seconds,
        operator=user.username,
        declared_names=declared_names,
        asset_defaults=asset_default_params(api.get("inputs")),
        validate_params=lambda params: _validate_run_params(form, params),
        request_override=body.request_override,
    )
    return _run_response(record)
