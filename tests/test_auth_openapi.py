"""Phase 3.3a OpenAPI 冻结：相对 Phase 3 快照只允许 auth 相关的逐项白名单差异。

``tests/snapshots/openapi_phase3_baseline.json`` = Control ``c5a904b`` 的 OpenAPI
（与 ``docs/phase3/openapi-phase3.json`` 相同）。
``docs/phase3_3/openapi-phase3_3.json`` 是当前冻结版，
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
        assert now == schema, f"schema {name} 发生漂移"


def test_execution_auth_shape(current: dict[str, Any]) -> None:
    auth = current["components"]["schemas"]["ExecutionAuth"]
    assert set(auth["properties"]) == {"identity", "header_names", "overridden_headers"}
    assert set(auth["required"]) == {"identity", "header_names", "overridden_headers"}
    assert auth["additionalProperties"] is False
    for key in ("header_names", "overridden_headers"):
        assert auth["properties"][key] == {
            **auth["properties"][key],
            "type": "array",
            "items": {"type": "string"},
        }


def test_frozen_openapi_document_matches(current: dict[str, Any]) -> None:
    assert json.loads(FROZEN.read_text("utf-8")) == current
