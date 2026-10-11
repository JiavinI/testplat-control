"""真实 Engine 端到端：Control -> PackageEngineAdapter -> SingleApiEngine -> 本地 HTTP。

不注入 Fake；不访问公网。覆盖 success / business failed / timeout / transport /
invalid environment，并核对错误记录规则。
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient

from testplat_control.deps import get_engine_port
from testplat_control.main import app
from testplat_control.services import execution_service


class _LocalHandler(BaseHTTPRequestHandler):
    """本地目标服务：成功、断言失败、慢响应。"""

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        elif self.path == "/assert-fail":
            self._json(200, {"status": "bad"})
        elif self.path == "/slow":
            time.sleep(2.0)
            self._json(200, {"slow": True})
        else:
            self.send_error(404)

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


@pytest.fixture
def local_server() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _write_assets(assets: Path) -> None:
    api = assets / "api" / "common"
    api.mkdir(parents=True)
    (api / "health_check.yaml").write_text(
        "id: api.common.health_check\n"
        "name: health\n"
        "host: local\n"
        "method: GET\n"
        "url: /health\n"
        "request:\n"
        "  inputs: {}\n"
        "success:\n"
        "  status_code: 200\n"
        "  path: $.status\n"
        "  value: ok\n",
        encoding="utf-8",
    )
    (api / "assert_fail.yaml").write_text(
        "id: api.common.assert_fail\n"
        "name: assert-fail\n"
        "host: local\n"
        "method: GET\n"
        "url: /assert-fail\n"
        "request:\n"
        "  inputs: {}\n"
        "success:\n"
        "  status_code: 200\n"
        "  path: $.status\n"
        "  value: ok\n",
        encoding="utf-8",
    )
    (api / "slow.yaml").write_text(
        "id: api.common.slow\n"
        "name: slow\n"
        "host: local\n"
        "method: GET\n"
        "url: /slow\n"
        "request:\n"
        "  inputs: {}\n"
        "success:\n"
        "  status_code: 200\n",
        encoding="utf-8",
    )


@pytest.fixture
def real_project(tmp_path: Path, local_server: str) -> dict[str, str]:
    """构造指向本地 HTTP 的资产与环境；使用默认真实 PackageEngineAdapter。"""
    assets = tmp_path / "assets"
    _write_assets(assets)
    config = tmp_path / "config"
    (config / "envs").mkdir(parents=True)
    (config / "envs" / "test.yaml").write_text(
        yaml.safe_dump(
            {"api_hosts": {"local": local_server}, "timeout": {"default": 30}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    app.dependency_overrides.pop(get_engine_port, None)

    with TestClient(app) as client:
        resp = client.post(
            "/projects",
            json={
                "name": f"real-engine-{uuid4().hex[:8]}",
                "assets_root": str(assets),
                "config_root": str(config),
                "env": "test",
            },
        )
        assert resp.status_code == 200, resp.text
        project_id = resp.json()["id"]
    return {
        "project_id": project_id,
        "assets_root": str(assets),
        "config_root": str(config),
        "base_url": local_server,
    }


def _run(client: TestClient, project_id: str, asset_id: str):
    return client.post(
        f"/projects/{project_id}/assets/{asset_id}/run",
        json={"params": {}},
    )


def _list_records(client: TestClient, project_id: str, **params):
    return client.get(f"/projects/{project_id}/execution-records", params=params)


def _detail(client: TestClient, project_id: str, record_id: str):
    return client.get(f"/projects/{project_id}/execution-records/{record_id}")


def test_real_engine_success(real_project: dict[str, str]) -> None:
    """真实 Engine 成功：HTTP 200，落 success 记录并可查详情。"""
    with TestClient(app) as client:
        resp = _run(client, real_project["project_id"], "api.common.health_check")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "success"
        record_id = body["record_id"]
        detail = _detail(client, real_project["project_id"], record_id)
        assert detail.status_code == 200
        assert detail.json()["status"] == "success"
        assert detail.json()["result"]["status"] == "success"


def test_real_engine_business_failed_is_http_200(real_project: dict[str, str]) -> None:
    """业务断言失败仍是 HTTP 200，记录 status=failed。"""
    with TestClient(app) as client:
        resp = _run(client, real_project["project_id"], "api.common.assert_fail")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "failed"
        assert body["result"]["status"] == "failed"
        assert body["result"]["error"]


def test_real_engine_timeout_maps_504_and_records(
    real_project: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """超时：HTTP 504，execution 阶段落 failed 记录。

    路由未暴露 timeout_seconds，测试通过缩短 run_single_api 默认超时证明映射。
    """
    original = execution_service.run_single_api

    async def _short_timeout(**kwargs):  # noqa: ANN003
        kwargs["timeout_seconds"] = 0.2
        return await original(**kwargs)

    monkeypatch.setattr(execution_service, "run_single_api", _short_timeout)
    monkeypatch.setattr(
        "testplat_control.api.run.run_single_api",
        _short_timeout,
    )

    with TestClient(app) as client:
        resp = _run(client, real_project["project_id"], "api.common.slow")
        assert resp.status_code == 504, resp.text
        listing = _list_records(
            client, real_project["project_id"], asset_id="api.common.slow"
        )
        assert listing.status_code == 200
        items = listing.json()
        assert any(item.get("status") == "failed" for item in items)


def test_real_engine_transport_maps_502_and_records(real_project: dict[str, str]) -> None:
    """传输失败：api_hosts 指向关闭端口，期望 502 + failed 记录。"""
    config = Path(real_project["config_root"])
    (config / "envs" / "test.yaml").write_text(
        yaml.safe_dump(
            {"api_hosts": {"local": "http://127.0.0.1:1"}, "timeout": {"default": 2}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    with TestClient(app) as client:
        before = _list_records(client, real_project["project_id"])
        before_count = len(before.json())
        resp = _run(client, real_project["project_id"], "api.common.health_check")
        assert resp.status_code == 502, resp.text
        after = _list_records(client, real_project["project_id"])
        assert len(after.json()) == before_count + 1
        assert after.json()[0]["status"] == "failed"


def test_real_engine_invalid_environment_no_record(real_project: dict[str, str]) -> None:
    """无效环境：422 preflight，不写记录。"""
    with TestClient(app) as client:
        proj = client.get(f"/projects/{real_project['project_id']}")
        assert proj.status_code == 200
        payload = proj.json()
        upd = client.put(
            f"/projects/{real_project['project_id']}",
            json={
                "name": payload["name"],
                "assets_root": payload["assets_root"],
                "config_root": payload["config_root"],
                "env": "missing-env",
            },
        )
        assert upd.status_code == 200, upd.text
        before = _list_records(client, real_project["project_id"])
        before_count = len(before.json())
        resp = _run(client, real_project["project_id"], "api.common.health_check")
        assert resp.status_code == 422, resp.text
        after = _list_records(client, real_project["project_id"])
        assert len(after.json()) == before_count
