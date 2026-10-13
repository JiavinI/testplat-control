"""Phase 3.3b OpenAPI 冻结：相对 Phase 3 快照只允许鉴权/登录相关的白名单差异。

``tests/snapshots/openapi_phase3_baseline.json`` = Phase 3 基线。
``docs/phase3_3/openapi-phase3_3.json`` 是当前冻结版（3.3b 覆盖 3.3a），
供前端（Agent 3）使用；两者都由本文件校验，防止文档与实现静默分叉。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from testplat_control.main import app

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads(
    (Path(__file__).parent / "snapshots" / "openapi_phase3_baseline.json").read_text("utf-8")
)
FROZEN = ROOT / "docs" / "phase3_3" / "openapi-phase3_3.json"
AUTH_PROPERTY_ADDED = {"RunResponse", "ExecutionRecordDetailResponse", "CaseStepResult"}
CASE_RESULT_ADDED = {"logins"}
CASE_STEP_REQUEST_ADDED = {"body_type", "query"}


@pytest.fixture(scope="module")
def current() -> dict[str, Any]:
    return json.loads(json.dumps(app.openapi(), sort_keys=True))


def test_paths_unchanged_vs_phase3(current: dict[str, Any]) -> None:
    assert current["paths"] == BASELINE["paths"]


def test_only_auth_additions_vs_phase3(current: dict[str, Any]) -> None:
    schemas = current["components"]["schemas"]
    assert set(schemas) - set(BASELINE["components"]["schemas"]) == {"ExecutionAuth"}
    for name, schema in BASELINE["components"]["schemas"].items():
        now = copy.deepcopy(schemas[name])
        if name in AUTH_PROPERTY_ADDED:
            auth = now["properties"].pop("auth")
            assert "auth" not in now.get("required", [])
            refs = [branch.get("$ref") for branch in auth["anyOf"]]
            assert refs == ["#/components/schemas/ExecutionAuth", None]
            assert auth["anyOf"][1] == {"type": "null"}
        if name == "CaseResult":
            for key in CASE_RESULT_ADDED:
                assert key in now["properties"]
                now["properties"].pop(key)
                if key in now.get("required", []):
                    now["required"].remove(key)
            now["description"] = schema["description"]
        if name == "CaseStepRequest":
            for key in CASE_STEP_REQUEST_ADDED:
                assert key in now["properties"]
                now["properties"].pop(key)
                if key in now.get("required", []):
                    now["required"].remove(key)
            now["description"] = schema["description"]
        if name == "CaseStepResult":
            # skip_reason 枚举扩展为 fail_fast | login_failed（H4）
            skip = now["properties"]["skip_reason"]["anyOf"][0]
            assert set(skip.get("enum", [])) == {"fail_fast", "login_failed"}
            # 与基线比较时还原 skip_reason 整段（枚举 + 描述）
            now["properties"]["skip_reason"] = copy.deepcopy(schema["properties"]["skip_reason"])
        assert now == schema, f"schema {name} 发生漂移"


def test_execution_auth_shape(current: dict[str, Any]) -> None:
    """U3/H5：公开 auth 恰好七键。"""
    auth = current["components"]["schemas"]["ExecutionAuth"]
    expected = {
        "identity",
        "kind",
        "tier",
        "header_names",
        "overridden_headers",
        "cookie_names",
        "login_ref",
    }
    assert set(auth["properties"]) == expected
    assert set(auth["required"]) == {
        "identity",
        "kind",
        "header_names",
        "overridden_headers",
        "cookie_names",
    }
    assert auth["additionalProperties"] is False
    for key in ("header_names", "overridden_headers", "cookie_names"):
        assert auth["properties"][key]["type"] == "array"
        assert auth["properties"][key]["items"] == {"type": "string"}


def test_case_result_has_logins(current: dict[str, Any]) -> None:
    result = current["components"]["schemas"]["CaseResult"]
    assert "logins" in result["properties"]
    assert "logins" not in result.get("required", [])


def test_frozen_openapi_document_matches(current: dict[str, Any]) -> None:
    assert json.loads(FROZEN.read_text("utf-8")) == current
