#!/usr/bin/env python3
"""Phase 4.1a 集成矩阵：设计稿 §8.1 A1–A13。

本地假服务证明 host、入参和账号凭据进入请求。真实 GSB 不可达时允许 transport，
执行记录仍须带 operator、env、commit、config_revision。不把真实业务成功当作必过。

用法（Control 仓库根）::

    uv run python scripts/phase4_1a_matrix.py

``PHASE4_1A_INJECT_LEAK=1`` 把已签发的业务 token 和最新会话写进被监听日志，LEAK 必须失败。
默认关闭，不进入正常运行路径。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("PHASE4_1A_OUT", ROOT / "frontend" / "screenshots" / "phase4_1a"))
ASSETS_SHA = "f226b4a88b68fd582f717f5f0ff3652c1f56eb7e"
PLATFORM_USER = "matrixop"
PLATFORM_PASSWORD = "matrix-pass-1"
PASS_A = "pw-project-a-91"
PASS_B = "pw-project-b-82"
NEW_PASS = "pw-project-a-new7"
USER_A = "buyer-user-a"
USER_B = "buyer-user-b"
FALLBACK = "should-not-fallback-99"
USER_ID = "user-id-9"
SECRETS = [PLATFORM_PASSWORD, PASS_A, PASS_B, NEW_PASS, FALLBACK]
PASSWORD_SECRETS = (PLATFORM_PASSWORD, PASS_A, PASS_B, NEW_PASS, FALLBACK)
ISSUED_BUSINESS_TOKENS: list[str] = []
SESSION_COOKIES: list[str] = []


def token_for(password: str) -> str:
    """按密码派生固定 token，便于在线上区分两次登录，且不含密码原文。"""
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()[:12]
    return f"tok-{digest}"


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
id: api.gsb.account.balance
type: api
name: 查询账户余额
host: gsb
method: POST
url: /api/account/balance
auth: gsb
request:
  type: json
  inputs: {}
  body: {}
success:
  path: $.errorCode
  value: "0"
"""

SEARCH = """\
id: api.gsb.order.search_product
type: api
name: 搜索商品
host: gsb
method: GET
url: /api/b2/orders/search/product
auth: gsb
request:
  type: query
  inputs:
    product_keyword: str
  body:
    keywords: "${product_keyword}"
success:
  path: $.errorCode
  value: "0"
"""

SMOKE = """\
schema_version: "0.2"
id: case.gsb.smoke
name: 冒烟
params:
  product_keyword: "示例商品"
steps:
  - step_id: balance
    type: api
    api_id: api.gsb.account.balance
  - step_id: search_product
    type: api
    api_id: api.gsb.order.search_product
    params:
      product_keyword: "${params.product_keyword}"
"""

RESULTS: list[dict[str, Any]] = []


def redact(text: str) -> str:
    cleaned = text
    for secret in SECRETS:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


def remember(*values: str) -> None:
    for value in values:
        if value and value not in SECRETS:
            SECRETS.append(value)


def note_business_token(value: str) -> None:
    if value and value not in ISSUED_BUSINESS_TOKENS:
        ISSUED_BUSINESS_TOKENS.append(value)
        remember(value)


def note_session(value: str | None) -> None:
    if value and value not in SESSION_COOKIES:
        SESSION_COOKIES.append(value)
        remember(value)


def scan_secret_carriers(
    *,
    logs: str,
    sqlite_blob: bytes,
    traffic: list[tuple[str, int, str]],
) -> None:
    """响应正文、日志和 SQLite 不得含密码、主密钥、业务 token 或会话 cookie。

    凭据接口可以回显账号密码，但仍不得出现 token 或会话。断言文案不含秘密本身。
    """
    passwords = [item for item in PASSWORD_SECRETS if item]
    sensitive: list[str] = []
    for item in (*ISSUED_BUSINESS_TOKENS, *SESSION_COOKIES, *SECRETS):
        if item and item not in passwords and item not in sensitive:
            sensitive.append(item)
    for secret in (*passwords, *sensitive):
        if secret in logs:
            raise AssertionError("log")
        if secret.encode() in sqlite_blob:
            raise AssertionError("sqlite")
    for url, _status, text in traffic:
        for secret in sensitive:
            if secret in text:
                raise AssertionError("response")
        if url.endswith("/credentials"):
            continue
        for secret in passwords:
            if secret in text:
                raise AssertionError("response")


def inject_leak_markers() -> None:
    """测试钩子：把实际派发的业务 token 和最新会话写进 testplat_engine 日志。"""
    if os.environ.get("PHASE4_1A_INJECT_LEAK") != "1":
        return
    if not ISSUED_BUSINESS_TOKENS:
        note_business_token(token_for(PASS_A))
    if not SESSION_COOKIES:
        return
    logger = logging.getLogger("testplat_engine")
    logger.info("%s", ISSUED_BUSINESS_TOKENS[0])
    logger.info("%s", SESSION_COOKIES[-1])


class Capture:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.hold = threading.Event()
        self.sleep_seconds = 0.0

    def add(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.events.append(event)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.events)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def _handle(self, method: str) -> None:
        capture: Capture = self.server.capture  # type: ignore[attr-defined]
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
                "x_resource_id": self.headers.get("X-Resource-Id"),
            }
        )
        if parsed.path == "/site/login":
            issued = token_for(query.get("password", ""))
            note_business_token(issued)
            self._json(200, {"code": 0, "data": {"hash": issued, "userId": USER_ID}})
            return
        if parsed.path == "/slow":
            time.sleep(0.8)
            self._json(200, {"errorCode": "0"})
            return
        if parsed.path == "/hold":
            capture.hold.wait(4)
            self._json(200, {"errorCode": "0"})
            return
        if parsed.path == "/demo/resources" and method == "POST":
            self._json(201, {"id": "res-42"})
            return
        if parsed.path == "/status/200":
            self._json(200, {"ok": True})
            return
        self._json(200, {"errorCode": "0"})

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


class Server(ThreadingHTTPServer):
    def __init__(self, capture: Capture) -> None:
        self.capture = capture
        super().__init__(("127.0.0.1", 0), Handler)

    @property
    def base(self) -> str:
        host, port = self.server_address
        return f"http://{host}:{port}"


def start_server(capture: Capture) -> Server:
    server = Server(capture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.thread = thread  # type: ignore[attr-defined]
    return server


def stop_server(server: Server) -> None:
    server.shutdown()
    server.server_close()
    server.thread.join(timeout=5)  # type: ignore[attr-defined]


def _row(item: str, status: str, evidence: str) -> None:
    RESULTS.append({"item": item, "status": status, "evidence": redact(evidence)})
    print(f"{status:5} {item}  {redact(evidence)}", flush=True)


def _check(item: str, fn) -> None:  # noqa: ANN001
    try:
        _row(item, "PASS", fn() or item)
    except Exception as exc:  # noqa: BLE001
        _row(item, "FAIL", f"{type(exc).__name__}: {exc}")


def _queries(capture: Capture, path: str) -> list[dict[str, str]]:
    return [item["query"] for item in capture.snapshot() if item["path"] == path]


def _paths(capture: Capture, path: str) -> list[dict[str, Any]]:
    return [item for item in capture.snapshot() if item["path"] == path]


def project_files() -> dict[str, str]:
    files = {
        "testplat.yaml": """\
schema_version: "1"
projects:
  demo:
    name: Demo
    assets: projects/demo
    config: projects/demo/config
    default_env: test
  other:
    name: Other
    assets: projects/other
    config: projects/other/config
    default_env: test
""",
        "projects/demo/config/auth/_profiles.yaml": PROFILE,
        "projects/demo/config/auth/test.yaml": "identities: {}\n",
        "projects/demo/config/envs/test.yaml": "api_hosts:\n  local: http://127.0.0.1:9\n",
        # 资产 id 由路径推导，必须与 YAML id 一致，否则运行入口 404。
        "projects/demo/api/gsb/account/balance.yaml": BALANCE,
        "projects/demo/api/gsb/order/search_product.yaml": SEARCH,
        "projects/demo/api/gsb/anon.yaml": """\
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
""",
        "projects/demo/api/gsb/ghost.yaml": """\
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
""",
        "projects/demo/api/gsb/slow.yaml": """\
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
""",
        "projects/demo/api/gsb/hold.yaml": """\
id: api.gsb.hold
type: api
name: hold
host: gsb
method: GET
url: /hold
auth: gsb
request: {}
success:
  status_code: 200
""",
        "projects/demo/api/gsb/next.yaml": """\
id: api.gsb.next
type: api
name: next
host: gsb
method: GET
url: /next
auth: gsb
request: {}
success:
  status_code: 200
""",
        "projects/demo/scenarios/gsb/smoke.case.yaml": SMOKE,
        "projects/demo/scenarios/gsb/hold.case.yaml": """\
schema_version: "0.2"
id: case.gsb.hold
steps:
  - step_id: hold
    type: api
    api_id: api.gsb.hold
  - step_id: nxt
    type: api
    api_id: api.gsb.next
""",
        "projects/demo/api/demo/create.yaml": """\
id: api.demo.create
type: api
name: 创建
host: local
method: POST
url: /demo/resources
auth: none
request:
  body:
    name: "${name}"
success:
  status_code: 201
""",
        "projects/demo/api/demo/get.yaml": """\
id: api.demo.get
type: api
name: 查询
host: local
method: GET
url: /demo/resources/item
auth: none
request:
  headers:
    X-Resource-Id: "${resource_id}"
success:
  status_code: 200
""",
        "projects/demo/api/demo/fail.yaml": """\
id: api.demo.fail
type: api
name: 断言失败
host: local
method: GET
url: /status/200
auth: none
request: {}
success:
  status_code: 999
""",
        "projects/demo/scenarios/demo/alias.case.yaml": """\
schema_version: "0.2"
id: case.demo.alias
steps:
  - step_id: create
    type: api
    api_id: api.demo.create
    params:
      name: alpha
    output: created
  - step_id: get
    type: api
    api_id: api.demo.get
    params:
      resource_id: "${created.body.id}"
""",
        "projects/demo/scenarios/demo/failfast.case.yaml": """\
schema_version: "0.2"
id: case.demo.failfast
steps:
  - step_id: bad
    type: api
    api_id: api.demo.fail
  - step_id: after
    type: api
    api_id: api.demo.get
    params:
      resource_id: later
""",
        "projects/demo/scenarios/demo/account.case.yaml": """\
schema_version: "0.2"
id: case.demo.account
steps:
  - step_id: only
    type: api
    api_id: api.demo.get
    account: gsb
    params:
      resource_id: x
""",
    }
    for name in (
        "account/balance.yaml",
        "order/search_product.yaml",
        "anon.yaml",
        "ghost.yaml",
        "slow.yaml",
        "hold.yaml",
        "next.yaml",
    ):
        files[f"projects/other/api/gsb/{name}"] = files[f"projects/demo/api/gsb/{name}"]
    files["projects/other/config/auth/_profiles.yaml"] = PROFILE
    files["projects/other/config/envs/test.yaml"] = files["projects/demo/config/envs/test.yaml"]
    files["projects/other/scenarios/gsb/smoke.case.yaml"] = SMOKE
    return files


class Trace:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.traffic: list[tuple[str, int, str]] = []
        self.cookies = client.cookies

    def _add(self, url: str, response: Any) -> Any:
        self.traffic.append((url, response.status_code, response.text))
        return response

    def get(self, url: str, **kwargs: Any) -> Any:
        return self._add(url, self.client.get(url, **kwargs))

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._add(url, self.client.post(url, **kwargs))

    def put(self, url: str, **kwargs: Any) -> Any:
        return self._add(url, self.client.put(url, **kwargs))


def restart_main() -> int:
    """新进程用同一把主密钥读取凭据，并确认库里没有明文。"""
    from fastapi.testclient import TestClient

    from testplat_control.main import app
    from tests.platform_gate import establish

    client = TestClient(app)
    establish(
        client,
        username=os.environ["GATE_USER"],
        password=os.environ["GATE_PASSWORD"],
    )
    response = client.get(os.environ["CRED_PATH"])
    if response.status_code != 200:
        print(json.dumps({"ok": False, "status": response.status_code}))
        return 1
    got = (response.json().get("credentials") or {}).get("password")
    if got != os.environ["GATE_ACCOUNT_PASSWORD"]:
        print(json.dumps({"ok": False, "mismatch": True}))
        return 1
    db_path = os.environ["DATABASE_URL"].removeprefix("sqlite:///")
    blob = Path(db_path).read_bytes()
    leaked = [
        name
        for name, secret in (
            ("account", os.environ["GATE_ACCOUNT_PASSWORD"]),
            ("platform", os.environ["GATE_PASSWORD"]),
            ("master", os.environ.get("TESTPLAT_MASTER_KEY", "")),
        )
        if secret and secret.encode() in blob
    ]
    print(json.dumps({"ok": not leaked, "sqlite_leaks": leaked}))
    return 0 if not leaked else 1


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="phase4_1a_matrix_"))
    db_path = work / "control.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ.pop("TESTPLAT_REPOS_FILE", None)
    from cryptography.fernet import Fernet

    master = Fernet.generate_key().decode("ascii")
    os.environ["TESTPLAT_MASTER_KEY"] = master
    os.environ["TESTPLAT_GSB_PASSWORD"] = FALLBACK
    os.environ["TESTPLAT_GSB_USERNAME"] = FALLBACK
    remember(master)
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT))

    from fastapi.testclient import TestClient

    from testplat_control.main import app
    from tests.platform_gate import establish, inherit_cookies
    from tests.repo_support import bootstrap_synced_project, commit_all, sync_repo

    logs: list[str] = []

    class LogHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logs.append(record.getMessage())

    handler = LogHandler()
    handler.setLevel(logging.DEBUG)
    for name in ("testplat_control", "testplat_engine"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

    login = start_server(Capture())
    biz_a = start_server(Capture())
    biz_b = start_server(Capture())
    raw = TestClient(app)
    token = establish(raw, username=PLATFORM_USER, password=PLATFORM_PASSWORD)
    note_session(token)
    client = Trace(raw)
    ctx = bootstrap_synced_project(
        raw, work / "git", project_files(), repo_key="mx", project_key="demo"
    )
    base = ctx["base"]
    other = f"/repos/{ctx['repo']}/projects/other"
    state: dict[str, Any] = {}

    def create_env(path: str, env: str, gsb: str, unified: str, **extra: object) -> dict:
        payload: dict[str, object] = {
            "env": env,
            "api_hosts": {"gsb": gsb, "unified_login": unified, "local": gsb},
            "enabled": True,
        }
        payload.update(extra)
        response = client.post(f"{path}/environments", json=payload)
        assert response.status_code == 201, response.status_code
        return response.json()

    def create_account(path: str, env: str, username: str, password: str) -> dict:
        response = client.post(
            f"{path}/environments/{env}/accounts",
            json={
                "account_name": "gsb",
                "display_name": "采购员",
                "business_role": "商家",
                "login_profile": "gsb_login",
                "credentials": {"username": username, "password": password},
            },
        )
        assert response.status_code == 201, response.status_code
        assert password not in response.text
        return response.json()

    try:

        def a1() -> str:
            assert client.get("/health").status_code == 200
            bare = TestClient(app)
            assert bare.get("/projects").status_code == 401
            me = client.get("/auth/me")
            assert me.json()["username"] == PLATFORM_USER
            refreshed = TestClient(app)
            inherit_cookies(raw, refreshed)
            assert refreshed.get("/auth/me").json()["username"] == PLATFORM_USER
            assert refreshed.cookies is not raw.cookies
            logged_out = client.post("/auth/logout")
            assert logged_out.status_code == 204
            assert client.get("/projects").status_code == 401
            again = client.post(
                "/auth/login",
                json={"username": PLATFORM_USER, "password": PLATFORM_PASSWORD},
            )
            assert again.status_code == 200
            new_token = raw.cookies.get("testplat_session")
            assert isinstance(new_token, str) and new_token != token, "relogin_session"
            note_session(new_token)
            created = create_env(base, "lab", biz_a.base, login.base, timeout_seconds=2)
            assert created["updated_by"] == PLATFORM_USER
            state["lab_revision"] = created["revision"]
            return "register login refresh logout relogin lab_env"

        def a2() -> str:
            create_env(base, "test", biz_a.base, login.base, timeout_seconds=2)
            create_account(base, "test", USER_A, PASS_A)
            create_env(other, "test", login.base, biz_a.base, timeout_seconds=2)
            create_account(other, "test", USER_B, PASS_B)
            first = client.post(
                f"{base}/assets/api.gsb.account.balance/run",
                json={"env": "test", "params": {}},
            )
            second = client.post(
                f"{other}/assets/api.gsb.account.balance/run",
                json={"env": "test", "params": {}},
            )
            assert first.status_code == 200, first.status_code
            assert second.status_code == 200, second.status_code
            assert first.json()["operator"] == PLATFORM_USER
            assert first.json()["operator"] != USER_A
            assert _queries(login.capture, "/site/login") == [
                {"username": USER_A, "password": PASS_A, "source": "go2"}
            ]
            assert _queries(biz_a.capture, "/site/login") == [
                {"username": USER_B, "password": PASS_B, "source": "go2"}
            ]
            assert _paths(biz_a.capture, "/api/account/balance")
            assert _paths(login.capture, "/api/account/balance")
            assert FALLBACK not in json.dumps(login.capture.snapshot())
            return "demo_and_other hosts isolated"

        def a3() -> str:
            created = create_env(base, "pre", biz_a.base, login.base, timeout_seconds=2)
            assert created["env"] == "pre"
            create_account(base, "pre", USER_A, PASS_A)
            run = client.post(f"{base}/cases/case.gsb.smoke/run", json={"env": "pre", "params": {}})
            assert run.status_code == 200, run.status_code
            body = run.json()
            assert body["status"] == "success"
            detail = client.get(f"{base}/case-execution-records/{body['record_id']}")
            assert detail.status_code == 200, detail.status_code
            assert detail.json()["env"] == "pre"
            assert detail.json()["operator"] == PLATFORM_USER
            keywords = [
                item["query"].get("keywords")
                for item in biz_a.capture.snapshot()
                if item["path"] == "/api/b2/orders/search/product"
            ]
            assert "示例商品" in keywords
            return "pre not in git; smoke success"

        def a4() -> str:
            balance = [
                item
                for item in biz_a.capture.snapshot()
                if item["path"] == "/api/account/balance" and item["method"] == "POST"
            ]
            search = [
                item
                for item in biz_a.capture.snapshot()
                if item["path"] == "/api/b2/orders/search/product" and item["method"] == "GET"
            ]
            assert balance and balance[-1]["x_token"] == token_for(PASS_A)
            assert balance[-1]["x_user_id"] == USER_ID
            assert search and search[-1]["query"].get("keywords") == "示例商品"
            assert search[-1]["query"].get("source") is None
            assert _queries(login.capture, "/site/login")[-1]["source"] == "go2"
            return "unified_login + gsb POST balance GET search"

        def a5() -> str:
            current = client.get(f"{base}/environments/test").json()
            updated = client.put(
                f"{base}/environments/test",
                json={
                    "revision": current["revision"],
                    "api_hosts": {
                        "gsb": biz_b.base,
                        "unified_login": login.base,
                        "local": biz_b.base,
                    },
                    "timeout_seconds": 0.2,
                    "case_params": {"product_keyword": "from-env"},
                },
            )
            assert updated.status_code == 200, updated.status_code
            from_env = client.post(
                f"{base}/assets/api.gsb.order.search_product/run",
                json={"env": "test", "params": {}},
            )
            assert from_env.status_code == 200, from_env.status_code
            assert (
                _paths(biz_b.capture, "/api/b2/orders/search/product")[-1]["query"]["keywords"]
                == "from-env"
            )
            explicit = client.post(
                f"{base}/assets/api.gsb.order.search_product/run",
                json={"env": "test", "params": {"product_keyword": "from-req"}},
            )
            assert explicit.status_code == 200, explicit.status_code
            assert (
                _paths(biz_b.capture, "/api/b2/orders/search/product")[-1]["query"]["keywords"]
                == "from-req"
            )
            slow = client.post(
                f"{base}/assets/api.gsb.slow/run", json={"env": "test", "params": {}}
            )
            assert slow.status_code == 504, slow.status_code
            widened = client.put(
                f"{base}/environments/test",
                json={"revision": updated.json()["revision"], "timeout_seconds": 2},
            )
            assert widened.status_code == 200, widened.status_code
            overridden = client.post(
                f"{base}/assets/api.gsb.slow/run",
                json={"env": "test", "params": {}, "timeout_seconds": 0.2},
            )
            assert overridden.status_code == 504, overridden.status_code
            return "keyword host timeout override"

        def a6() -> str:
            cached = client.post(
                f"{base}/assets/api.gsb.account.balance/run",
                json={"env": "test", "params": {}},
            )
            assert cached.status_code == 200, cached.status_code
            assert cached.json()["auth"]["session_source"] == "cache"
            before = len(_queries(login.capture, "/site/login"))
            account = client.get(f"{base}/environments/test/accounts/gsb").json()
            changed = client.put(
                f"{base}/environments/test/accounts/gsb",
                json={
                    "revision": account["revision"],
                    "credentials": {"username": USER_A, "password": NEW_PASS},
                },
            )
            assert changed.status_code == 200, changed.status_code
            state["account_password"] = NEW_PASS
            again = client.post(
                f"{base}/assets/api.gsb.account.balance/run",
                json={"env": "test", "params": {}},
            )
            assert again.status_code == 200, again.status_code
            assert again.json()["auth"]["session_source"] == "login"
            assert len(_queries(login.capture, "/site/login")) == before + 1
            assert _queries(login.capture, "/site/login")[-1]["password"] == NEW_PASS
            return "new password misses old cache; unchanged reuses"

        def a7() -> str:
            biz_b.capture.hold.clear()
            before_next = len(_paths(biz_b.capture, "/next"))
            before_balance = len(_paths(biz_a.capture, "/api/account/balance"))
            holder: dict[str, Any] = {}
            runner_client = TestClient(app)
            inherit_cookies(raw, runner_client)

            def runner() -> None:
                holder["response"] = runner_client.post(
                    f"{base}/cases/case.gsb.hold/run",
                    json={"env": "test", "timeout_seconds": 8},
                )

            thread = threading.Thread(target=runner)
            thread.start()
            deadline = time.time() + 5
            while time.time() < deadline and not _paths(biz_b.capture, "/hold"):
                time.sleep(0.02)
            assert _paths(biz_b.capture, "/hold"), "hold request missing"
            current = client.get(f"{base}/environments/test").json()
            moved = client.put(
                f"{base}/environments/test",
                json={
                    "revision": current["revision"],
                    "api_hosts": {
                        "gsb": biz_a.base,
                        "unified_login": login.base,
                        "local": biz_a.base,
                    },
                },
            )
            assert moved.status_code == 200, moved.status_code
            account = client.get(f"{base}/environments/test/accounts/gsb").json()
            restored = client.put(
                f"{base}/environments/test/accounts/gsb",
                json={
                    "revision": account["revision"],
                    "credentials": {"username": USER_A, "password": PASS_A},
                },
            )
            assert restored.status_code == 200, restored.status_code
            biz_b.capture.hold.set()
            thread.join(10)
            assert holder["response"].status_code == 200, holder["response"].status_code
            next_b = _paths(biz_b.capture, "/next")
            next_a = _paths(biz_a.capture, "/next")
            assert len(next_b) == before_next + 1, (
                f"biz_b_next={len(next_b)} biz_a_next={len(next_a)}"
            )
            assert not next_a, f"biz_a_next={len(next_a)}"
            fresh = client.post(
                f"{base}/assets/api.gsb.account.balance/run",
                json={"env": "test", "params": {}},
            )
            assert fresh.status_code == 200, fresh.status_code
            balances = _paths(biz_a.capture, "/api/account/balance")
            assert len(balances) == before_balance + 1, (
                f"biz_a_balance={len(balances)} want={before_balance + 1}"
            )
            assert next_b[-1]["x_token"] == token_for(NEW_PASS), "inflight_token"
            assert balances[-1]["x_token"] == token_for(PASS_A), "fresh_token"
            state["account_password"] = PASS_A
            return "in-flight steps keep old host; next run uses new host"

        def a8() -> str:
            lab = client.get(f"{base}/environments/lab").json()
            disabled = client.put(
                f"{base}/environments/lab",
                json={"revision": lab["revision"], "enabled": False},
            )
            assert disabled.status_code == 200, disabled.status_code
            frozen_hosts = disabled.json()["api_hosts"]
            repo = ctx["repo_path"]
            env_file = repo / "projects" / "demo" / "config" / "envs" / "test.yaml"
            env_file.write_text("api_hosts:\n  local: http://127.0.0.1:1\n", encoding="utf-8")
            new_sha = commit_all(repo, "template only")
            synced = sync_repo(raw, ctx["repo"])
            assert synced["commit_sha"] == new_sha != ctx["commit_sha"]
            again = client.get(f"{base}/environments/lab").json()
            assert again["enabled"] is False
            assert again["api_hosts"] == frozen_hosts
            assert again["revision"] == disabled.json()["revision"]
            project = client.get(base).json()
            assert project["commit_sha"] == new_sha
            return f"web kept; commit {new_sha[:7]}"

        def a9() -> str:
            spare = client.post(
                f"{base}/environments/test/accounts",
                json={
                    "account_name": "spare",
                    "login_profile": "gsb_login",
                    "credentials": {"username": USER_A},
                },
            )
            assert spare.status_code == 201, spare.status_code
            anon = client.post(
                f"{base}/assets/api.gsb.anon/run", json={"env": "test", "params": {}}
            )
            assert anon.status_code == 200, anon.status_code
            assert anon.json()["auth"] is None
            before = len(biz_a.capture.snapshot()) + len(login.capture.snapshot())
            missing = client.post(
                f"{base}/assets/api.gsb.ghost/run", json={"env": "test", "params": {}}
            )
            assert missing.status_code == 422
            assert FALLBACK not in missing.text
            assert "TESTPLAT_GSB" not in missing.text
            after_missing = len(biz_a.capture.snapshot()) + len(login.capture.snapshot())
            assert after_missing == before
            account = client.get(f"{base}/environments/test/accounts/gsb").json()
            disabled = client.put(
                f"{base}/environments/test/accounts/gsb",
                json={"revision": account["revision"], "enabled": False},
            )
            assert disabled.status_code == 200, disabled.status_code
            blocked = client.post(
                f"{base}/assets/api.gsb.account.balance/run",
                json={"env": "test", "params": {}},
            )
            assert blocked.status_code == 422
            assert FALLBACK not in blocked.text
            assert PASS_A not in blocked.text
            return "spare ignored; missing and disabled preflight"

        def a10() -> str:
            run = client.post(f"{base}/assets/api.gsb.anon/run", json={"env": "test", "params": {}})
            assert run.status_code == 200, run.status_code
            body = run.json()
            record_id = body["record_id"]
            frozen_revision = body["config_revision"]
            current = client.get(f"{base}/environments/test").json()
            client.put(
                f"{base}/environments/test",
                json={"revision": current["revision"], "timeout_seconds": 3},
            )
            detail = client.get(f"{base}/execution-records/{record_id}")
            saved = detail.json()
            assert saved["operator"] == PLATFORM_USER
            assert saved["env"] == "test"
            assert saved["commit_sha"]
            assert saved["config_revision"] == frozen_revision
            assert PASS_A not in detail.text
            assert NEW_PASS not in detail.text
            changes = client.get(f"{base}/environments/test")
            assert PASS_A not in changes.text
            return f"history revision {frozen_revision} unchanged"

        def a11() -> str:
            current = client.get(f"{base}/environments/lab").json()
            revision = current["revision"]
            first = TestClient(app)
            second = TestClient(app)
            inherit_cookies(raw, first)
            inherit_cookies(raw, second)
            ok = first.put(
                f"{base}/environments/lab",
                json={"revision": revision, "timeout_seconds": 4},
            )
            conflict = second.put(
                f"{base}/environments/lab",
                json={"revision": revision, "timeout_seconds": 5},
            )
            assert ok.status_code == 200, ok.status_code
            assert conflict.status_code == 409, conflict.status_code
            assert "配置版本冲突" in conflict.text
            run = client.post(f"{base}/assets/api.gsb.anon/run", json={"env": "pre", "params": {}})
            assert run.status_code == 200, run.status_code
            assert isinstance(run.json()["config_revision"], int)
            return "second writer 409; run has one revision"

        def a12() -> str:
            env = os.environ.copy()
            env["PHASE4_1A_CHILD"] = "restart"
            env["GATE_USER"] = PLATFORM_USER
            env["GATE_PASSWORD"] = PLATFORM_PASSWORD
            env["GATE_ACCOUNT_PASSWORD"] = PASS_A
            env["CRED_PATH"] = f"{base}/environments/pre/accounts/gsb/credentials"
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve())],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            line = (proc.stdout or "").strip().splitlines()
            payload = json.loads(line[-1]) if line else {"ok": False, "status": proc.returncode}
            assert payload.get("ok") is True, payload
            blob = db_path.read_bytes()
            for secret in (token, master, PASS_A, *SESSION_COOKIES, *ISSUED_BUSINESS_TOKENS):
                assert secret.encode() not in blob, "sqlite"
            return "restart decrypts; sqlite has no plaintext"

        def a13() -> str:
            strict = client.post(
                f"{base}/cases/case.demo.account/run",
                json={"env": "test", "params": {}},
            )
            assert strict.status_code == 422, strict.status_code
            assert "Traceback" not in strict.text
            assert PASS_A not in strict.text
            alias = client.post(
                f"{base}/cases/case.demo.alias/run",
                json={"env": "test", "params": {}},
            )
            assert alias.status_code == 200, alias.status_code
            assert alias.json()["status"] == "success"
            headers = [
                item["x_resource_id"]
                for item in biz_a.capture.snapshot()
                if item["path"] == "/demo/resources/item"
            ]
            assert "res-42" in headers
            before = len(_paths(biz_a.capture, "/demo/resources/item"))
            failed = client.post(
                f"{base}/cases/case.demo.failfast/run",
                json={"env": "test", "params": {}, "fail_fast": False},
            )
            assert failed.status_code == 200, failed.status_code
            result = failed.json()["result"]
            assert result["steps"][0]["status"] == "failed"
            assert result["steps"][1]["status"] == "skipped"
            assert result["steps"][1]["skip_reason"] == "fail_fast"
            assert len(_paths(biz_a.capture, "/demo/resources/item")) == before
            return "strict schema alias fail-fast; cache covered by A6"

        for item, fn in (
            ("A1", a1),
            ("A2", a2),
            ("A3", a3),
            ("A4", a4),
            ("A5", a5),
            ("A6", a6),
            ("A7", a7),
            ("A8", a8),
            ("A9", a9),
            ("A10", a10),
            ("A11", a11),
            ("A12", a12),
            ("A13", a13),
        ):
            _check(item, fn)

        def real_assets() -> str:
            import yaml

            from tests.platform_gate import default_assets_checkout
            from tests.repo_support import attach_repos_config

            src = default_assets_checkout(ROOT)
            if not src.is_dir():
                raise RuntimeError("assets_checkout_missing")
            dest = work / "assets-copy"
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".venv", "__pycache__"))
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"

            def git(args: list[str]) -> str:
                result = subprocess.run(
                    ["git", *args],
                    cwd=str(dest),
                    env=env,
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"git_failed:{args[0]}")
                return result.stdout.decode().strip()

            git(["checkout", "-B", "phase4-1a-pin", ASSETS_SHA])
            git(["config", "user.email", "matrix@example.com"])
            git(["config", "user.name", "Matrix"])
            sha = git(["rev-parse", "HEAD"])
            assert sha == ASSETS_SHA
            data_dir = work / "assets-data"
            data_dir.mkdir()
            attach_repos_config(
                data_dir=data_dir,
                url=dest.resolve().as_uri(),
                repo_key="assets",
                branch="phase4-1a-pin",
            )
            synced = sync_repo(raw, "assets")
            assert synced["commit_sha"] == ASSETS_SHA
            asset_base = "/repos/assets/projects/gsb"
            profiles = client.get(f"{asset_base}/login-profiles").json()
            assert any(item["name"] == "gsb_login" for item in profiles["profiles"])
            for env_name in ("test", "pre"):
                create_env(
                    asset_base,
                    env_name,
                    biz_a.base,
                    login.base,
                    timeout_seconds=2,
                    case_params={"product_keyword": "示例商品"},
                )
                create_account(asset_base, env_name, USER_A, PASS_A)
            login.capture.events.clear()
            biz_a.capture.events.clear()
            balance = client.post(
                f"{asset_base}/assets/api.gsb.account.balance/run",
                json={"env": "test", "params": {}},
            )
            smoke = client.post(
                f"{asset_base}/cases/case.gsb.smoke/run",
                json={"env": "pre", "params": {}},
            )
            assert balance.status_code == 200, balance.status_code
            assert smoke.status_code == 200, smoke.status_code
            assert _queries(login.capture, "/site/login")[0]["password"] == PASS_A
            assert _paths(biz_a.capture, "/api/account/balance")
            assert _paths(biz_a.capture, "/api/b2/orders/search/product")
            template = yaml.safe_load(
                (dest / "projects/gsb/config/envs/test.yaml").read_text(encoding="utf-8")
            )["api_hosts"]
            current = client.get(f"{asset_base}/environments/test").json()
            live = client.put(
                f"{asset_base}/environments/test",
                json={
                    "revision": current["revision"],
                    "api_hosts": template,
                    "timeout_seconds": 2,
                },
            )
            assert live.status_code == 200, live.status_code
            live_run = client.post(
                f"{asset_base}/assets/api.gsb.account.balance/run",
                json={"env": "test", "params": {}},
            )
            assert live_run.status_code in {200, 502, 504}, live_run.status_code
            assert PASS_A not in live_run.text
            rows = client.get(
                f"{asset_base}/execution-records", params={"env": "test", "limit": 5}
            ).json()
            assert rows
            detail = client.get(f"{asset_base}/execution-records/{rows[0]['id']}").json()
            assert detail["operator"] == PLATFORM_USER
            assert detail["env"] == "test"
            assert detail["commit_sha"] == ASSETS_SHA
            assert isinstance(detail["config_revision"], int)
            kept = client.get(f"{asset_base}/environments/pre").json()
            (dest / "projects/gsb/config/envs/test.yaml").write_text(
                "api_hosts:\n  gsb: http://127.0.0.1:1\n  unified_login: http://127.0.0.1:1\n",
                encoding="utf-8",
            )
            git(["add", "-A"])
            git(["commit", "-m", "template only"])
            new_sha = git(["rev-parse", "HEAD"])
            synced_again = sync_repo(raw, "assets")
            assert synced_again["commit_sha"] == new_sha != ASSETS_SHA
            again = client.get(f"{asset_base}/environments/pre").json()
            assert again["api_hosts"] == kept["api_hosts"]
            assert again["enabled"] is True
            state["live_http"] = live_run.status_code
            return (
                f"fake_assets_ok live_http={live_run.status_code} "
                "real_gsb_business_not_required sync_kept_web"
            )

        def leak() -> str:
            list_accounts = client.get(f"{base}/environments/test/accounts")
            assert PASS_A not in list_accounts.text
            assert "credentials" not in list_accounts.text
            creds = client.get(f"{base}/environments/pre/accounts/gsb/credentials")
            assert creds.status_code == 200
            assert "no-store" in creds.headers.get("cache-control", "")
            inject_leak_markers()
            blob_logs = "\n".join(logs)
            scan_secret_carriers(
                logs=blob_logs,
                sqlite_blob=db_path.read_bytes(),
                traffic=client.traffic,
            )
            joined = blob_logs + "\n".join(text for _url, _status, text in client.traffic)
            assert "Traceback" not in joined
            return (
                f"responses logs sqlite clean; tokens={len(ISSUED_BUSINESS_TOKENS)} "
                f"sessions={len(SESSION_COOKIES)}; live_http={state.get('live_http')}"
            )

        _check("REAL", real_assets)
        _check("LEAK", leak)
    finally:
        for server in (login, biz_a, biz_b):
            stop_server(server)
        for name in ("testplat_control", "testplat_engine"):
            logging.getLogger(name).removeHandler(handler)

    report = {
        "phase": "4.1a",
        "assets_sha": ASSETS_SHA,
        "real_gsb_business_pass_required": False,
        "results": RESULTS,
        "passed": sum(1 for row in RESULTS if row["status"] == "PASS"),
        "failed": sum(1 for row in RESULTS if row["status"] == "FAIL"),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    text = redact(json.dumps(report, ensure_ascii=False, indent=2))
    (OUT / "phase4_1a-matrix-report.json").write_text(text + "\n", encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({"passed": report["passed"], "failed": report["failed"]}))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    if os.environ.get("PHASE4_1A_CHILD") == "restart":
        sys.path.insert(0, str(ROOT / "src"))
        sys.path.insert(0, str(ROOT))
        raise SystemExit(restart_main())
    raise SystemExit(main())
