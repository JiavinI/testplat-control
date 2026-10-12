"""真实 Engine 0.2 端到端：Control -> PackageEngineAdapter -> CaseRunner -> 本地 HTTP。

不注入 Fake；目标服务只监听 127.0.0.1，不访问公网。覆盖 success / 业务 failed /
变量解析失败 / 各类 preflight / timeout / transport，并核对记录规则与步骤数据。
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest
from fastapi.testclient import TestClient

from testplat_control.database.models import ExecutionRecord
from testplat_control.database.session import SessionLocal
from testplat_control.deps import get_engine_port
from testplat_control.main import app
from testplat_control.services import execution_service
from tests.case_support import (
    assert_case_result_invariants,
    create_project,
    write_assets,
    write_env,
)

SERVER_SECRET = "srv-secret-token-9f31"


class _Handler(BaseHTTPRequestHandler):
    """本地目标服务；把收到的请求记录到 ``server.requests`` 以便断言。"""

    def _record(self, body: bytes = b"") -> None:
        self.server.requests.append(  # type: ignore[attr-defined]
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body.decode("utf-8") if body else "",
            }
        )

    def _json(self, status: int, payload: object) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self._record(self.rfile.read(length) if length else b"")
        if self.path == "/demo/resources":
            # 响应里带一个秘密键：Engine 必须在公开结果里脱敏/移除，落库后也不得出现。
            self._json(201, {"id": "res-42", "access_token": SERVER_SECRET})
        else:
            self.send_error(404)

    def do_GET(self) -> None:  # noqa: N802
        self._record()
        if self.path == "/demo/resources/item":
            self._json(200, {"ok": True})
        elif self.path == "/status/200":
            self._json(200, {"ok": True})
        elif self.path == "/demo/slow":
            time.sleep(1.5)
            self._json(200, {"slow": True})
        else:
            self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


@pytest.fixture
def local_server() -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def real(tmp_path: Path, local_server: ThreadingHTTPServer) -> Iterator[dict[str, Any]]:
    """真实 PackageEngineAdapter（不注入 Fake）+ 指向本地服务的项目。"""
    assets = tmp_path / "assets"
    config = tmp_path / "config"
    write_assets(assets)
    host, port = local_server.server_address
    write_env(config, f"http://{host}:{port}")
    app.dependency_overrides.pop(get_engine_port, None)
    with TestClient(app) as client:
        yield {
            "client": client,
            "project_id": create_project(client, assets, config),
            "requests": local_server.requests,  # type: ignore[attr-defined]
        }


def _run(real: dict[str, Any], case_id: str, params: dict[str, Any] | None = None):
    return real["client"].post(
        f"/projects/{real['project_id']}/cases/{case_id}/run", json={"params": params or {}}
    )


def _records(real: dict[str, Any], **query: Any) -> list[dict[str, Any]]:
    response = real["client"].get(
        f"/projects/{real['project_id']}/execution-records", params=query
    )
    assert response.status_code == 200
    return response.json()


def _stored(record_id: str) -> ExecutionRecord:
    db = SessionLocal()
    try:
        record = db.query(ExecutionRecord).filter(ExecutionRecord.id == record_id).one()
        db.expunge(record)
        return record
    finally:
        db.close()


def _short_step_timeout(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """路由未暴露 timeout_seconds：通过包装 run_case 缩短每步骤超时来触发 timeout。"""
    original = execution_service.run_case

    async def _wrapped(**kwargs: Any):
        kwargs["timeout_seconds"] = seconds
        return await original(**kwargs)

    monkeypatch.setattr("testplat_control.api.cases.run_case", _wrapped)


def test_real_case_success_passes_alias_between_steps(real: dict[str, Any]) -> None:
    resp = _run(real, "case.demo.create_then_get", {"resource_name": "alpha"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    result = body["result"]
    assert result["summary"] == {"total": 2, "success": 2, "failed": 0, "skipped": 0}
    assert_case_result_invariants(result, ["create", "get"])
    assert result["steps"][0]["output"] == "created"
    assert result["steps"][1]["output"] is None

    # 请求参数覆盖生效，且第二步确实收到了第一步响应里的 id。
    create_req, get_req = real["requests"]
    assert json.loads(create_req["body"]) == {"name": "alpha"}
    assert get_req["headers"]["X-Resource-Id"] == "res-42"

    # 保存的是完整步骤结果，且秘密不入库、不外显。
    saved = _stored(body["record_id"])
    assert (saved.asset_type, saved.asset_id, saved.status) == (
        "case",
        "case.demo.create_then_get",
        "success",
    )
    assert SERVER_SECRET not in saved.result_json
    assert SERVER_SECRET not in resp.text
    assert json.loads(saved.result_json)["steps"][0]["response"]["body"]["id"] == "res-42"

    detail = real["client"].get(
        f"/projects/{real['project_id']}/case-execution-records/{body['record_id']}"
    )
    assert detail.status_code == 200
    assert detail.json()["result"]["summary"]["success"] == 2
    assert [r["id"] for r in _records(real, asset_type="case")] == [body["record_id"]]


def test_real_case_assertion_failure_is_http_200_and_saved(real: dict[str, Any]) -> None:
    resp = _run(real, "case.demo.assert_failed")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "failed"
    result = body["result"]
    assert result["summary"] == {"total": 2, "success": 0, "failed": 1, "skipped": 1}
    assert result["steps"][0]["error"]["kind"] == "assertion"
    assert result["steps"][1]["status"] == "skipped"
    assert_case_result_invariants(result, ["bad_assert", "after"])
    assert len(real["requests"]) == 1  # fail-fast：after 步骤没有发请求
    assert _stored(body["record_id"]).status == "failed"


def test_real_case_runtime_variable_failure_is_business_failed(real: dict[str, Any]) -> None:
    resp = _run(real, "case.demo.missing_runtime_path")

    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert [s["status"] for s in result["steps"]] == ["success", "failed", "skipped"]
    consume = result["steps"][1]
    assert consume["error"]["kind"] == "variable_resolution"
    assert consume["error"]["step_id"] == "consume"
    assert consume["request"] is None and consume["response"] is None
    assert len(real["requests"]) == 1  # 只有 create 发了请求
    assert _stored(resp.json()["record_id"]).status == "failed"


@pytest.mark.parametrize(
    ("case_id", "params", "http_status", "detail_contains"),
    [
        ("case.demo.undeclared_alias", None, 422, "alias"),
        ("case.demo.unsupported_step", None, 422, "ui"),
        ("case.demo.missing_params", None, 422, "params.missing"),
        ("case.demo.does_not_exist", None, 404, "不存在"),
    ],
)
def test_real_case_preflight_errors_do_not_create_records(
    real: dict[str, Any], case_id: str, params: Any, http_status: int, detail_contains: str
) -> None:
    resp = _run(real, case_id, params)

    assert resp.status_code == http_status, resp.text
    assert detail_contains in resp.json()["detail"]
    assert real["requests"] == []  # preflight：零 HTTP 副作用
    assert _records(real) == []


def test_real_case_missing_params_can_be_supplied_by_request(real: dict[str, Any]) -> None:
    """同一资产：缺参数 → invalid_input/422；请求提供后 → 200 success。"""
    assert _run(real, "case.demo.missing_params").status_code == 422
    resp = _run(real, "case.demo.missing_params", {"missing": "now-here"})
    assert resp.status_code == 200, resp.text
    assert json.loads(real["requests"][-1]["body"]) == {"name": "now-here"}


def test_real_case_timeout_maps_504_and_saves_partial_steps(
    real: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _short_step_timeout(monkeypatch, 0.2)

    resp = _run(real, "case.demo.timeout")

    assert resp.status_code == 504, resp.text
    (item,) = _records(real, asset_type="case")
    assert item["status"] == "failed"
    typed = real["client"].get(
        f"/projects/{real['project_id']}/case-execution-records/{item['id']}"
    ).json()
    result = typed["result"]
    assert [(s["step_id"], s["status"]) for s in result["steps"]] == [
        ("create", "success"),
        ("slow", "failed"),
        ("after", "skipped"),
    ]
    assert result["steps"][1]["error"]["kind"] == "timeout"
    assert result["error"]["kind"] == "timeout" and result["error"]["stage"] == "execution"
    assert_case_result_invariants(result, ["create", "slow", "after"])


def test_real_case_transport_maps_502_and_saves_partial_steps(real: dict[str, Any]) -> None:
    resp = _run(real, "case.demo.transport")

    assert resp.status_code == 502, resp.text
    (item,) = _records(real, asset_type="case")
    typed = real["client"].get(
        f"/projects/{real['project_id']}/case-execution-records/{item['id']}"
    ).json()
    result = typed["result"]
    assert [(s["step_id"], s["status"]) for s in result["steps"]] == [
        ("create", "success"),
        ("dead", "failed"),
        ("after", "skipped"),
    ]
    assert result["error"]["kind"] == "transport"
    assert typed["status"] == "failed"


def test_real_case_tree_and_detail_ids_agree_with_engine(real: dict[str, Any]) -> None:
    """Control 由路径推导的 Case id 与 Engine 的路径权威一致：树/详情给出的 id 可直接运行。"""
    tree = real["client"].get(f"/projects/{real['project_id']}/assets").json()

    def walk(node: dict[str, Any]):
        yield node
        for child in node.get("children") or []:
            yield from walk(child)

    case_ids = sorted(n["id"] for n in walk(tree) if n["id"].startswith("case."))
    assert "case.demo.create_then_get" in case_ids
    for case_id in case_ids:
        detail = real["client"].get(f"/projects/{real['project_id']}/cases/{case_id}")
        assert detail.status_code == 200
        # 运行时 Engine 不会报 asset_not_found（可能是其他 preflight 或业务/系统结果）。
        resp = _run(real, case_id, {"missing": "x", "resource_name": "x"})
        assert resp.status_code != 404, (case_id, resp.text)
