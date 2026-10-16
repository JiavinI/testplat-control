"""本地假服务：证明数据库 host、超时、参数和登录凭据进入真实 Engine 请求。

不访问公网。假服务不写访问日志，避免 query 中的密码进入进程日志。
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from testplat_control.config import settings
from testplat_control.database.models import Project
from testplat_control.database.session import SessionLocal
from testplat_control.deps import get_engine_port
from testplat_control.main import app
from testplat_control.services.project_access import ensure_snapshot_dirs
from testplat_control.services.run_config import resolve_run_config
from tests.repo_support import bootstrap_synced_project

PASS_A = "pw-project-a-91"
PASS_B = "pw-project-b-82"
NEW_PASS = "pw-project-a-new7"
USER_A = "buyer-user-a"
USER_B = "buyer-user-b"
FALLBACK = "should-not-fallback-99"
TOKEN = "tok-fixed-9f31ab"
USER_ID = "user-id-9"

PROFILE = """\
identities:
  gsb_login:
    login:
      host: unified_login
      steps:
        - name: login
          method: GET
          path: /site/login
          body:
            type: query
            fields:
              username: "${secret:username}"
              password: "${secret:password}"
              source: go2
          extract:
            - {source: body_json, path: "$.data.hash", as: token}
            - {source: body_json, path: "$.data.userId", as: user_id}
      validity:
        ttl_seconds: 14400
      inject:
        headers:
          X-TOKEN: "${login:token}"
          X-USER-ID: "${login:user_id}"
"""

BALANCE = """\
id: api.gsb.balance
type: api
name: 余额
host: gsb
method: POST
url: /balance
auth: gsb
request:
  type: json
  inputs:
    keyword:
      type: string
      required: false
      description: 关键字
  body:
    keyword: "${keyword}"
success:
  status_code: 200
"""

SEARCH = """\
id: api.gsb.search
type: api
name: 搜索
host: gsb
method: GET
url: /search
auth: gsb
request:
  type: query
  inputs:
    keyword:
      type: string
      required: false
      description: 关键字
  body:
    keyword: "${keyword}"
success:
  status_code: 200
"""

ANON = """\
id: api.gsb.anon
type: api
name: 匿名
host: gsb
method: GET
url: /anon
auth: none
request: {}
success:
  status_code: 200
"""

GHOST = """\
id: api.gsb.ghost
type: api
name: 缺失身份
host: gsb
method: GET
url: /ghost
auth: ghost
request: {}
success:
  status_code: 200
"""

SLOW = """\
id: api.gsb.slow
type: api
name: 慢接口
host: gsb
method: GET
url: /slow
auth: none
request: {}
success:
  status_code: 200
"""

CASE = """\
schema_version: "0.2"
id: case.gsb.search
name: 搜索
params:
  keyword: from-asset
steps:
  - step_id: search
    type: api
    api_id: api.gsb.search
    params:
      keyword: "${params.keyword}"
"""

MANIFEST = """\
schema_version: "1"
projects:
  demo:
    name: Demo Project
    assets: projects/demo
    config: projects/demo/config
    default_env: test
  other:
    name: Other Project
    assets: projects/other
    config: projects/other/config
    default_env: test
"""


class _Capture:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.sleep_seconds = 0.8

    def add(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.events.append(event)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.events)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def _handle(self, method: str) -> None:
        capture: _Capture = self.server.capture  # type: ignore[attr-defined]
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        query = {key: values[0] for key, values in parse_qs(parsed.query).items() if values}
        capture.add(
            {
                "method": method,
                "path": parsed.path,
                "query": query,
                "body": raw.decode("utf-8") if raw else "",
                "x_token": self.headers.get("X-TOKEN"),
                "x_user_id": self.headers.get("X-USER-ID"),
            }
        )
        if parsed.path == "/site/login":
            self._json(200, {"code": 0, "data": {"hash": TOKEN, "userId": USER_ID}})
            return
        if parsed.path == "/slow":
            time.sleep(capture.sleep_seconds)
            self._json(200, {"ok": True})
            return
        if parsed.path in {"/balance", "/search", "/anon"}:
            self._json(200, {"ok": True})
            return
        self._json(404, {"missing": True})

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


class _Server(ThreadingHTTPServer):
    def __init__(self, capture: _Capture) -> None:
        self.capture = capture
        super().__init__(("127.0.0.1", 0), _Handler)

    @property
    def base(self) -> str:
        host, port = self.server_address
        return f"http://{host}:{port}"


def _start(capture: _Capture) -> _Server:
    server = _Server(capture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.thread = thread  # type: ignore[attr-defined]
    return server


def _stop(server: _Server) -> None:
    server.shutdown()
    server.server_close()
    server.thread.join(timeout=5)  # type: ignore[attr-defined]


def _project_files() -> dict[str, str]:
    files = {
        "testplat.yaml": MANIFEST,
        "projects/demo/config/auth/_profiles.yaml": PROFILE,
        "projects/demo/api/gsb/balance.yaml": BALANCE,
        "projects/demo/api/gsb/search.yaml": SEARCH,
        "projects/demo/api/gsb/anon.yaml": ANON,
        "projects/demo/api/gsb/ghost.yaml": GHOST,
        "projects/demo/api/gsb/slow.yaml": SLOW,
        "projects/demo/scenarios/gsb/search.case.yaml": CASE,
        "projects/demo/config/envs/test.yaml": "api_hosts:\n  local: http://127.0.0.1:9\n",
    }
    for name in ("balance", "search", "anon", "ghost", "slow"):
        files[f"projects/other/api/gsb/{name}.yaml"] = files[f"projects/demo/api/gsb/{name}.yaml"]
    files["projects/other/config/auth/_profiles.yaml"] = PROFILE
    files["projects/other/scenarios/gsb/search.case.yaml"] = CASE
    files["projects/other/config/envs/test.yaml"] = files["projects/demo/config/envs/test.yaml"]
    # 保留一份历史 auth 文件，证明平台路径不读它。
    files["projects/demo/config/auth/test.yaml"] = (
        "identities:\n  gsb:\n    headers:\n      X-TOKEN: ${secret:TESTPLAT_GSB_PASSWORD}\n"
    )
    return files


@pytest.fixture
def master_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "testplat_master_key", key)
    return key


@pytest.fixture
def world(tmp_path: Path, master_key: str, monkeypatch: pytest.MonkeyPatch):
    del master_key
    monkeypatch.setenv("TESTPLAT_GSB_PASSWORD", FALLBACK)
    monkeypatch.setenv("TESTPLAT_GSB_USERNAME", FALLBACK)
    app.dependency_overrides.pop(get_engine_port, None)
    login = _start(_Capture())
    business = _start(_Capture())
    repo_key = f"fh{uuid4().hex[:8]}"
    try:
        with TestClient(app) as client:
            ctx = bootstrap_synced_project(
                client,
                tmp_path,
                _project_files(),
                repo_key=repo_key,
                project_key="demo",
            )
            yield {
                "client": client,
                "ctx": ctx,
                "login": login,
                "business": business,
            }
    finally:
        _stop(login)
        _stop(business)


def _env(client: TestClient, base: str, login: str, business: str, **extra: object) -> dict:
    payload = {
        "env": "test",
        "api_hosts": {"gsb": business, "unified_login": login},
        "timeout_seconds": 2,
        "enabled": True,
    }
    payload.update(extra)
    response = client.post(f"{base}/environments", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _account(
    client: TestClient,
    base: str,
    *,
    name: str = "gsb",
    username: str = USER_A,
    password: str = PASS_A,
    profile: str = "gsb_login",
) -> dict:
    response = client.post(
        f"{base}/environments/test/accounts",
        json={
            "account_name": name,
            "display_name": "采购员",
            "login_profile": profile,
            "credentials": {"username": username, "password": password},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _queries(capture: _Capture, path: str) -> list[dict[str, str]]:
    return [item["query"] for item in capture.snapshot() if item["path"] == path]


def test_fake_target_carries_host_params_and_credentials(world: dict) -> None:
    """登录走 unified_login，业务走 gsb；参数与凭据字段进入请求，且不回退环境变量。"""
    client: TestClient = world["client"]
    login: _Server = world["login"]
    business: _Server = world["business"]
    base = world["ctx"]["base"]
    _env(client, base, login.base, business.base, case_params={"keyword": "from-env"})
    _account(client, base)

    omitted = client.post(
        f"{base}/assets/api.gsb.balance/run",
        json={"env": "test", "params": {}},
    )
    assert omitted.status_code == 200, omitted.text
    assert omitted.json()["operator"] == "tester"
    assert omitted.json()["auth"]["identity"] == "gsb"
    assert omitted.json()["auth"]["session_source"] == "login"
    login_qs = _queries(login.capture, "/site/login")
    assert login_qs == [{"username": USER_A, "password": PASS_A, "source": "go2"}]
    assert FALLBACK not in json.dumps(login_qs)
    assert _queries(business.capture, "/site/login") == []
    posted = [item for item in business.capture.snapshot() if item["path"] == "/balance"]
    assert len(posted) == 1
    assert json.loads(posted[0]["body"]) == {"keyword": "from-env"}
    assert posted[0]["x_token"] == TOKEN
    assert posted[0]["x_user_id"] == USER_ID
    assert PASS_A not in omitted.text
    assert FALLBACK not in omitted.text

    explicit = client.post(
        f"{base}/assets/api.gsb.balance/run",
        json={"env": "test", "params": {"keyword": "from-req"}},
    )
    assert explicit.status_code == 200, explicit.text
    assert explicit.json()["auth"]["session_source"] == "cache"
    assert len(_queries(login.capture, "/site/login")) == 1
    bodies = [
        json.loads(item["body"])
        for item in business.capture.snapshot()
        if item["path"] == "/balance"
    ]
    assert bodies[-1] == {"keyword": "from-req"}

    changed = client.put(
        f"{base}/environments/test/accounts/gsb",
        json={"revision": 1, "credentials": {"username": USER_A, "password": NEW_PASS}},
    )
    assert changed.status_code == 200, changed.text
    again = client.post(
        f"{base}/assets/api.gsb.balance/run",
        json={"env": "test", "params": {"keyword": "after"}},
    )
    assert again.status_code == 200, again.text
    assert _queries(login.capture, "/site/login")[-1]["password"] == NEW_PASS
    assert again.json()["auth"]["session_source"] == "login"


def test_timeout_comes_from_request_then_environment(world: dict) -> None:
    """省略超时用环境值；显式更小的超时覆盖环境。慢接口因此返回 504。"""
    client: TestClient = world["client"]
    login: _Server = world["login"]
    business: _Server = world["business"]
    base = world["ctx"]["base"]
    created = _env(client, base, login.base, business.base, timeout_seconds=0.2)
    business.capture.sleep_seconds = 0.8
    omitted = client.post(f"{base}/assets/api.gsb.slow/run", json={"env": "test", "params": {}})
    assert omitted.status_code == 504, omitted.text

    client.put(
        f"{base}/environments/test",
        json={"revision": created["revision"], "timeout_seconds": 2},
    )
    explicit = client.post(
        f"{base}/assets/api.gsb.slow/run",
        json={"env": "test", "params": {}, "timeout_seconds": 0.2},
    )
    assert explicit.status_code == 504, explicit.text


def test_case_param_overlay_and_cache_scope(world: dict) -> None:
    """请求参数覆盖环境 case_params，环境再覆盖 case 资产 params。"""
    client: TestClient = world["client"]
    login: _Server = world["login"]
    business: _Server = world["business"]
    ctx = world["ctx"]
    base = ctx["base"]
    _env(client, base, login.base, business.base)
    _account(client, base)
    asset_only = client.post(
        f"{base}/cases/case.gsb.search/run", json={"env": "test", "params": {}}
    )
    assert asset_only.status_code == 200, asset_only.text
    assert _queries(business.capture, "/search")[-1]["keyword"] == "from-asset"

    current = client.get(f"{base}/environments/test").json()
    client.put(
        f"{base}/environments/test",
        json={"revision": current["revision"], "case_params": {"keyword": "from-env"}},
    )
    from_env = client.post(f"{base}/cases/case.gsb.search/run", json={"env": "test", "params": {}})
    assert from_env.status_code == 200, from_env.text
    assert _queries(business.capture, "/search")[-1]["keyword"] == "from-env"

    from_req = client.post(
        f"{base}/cases/case.gsb.search/run",
        json={"env": "test", "params": {"keyword": "from-req"}},
    )
    assert from_req.status_code == 200, from_req.text
    assert _queries(business.capture, "/search")[-1]["keyword"] == "from-req"

    with SessionLocal() as db:
        project = db.get(Project, ctx["project_id"])
        assert project is not None
        _sha, _assets, config_root = ensure_snapshot_dirs(app.state.repo_sync.config, project)
        resolved = resolve_run_config(
            db,
            project,
            "test",
            config_root,
            request_params={"keyword": "from-req"},
            request_timeout=None,
        )
    assert resolved.auth is not None
    assert resolved.auth.table.cache_scope == f"{ctx['repo']}:demo:test"
    assert resolved.params["keyword"] == "from-req"
    assert resolved.timeout_seconds == 2


def test_projects_isolate_accounts_and_hosts(world: dict) -> None:
    """A2：同名账号在两个项目使用各自地址和凭据；操作人不是测试账号。"""
    client: TestClient = world["client"]
    login: _Server = world["login"]
    business: _Server = world["business"]
    demo = world["ctx"]["base"]
    other = f"/repos/{world['ctx']['repo']}/projects/other"
    _env(client, demo, login.base, business.base)
    _account(client, demo, username=USER_A, password=PASS_A)
    _env(client, other, business.base, login.base)
    _account(client, other, username=USER_B, password=PASS_B)

    first = client.post(
        f"{demo}/assets/api.gsb.balance/run",
        json={"env": "test", "params": {"keyword": "demo"}},
    )
    assert first.status_code == 200, first.text
    assert first.json()["operator"] == "tester"
    second = client.post(
        f"{other}/assets/api.gsb.balance/run",
        json={"env": "test", "params": {"keyword": "other"}},
    )
    assert second.status_code == 200, second.text

    assert _queries(login.capture, "/site/login") == [
        {"username": USER_A, "password": PASS_A, "source": "go2"}
    ]
    assert _queries(business.capture, "/site/login") == [
        {"username": USER_B, "password": PASS_B, "source": "go2"}
    ]
    demo_body = [
        json.loads(item["body"])
        for item in business.capture.snapshot()
        if item["path"] == "/balance"
    ]
    other_body = [
        json.loads(item["body"]) for item in login.capture.snapshot() if item["path"] == "/balance"
    ]
    assert demo_body == [{"keyword": "demo"}]
    assert other_body == [{"keyword": "other"}]
    assert FALLBACK not in json.dumps(login.capture.snapshot())
    assert FALLBACK not in json.dumps(business.capture.snapshot())


def test_unreferenced_incomplete_account_does_not_block(world: dict) -> None:
    """A9：未引用且未配全的账号不阻断匿名接口；被引用的缺失/停用在发请求前失败。"""
    client: TestClient = world["client"]
    login: _Server = world["login"]
    business: _Server = world["business"]
    base = world["ctx"]["base"]
    _env(client, base, login.base, business.base)
    spare = client.post(
        f"{base}/environments/test/accounts",
        json={
            "account_name": "spare",
            "login_profile": "gsb_login",
            "credentials": {"username": USER_A},
        },
    )
    assert spare.status_code == 201, spare.text

    anon = client.post(f"{base}/assets/api.gsb.anon/run", json={"env": "test", "params": {}})
    assert anon.status_code == 200, anon.text
    assert anon.json()["auth"] is None
    assert [item["path"] for item in business.capture.snapshot()] == ["/anon"]
    assert login.capture.snapshot() == []

    before = len(business.capture.snapshot()) + len(login.capture.snapshot())
    missing = client.post(f"{base}/assets/api.gsb.ghost/run", json={"env": "test", "params": {}})
    assert missing.status_code == 422
    assert FALLBACK not in missing.text
    assert "TESTPLAT_GSB" not in missing.text
    assert len(business.capture.snapshot()) + len(login.capture.snapshot()) == before

    _account(client, base)
    disabled = client.put(
        f"{base}/environments/test/accounts/gsb",
        json={"revision": 1, "enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    blocked = client.post(
        f"{base}/assets/api.gsb.balance/run",
        json={"env": "test", "params": {"keyword": "x"}},
    )
    assert blocked.status_code == 422
    assert "已停用" in blocked.json()["detail"]
    assert PASS_A not in blocked.text
    assert FALLBACK not in blocked.text
    assert _queries(login.capture, "/site/login") == []
