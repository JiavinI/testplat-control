"""``docs/phase3_3/examples`` 冻结示例须符合当前 schema，且不含任何假秘密（§6-1）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from testplat_control.api.case_schemas import CaseExecutionRecordDetailResponse, CaseRunResponse
from testplat_control.api.run import RunResponse
from testplat_control.api.schemas import ExecutionRecordDetailResponse
from tests.auth_support import assert_no_secret

DOCS = Path(__file__).resolve().parents[1] / "docs" / "phase3_3"
EXAMPLES = DOCS / "examples"


def _load(name: str):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("api-run-with-auth.json", RunResponse),
        ("api-history-detail-with-auth.json", ExecutionRecordDetailResponse),
        ("case-run-with-auth.json", CaseRunResponse),
        ("case-history-detail-with-auth.json", CaseExecutionRecordDetailResponse),
    ],
)
def test_examples_match_schema_and_carry_auth(name: str, model) -> None:  # noqa: ANN001
    parsed = model.model_validate(_load(name))
    if isinstance(parsed, (RunResponse, ExecutionRecordDetailResponse)):
        assert parsed.auth is not None and parsed.auth.identity == "admin"
    else:
        assert all(step.auth is not None for step in parsed.result.steps)


def test_error_examples_are_422_detail_only() -> None:
    for item in _load("auth-error-responses.json").values():
        assert item["status"] == 422 and set(item["body"]) == {"detail"}


def test_no_fake_secret_in_any_frozen_doc() -> None:
    files = sorted(DOCS.rglob("*"))
    assert files
    assert_no_secret([path.read_text("utf-8") for path in files if path.is_file()])
