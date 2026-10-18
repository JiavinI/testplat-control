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
        query = {
            key: values[0]
            for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
            if values
        }
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


@pytest.mark.parametrize(
    ("username", "password"),
    [
        (USER_A, PASS_A),
        ("张建雨", "123456"),
        ("u", "p"),
        ("", ""),
        ("  用户\t  ", "pw\r\n\x00末尾 "),
    ],
)
def test_fake_target_carries_host_params_and_credentials(
    world: dict, username: str, password: str
) -> None:
    """登录走 unified_login，业务走 gsb；参数与凭据字段进入请求，且不回退环境变量。"""
    client: TestClient = world["client"]
    login: _Server = world["login"]
    business: _Server = world["business"]
    base = world["ctx"]["base"]
    _env(client, base, login.base, business.base, case_params={"keyword": "from-env"})
    _account(client, base, username=username, password=password)
    stored = client.get(f"{base}/environments/test/accounts/gsb/credentials")
    assert stored.status_code == 200
    assert stored.json()["credentials"] == {"username": username, "password": password}

    omitted = client.post(
        f"{base}/assets/api.gsb.balance/run",
        json={"env": "test", "params": {}},
    )
    assert omitted.status_code == 200, omitted.text
    assert omitted.json()["operator"] == "tester"
    assert omitted.json()["auth"]["identity"] == "gsb"
    assert omitted.json()["auth"]["session_source"] == "login"
    login_qs = _queries(login.capture, "/site/login")
    assert login_qs == [{"username": username, "password": password, "source": "go2"}]
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

    updated = client.put(
        f"{base}/environments/test/accounts/gsb",
        json={"revision": 2, "credentials": {"username": username, "password": password}},
    )
    assert updated.status_code == 200, updated.text
    stored_again = client.get(f"{base}/environments/test/accounts/gsb/credentials")
    assert stored_again.json()["credentials"] == {"username": username, "password": password}


def test_login_profile_without_credentials_can_run(world: dict) -> None:
    from tests.repo_support import commit_all, sync_repo

    client = world["client"]
    ctx = world["ctx"]
    profile_path = ctx["repo_path"] / "projects/demo/config/auth/_profiles.yaml"
    profile_path.write_text(
        PROFILE.replace("${secret:username}", "").replace("${secret:password}", ""),
        encoding="utf-8",
    )
    commit_all(ctx["repo_path"])
    sync_repo(client, ctx["repo"])
    _env(client, ctx["base"], world["login"].base, world["business"].base)
    created = client.post(
        f"{ctx['base']}/environments/test/accounts",
        json={"account_name": "gsb", "login_profile": "gsb_login", "credentials": {}},
    )
    assert created.status_code == 201, created.text
    run = client.post(
        f"{ctx['base']}/assets/api.gsb.balance/run", json={"env": "test", "params": {}}
    )
    assert run.status_code == 200, run.text
    assert run.json()["auth"]["session_source"] == "login"
    assert _queries(world["login"].capture, "/site/login") == [
        {"username": "", "password": "", "source": "go2"}
    ]


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


def test_parameter_preview_defaults_match_real_requests(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """传给 Engine 的参数保留类型；隔离目标收到既有模板渲染后的字符串值。"""
    from testplat_control.adapters.package_engine import PackageEngineAdapter
    from tests.repo_support import commit_all, sync_repo, write_tree

    submitted = []
    execute = PackageEngineAdapter.execute

    async def capture_execute(self, request):
        submitted.append(request.to_dict()["params"])
        return await execute(self, request)

    monkeypatch.setattr(PackageEngineAdapter, "execute", capture_execute)
    client, ctx = world["client"], world["ctx"]
    base = ctx["base"]
    write_tree(ctx["repo_path"], {
        "projects/demo/api/gsb/preview.yaml": """\
id: api.gsb.preview
type: api
name: 参数预览验收接口
host: gsb
method: POST
url: /balance
auth: none
request:
  type: json
  inputs:
    keyword: {type: string, required: true, default: ""}
    count: {type: number, required: true, default: 0}
    active: {type: boolean, required: true, default: false}
  body:
    keyword: "${keyword}"
    count: "${count}"
    active: "${active}"
success:
  status_code: 200
""",
        "projects/demo/scenarios/gsb/preview.case.yaml": """\
schema_version: "0.2"
id: case.gsb.preview
name: Preview fixture
params:
  keyword: from-case
  filter: {a: 7, b: 8}
  active: true
steps:
  - step_id: send
    type: api
    api_id: api.gsb.preview
    params:
      keyword: "${params.keyword}"
      count: "${params.filter.a}"
      active: "${params.active}"
""",
    })
    commit_all(ctx["repo_path"], "add parameter preview fixtures")
    assert sync_repo(client, ctx["repo"])["ok"]
    _env(client, base, world["login"].base, world["business"].base)
    preview = client.get(f"{base}/assets/api.gsb.preview/params")
    assert preview.status_code == 200
    assert preview.json()["asset_defaults"] == {"keyword": "", "count": 0, "active": False}

    def sent_body() -> dict:
        events = world["business"].capture.snapshot()
        return json.loads([event["body"] for event in events if event["path"] == "/balance"][-1])

    first = client.post(f"{base}/assets/api.gsb.preview/run", json={"env": "test", "params": {}})
    assert first.status_code == 200, first.json().get("detail")
    assert first.json()["status"] == "success"
    assert submitted[-1] == preview.json()["asset_defaults"]
    assert sent_body() == {"keyword": "", "count": "0", "active": "False"}
    environment = client.get(f"{base}/environments/test").json()
    updated = client.put(f"{base}/environments/test", json={
        "revision": environment["revision"],
        "case_params": {"keyword": "from-env", "count": 4, "active": True, "filter": {"a": 5, "b": 6}},
    })
    assert updated.status_code == 200
    for params, expected in [
        ({}, {"keyword": "from-env", "count": 4, "active": True}),
        ({"count": 0, "active": False}, {"keyword": "from-env", "count": 0, "active": False}),
    ]:
        response = client.post(f"{base}/assets/api.gsb.preview/run", json={"env": "test", "params": params})
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert submitted[-1] == expected
        # 预览输入不等于最终请求体：当前模板插值将 number／boolean 字符串化。
        assert sent_body() == {key: str(value) for key, value in expected.items()}

    case_response = client.post(f"{base}/cases/case.gsb.preview/run", json={
        "env": "test", "params": {"keyword": "", "filter": {"a": 0}, "active": False, "optional": None},
    })
    assert case_response.status_code == 200
    assert case_response.json()["status"] == "success"
    # Case 步骤的引用解析保留类型，区别于当前单接口的模板插值。
    assert sent_body() == {"keyword": "", "count": 0, "active": False}
    assert submitted[-1]["filter"] == {"a": 0}
    assert submitted[-1]["optional"] is None


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


@pytest.mark.parametrize("legacy", [False, True])
def test_missing_web_host_does_not_use_git(
    world: dict,
    monkeypatch: pytest.MonkeyPatch,
    legacy: bool,
) -> None:
    """即使 Git 有可用 host，Web 环境缺少 host 也必须在联网前失败。"""
    monkeypatch.setattr(settings, "testplat_legacy_git_config", legacy)
    client, base = world["client"], world["ctx"]["base"]
    response = client.post(f"{base}/environments", json={"env": "test", "api_hosts": {}})
    assert response.status_code == 201

    def forbidden(*args, **kwargs):
        pytest.fail("已有 Web 环境不可读取 Git 配置")

    monkeypatch.setattr("testplat_control.services.run_config.load_auth", forbidden)
    monkeypatch.setattr("testplat_control.services.run_config.load_project_environment", forbidden)
    blocked = client.post(f"{base}/assets/api.gsb.anon/run", json={"env": "test"})
    assert blocked.status_code == 422
    assert world["login"].capture.snapshot() == []
    assert world["business"].capture.snapshot() == []


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


def test_grouped_account_reference_selects_exact_identity(world: dict) -> None:
    """同名 primary 分属 b1/b2；auth 精确选择 b2，实际触发登录和业务请求。"""
    from tests.repo_support import commit_all, sync_repo

    client, ctx = world["client"], world["ctx"]
    for path in (ctx["repo_path"] / "projects/demo/api").rglob("*.yaml"):
        path.write_text(path.read_text().replace("auth: gsb\n", "auth: gsb.b2.primary\n"))
    commit_all(ctx["repo_path"], "use grouped account reference")
    sync_repo(client, ctx["repo"])
    base = ctx["base"]
    _env(client, base, world["login"].base, world["business"].base)
    _account(client, base, name="gsb.b1.primary", username=USER_B, password=PASS_B)
    _account(client, base, name="gsb.b2.primary")
    response = client.post(f"{base}/assets/api.gsb.balance/run", json={"env": "test"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success"
    assert response.json()["auth"]["identity"] == "gsb.b2.primary"
    assert len(_queries(world["login"].capture, "/site/login")) == 1
    assert _queries(world["login"].capture, "/site/login")[0]["username"] == USER_A
    assert any(item["path"] == "/balance" for item in world["business"].capture.snapshot())
    assert PASS_A not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {
            "new_field": 12,
            "nested": {"enabled": False},
            "items": [1, None],
            "literal": "${keyword}",
        },
        {},
        [1, False, None],
        None,
    ],
)
def test_temporary_json_body_is_sent_and_recorded_without_changing_assets(
    world: dict, body: Any
) -> None:
    client, ctx = world["client"], world["ctx"]
    base = ctx["base"]
    _env(client, base, world["login"].base, world["business"].base)
    _account(client, base)
    with SessionLocal() as db:
        project = db.get(Project, ctx["project_id"])
        _, root, _ = ensure_snapshot_dirs(app.state.repo_sync.config, project)
    source = root / "api/gsb/balance.yaml"
    original = source.read_bytes()
    response = client.post(
        f"{base}/assets/api.gsb.balance/run",
        json={
            "env": "test",
            "request_override": {"body": body},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success"
    sent = [item for item in world["business"].capture.snapshot() if item["path"] == "/balance"][-1]
    assert json.loads(sent["body"]) == body
    assert sent["x_token"] == TOKEN
    assert response.json()["result"]["request"]["body"] == body
    record = client.get(f"{base}/execution-records/{response.json()['record_id']}")
    assert record.status_code == 200
    assert record.json()["result"]["request"]["body"] == body
    assert source.read_bytes() == original
    normal = client.post(
        f"{base}/assets/api.gsb.balance/run",
        json={"env": "test", "params": {"keyword": "original"}},
    )
    assert normal.json()["result"]["request"]["body"] == {"keyword": "original"}


@pytest.mark.parametrize(
    ("request_type", "body", "expected"),
    [
        (
            "query",
            {"new": "a&b", "active": False, "count": 2},
            {"new": "a&b", "active": "false", "count": "2"},
        ),
        ("form", {"new": "a&b", "active": False}, {"new": "a&b", "active": ["false"]}),
        ("raw", "arbitrary text\n${literal}", "arbitrary text\n${literal}"),
    ],
)
def test_temporary_request_supports_query_form_and_raw(
    world: dict, request_type: str, body: Any, expected: Any
) -> None:
    from tests.repo_support import commit_all, sync_repo

    client, ctx = world["client"], world["ctx"]
    path = ctx["repo_path"] / "projects/demo/api/gsb/balance.yaml"
    source = (
        path.read_text()
        .replace("type: json", f"type: {request_type}")
        .replace("required: false", "required: true")
    )
    if request_type == "raw":
        source = source.replace(
            '  body:\n    keyword: "${keyword}"', '  content_type: text/plain\n  body: "${keyword}"'
        )
    path.write_text(source)
    commit_all(ctx["repo_path"], "request type")
    sync_repo(client, ctx["repo"])
    base = ctx["base"]
    _env(client, base, world["login"].base, world["business"].base)
    _account(client, base)
    response = client.post(
        f"{base}/assets/api.gsb.balance/run",
        json={"env": "test", "request_override": {"body": body}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success"
    sent = [item for item in world["business"].capture.snapshot() if item["path"] == "/balance"][-1]
    if request_type == "query":
        assert sent["query"] == expected
        assert sent["body"] == ""
    elif request_type == "form":
        assert parse_qs(sent["body"]) == {"new": ["a&b"], "active": ["false"]}
    else:
        assert sent["body"] == expected


def test_temporary_request_cannot_change_auth_or_method(world: dict) -> None:
    client, ctx = world["client"], world["ctx"]
    base = ctx["base"]
    _env(client, base, world["login"].base, world["business"].base)
    _account(client, base)
    for override in ({}, {"body": {}, "auth": "none"}, {"body": {}, "method": "DELETE"}):
        response = client.post(
            f"{base}/assets/api.gsb.balance/run", json={"env": "test", "request_override": override}
        )
        assert response.status_code == 422
    assert world["login"].capture.snapshot() == []
    assert world["business"].capture.snapshot() == []
