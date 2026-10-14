"""H5：parse_execution_auth 失败记 warning（只含记录 id）。"""

from __future__ import annotations

import logging

import pytest

from testplat_control.api.schemas import ExecutionAuth, parse_execution_auth
from tests.auth_support import FAKE_SECRET, assert_no_secret, log_text


def test_parse_seven_key_auth() -> None:
    auth = parse_execution_auth(
        {
            "auth": {
                "identity": "admin",
                "kind": "static_headers",
                "tier": None,
                "header_names": ["Authorization"],
                "overridden_headers": [],
                "cookie_names": [],
                "login_ref": None,
            }
        }
    )
    assert isinstance(auth, ExecutionAuth)
    assert auth.kind == "static_headers"
    assert auth.tier is None
    assert auth.session_source is None
    assert auth.reauthenticated is False


def test_parse_failure_logs_warning_with_record_id_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="testplat_control.api.schemas"):
        assert (
            parse_execution_auth(
                {"auth": {"identity": "admin", "header_names": []}},
                record_id="rec-123",
            )
            is None
        )
    messages = log_text(caplog.records)
    assert any("rec-123" in m for m in messages)
    assert_no_secret(messages, secrets=(FAKE_SECRET,))
