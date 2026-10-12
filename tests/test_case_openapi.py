"""OpenAPI 契约：Phase 2.5 既有 API 不漂移；Case 表面有明确 schema。

``tests/snapshots/openapi_phase2_5_baseline.json`` 是基线 ``da5e26f`` 的 OpenAPI 快照。
允许的差异是**显式白名单**：

1. 新增 3 条 Case 路由及其 schema；
2. ``GET /projects/{project_id}/execution-records`` 新增一个可选查询参数 ``asset_type``；
3. Phase 3.3a：新增 ``ExecutionAuth`` schema，``RunResponse`` / ``ExecutionRecordDetailResponse``
   各新增一个可选属性 ``auth``（相对 Phase 3 快照的逐项白名单见 ``tests/test_auth_openapi.py``）。

除此之外，基线里的每条 path/operation 与每个 component schema 必须逐字节相等。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from testplat_control.main import app

BASELINE = json.loads(
    (Path(__file__).parent / "snapshots" / "openapi_phase2_5_baseline.json").read_text("utf-8")
)
LIST_RECORDS = "/projects/{project_id}/execution-records"
NEW_PATHS = {
    "/projects/{project_id}/cases/{case_id}": {"get"},
    "/projects/{project_id}/cases/{case_id}/run": {"post"},
    "/projects/{project_id}/case-execution-records/{record_id}": {"get"},
}
NEW_SCHEMAS = {
    "CaseAssetDetailResponse",
    "CaseExecutionRecordDetailResponse",
    "CaseResult",
    "CaseRunRequest",
    "CaseRunResponse",
    "CaseStepError",
    "CaseStepRequest",
    "CaseStepResponse",
    "CaseStepResult",
    "CaseSummary",
    "CaseSystemError",
}
# Phase 3.3a 新增的非 Case schema 与给既有 schema 追加的属性。
AUTH_SCHEMAS = {"ExecutionAuth"}
AUTH_PROPERTY_ADDED = {"RunResponse", "ExecutionRecordDetailResponse"}


@pytest.fixture(scope="module")
def current() -> dict[str, Any]:
    return json.loads(json.dumps(app.openapi(), sort_keys=True))


def test_phase_2_5_paths_do_not_drift(current: dict[str, Any]) -> None:
    for path, operations in BASELINE["paths"].items():
        assert path in current["paths"], f"基线路由丢失: {path}"
        for method, operation in operations.items():
            now = copy.deepcopy(current["paths"][path][method])
            if path == LIST_RECORDS and method == "get":
                names = [p["name"] for p in now["parameters"]]
                assert "asset_type" in names
                now["parameters"] = [p for p in now["parameters"] if p["name"] != "asset_type"]
                # 说明文字随新增参数更新；其余字段（参数、响应、状态码）必须逐字相等。
                assert "asset_type" in now.pop("description")
                operation = {k: v for k, v in operation.items() if k != "description"}
            assert now == operation, f"{method.upper()} {path} 发生漂移"


def test_phase_2_5_component_schemas_do_not_drift(current: dict[str, Any]) -> None:
    for name, schema in BASELINE["components"]["schemas"].items():
        now = copy.deepcopy(current["components"]["schemas"][name])
        if name in AUTH_PROPERTY_ADDED:
            # 3.3a 唯一允许的变化：追加可选 auth（不进 required）；其余逐字相等。
            assert "auth" in now["properties"] and "auth" not in now.get("required", [])
            now["properties"].pop("auth")
        assert now == schema, f"schema {name} 发生漂移"


def test_only_expected_additions(current: dict[str, Any]) -> None:
    added_paths = set(current["paths"]) - set(BASELINE["paths"])
    assert added_paths == set(NEW_PATHS)
    for path, methods in NEW_PATHS.items():
        assert set(current["paths"][path]) == methods
    added_schemas = set(current["components"]["schemas"]) - set(BASELINE["components"]["schemas"])
    assert added_schemas == NEW_SCHEMAS | AUTH_SCHEMAS


def test_list_records_asset_type_parameter_is_optional_enum(current: dict[str, Any]) -> None:
    params = {p["name"]: p for p in current["paths"][LIST_RECORDS]["get"]["parameters"]}
    asset_type = params["asset_type"]
    assert asset_type["in"] == "query" and asset_type["required"] is False
    enum_values = {
        value for branch in asset_type["schema"]["anyOf"] for value in branch.get("enum", [])
    }
    assert enum_values == {"api", "case"}


def _literal(spec: dict[str, Any]) -> list[str]:
    """读取 Literal 字段的取值（pydantic 对单值用 const，多值用 enum）。"""
    if "enum" in spec:
        return list(spec["enum"])
    return [spec["const"]]


def _ref_name(ref: dict[str, Any]) -> str:
    target = ref.get("$ref") or ref["allOf"][0]["$ref"]
    return target.rsplit("/", 1)[1]


def test_case_operations_reference_explicit_schemas(current: dict[str, Any]) -> None:
    paths = current["paths"]
    detail = paths["/projects/{project_id}/cases/{case_id}"]["get"]
    run = paths["/projects/{project_id}/cases/{case_id}/run"]["post"]
    history = paths["/projects/{project_id}/case-execution-records/{record_id}"]["get"]

    assert _ref_name(detail["responses"]["200"]["content"]["application/json"]["schema"]) == (
        "CaseAssetDetailResponse"
    )
    assert _ref_name(run["responses"]["200"]["content"]["application/json"]["schema"]) == (
        "CaseRunResponse"
    )
    assert _ref_name(run["requestBody"]["content"]["application/json"]["schema"]) == (
        "CaseRunRequest"
    )
    assert _ref_name(history["responses"]["200"]["content"]["application/json"]["schema"]) == (
        "CaseExecutionRecordDetailResponse"
    )


def test_case_result_structure(current: dict[str, Any]) -> None:
    """CaseResult 的每个字段都有类型；开放 JSON 只出现在 body/headers/params 这些被测系统数据上。"""
    schemas = current["components"]["schemas"]

    result = schemas["CaseResult"]
    assert set(result["properties"]) == {
        "case_id",
        "status",
        "duration_seconds",
        "steps",
        "summary",
        "error",
    }
    assert set(result["required"]) == {"case_id", "status", "duration_seconds", "steps", "summary"}
    assert _literal(result["properties"]["status"]) == ["success", "failed"]
    assert _ref_name(result["properties"]["steps"]["items"]) == "CaseStepResult"
    assert _ref_name(result["properties"]["summary"]) == "CaseSummary"

    step = schemas["CaseStepResult"]
    assert set(step["required"]) == {"step_id", "type", "status", "duration_seconds"}
    assert _literal(step["properties"]["status"]) == ["success", "failed", "skipped"]
    skip_reason = step["properties"]["skip_reason"]["anyOf"][0]
    assert _literal(skip_reason) == ["fail_fast"]
    assert step["properties"]["duration_seconds"]["minimum"] == 0
    assert set(step["properties"]) == {
        "step_id",
        "name",
        "type",
        "status",
        "duration_seconds",
        "request",
        "response",
        "error",
        "output",
        "skip_reason",
        "auth",
    }
    assert schemas["CaseSummary"]["required"] == ["total", "success", "failed", "skipped"]
    assert set(_literal(schemas["CaseSystemError"]["properties"]["kind"])) == {
        "timeout",
        "transport",
        "internal",
    }
    assert _literal(schemas["CaseSystemError"]["properties"]["stage"]) == ["execution"]
    record_detail = schemas["CaseExecutionRecordDetailResponse"]
    assert _literal(record_detail["properties"]["asset_type"]) == ["case"]
    assert set(schemas["CaseAssetDetailResponse"]["required"]) == {
        "case_id",
        "path",
        "file_name",
        "size_bytes",
        "modified_at",
    }


def test_no_unconstrained_object_in_case_surface(current: dict[str, Any]) -> None:
    """Case schema 里不得出现“无 properties 的裸 object”，白名单之外的字段必须有结构。"""
    allowed_open = {
        ("CaseStepRequest", "headers"),
        ("CaseStepRequest", "body"),
        ("CaseStepResponse", "headers"),
        ("CaseStepResponse", "body"),
        ("CaseRunRequest", "params"),
    }
    schemas = current["components"]["schemas"]
    for name in NEW_SCHEMAS:
        for prop, spec in schemas[name].get("properties", {}).items():
            branches = spec.get("anyOf", [spec])
            for branch in branches:
                bare_object = branch.get("type") == "object" and "properties" not in branch
                untyped = not branch or branch == {"default": None}
                if (bare_object or untyped) and (name, prop) not in allowed_open:
                    raise AssertionError(f"{name}.{prop} 是无约束 dict/Any: {spec}")
