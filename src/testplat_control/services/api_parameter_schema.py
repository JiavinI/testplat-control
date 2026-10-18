"""API 输入表单与默认值规则；供运行路由和离线审计复用，无数据库初始化。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ParamType = Literal["string", "number", "boolean"]

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
