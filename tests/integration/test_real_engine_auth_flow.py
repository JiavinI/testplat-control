"""真实 Engine 0.3 端到端鉴权：Control → PackageEngineAdapter → Engine → 本地回显目标。

本地目标把收到的凭证头回显到**非敏感键** ``$.echo.value``，并记录实际收到的 header，
用于证明：凭证确实发出（单 API 与 Case 每一步）、两个身份交替不串号、
公开结果 / SQLite 原始行 / 日志中秘密均不出现、auth 公开字段透传到响应与历史详情。
不访问公网。
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import text

from testplat_control.database.session import SessionLocal
from testplat_control.deps import get_engine_port
from testplat_control.main import app
from tests.auth_support import (
    FAKE_PARTNER,
    FAKE_SECRET,
    STANDARD_CONFIG,
    STANDARD_ENV,
    assert_no_secret,
    log_text,
    write_auth,
)

RECEIVED: list[dict[str, str]] = []


class _EchoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        headers = {key.lower(): value for key, value in self.headers.items()}
        RECEIVED.append({"path": self.path, **headers})
        value = headers.get("authorization") or headers.get("x-api-key")
        body = json.dumps({"echo": {"value": value}}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def _api(name: str, auth: str | None) -> str:
    lines = [
        f"id: api.auth.{name}",
        f"name: {name}",
        "host: local",
        "method: GET",
        f"url: /echo/{name}",
    ]
    if auth is not None:
        lines.append(f"auth: {auth}")
    lines += ["success:", "  status_code: 200", ""]
    return "\n".join(lines)


CASE = """\
schema_version: "0.2"
id: case.auth.alternate
name: 身份交替
steps:
  - step_id: first_admin
    type: api
    api_id: api.auth.admin_echo
  - step_id: then_partner
    type: api
    api_id: api.auth.partner_echo
  - step_id: anonymous
    type: api
    api_id: api.auth.none_echo
  - step_id: back_to_admin
    type: api
    api_id: api.auth.default_echo
"""


@pytest.fixture
def server() -> str:
    RECEIVED.clear()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture
def project(tmp_path: Path, server: str, monkeypatch: pytest.MonkeyPatch):
    for name, value in STANDARD_ENV.items():
        monkeypatch.setenv(name, value)
    assets = tmp_path / "assets"
    (assets / "api" / "auth").mkdir(parents=True)
    for name, auth in {
        "admin_echo": "admin",
        "partner_echo": "partner",
        "none_echo": "none",
        "default_echo": None,
        "ghost_echo": "ghost",
    }.items():
        (assets / "api" / "auth" / f"{name}.yaml").write_text(_api(name, auth), encoding="utf-8")
    (assets / "scenarios" / "auth").mkdir(parents=True)
    (assets / "scenarios" / "auth" / "alternate.case.yaml").write_text(CASE, encoding="utf-8")
    config = tmp_path / "config"
    (config / "envs").mkdir(parents=True)
    (config / "envs" / "test.yaml").write_text(
        yaml.safe_dump({"api_hosts": {"local": server}}), encoding="utf-8"
    )
    app.dependency_overrides.pop(get_engine_port, None)

    def create(with_auth: bool = True) -> str:
        if with_auth:
            write_auth(config, STANDARD_CONFIG)
        with TestClient(app) as client:
            response = client.post(
                "/projects",
                json={
                    "name": f"auth-real-{uuid4().hex[:8]}",
                    "assets_root": str(assets),
                    "config_root": str(config),
                    "env": "test",
                },
            )
        assert response.status_code == 200, response.text
        return response.json()["id"]

    return create


def _rows(project_id: str) -> list[str]:
    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT * FROM execution_records WHERE project_id = :pid"), {"pid": project_id}
        ).fetchall()
        return [repr(tuple(row)) for row in rows]
    finally:
        db.close()


def test_single_api_sends_credential_and_redacts_echo(
    project, caplog: pytest.LogCaptureFixture
) -> None:
    project_id = project()
    with TestClient(app) as client, caplog.at_level(logging.DEBUG):
        response = client.post(
            f"/projects/{project_id}/assets/api.auth.admin_echo/run", json={"params": {}}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        detail = client.get(f"/projects/{project_id}/execution-records/{body['record_id']}")
    assert RECEIVED[-1]["authorization"] == f"Bearer {FAKE_SECRET}"
    expected = {
        "identity": "admin",
        "kind": "static_headers",
        "tier": None,
        "header_names": ["Authorization"],
        "overridden_headers": [],
        "cookie_names": [],
        "login_ref": None,
        "session_source": None,
        "reauthenticated": False,
    }
    assert body["auth"] == expected and detail.json()["auth"] == expected
    # 非敏感键下的回显被按值替换。
    assert "***" in json.dumps(body["result"]["response"])
    assert_no_secret([response.text, detail.text, *_rows(project_id), *log_text(caplog.records)])


def test_case_alternates_identities_without_crosstalk(
    project, caplog: pytest.LogCaptureFixture
) -> None:
    project_id = project()
    with TestClient(app) as client, caplog.at_level(logging.DEBUG):
        response = client.post(
            f"/projects/{project_id}/cases/case.auth.alternate/run", json={"params": {}}
        )
        assert response.status_code == 200, response.text
        record_id = response.json()["record_id"]
        typed = client.get(f"/projects/{project_id}/case-execution-records/{record_id}")
    sent = {item["path"]: item for item in RECEIVED}
    assert sent["/echo/admin_echo"]["authorization"] == f"Bearer {FAKE_SECRET}"
    assert "x-api-key" not in sent["/echo/admin_echo"]
    assert sent["/echo/partner_echo"]["x-api-key"] == FAKE_PARTNER
    assert "authorization" not in sent["/echo/partner_echo"]
    assert "authorization" not in sent["/echo/none_echo"]
    assert "x-api-key" not in sent["/echo/none_echo"]
    assert sent["/echo/default_echo"]["authorization"] == f"Bearer {FAKE_SECRET}"
    identities = [
        None if step["auth"] is None else step["auth"]["identity"]
        for step in typed.json()["result"]["steps"]
    ]
    assert identities == ["admin", "partner", None, "admin"]
    assert_no_secret([response.text, typed.text, *_rows(project_id), *log_text(caplog.records)])


def test_unknown_identity_is_422_without_record(project) -> None:
    project_id = project()
    with TestClient(app) as client:
        response = client.post(
            f"/projects/{project_id}/assets/api.auth.ghost_echo/run", json={"params": {}}
        )
        records = client.get(f"/projects/{project_id}/execution-records").json()
    assert response.status_code == 422 and "ghost" in response.json()["detail"]
    assert records == [] and RECEIVED == []


def test_declared_identity_without_auth_file_is_422(project) -> None:
    """Q2：资产声明身份但项目没有 auth 配置 → 422，不静默匿名。"""
    project_id = project(with_auth=False)
    with TestClient(app) as client:
        declared = client.post(
            f"/projects/{project_id}/assets/api.auth.admin_echo/run", json={"params": {}}
        )
        anonymous = client.post(
            f"/projects/{project_id}/assets/api.auth.default_echo/run", json={"params": {}}
        )
    assert declared.status_code == 422
    assert anonymous.status_code == 200 and anonymous.json()["auth"] is None
    assert [item["path"] for item in RECEIVED] == ["/echo/default_echo"]


def test_unavailable_identity_is_422_in_case_before_any_step(
    project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TESTPLAT_PARTNER_KEY")
    project_id = project()
    with TestClient(app) as client:
        response = client.post(
            f"/projects/{project_id}/cases/case.auth.alternate/run", json={"params": {}}
        )
        records = client.get(f"/projects/{project_id}/execution-records").json()
    assert response.status_code == 422
    assert "TESTPLAT_PARTNER_KEY" in response.json()["detail"]
    assert records == [] and RECEIVED == []  # Case 预检一次性失败，没有任何步骤发出
