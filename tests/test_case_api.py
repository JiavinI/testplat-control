"""Case 资产详情、运行端点与历史详情（Fake Engine）。

每个场景都精确断言：HTTP 状态码、是否新增执行记录、记录状态、步骤结果。
Case 语法校验的权威在 Engine，这里的 Fake 通过 ``system_error`` 复现 Engine 的
各类 preflight / execution 错误，只验证 Control 的编排、持久化与映射。
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from testplat_engine import (
    ApiExecutionOutcome,
    AssetNotFoundError,
    CaseExecutionRequest,
    EngineInternalError,
    EngineTimeoutError,
    EngineTransportError,
    InvalidAssetError,
    InvalidEnvironmentError,
    InvalidInputError,
)

from testplat_control.adapters.fake_engine import (
    FakeEngineAdapter,
    build_case_outcome,
    build_partial_outcome,
)
from testplat_control.api.case_schemas import CaseResult
from testplat_control.database.models import ExecutionRecord
from testplat_control.database.session import SessionLocal
from testplat_control.deps import get_engine_port
from testplat_control.main import app
from testplat_control.services.case_asset_service import find_case_file
from tests.case_support import (
    assert_case_result_invariants,
    create_project,
    project_api_base,
    write_assets,
    write_env,
)

client = TestClient(app)

CASE_ID = "case.demo.create_then_get"
STEP_IDS = ["create", "get"]


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    assets = tmp_path / "assets"
    config = tmp_path / "config"
    write_assets(assets)
    write_env(config, "http://127.0.0.1:9")
    return assets, config


def _use_engine(fake: FakeEngineAdapter) -> None:
    app.dependency_overrides[get_engine_port] = lambda: fake


@pytest.fixture
def fake() -> Iterator[FakeEngineAdapter]:
    engine = FakeEngineAdapter()
    _use_engine(engine)
    yield engine
    app.dependency_overrides.pop(get_engine_port, None)


@pytest.fixture
def project_id(dirs: tuple[Path, Path], fake: FakeEngineAdapter) -> str:
    return create_project(client, *dirs)


def _run(project_id: str, case_id: str = CASE_ID, params: dict[str, Any] | None = None):
    return client.post(
        f"{project_api_base(project_id)}/cases/{case_id}/run",
        json={"env": "test", "params": params or {}},
    )


def _records(project_id: str, **query: Any) -> list[dict[str, Any]]:
    response = client.get(f"{project_api_base(project_id)}/execution-records", params=query)
    assert response.status_code == 200, response.text
    return response.json()


def _typed_detail(project_id: str, record_id: str):
    return client.get(f"{project_api_base(project_id)}/case-execution-records/{record_id}")


def _db_record(record_id: str) -> ExecutionRecord:
    db = SessionLocal()
    try:
        record = db.query(ExecutionRecord).filter(ExecutionRecord.id == record_id).one()
        db.expunge(record)
        return record
    finally:
        db.close()


# ---------------------------------------------------------------- 资产详情


def test_case_detail_returns_file_metadata_only(project_id: str, dirs: tuple[Path, Path]) -> None:
    """详情只含文件级元信息：不解析 YAML，因此没有 name/tags/steps 等语义字段。"""
    response = client.get(f"{project_api_base(project_id)}/cases/{CASE_ID}")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"case_id", "path", "file_name", "size_bytes", "modified_at"}
    assert data["case_id"] == CASE_ID
    assert data["path"] == "scenarios/demo/create_then_get.case.yaml"
    assert data["file_name"] == "create_then_get.case.yaml"
    on_disk = dirs[0] / data["path"]
    assert data["size_bytes"] == on_disk.stat().st_size
    assert data["modified_at"].startswith("20")


@pytest.mark.parametrize(
    "case_id",
    [
        "case.demo.nope",  # 文件不存在
        "case.demo.legacy",  # 旧格式 .yaml：契约 §2 只认 .case.yaml
        "case.demo",  # 目录而不是文件
        "case.demo.create_then_get.case",  # 双后缀不是规范 id
        "case.Demo.create_then_get",  # 不做大小写归一
        "case.demo..create_then_get",  # 空 segment
        "case.demo.create-then-get",  # 不做连字符/下划线归一
        "demo.create_then_get",  # 缺少 case. 前缀
        "case.demo.%2e%2e",  # 编码的路径穿越尝试
    ],
)
def test_case_detail_rejects_illegal_assets_with_404(
    project_id: str, dirs: tuple[Path, Path], case_id: str
) -> None:
    """非法或不存在的 Case id 一律 404，且不会把请求 id 拼成路径。"""
    legacy = dirs[0] / "scenarios" / "demo" / "legacy.yaml"
    legacy.write_text("id: case.demo.legacy\nsteps: []\n", encoding="utf-8")

    response = client.get(f"{project_api_base(project_id)}/cases/{case_id}")

    assert response.status_code == 404
    assert "detail" in response.json()


def test_case_detail_symlink_escape_is_404(project_id: str, dirs: tuple[Path, Path]) -> None:
    """指向 scenarios 之外的符号链接文件视为不存在。"""
    outside = dirs[0].parent / "outside.case.yaml"
    outside.write_text('schema_version: "0.2"\nid: case.demo.escape\nsteps: []\n', encoding="utf-8")
    os.symlink(outside, dirs[0] / "scenarios" / "demo" / "escape.case.yaml")

    response = client.get(f"{project_api_base(project_id)}/cases/case.demo.escape")

    assert response.status_code == 404


def test_case_detail_project_not_found(fake: FakeEngineAdapter) -> None:
    response = client.get(f"/projects/missing-project/cases/{CASE_ID}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_case_detail_without_scenarios_dir(tmp_path: Path, fake: FakeEngineAdapter) -> None:
    """assets_root 下没有 scenarios 目录时 404，而不是 500。"""
    assets = tmp_path / "assets"
    assets.mkdir()
    config = tmp_path / "config"
    write_env(config, "http://127.0.0.1:9")
    pid = create_project(client, assets, config)
    assert client.get(f"{project_api_base(pid)}/cases/{CASE_ID}").status_code == 404


def test_asset_tree_uses_canonical_case_id(project_id: str) -> None:
    """资产树里 .case.yaml 的 id 是 case.<...>，不再带 ``scenarios.…​.case`` 双后缀。"""
    tree = client.get(f"{project_api_base(project_id)}/assets").json()

    def walk(node: dict[str, Any]):
        yield node
        for child in node.get("children") or []:
            yield from walk(child)

    ids = {n["id"]: n for n in walk(tree)}
    assert CASE_ID in ids
    assert ids[CASE_ID]["path"] == "scenarios/demo/create_then_get.case.yaml"
    assert "scenarios.demo.create_then_get.case" not in ids
    # 树上的 id 可直接用于 Case 详情。
    assert client.get(f"{project_api_base(project_id)}/cases/{CASE_ID}").status_code == 200


# ---------------------------------------------------------------- 运行：业务结果


def test_run_success_creates_success_record(project_id: str, fake: FakeEngineAdapter) -> None:
    before = len(_records(project_id))

    response = _run(project_id, params={"resource_name": "alpha"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    result = body["result"]
    assert result["case_id"] == CASE_ID
    assert result["error"] is None
    assert result["summary"] == {"total": 2, "success": 2, "failed": 0, "skipped": 0}
    assert_case_result_invariants(result, STEP_IDS)
    assert result["steps"][0]["output"] == "created"
    assert result["steps"][0]["response"]["body"] == {"id": "create-1"}

    # 请求 DTO：Control 只传身份、资产根、环境、参数与每步骤超时。
    request = fake.calls[-1]
    assert isinstance(request, CaseExecutionRequest)
    assert request.case_id == CASE_ID
    assert request.params["resource_name"] == "alpha"
    assert request.timeout_seconds == 30.0
    assert request.environment["api_hosts"]["local"] == "http://127.0.0.1:9"

    records = _records(project_id)
    assert len(records) == before + 1
    saved = _db_record(body["record_id"])
    assert (saved.asset_type, saved.asset_id, saved.status) == ("case", CASE_ID, "success")
    assert json.loads(saved.result_json) == {**result}
    assert saved.end_time is not None and saved.duration is not None


def test_run_business_failed_is_http_200_and_saved(
    project_id: str, fake: FakeEngineAdapter
) -> None:
    """断言失败：HTTP 200、保存 failed 记录、后续步骤 skipped。"""
    fake.case_step_ids = ("bad_assert", "after")
    fake.case_fail_at = "bad_assert"
    before = len(_records(project_id))

    response = _run(project_id, "case.demo.assert_failed")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    result = body["result"]
    assert result["error"] is None  # 业务失败不是系统错误
    assert result["summary"] == {"total": 2, "success": 0, "failed": 1, "skipped": 1}
    assert [s["status"] for s in result["steps"]] == ["failed", "skipped"]
    assert result["steps"][0]["error"]["kind"] == "assertion"
    assert_case_result_invariants(result, ["bad_assert", "after"])
    assert len(_records(project_id)) == before + 1
    assert _db_record(body["record_id"]).status == "failed"


def test_run_variable_resolution_failure_is_business_failed(
    project_id: str, fake: FakeEngineAdapter
) -> None:
    """运行时路径缺失：变量解析失败属业务 failed（A4），request 为 null，HTTP 200 并保存。"""
    fake.case_step_ids = ("create", "consume", "after")
    fake.case_fail_at = "consume"
    fake.case_fail_kind = "variable_resolution"

    response = _run(project_id, "case.demo.missing_runtime_path")

    assert response.status_code == 200
    result = response.json()["result"]
    consume = result["steps"][1]
    assert consume["status"] == "failed"
    assert consume["request"] is None and consume["response"] is None
    assert consume["error"]["kind"] == "variable_resolution"
    assert consume["error"]["step_id"] == "consume"
    assert consume["error"]["path"] == "created.body.missing"
    assert [s["status"] for s in result["steps"]] == ["success", "failed", "skipped"]
    assert_case_result_invariants(result, ["create", "consume", "after"])
    assert _db_record(response.json()["record_id"]).status == "failed"


# ---------------------------------------------------------------- 运行：preflight


@pytest.mark.parametrize(
    ("error", "expected_http", "expected_kind"),
    [
        (AssetNotFoundError("Case 资产不存在: case.demo.x"), 404, "asset_not_found"),
        (InvalidAssetError("Case 资产无效: case.demo.x"), 422, "invalid_asset"),
        (InvalidInputError("Case 参数缺失: params.missing"), 422, "invalid_input"),
        (InvalidEnvironmentError("执行环境缺少 host: local"), 422, "invalid_environment"),
    ],
)
def test_run_preflight_errors_do_not_create_records(
    project_id: str,
    fake: FakeEngineAdapter,
    error: Any,
    expected_http: int,
    expected_kind: str,
) -> None:
    assert error.kind == expected_kind and error.stage == "preflight"
    fake.system_error = error
    before = len(_records(project_id))

    response = _run(project_id)

    assert response.status_code == expected_http
    assert response.json() == {"detail": error.public_message}
    assert len(_records(project_id)) == before
    assert _records(project_id, asset_type="case") == []


def test_run_invalid_project_env_is_422_without_record(
    dirs: tuple[Path, Path], fake: FakeEngineAdapter
) -> None:
    """运行 env 不在项目 envs 内：422、不调用 Engine、不写记录。"""
    pid = create_project(client, dirs[0], dirs[1])
    response = client.post(
        f"{project_api_base(pid)}/cases/{CASE_ID}/run",
        json={"env": "missing-env", "params": {}},
    )
    assert response.status_code == 422
    assert "环境不在可选列表中" in response.json()["detail"]
    assert fake.calls == []
    assert _records(pid) == []


def test_run_project_not_found(fake: FakeEngineAdapter) -> None:
    response = _run("missing/nope")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fake.calls == []


def test_run_rejects_non_object_params(project_id: str, fake: FakeEngineAdapter) -> None:
    """params 必须是对象。fail_fast 仍被忽略；显式 timeout_seconds 覆盖默认 30。"""
    response = client.post(
        f"{project_api_base(project_id)}/cases/{CASE_ID}/run",
        json={"env": "test", "params": ["not", "object"]},
    )
    assert response.status_code == 422
    assert fake.calls == []

    explicit = client.post(
        f"{project_api_base(project_id)}/cases/{CASE_ID}/run",
        json={"env": "test", "params": {}, "fail_fast": False, "timeout_seconds": 1},
    )
    assert explicit.status_code == 200
    assert fake.calls[-1].timeout_seconds == 1.0


# ---------------------------------------------------------------- 运行：execution 系统错误


@pytest.mark.parametrize(
    ("kind", "error_cls", "expected_http"),
    [
        ("timeout", EngineTimeoutError, 504),
        ("transport", EngineTransportError, 502),
        ("internal", None, 500),
    ],
)
def test_run_execution_system_error_saves_failed_record_with_partial_steps(
    project_id: str,
    fake: FakeEngineAdapter,
    kind: str,
    error_cls: Any,
    expected_http: int,
) -> None:
    partial = build_partial_outcome(CASE_ID, kind, ("a", "b", "c"), fail_at="b")
    if error_cls is None:
        fake.system_error = EngineInternalError("execution", partial_outcome=partial)
    else:
        fake.system_error = error_cls(partial_outcome=partial)
    before = len(_records(project_id))

    response = _run(project_id)

    assert response.status_code == expected_http
    assert response.json() == {"detail": fake.system_error.public_message}

    records = _records(project_id)
    assert len(records) == before + 1
    saved_list = _records(project_id, asset_type="case", status="failed")
    assert len(saved_list) == 1 and saved_list[0]["asset_id"] == CASE_ID
    record_id = saved_list[0]["id"]
    saved = _db_record(record_id)
    assert (saved.asset_type, saved.status) == ("case", "failed")

    detail = _typed_detail(project_id, record_id)
    assert detail.status_code == 200
    result = detail.json()["result"]
    assert result["status"] == "failed"
    assert result["error"] == {
        "kind": kind,
        "stage": "execution",
        "message": fake.system_error.public_message,
    }
    assert [(s["step_id"], s["status"]) for s in result["steps"]] == [
        ("a", "success"),
        ("b", "failed"),
        ("c", "skipped"),
    ]
    assert result["steps"][1]["error"]["kind"] == kind
    assert result["summary"] == {"total": 3, "success": 1, "failed": 1, "skipped": 1}
    assert_case_result_invariants(result, ["a", "b", "c"])


def test_run_execution_error_without_partial_saves_empty_steps(
    project_id: str, fake: FakeEngineAdapter
) -> None:
    """防御：Engine 缺陷导致 execution 错误没带 partial 时，仍保存 failed 记录，但不伪造步骤。"""
    fake.system_error = EngineTimeoutError()

    response = _run(project_id)

    assert response.status_code == 504
    (item,) = _records(project_id, asset_type="case")
    detail = _typed_detail(project_id, item["id"]).json()
    assert detail["status"] == "failed"
    assert detail["result"]["steps"] == []
    assert detail["result"]["summary"] == {"total": 0, "success": 0, "failed": 0, "skipped": 0}
    assert detail["result"]["error"]["kind"] == "timeout"


def test_run_unclassified_exception_is_500_without_record(
    project_id: str, fake: FakeEngineAdapter
) -> None:
    """非 EngineError 的异常：不猜 stage、不写记录，外显只含类型名。"""
    fake.system_error = RuntimeError("boom")  # type: ignore[assignment]

    response = _run(project_id)

    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to execute Case: RuntimeError"}
    assert _records(project_id) == []


def test_run_invalid_engine_outcome_is_500_without_record(
    project_id: str, fake: FakeEngineAdapter
) -> None:
    """Engine 返回了不是 CaseExecutionOutcome 的对象（契约违约）：500、不写记录。"""
    fake.case_outcome = ApiExecutionOutcome(status="success")  # type: ignore[assignment]

    response = _run(project_id)

    assert response.status_code == 500
    assert _records(project_id) == []


# ---------------------------------------------------------------- 历史：筛选 / 分页 / 排序 / 兼容


def _seed_history(project_id: str, fake: FakeEngineAdapter) -> dict[str, list[str]]:
    """交错生成 API 与 Case 记录；返回按创建顺序的 record id。"""
    ids: dict[str, list[str]] = {"case": [], "api": []}
    api_asset = "api.common.health_check"
    for index in range(3):
        fake.case_fail_at = "get" if index == 1 else None
        case_resp = _run(project_id)
        assert case_resp.status_code == 200
        ids["case"].append(case_resp.json()["record_id"])
        api_resp = client.post(
            f"{project_api_base(project_id)}/assets/{api_asset}/run",
            json={"env": "test", "params": {}},
        )
        assert api_resp.status_code == 200, api_resp.text
        ids["api"].append(api_resp.json()["record_id"])
    return ids


@pytest.fixture
def seeded(dirs: tuple[Path, Path], fake: FakeEngineAdapter) -> dict[str, Any]:
    """先写入 health API，再同步建项目，保证快照内有该资产。"""
    health = dirs[0] / "api" / "common" / "health_check.yaml"
    health.parent.mkdir(parents=True, exist_ok=True)
    health.write_text(
        "id: api.common.health_check\ntype: api\nname: h\nhost: local\nmethod: GET\nurl: /health\n"
    )
    project_id = create_project(client, *dirs)
    return {"project_id": project_id, "ids": _seed_history(project_id, fake)}


def test_history_filter_by_asset_type(seeded: dict[str, Any]) -> None:
    pid, ids = seeded["project_id"], seeded["ids"]

    cases = _records(pid, asset_type="case")
    apis = _records(pid, asset_type="api")
    mixed = _records(pid)

    assert {r["id"] for r in cases} == set(ids["case"])
    assert {r["id"] for r in apis} == set(ids["api"])
    assert len(mixed) == 6  # 不带 asset_type 时保持 Phase 2.5 的混合行为
    assert (
        client.get(
            f"{project_api_base(pid)}/execution-records", params={"asset_type": "ui"}
        ).status_code
        == 422
    )


def test_history_filter_by_status_and_asset_id_for_cases(seeded: dict[str, Any]) -> None:
    pid, ids = seeded["project_id"], seeded["ids"]

    failed = _records(pid, asset_type="case", status="failed")
    assert [r["id"] for r in failed] == [ids["case"][1]]
    assert len(_records(pid, asset_type="case", status="success")) == 2
    assert len(_records(pid, asset_type="case", asset_id=CASE_ID)) == 3
    assert _records(pid, asset_type="case", asset_id="case.demo.other") == []


def test_history_pagination_and_ordering_for_cases(seeded: dict[str, Any]) -> None:
    pid, ids = seeded["project_id"], seeded["ids"]

    desc = [r["id"] for r in _records(pid, asset_type="case", order_by="-start_time")]
    asc = [r["id"] for r in _records(pid, asset_type="case", order_by="start_time_asc")]
    assert asc == ids["case"]
    assert desc == list(reversed(ids["case"]))
    assert [r["id"] for r in _records(pid, asset_type="case")] == desc  # 默认降序

    page1 = _records(pid, asset_type="case", order_by="+start_time", skip=0, limit=2)
    page2 = _records(pid, asset_type="case", order_by="+start_time", skip=2, limit=2)
    assert [r["id"] for r in page1] == ids["case"][:2]
    assert [r["id"] for r in page2] == ids["case"][2:]
    assert _records(pid, asset_type="case", skip=3, limit=2) == []


def test_history_list_item_shape_is_unchanged(seeded: dict[str, Any]) -> None:
    """列表项在既有五字段上追加 login_failed（Phase 3.3b 历史标记）。"""
    item = _records(seeded["project_id"], asset_type="case", limit=1)[0]
    assert set(item) >= {
        "id",
        "asset_id",
        "status",
        "start_time",
        "duration",
        "login_failed",
        "env",
        "commit_sha",
    }
    assert item["login_failed"] is False


def test_history_generic_detail_stays_compatible_for_case_records(seeded: dict[str, Any]) -> None:
    """通用详情端点对 Case 记录依然可用：result 为完整 Case 结果，request/response 为 null。"""
    pid, record_id = seeded["project_id"], seeded["ids"]["case"][1]

    generic = client.get(f"{project_api_base(pid)}/execution-records/{record_id}")

    assert generic.status_code == 200
    body = generic.json()
    assert body["asset_type"] == "case" and body["status"] == "failed"
    assert body["request"] is None and body["response"] is None
    assert body["result"]["steps"][1]["status"] == "failed"
    assert body["display"]["duration"] is not None

    typed = _typed_detail(pid, record_id).json()
    # 类型化详情是同一份存档按 CaseResult schema 的规范化视图（补齐默认 null 字段）。
    assert typed["result"] == CaseResult.model_validate(body["result"]).model_dump(mode="json")
    assert [s["step_id"] for s in typed["result"]["steps"]] == [
        s["step_id"] for s in body["result"]["steps"]
    ]
    assert typed["asset_type"] == "case"
    assert set(typed) >= {
        "id",
        "project_id",
        "asset_id",
        "asset_type",
        "status",
        "start_time",
        "end_time",
        "duration",
        "display",
        "result",
        "env",
        "commit_sha",
    }


def test_history_api_record_detail_is_unchanged_and_not_a_case(seeded: dict[str, Any]) -> None:
    """API 记录：通用详情不变；Case 类型化详情对它返回 404。"""
    pid, api_id = seeded["project_id"], seeded["ids"]["api"][0]

    detail = client.get(f"{project_api_base(pid)}/execution-records/{api_id}")
    assert detail.status_code == 200
    assert detail.json()["asset_type"] == "api"
    assert detail.json()["request"] is not None

    assert _typed_detail(pid, api_id).status_code == 404
    assert _typed_detail(pid, "missing").status_code == 404
    assert client.get("/repos/missing/projects/nope/case-execution-records/x").status_code == 404


def test_typed_detail_tolerates_legacy_or_corrupt_result_json(
    project_id: str, fake: FakeEngineAdapter
) -> None:
    """历史里的 Case 记录若 result_json 缺失/损坏/形状旧，类型化详情返回 result=null 而不是 500。"""
    db = SessionLocal()
    now = datetime.now(UTC)
    try:
        for rid, payload in {
            "legacy-none": None,
            "legacy-bad": "not json{",
            "legacy-old-shape": json.dumps({"status": "failed", "error": {"kind": "x"}}),
        }.items():
            db.add(
                ExecutionRecord(
                    id=f"{project_id[:8]}-{rid}",
                    project_id=project_id,
                    asset_type="case",
                    asset_id=CASE_ID,
                    status="failed",
                    start_time=now,
                    end_time=now,
                    duration=0.0,
                    result_json=payload,
                )
            )
        db.commit()
    finally:
        db.close()

    for rid in ("legacy-none", "legacy-bad", "legacy-old-shape"):
        record_id = f"{project_id[:8]}-{rid}"
        typed = _typed_detail(project_id, record_id)
        assert typed.status_code == 200
        assert typed.json()["result"] is None
        # 通用详情照常工作（旧 API 兼容）。
        generic = client.get(f"{project_api_base(project_id)}/execution-records/{record_id}")
        assert generic.status_code == 200


def test_build_case_outcome_helpers_enforce_engine_invariants() -> None:
    """Fake 的 outcome 由 Engine DTO 构造，天然满足顺序/计数/fail-fast 不变量。"""
    outcome = build_case_outcome(CASE_ID, ("a", "b", "c"), fail_at="b")
    assert [s.status for s in outcome.steps] == ["success", "failed", "skipped"]
    assert outcome.summary == {"total": 3, "success": 1, "failed": 1, "skipped": 1}


def test_find_case_file_never_builds_paths_from_the_request(tmp_path: Path) -> None:
    """请求 id 只与“由真实文件推导出的 id”做精确比较，穿越/分隔符类 id 永远匹配不到。"""
    assets = tmp_path / "assets"
    write_assets(assets)
    (tmp_path / "secret.case.yaml").write_text("x: 1\n", encoding="utf-8")

    assert find_case_file(assets, CASE_ID) is not None
    for bad in (
        "../secret",
        "case.../secret",
        "case.demo/../../secret",
        "case.demo\\create_then_get",
        "case/demo/create_then_get",
        "",
    ):
        assert find_case_file(assets, bad) is None, bad
