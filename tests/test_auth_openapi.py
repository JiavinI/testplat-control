"""Phase 4.0：鉴权相关 OpenAPI 字段仍在（ExecutionAuth 九键）。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from testplat_control.main import app


@pytest.fixture(scope="module")
def current() -> dict[str, Any]:
    return json.loads(json.dumps(app.openapi(), sort_keys=True))


def test_execution_auth_schema_has_nine_keys(current: dict[str, Any]) -> None:
    auth = current["components"]["schemas"]["ExecutionAuth"]
    props = set(auth["properties"])
    assert {
        "identity",
        "kind",
        "tier",
        "header_names",
        "overridden_headers",
        "cookie_names",
        "login_ref",
        "session_source",
        "reauthenticated",
    } <= props


def test_run_response_still_has_auth(current: dict[str, Any]) -> None:
    props = current["components"]["schemas"]["RunResponse"]["properties"]
    assert "auth" in props
    assert "commit_sha" in props
