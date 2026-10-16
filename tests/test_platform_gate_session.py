"""平台门禁会话：注册登录后，新客户端必须显式继承 cookie。"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient

from testplat_control.main import app
from tests.platform_gate import establish, inherit_cookies, inherit_httpx

pytestmark = pytest.mark.platform_auth


def test_establish_and_explicit_inherit_do_not_share_jar() -> None:
    """未登录 401；继承后的新客户端可读当前用户；改源 jar 不影响副本。"""
    anonymous = TestClient(app)
    assert anonymous.get("/projects").status_code == 401

    owner = TestClient(app)
    establish(owner, username="gateinherit", password="gate-pass-1")
    assert owner.get("/auth/me").json()["username"] == "gateinherit"

    child = TestClient(app)
    assert child.get("/projects").status_code == 401
    inherit_cookies(owner, child)
    assert child.get("/auth/me").json()["username"] == "gateinherit"
    assert child.cookies is not owner.cookies

    owner.cookies.set("testplat_session", "replaced-token-value")
    assert child.get("/auth/me").status_code == 200


def test_httpx_inherit_sends_cookie_to_new_client() -> None:
    """并发新建的 httpx 客户端要带上已复制的会话，而不是空 jar。"""
    seen: dict[str, str | None] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            seen["cookie"] = self.headers.get("Cookie")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source = httpx.Client()
    child = None
    try:
        source.cookies.set("testplat_session", "tok-explicit", domain="127.0.0.1", path="/")
        child = inherit_httpx(source, timeout=5)
        assert child.cookies is not source.cookies
        port = server.server_address[1]
        response = child.get(f"http://127.0.0.1:{port}/auth/me")
        assert response.status_code == 200
        assert seen["cookie"] == "testplat_session=tok-explicit"
        source.cookies.set("testplat_session", "replaced", domain="127.0.0.1", path="/")
        child.get(f"http://127.0.0.1:{port}/again")
        assert seen["cookie"] == "testplat_session=tok-explicit"
    finally:
        if child is not None:
            child.close()
        source.close()
        server.shutdown()
        thread.join(timeout=5)
