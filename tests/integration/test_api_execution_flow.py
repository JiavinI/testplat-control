"""从建项目到查询执行记录的端到端流程。

引擎用 FakeEngineAdapter 代替，HTTP 路由、资产扫描和数据库都走真实实现。
登录接口在 password 为 ``wrong-password`` 时由替身返回失败，其余调用成功。
Fake 通过 dependency_overrides 注入，不 monkeypatch 路由全局符号。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from testplat_control.adapters.fake_engine import FakeEngineAdapter
from testplat_control.deps import get_engine_port
from testplat_control.main import app
from tests.case_support import create_project, project_api_base

# 历史 Git 配置兼容测试；生产默认关闭。
pytestmark = pytest.mark.legacy_git_config

client = TestClient(app)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ASSETS_ROOT = FIXTURES / "assets"
CONFIG_ROOT = FIXTURES / "config"
LOGIN = "api.user.login"
CREATE = "api.user.create"
HEALTH = "api.common.health_check"


def assert_execution_record(record: dict, expected_status: str) -> None:
    """校验列表项或详情共有的执行记录字段。

    Args:
        record: 列表项或详情 JSON。
        expected_status: 期望的 success 或 failed。
    """
    assert record["status"] == expected_status
    assert isinstance(record["id"], str) and record["id"]
    assert isinstance(record["asset_id"], str) and record["asset_id"]
    assert record["start_time"]
    duration = record.get("duration")
    if duration is not None:
        assert isinstance(duration, (int, float))
        assert duration >= 0
    if "result" in record:
        assert isinstance(record["result"], dict)
        assert record["result"]["status"] == expected_status
    if "display" in record:
        assert record["display"]["start_time"]
        if duration is not None:
            assert record["display"]["duration"]


def _find_asset(node: dict, asset_id: str) -> dict | None:
    if node.get("id") == asset_id:
        return node
    for child in node.get("children") or []:
        found = _find_asset(child, asset_id)
        if found is not None:
            return found
    return None


def _run(project_id: str, asset_id: str, params: dict | None = None):
    return client.post(
        f"{project_api_base(project_id)}/assets/{asset_id}/run",
        json={"env": "test", "params": params or {}},
    )


def _list(project_id: str, **params: str):
    return client.get(f"{project_api_base(project_id)}/execution-records", params=params)


@pytest.fixture
def engine() -> FakeEngineAdapter:
    """把执行路由上的 EnginePort 换成 Fake（DI override）。"""
    fake = FakeEngineAdapter()
    app.dependency_overrides[get_engine_port] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_engine_port, None)


@pytest.fixture
def project_id(engine: FakeEngineAdapter, tmp_path: Path) -> str:
    """把 fixtures 资产树同步进本地 git 仓并返回 project_id。"""
    import shutil

    assert ASSETS_ROOT.is_dir()
    assert (CONFIG_ROOT / "envs" / "test.yaml").is_file()
    assets = tmp_path / "assets"
    config = tmp_path / "config"
    shutil.copytree(ASSETS_ROOT, assets)
    shutil.copytree(CONFIG_ROOT, config)
    return create_project(client, assets, config, name=f"integration-{uuid4().hex[:8]}")


def test_full_api_execution_flow(project_id: str) -> None:
    """建项目、看资产树、取参数表单、执行，再查列表和详情。"""
    tree = client.get(f"{project_api_base(project_id)}/assets")
    assert tree.status_code == 200
    login = _find_asset(tree.json(), LOGIN)
    assert login is not None
    assert login["type"] == "file"
    assert login["path"] == "api/user/login.yaml"

    form = client.get(f"{project_api_base(project_id)}/assets/{LOGIN}/params")
    assert form.status_code == 200
    assert form.json()["asset_id"] == LOGIN
    by_name = {item["name"]: item for item in form.json()["params"]}
    assert by_name["username"]["type"] == "string"
    assert by_name["username"]["required"] is False
    assert by_name["username"]["description"] == "用户名"
    assert by_name["password"]["required"] is True
    assert by_name["password"]["description"] == "密码"

    run = _run(project_id, LOGIN, {"username": "alice", "password": "secret"})
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "success"
    assert body["result"]["response"]["status_code"] == 200
    record_id = body["record_id"]

    listed = _list(project_id)
    assert listed.status_code == 200
    matched = next(item for item in listed.json() if item["id"] == record_id)
    assert_execution_record(matched, "success")
    assert matched["asset_id"] == LOGIN

    detail = client.get(f"{project_api_base(project_id)}/execution-records/{record_id}")
    assert detail.status_code == 200
    saved = detail.json()
    assert_execution_record(saved, "success")
    assert saved["project_id"] == project_id
    assert saved["asset_type"] == "api"
    assert saved["request"]["params"]["username"] == "alice"
    assert saved["response"]["body"]["ok"] is True


def test_execution_with_invalid_params(project_id: str) -> None:
    """缺必填或类型不对时返回 422，并且不产生执行记录。"""
    before = _list(project_id).json()

    missing = _run(project_id, LOGIN, {"username": "alice"})
    assert missing.status_code == 422
    assert "password" in missing.json()["detail"]

    wrong_type = _run(project_id, CREATE, {"username": "alice", "email": 1})
    assert wrong_type.status_code == 422
    assert "email" in wrong_type.json()["detail"]

    unknown = _run(project_id, HEALTH, {"extra": "x"})
    assert unknown.status_code == 422
    assert "unknown param" in unknown.json()["detail"]

    assert _list(project_id).json() == before


def test_execution_record_filtering(project_id: str) -> None:
    """多次执行后可以按状态和资产过滤，默认新的记录在前。"""
    assert _run(project_id, LOGIN, {"password": "secret"}).status_code == 200
    failed = _run(project_id, LOGIN, {"password": "wrong-password"})
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    created = _run(project_id, CREATE, {"username": "alice", "email": "a@example.com"})
    assert created.status_code == 200
    assert _run(project_id, HEALTH).status_code == 200

    successes = _list(project_id, status="success").json()
    assert len(successes) == 3
    assert all(item["status"] == "success" for item in successes)

    login_only = _list(project_id, asset_id=LOGIN).json()
    assert len(login_only) == 2
    assert {item["status"] for item in login_only} == {"success", "failed"}

    login_failed = _list(project_id, status="failed", asset_id=LOGIN).json()
    assert len(login_failed) == 1
    assert_execution_record(login_failed[0], "failed")
    assert login_failed[0]["id"] == failed.json()["record_id"]

    ordered = _list(project_id).json()
    assert ordered[0]["asset_id"] == HEALTH
    assert ordered[-1]["asset_id"] == LOGIN
    assert ordered[-1]["status"] == "success"


def test_multiple_executions(project_id: str) -> None:
    """同一接口连续执行会产生多条独立记录。"""
    record_ids = []
    for _ in range(3):
        response = _run(project_id, HEALTH)
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        record_ids.append(response.json()["record_id"])

    assert len(set(record_ids)) == 3
    listed = _list(project_id, asset_id=HEALTH).json()
    assert [item["id"] for item in listed] == list(reversed(record_ids))
    for item in listed:
        assert_execution_record(item, "success")
        assert item["asset_id"] == HEALTH


def test_execution_failure_handling(project_id: str) -> None:
    """引擎判定失败时仍返回记录，列表和详情都能看到 failed。"""
    response = _run(project_id, LOGIN, {"username": "alice", "password": "wrong-password"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["result"]["error"]["message"] == "assertion failed"
    assert body["result"]["response"] is None

    detail = client.get(f"{project_api_base(project_id)}/execution-records/{body['record_id']}")
    assert detail.status_code == 200
    saved = detail.json()
    assert_execution_record(saved, "failed")
    assert saved["response"] is None
    # Engine 0.2 的公开 DTO 在构造期递归脱敏：保存的请求快照不再含 password 明文。
    assert saved["request"]["params"]["password"] == "***"
    assert "wrong-password" not in json.dumps(saved, ensure_ascii=False)
    assert saved["display"]["duration"] is not None

    listed = _list(project_id, status="failed").json()
    assert len(listed) == 1
    assert_execution_record(listed[0], "failed")


def test_concurrent_executions(project_id: str, engine: FakeEngineAdapter) -> None:
    """并发执行同一接口时，每条请求都留下自己的成功记录。"""
    engine.delay = 0.05

    async def _run_many() -> list[dict]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            responses = await asyncio.gather(
                *[
                    http.post(
                        f"{project_api_base(project_id)}/assets/{HEALTH}/run",
                        json={"env": "test", "params": {}},
                    )
                    for _ in range(5)
                ]
            )
        payloads = []
        for response in responses:
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "success"
            payloads.append(payload)
        return payloads

    payloads = asyncio.run(_run_many())
    record_ids = [item["record_id"] for item in payloads]
    assert len(set(record_ids)) == 5

    listed = _list(project_id, asset_id=HEALTH).json()
    assert len(listed) == 5
    assert {item["id"] for item in listed} == set(record_ids)
    for item in listed:
        assert_execution_record(item, "success")
