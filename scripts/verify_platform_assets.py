"""Actual Assets + real local Engine acceptance against isolated fake services only."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet

# No preview config is read; all credentials in this acceptance are invented.
with tempfile.TemporaryDirectory(prefix="testplat-platform-actual-") as d:
    os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(d) / "isolated.db")
    os.environ["TESTPLAT_MASTER_KEY"] = Fernet.generate_key().decode()
    os.environ["TESTPLAT_LEGACY_GIT_CONFIG"] = "false"
    from fastapi.testclient import TestClient

    from testplat_control.database.session import SessionLocal
    from testplat_control.main import app
    from testplat_control.platform_import import build_plan, import_plan
    from tests.platform_gate import establish
    from tests.repo_support import bootstrap_synced_project
    from tests.test_platform_workspaces import source_tree

    events = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            path = urlsplit(self.path)
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            query = parse_qs(path.query if self.command == "GET" else raw.decode())
            events.append(
                {
                    "path": path.path,
                    "fields": query,
                    "token": self.headers.get("Authorization"),
                    "cookie": bool(self.headers.get("Cookie")),
                }
            )
            if path.path == "/site/login":
                data = {"data": {"hash": "fake-token", "userId": "fake-user"}}
            elif path.path == "/login":
                data = {"data": {"token": "fake-picker-token", "userId": "fake-picker-user"}}
            elif path.path == "/api/account/balance":
                data = {"errorCode": "0", "data": {"balance": 100}}
            else:
                data = {"ok": True}
            body = json.dumps(data).encode()
            self.send_response(200)
            if path.path == "/login":
                self.send_header("Set-Cookie", "SESSION=fake-cookie; Path=/")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        source = Path(d) / "old"
        source_tree(source, f"http://127.0.0.1:{server.server_port}")
        with TestClient(app) as client:
            establish(client, username="isoplat", password="fake-platform-acceptance")
            assets = Path(
                os.environ.get(
                    "TESTPLAT_ASSETS_SOURCE",
                    Path(__file__).resolve().parents[2] / "testplat-assets",
                )
            )
            files = {
                str(p.relative_to(assets)): p.read_text()
                for p in assets.rglob("*.yaml")
                if ".git" not in p.parts
            }
            files["projects/daifa_picker/api/picker_probe.yaml"] = json.dumps(
                {
                    "id": "api.picker_probe",
                    "name": "fake-only profile probe",
                    "host": "daifa_picker",
                    "method": "GET",
                    "url": "/probe",
                    "auth": "df_picker.default",
                    "request": {},
                    "success": {"status_code": 200},
                }
            )
            bootstrap_synced_project(client, Path(d), files, project_key="gsb")
            plans = build_plan(source, allow_e3e3_b2_rename=True)
            with SessionLocal() as db:
                result = import_plan(db, plans, repo="main", operator="isolated", apply=True)
            # Existing verified account is intentionally absent in this independent fixture.
            client.post(
                "/repos/main/projects/gsb/environments/test/accounts",
                json={
                    "account_name": "gsb.b2.primary",
                    "login_profile": "gsb_login",
                    "credentials": {
                        "username": "fake-existing",
                        "password": "fake-existing-password",
                    },
                },
            ).raise_for_status()
            runs = []
            for key, api in [
                ("gsb", "api.gsb.account.balance"),
                ("gsb_e3e3", "api.gsb.account.balance"),
                ("go2", "api.go2.entry"),
                ("e3e3", "api.e3e3.entry"),
                ("daifa_admin", "api.daifa_admin.entry"),
                ("daifa_admin_e3e3", "api.daifa_admin.entry"),
                ("daifa_picker", "api.picker_probe"),
                ("daifa_picker_e3e3", "api.picker_probe"),
                ("admin_go2", "api.admin_go2.entry"),
                ("admin_go2_e3e3", "api.admin_go2.entry"),
            ]:
                r = client.post(
                    f"/repos/main/projects/{key}/assets/{api}/run",
                    json={"env": "test", "params": {}},
                )
                assert r.status_code == 200 and r.json()["status"] == "success", (
                    key,
                    r.status_code,
                    r.json().get("status"),
                )
                runs.append(
                    {"workspace": key, "status": "success", "record_id": r.json()["record_id"]}
                )
            # GSB source isolation and management cookie probe actually sent by Engine.
            sources = [e["fields"]["source"][0] for e in events if e["path"] == "/site/login"]
            assert sources == ["go2", "e3e3"]
            assert any(e["path"] == "/nx/withdrawView" and e["cookie"] for e in events)
            assert [
                e["fields"]["source"][0]
                for e in events
                if e["path"] == "/login" and e["fields"].get("source")
            ] == ["go2", "e3e3"]
            assert [e["token"] for e in events if e["path"] == "/probe"] == [
                "fake-picker-token",
                "fake-picker-token",
            ]
            report = {
                "database_isolated": True,
                "actual_assets_runs": runs,
                "import": result,
                "login_sources": sources,
                "management_cookie_probe": True,
            }
            Path("/tmp/testplat-platform-acceptance.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2)
            )
            print(
                json.dumps(
                    {
                        "actual_assets_requests_passed": len(runs),
                        "login_sources": sources,
                        "management_cookie_probe": True,
                    }
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
