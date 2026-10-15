"""执行记录过滤、排序和详情测试。"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from testplat_control.api.schemas import (
    ExecutionRecordDetailResponse,
    ExecutionRecordListResponse,
    derive_login_failed,
    parse_result_json,
)
from testplat_control.database.models import ExecutionRecord
from testplat_control.database.session import SessionLocal
from testplat_control.main import app
from tests.case_support import project_api_base

client = TestClient(app)


def _create_project() -> str:
    """直接向 DB 插入 Repo+Project（执行记录测试不依赖资产树）。"""
    from datetime import datetime

    from testplat_control.database.models import Project, Repo

    db = SessionLocal()
    try:
        key = f"r{uuid4().hex[:6]}"
        proj = f"p{uuid4().hex[:6]}"
        if db.query(Repo).filter(Repo.key == key).first() is None:
            db.add(Repo(key=key, branch="main", current_sha="c" * 40, last_sync_result="ok"))
            db.flush()
        now = datetime.utcnow()
        project_id = f"{key}/{proj}"
        db.add(
            Project(
                id=project_id,
                repo=key,
                project_key=proj,
                name=f"exec-{uuid4().hex[:8]}",
                envs=["test", "staging"],
                default_env="test",
                archived=False,
                commit_sha="c" * 40,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        return project_id
    finally:
        db.close()


def _add_record(
    project_id: str,
    *,
    asset_id: str,
    status: str,
    start_time: datetime,
    end_time: datetime | None = None,
    duration: float | None = None,
    result: object | None = None,
    result_json: str | None = None,
    asset_type: str = "api",
    env: str | None = "test",
) -> str:
    record_id = str(uuid4())
    if result_json is None and result is not None:
        result_json = json.dumps(result)
    db = SessionLocal()
    try:
        repo = project_id.split("/", 1)[0] if "/" in project_id else None
        db.add(
            ExecutionRecord(
                id=record_id,
                project_id=project_id,
                asset_type=asset_type,
                asset_id=asset_id,
                status=status,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                result_json=result_json,
                env=env,
                repo=repo,
                commit_sha="c" * 40,
                operator=None,
            )
        )
        db.commit()
    finally:
        db.close()
    return record_id


def test_list_filters_by_status_and_asset_id() -> None:
    """status 与 asset_id 可单独或同时过滤。"""
    project_id = _create_project()
    login_ok = _add_record(
        project_id,
        asset_id="api.user.login",
        status="success",
        start_time=datetime(2026, 10, 10, 8, 0, 0),
        duration=1.0,
    )
    _add_record(
        project_id,
        asset_id="api.user.login",
        status="failed",
        start_time=datetime(2026, 10, 10, 9, 0, 0),
        duration=0.5,
    )
    create_ok = _add_record(
        project_id,
        asset_id="api.user.create",
        status="success",
        start_time=datetime(2026, 10, 10, 10, 0, 0),
        duration=2.0,
    )

    by_status = client.get(
        f"{project_api_base(project_id)}/execution-records",
        params={"status": "success"},
    )
    assert by_status.status_code == 200
    assert {item["id"] for item in by_status.json()} == {login_ok, create_ok}
    assert all(item["status"] == "success" for item in by_status.json())

    by_asset = client.get(
        f"{project_api_base(project_id)}/execution-records",
        params={"asset_id": "api.user.login"},
    )
    assert by_asset.status_code == 200
    assert len(by_asset.json()) == 2
    assert {item["asset_id"] for item in by_asset.json()} == {"api.user.login"}

    both = client.get(
        f"{project_api_base(project_id)}/execution-records",
        params={"status": "failed", "asset_id": "api.user.login"},
    )
    assert both.status_code == 200
    assert len(both.json()) == 1
    assert both.json()[0]["status"] == "failed"
    assert both.json()[0]["asset_id"] == "api.user.login"
    assert set(both.json()[0]) >= {
        "id",
        "asset_id",
        "status",
        "start_time",
        "duration",
        "login_failed",
        "env",
        "commit_sha",
    }


def test_list_defaults_to_start_time_desc_and_can_sort_asc() -> None:
    """默认按开始时间从新到旧，start_time_asc 反过来。"""
    project_id = _create_project()
    early = _add_record(
        project_id,
        asset_id="api.a",
        status="success",
        start_time=datetime(2026, 10, 1, 8, 0, 0),
        duration=1.0,
    )
    middle = _add_record(
        project_id,
        asset_id="api.b",
        status="success",
        start_time=datetime(2026, 10, 2, 8, 0, 0),
        duration=2.0,
    )
    late = _add_record(
        project_id,
        asset_id="api.c",
        status="failed",
        start_time=datetime(2026, 10, 3, 8, 0, 0),
        duration=3.0,
    )

    default = client.get(f"{project_api_base(project_id)}/execution-records")
    assert [item["id"] for item in default.json()] == [late, middle, early]

    explicit = client.get(
        f"{project_api_base(project_id)}/execution-records",
        params={"order_by": "start_time"},
    )
    assert [item["id"] for item in explicit.json()] == [late, middle, early]

    ascending = client.get(
        f"{project_api_base(project_id)}/execution-records",
        params={"order_by": "start_time_asc"},
    )
    assert [item["id"] for item in ascending.json()] == [early, middle, late]

    by_duration = client.get(
        f"{project_api_base(project_id)}/execution-records",
        params={"order_by": "-duration"},
    )
    assert [item["id"] for item in by_duration.json()] == [late, middle, early]


def test_list_paginates_after_sorting() -> None:
    """skip/limit 作用在排序之后。"""
    project_id = _create_project()
    ids = [
        _add_record(
            project_id,
            asset_id="api.page",
            status="success",
            start_time=datetime(2026, 10, day, 0, 0, 0),
            duration=1.0,
        )
        for day in (1, 2, 3)
    ]

    page = client.get(
        f"{project_api_base(project_id)}/execution-records",
        params={"skip": 1, "limit": 1},
    )
    assert page.status_code == 200
    assert [item["id"] for item in page.json()] == [ids[1]]


def test_list_rejects_unknown_order_and_missing_project() -> None:
    """无法识别的排序返回 422，项目不存在返回 404。"""
    project_id = _create_project()
    bad_order = client.get(
        f"{project_api_base(project_id)}/execution-records",
        params={"order_by": "name"},
    )
    assert bad_order.status_code == 422
    assert "order_by" in bad_order.json()["detail"]

    missing = client.get("/repos/missing/projects/nope/execution-records")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Project not found"


def test_detail_returns_parsed_result_request_and_display() -> None:
    """详情解析 result_json，抽出 request/response，并格式化时间与耗时。"""
    project_id = _create_project()
    payload = {
        "status": "success",
        "request": {"method": "POST", "url": "/users", "body": {"username": "alice"}},
        "response": {"status_code": 201, "body": {"id": "u1"}},
        "error": None,
    }
    record_id = _add_record(
        project_id,
        asset_id="api.user.create",
        status="success",
        start_time=datetime(2026, 10, 10, 8, 30, 0),
        end_time=datetime(2026, 10, 10, 8, 30, 2),
        duration=1.5,
        result=payload,
        asset_type="api",
    )

    response = client.get(f"{project_api_base(project_id)}/execution-records/{record_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == record_id
    assert body["project_id"] == project_id
    assert body["asset_id"] == "api.user.create"
    assert body["asset_type"] == "api"
    assert body["status"] == "success"
    assert body["duration"] == 1.5
    assert body["result"] == payload
    assert body["request"] == payload["request"]
    assert body["response"] == payload["response"]
    assert body["display"] == {
        "start_time": "2026-10-10 08:30:00",
        "end_time": "2026-10-10 08:30:02",
        "duration": "1.50s",
    }


def test_detail_handles_invalid_json() -> None:
    """损坏的 result_json 仍返回详情，并在 result 中标记解析失败。"""
    project_id = _create_project()
    record_id = _add_record(
        project_id,
        asset_id="api.user.login",
        status="failed",
        start_time=datetime(2026, 10, 10, 1, 0, 0),
        duration=0.25,
        result_json="{not-json",
    )

    response = client.get(f"{project_api_base(project_id)}/execution-records/{record_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["parse_error"] == "invalid JSON"
    assert body["result"]["raw"] == "{not-json"
    assert body["request"] is None
    assert body["response"] is None
    assert body["display"]["duration"] == "250ms"
    assert parse_result_json("{not-json") == body["result"]


def test_detail_not_found_and_other_project() -> None:
    """记录不存在，或属于其他项目时返回 404。"""
    project_id = _create_project()
    other_id = _create_project()
    record_id = _add_record(
        other_id,
        asset_id="api.user.login",
        status="success",
        start_time=datetime(2026, 10, 10, 1, 0, 0),
    )

    missing = client.get(f"{project_api_base(project_id)}/execution-records/missing-record")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Execution record not found"

    foreign = client.get(f"{project_api_base(project_id)}/execution-records/{record_id}")
    assert foreign.status_code == 404
    assert foreign.json()["detail"] == "Execution record not found"


def test_from_model_helpers_parse_result() -> None:
    """from_model / from_orm 直接解析模型，不经过 HTTP。"""
    record = ExecutionRecord(
        id="rec-1",
        project_id="proj-1",
        asset_type="case",
        asset_id="case.login",
        status="success",
        start_time=datetime(2026, 10, 10, 12, 0, 0),
        end_time=None,
        duration=None,
        result_json=json.dumps(["not", "a", "dict"]),
    )

    listed = ExecutionRecordListResponse.from_orm(record)
    assert listed.id == "rec-1"
    assert listed.duration is None
    assert listed.login_failed is False

    detail = ExecutionRecordDetailResponse.from_model(record)
    assert detail.result == {"value": ["not", "a", "dict"]}
    assert detail.display.start_time == "2026-10-10 12:00:00"
    assert detail.display.end_time is None
    assert detail.display.duration is None
    assert detail.request is None


def test_list_item_login_failed_true_for_single_api() -> None:
    """单 API：顶层 error.kind == login_failed → 列表项 login_failed=true。"""
    project_id = _create_project()
    record_id = _add_record(
        project_id,
        asset_id="api.user.login",
        status="failed",
        start_time=datetime(2026, 10, 10, 9, 0, 0),
        duration=0.12,
        result={
            "status": "failed",
            "request": None,
            "response": None,
            "error": {"kind": "login_failed", "message": "登录失败"},
        },
    )
    listed = client.get(f"{project_api_base(project_id)}/execution-records").json()
    item = next(row for row in listed if row["id"] == record_id)
    assert item["login_failed"] is True

    record = ExecutionRecord(
        id=record_id,
        project_id=project_id,
        asset_type="api",
        asset_id="api.user.login",
        status="failed",
        start_time=datetime(2026, 10, 10, 9, 0, 0),
        end_time=None,
        duration=0.12,
        result_json=json.dumps(
            {"error": {"kind": "login_failed", "message": "登录失败"}},
        ),
    )
    assert ExecutionRecordListResponse.from_model(record).login_failed is True


def test_list_item_login_failed_true_for_case_step() -> None:
    """Case：任一步骤 error.kind == login_failed → 列表项 login_failed=true。"""
    project_id = _create_project()
    record_id = _add_record(
        project_id,
        asset_id="case.order.create",
        status="failed",
        start_time=datetime(2026, 10, 10, 9, 5, 0),
        duration=0.2,
        asset_type="case",
        result={
            "case_id": "case.order.create",
            "status": "failed",
            "duration_seconds": 0.2,
            "error": None,
            "steps": [
                {
                    "step_id": "login",
                    "type": "api",
                    "status": "failed",
                    "duration_seconds": 0.05,
                    "error": {"kind": "login_failed", "message": "登录失败"},
                },
                {
                    "step_id": "create",
                    "type": "api",
                    "status": "skipped",
                    "duration_seconds": 0,
                    "skip_reason": "login_failed",
                    "error": None,
                },
            ],
            "summary": {"total": 2, "success": 0, "failed": 1, "skipped": 1},
        },
    )
    listed = client.get(f"{project_api_base(project_id)}/execution-records").json()
    item = next(row for row in listed if row["id"] == record_id)
    assert item["login_failed"] is True


def test_list_item_login_failed_false_when_absent_or_other_error() -> None:
    """无 error / 其它 kind / 畸形 result_json → login_failed 保持 false。"""
    project_id = _create_project()
    ok_id = _add_record(
        project_id,
        asset_id="api.user.profile",
        status="success",
        start_time=datetime(2026, 10, 10, 9, 10, 0),
        duration=0.05,
        result={"status": "success", "error": None},
    )
    assert_id = _add_record(
        project_id,
        asset_id="api.user.profile",
        status="failed",
        start_time=datetime(2026, 10, 10, 9, 11, 0),
        duration=0.05,
        result={"status": "failed", "error": {"kind": "assertion", "message": "断言失败"}},
    )
    bad_id = _add_record(
        project_id,
        asset_id="api.user.profile",
        status="failed",
        start_time=datetime(2026, 10, 10, 9, 12, 0),
        duration=0.01,
        result_json="{not-json",
    )
    none_id = _add_record(
        project_id,
        asset_id="api.user.profile",
        status="failed",
        start_time=datetime(2026, 10, 10, 9, 13, 0),
        duration=0.01,
        result_json=None,
    )
    listed = {
        row["id"]: row
        for row in client.get(f"{project_api_base(project_id)}/execution-records").json()
    }
    assert listed[ok_id]["login_failed"] is False
    assert listed[assert_id]["login_failed"] is False
    assert listed[bad_id]["login_failed"] is False
    assert listed[none_id]["login_failed"] is False

    assert derive_login_failed(None) is False
    assert derive_login_failed("{") is False
    assert derive_login_failed(json.dumps({"error": "not-a-dict"})) is False
    assert derive_login_failed(json.dumps({"steps": [{"error": {"kind": "assertion"}}]})) is False
