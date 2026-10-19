"""真实迁入资产 + Control + 本地 Engine；隔离库、假账号、本机 HTTP 目标。"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from testplat_control.config import settings
from testplat_control.main import app
from tests.repo_support import bootstrap_synced_project

ASSETS = Path(__file__).resolve().parents[2] / "testplat-assets"


class Handler(BaseHTTPRequestHandler):
    """只记录断言需要的假数据，禁用访问日志。"""

    def do_GET(self):  # noqa: N802
        self.respond()

    def do_POST(self):  # noqa: N802
        self.respond()

    def respond(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(raw) if raw else None
        self.server.events.append(
            {
                "path": parsed.path,
                "query": query,
                "body": payload,
                "token": self.headers.get("X-TOKEN"),
                "user": self.headers.get("X-USER-ID"),
            }
        )
        if parsed.path == "/site/login":
            value = query["source"][0] + "-" + query["username"][0]
            data = {"data": {"hash": "fake-token-" + value, "userId": "fake-user-" + value}}
        else:
            data = {"errorCode": "0", "data": []}
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    if not ASSETS.is_dir():
        pytest.skip("未检出 Assets")
    monkeypatch.setattr(settings, "testplat_master_key", Fernet.generate_key().decode())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.events = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        files = {"testplat.yaml": (ASSETS / "testplat.yaml").read_text()}
        files.update(
            {
                str(p.relative_to(ASSETS)): p.read_text()
                for p in (ASSETS / "projects").rglob("*.yaml")
            }
        )
        with TestClient(app) as client:
            ctx = bootstrap_synced_project(
                client,
                tmp_path,
                files,
                repo_key="migration-" + uuid4().hex[:8],
                project_key="gsb",
            )
            base = f"/repos/{ctx['repo']}/projects"
            for project in ("gsb", "gsb_e3e3"):
                origin = f"http://127.0.0.1:{server.server_port}"
                response = client.post(
                    f"{base}/{project}/environments",
                    json={
                        "env": "test",
                        "api_hosts": {"gsb": origin, "unified_login": origin},
                    },
                )
                assert response.status_code == 201
                for account in ("buyer", "alternate", "gsb.b2.primary"):
                    response = client.post(
                        f"{base}/{project}/environments/test/accounts",
                        json={
                            "account_name": account,
                            "login_profile": "gsb_login",
                            "credentials": {
                                "username": account,
                                "password": "fake-isolated-password",
                            },
                        },
                    )
                    assert response.status_code == 201
            yield client, base, server.events
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def call(client, base, project, api, params, identity="buyer", **extra):
    return client.post(
        f"{base}/{project}/assets/{api}/run",
        json={
            "env": "test",
            "params": params,
            "identity": identity,
            **extra,
        },
    )


def test_common_api_uses_callers_account_and_project_headers(migrated):
    client, base, events = migrated
    params = {"express_id": "fake-express", "quantity": 2, "receiver_province": "四川省"}
    for project, business in (("gsb", "go2"), ("gsb_e3e3", "e3e3")):
        for identity in ("buyer", "alternate"):
            response = call(client, base, project, "api.gsb.b2.order.freight", params, identity)
            assert response.status_code == 200 and response.json()["status"] == "success"
            request = events[-1]
            assert request["token"] == f"fake-token-{business}-{identity}"
            assert request["user"] == f"fake-user-{business}-{identity}"
            assert request["body"]["productCount"] == 2
            assert response.json()["auth"]["identity"] == identity
            assert (
                "fake-token" not in response.text and "fake-isolated-password" not in response.text
            )
            history = client.get(
                f"{base}/{project}/execution-records/{response.json()['record_id']}"
            )
            assert history.status_code == 200 and "fake-token" not in history.text
    sources = [event["query"]["source"][0] for event in events if event["path"] == "/site/login"]
    assert sources == ["go2", "go2", "e3e3", "e3e3"]
    response = call(client, base, "gsb", "api.gsb.b2.order.freight", params, "none")
    assert response.status_code == 200 and events[-1]["token"] is None


def test_required_fields_and_project_guards_never_send_requests(migrated):
    client, base, events = migrated
    form = client.get(f"{base}/gsb/assets/api.gsb.b2.order.freight/params").json()["params"]
    assert {p["name"] for p in form if p["required"]} == {
        "express_id",
        "quantity",
        "receiver_province",
    }
    missing = call(client, base, "gsb", "api.gsb.b2.order.freight", {})
    assert missing.status_code == 422
    nested = call(
        client,
        base,
        "gsb_e3e3",
        "api.gsb.b2.order.e3e3.coupons",
        {
            "product": {},
            "quantity": 1,
        },
    )
    assert nested.status_code == 422 and "product.id" in nested.json()["detail"]
    wrong = call(
        client,
        base,
        "gsb",
        "api.gsb.b2.order.e3e3.coupons",
        {
            "product": {"id": "p1"},
            "quantity": 1,
        },
    )
    assert wrong.status_code == 422
    assert events == []
    for project, allowed, excluded in (("gsb", "go2", "e3e3"), ("gsb_e3e3", "e3e3", "go2")):
        tree = client.get(f"{base}/{project}/assets").text
        assert f'api.gsb.b2.order.{allowed}.create"' in tree
        assert f'api.gsb.b2.order.{excluded}.create"' not in tree
        assert f'"id":"api.gsb.b2.order.{excluded}"' not in tree
        assert (
            client.get(f"{base}/{project}/assets/api.gsb.b2.order.{excluded}.create").status_code
            == 404
        )


def test_query_optional_fields_arrays_and_legacy_case(migrated):
    client, base, events = migrated
    keyword = "测试&A001"
    response = call(
        client, base, "gsb", "api.gsb.b2.order.search_product", {"product_keyword": keyword}
    )
    assert response.status_code == 200 and events[-1]["query"] == {"keywords": [keyword]}
    response = call(
        client,
        base,
        "gsb",
        "api.gsb.b2.order.search_page",
        {
            "search_field": "orderNo",
            "search_terms": "",
            "page_size": 20,
            "page_no": 1,
            "error_print_tag": 0,
            "take_states": ["WAIT"],
        },
    )
    assert response.status_code == 200
    body = events[-1]["body"]
    assert body["takeStates"] == ["WAIT"] and body["errorPrintTag"] == 0
    assert "orderState" not in body and body["searchTerms"] == ""
    response = call(
        client,
        base,
        "gsb",
        "api.gsb.b2.order.go2.create_items",
        {
            "order_items": [{"productId": "fake-product", "quantity": 2}],
            "freight_fee": "0.00",
            "web_order_amount": "100.00",
        },
    )
    assert response.status_code == 200
    order = events[-1]["body"]["orderCreateParameters"][0]
    assert order["orderItems"] == [{"productId": "fake-product", "quantity": 2}]
    assert order["channel"] == "PC" and order["goodsPayLaterFlag"] == "0"
    response = client.post(
        f"{base}/gsb/cases/case.gsb.smoke/run",
        json={
            "env": "test",
            "params": {"product_keyword": keyword},
        },
    )
    assert response.status_code == 200 and response.json()["status"] == "success"


def test_full_body_override_and_missing_or_disabled_account(migrated):
    client, base, events = migrated
    response = call(
        client,
        base,
        "gsb",
        "api.gsb.b2.order.freight",
        {},
        request_override={"body": {"productCount": 4}},
    )
    assert response.status_code == 200 and events[-1]["body"] == {"productCount": 4}
    count = len(events)
    missing = call(
        client,
        base,
        "gsb",
        "api.gsb.b2.order.freight",
        {},
        "missing",
        request_override={"body": {}},
    )
    assert missing.status_code == 422 and len(events) == count
    accounts = client.get(f"{base}/gsb/environments/test/accounts").json()
    buyer = next(a for a in accounts if a["account_name"] == "buyer")
    response = client.put(
        f"{base}/gsb/environments/test/accounts/buyer",
        json={
            "revision": buyer["revision"],
            "enabled": False,
        },
    )
    assert response.status_code == 200
    disabled = call(
        client, base, "gsb", "api.gsb.b2.order.freight", {}, request_override={"body": {}}
    )
    assert disabled.status_code == 422 and len(events) == count
