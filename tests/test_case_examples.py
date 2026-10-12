"""``docs/phase3/examples`` 的示例 JSON 必须始终符合当前 Pydantic/OpenAPI schema。

这些示例是给前端（Agent 4）固定契约用的；如果后端 schema 变了而示例没更新，这里会失败，
避免文档与实现静默分叉。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from testplat_control.api.case_schemas import (
    CaseAssetDetailResponse,
    CaseExecutionRecordDetailResponse,
    CaseRunResponse,
)
from testplat_control.api.schemas import ExecutionRecordDetailResponse, ExecutionRecordListResponse

EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "phase3" / "examples"


def _load(name: str):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    [
        "case-run-success.json",
        "case-run-business-failed-assertion.json",
        "case-run-business-failed-variable-resolution.json",
    ],
)
def test_run_response_examples_match_schema(name: str) -> None:
    CaseRunResponse.model_validate(_load(name))


@pytest.mark.parametrize(
    "name",
    [
        "case-history-detail-success.json",
        "case-history-detail-timeout.json",
        "case-history-detail-transport.json",
    ],
)
def test_history_detail_examples_match_schema(name: str) -> None:
    model = CaseExecutionRecordDetailResponse.model_validate(_load(name))
    assert model.result is not None


def test_other_examples_match_schema() -> None:
    CaseAssetDetailResponse.model_validate(_load("case-detail.json"))
    for item in _load("case-history-list-filtered.json"):
        ExecutionRecordListResponse.model_validate(item)
    generic = ExecutionRecordDetailResponse.model_validate(
        _load("case-history-generic-detail-compat.json")
    )
    assert generic.asset_type == "case" and generic.request is None


def test_error_response_examples_use_detail_body() -> None:
    for name, entry in _load("case-run-error-responses.json").items():
        assert set(entry["body"]) == {"detail"} and isinstance(entry["body"]["detail"], str)
        assert str(entry["http_status"]) == name.rsplit("_", 1)[1]
