"""Phase 3.3a Control 后端鉴权：路由 → ExecutionService → EnginePort（Fake）全链路。

覆盖手册 §5：auth 传给 Engine（含 Q2 的 None）、H3 透传到响应与历史详情、
不可用身份 / 配置错误 → 422 且不写记录、M1（422 detail 不含秘密，str(exc) 不再外显），
以及 SQLite 原始行与捕获日志的秘密值全文搜索。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from testplat_engine import (
    ApiExecutionRequest,
    AuthTable,
    CaseExecutionRequest,
    StaticHeaderAuth,
    UnavailableAuth,
)

from testplat_control.adapters.fake_engine import FakeEngineAdapter
from testplat_control.database.session import SessionLocal
from testplat_control.deps import get_engine_port
from testplat_control.main import app
from testplat_control.services import execution_service
from tests.auth_support import (
    FAKE_PARTNER,
    FAKE_SECRET,
    STANDARD_CONFIG,
    STANDARD_ENV,
    assert_no_secret,
    log_text,
    write_auth,
)
from tests.case_support import create_project, project_api_base, write_assets, write_env

# 历史 Git 配置兼容测试；生产默认关闭。
pytestmark = pytest.mark.legacy_git_config

client = TestClient(app)
API_ID = "api.demo.create"
CASE_ID = "case.demo.create_then_get"
ADMIN_AUTH = {
    "identity": "admin",
    "kind": "static_headers",
    "tier": None,
    "header_names": ["Authorization"],
    "overridden_headers": [],
    "cookie_names": [],
    "login_ref": None,
    "session_source": None,
    "reauthenticated": False,
}


@pytest.fixture(autouse=True)
def secrets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in STANDARD_ENV.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    assets = tmp_path / "assets"
    config = tmp_path / "config"
    write_assets(assets)
    write_env(config, "http://127.0.0.1:9")
    return assets, config


@pytest.fixture
def fake() -> Iterator[FakeEngineAdapter]:
    engine = FakeEngineAdapter()
    app.dependency_overrides[get_engine_port] = lambda: engine
    yield engine
    app.dependency_overrides.pop(get_engine_port, None)


def _project(dirs: tuple[Path, Path], config: dict | str | None = STANDARD_CONFIG) -> str:
    if config is not None:
        write_auth(dirs[1], config)
    return create_project(client, *dirs)


def _run_api(project_id: str):
    return client.post(
        f"{project_api_base(project_id)}/assets/{API_ID}/run", json={"env": "test", "params": {}}
    )


def _run_case(project_id: str):
    return client.post(
        f"{project_api_base(project_id)}/cases/{CASE_ID}/run", json={"env": "test", "params": {}}
    )


def _record_count(project_id: str) -> int:
    response = client.get(f"{project_api_base(project_id)}/execution-records")
    assert response.status_code == 200
    return len(response.json())


def _raw_rows(project_id: str) -> list[str]:
    """SQLite 原始行（全部列拼成文本），用于秘密值全文搜索。"""
    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT * FROM execution_records WHERE project_id = :pid"), {"pid": project_id}
        ).fetchall()
        return [repr(tuple(row)) for row in rows]
    finally:
        db.close()


# ------------------------------------------------------------------ Q2：无配置


def test_no_auth_file_passes_none_for_api_and_case(
    dirs: tuple[Path, Path], fake: FakeEngineAdapter
) -> None:
    """Q2：没有 auth 配置文件 → auth=None（不是空表），行为与 Phase 3 一致。"""
    project_id = _project(dirs, None)
    api = _run_api(project_id)
    case = _run_case(project_id)
    assert api.status_code == 200 and case.status_code == 200
    assert [type(call) for call in fake.calls] == [ApiExecutionRequest, CaseExecutionRequest]
    assert all(call.auth is None for call in fake.calls)
    assert api.json()["auth"] is None and api.json()["result"]["auth"] is None
    assert all(step["auth"] is None for step in case.json()["result"]["steps"])


# ------------------------------------------------------------------ 透传（H3）


def test_auth_table_is_passed_to_engine(dirs: tuple[Path, Path], fake: FakeEngineAdapter) -> None:
    project_id = _project(dirs)
    assert _run_api(project_id).status_code == 200
    assert _run_case(project_id).status_code == 200
    for call in fake.calls:
        assert isinstance(call.auth, AuthTable)
        assert call.auth.default_identity == "admin"
        assert set(call.auth.identities) == {"admin", "partner"}
        assert isinstance(call.auth.identities["admin"], StaticHeaderAuth)
        # 秘密不进 environment / params。
        assert_no_secret([repr(call.to_dict()), repr(call)])


def test_single_api_auth_flows_to_response_and_history(
    dirs: tuple[Path, Path], fake: FakeEngineAdapter
) -> None:
    fake.auth_overridden_headers = ("authorization",)
    project_id = _project(dirs)
    response = _run_api(project_id)
    assert response.status_code == 200, response.text
    body = response.json()
    expected = {**ADMIN_AUTH, "overridden_headers": ["authorization"]}
    assert body["auth"] == expected
    assert body["result"]["auth"] == expected
    detail = client.get(f"{project_api_base(project_id)}/execution-records/{body['record_id']}")
    assert detail.status_code == 200
    assert detail.json()["auth"] == expected
    assert detail.json()["result"]["auth"] == expected
    assert_no_secret([response.text, detail.text, *_raw_rows(project_id)])


def test_case_step_auth_flows_to_response_and_typed_history(
    dirs: tuple[Path, Path], fake: FakeEngineAdapter
) -> None:
    """H3：CaseStepResult 显式声明 auth，步骤 auth 不再被 pydantic 静默丢弃。"""
    fake.auth_identity = "partner"
    project_id = _project(dirs)
    response = _run_case(project_id)
    assert response.status_code == 200, response.text
    partner = {
        "identity": "partner",
        "kind": "static_headers",
        "tier": None,
        "header_names": ["X-Api-Key"],
        "overridden_headers": [],
        "cookie_names": [],
        "login_ref": None,
        "session_source": None,
        "reauthenticated": False,
    }
    steps = response.json()["result"]["steps"]
    assert [step["auth"] for step in steps] == [partner, partner]
    record_id = response.json()["record_id"]
    typed = client.get(f"{project_api_base(project_id)}/case-execution-records/{record_id}")
    assert typed.status_code == 200
    assert [step["auth"] for step in typed.json()["result"]["steps"]] == [partner, partner]
    generic = client.get(f"{project_api_base(project_id)}/execution-records/{record_id}")
    assert [step["auth"] for step in generic.json()["result"]["steps"]] == [partner, partner]
    assert_no_secret([response.text, typed.text, generic.text, *_raw_rows(project_id)])


def test_skipped_steps_keep_null_auth(dirs: tuple[Path, Path], fake: FakeEngineAdapter) -> None:
    fake.case_fail_at = "create"
    project_id = _project(dirs)
    steps = _run_case(project_id).json()["result"]["steps"]
    assert steps[0]["auth"] == ADMIN_AUTH
    assert steps[1]["status"] == "skipped" and steps[1]["auth"] is None


def test_legacy_record_without_auth_reads_as_null(
    dirs: tuple[Path, Path], fake: FakeEngineAdapter
) -> None:
    """Phase 3 旧记录没有 auth 键：详情 auth 为 null，不 500。"""
    project_id = _project(dirs, None)
    record_id = _run_api(project_id).json()["record_id"]
    db = SessionLocal()
    try:
        db.execute(
            text("UPDATE execution_records SET result_json = :j WHERE id = :id"),
            {
                "j": '{"status": "success", "request": null, "response": null, "error": null}',
                "id": record_id,
            },
        )
        db.commit()
    finally:
        db.close()
    detail = client.get(f"{project_api_base(project_id)}/execution-records/{record_id}")
    assert detail.status_code == 200 and detail.json()["auth"] is None


# ------------------------------------------------------------------ 422 且不写记录


@pytest.mark.parametrize("runner", [_run_api, _run_case], ids=["api", "case"])
@pytest.mark.parametrize(
    ("env_override", "fragment"),
    [
        ({"TESTPLAT_ADMIN_TOKEN": None}, "TESTPLAT_ADMIN_TOKEN 未设置"),
        ({"TESTPLAT_ADMIN_TOKEN": ""}, "TESTPLAT_ADMIN_TOKEN 为空"),
        ({"TESTPLAT_ADMIN_TOKEN": "tp-7ch!"}, "长度不足 8"),
    ],
    ids=["missing", "empty", "short"],
)
def test_unavailable_identity_used_is_422_without_record(
    dirs: tuple[Path, Path],
    fake: FakeEngineAdapter,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    runner,  # noqa: ANN001
    env_override: dict[str, str | None],
    fragment: str,
) -> None:
    for name, value in env_override.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    project_id = _project(dirs)
    with caplog.at_level(logging.DEBUG):
        response = runner(project_id)
    assert response.status_code == 422
    assert fragment in response.json()["detail"]
    # Fake 已收到表，确认是“用到时”才失败。
    assert isinstance(fake.calls[-1].auth.identities["admin"], UnavailableAuth)
    assert _record_count(project_id) == 0
    assert_no_secret([response.text, *log_text(caplog.records), *_raw_rows(project_id)])


def test_unused_unavailable_identity_does_not_block(
    dirs: tuple[Path, Path], fake: FakeEngineAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TESTPLAT_PARTNER_KEY")
    project_id = _project(dirs)
    assert _run_api(project_id).status_code == 200


def test_non_whitelisted_variable_is_422_without_value(
    dirs: tuple[Path, Path], fake: FakeEngineAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6-6：模板引用 AWS_SECRET_ACCESS_KEY → 用到时 422，响应里没有它的值。"""
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", FAKE_SECRET)
    project_id = _project(
        dirs,
        {
            "identities": {"evil": {"headers": {"X-Key": "${secret:AWS_SECRET_ACCESS_KEY}"}}},
            "default_identity": "evil",
        },
    )
    response = _run_api(project_id)
    assert response.status_code == 422
    assert "AWS_SECRET_ACCESS_KEY" in response.json()["detail"]
    assert_no_secret([response.text])
    assert _record_count(project_id) == 0


BAD_CONFIGS: dict[str, dict | str] = {
    "yaml_invalid": "identities: [\n  admin: ${secret:TESTPLAT_ADMIN_TOKEN}",
    "none_identity": {"identities": {"none": {"headers": {"A": "${secret:TESTPLAT_ADMIN_TOKEN}"}}}},
    "case_duplicate_header": {
        "identities": {
            "admin": {
                "headers": {
                    "X-Token": "${secret:TESTPLAT_ADMIN_TOKEN}",
                    "x-token": "${secret:TESTPLAT_PARTNER_KEY}",
                }
            }
        }
    },
    "no_placeholder": {"identities": {"admin": {"headers": {"X-Tenant": "tenant-9f31c2a7"}}}},
    "default_missing": {**STANDARD_CONFIG, "default_identity": "ghost"},
    "unknown_field": {**STANDARD_CONFIG, "token": FAKE_SECRET},
}


@pytest.mark.parametrize("runner", [_run_api, _run_case], ids=["api", "case"])
@pytest.mark.parametrize("name", list(BAD_CONFIGS))
def test_config_errors_are_422_without_record_or_secret(
    dirs: tuple[Path, Path],
    fake: FakeEngineAdapter,
    caplog: pytest.LogCaptureFixture,
    runner,  # noqa: ANN001
    name: str,
) -> None:
    """配置层错误：加载即 422（preflight），Engine 不被调用，不写记录；detail/日志无秘密（M1）。"""
    project_id = _project(dirs, BAD_CONFIGS[name])
    with caplog.at_level(logging.DEBUG):
        response = runner(project_id)
    assert response.status_code == 422, response.text
    assert "鉴权配置" in response.json()["detail"]
    assert fake.calls == []
    assert _record_count(project_id) == 0
    assert_no_secret([response.text, *log_text(caplog.records)])


@pytest.mark.parametrize("runner", [_run_api, _run_case], ids=["api", "case"])
def test_request_build_error_detail_never_echoes_exception_text(
    dirs: tuple[Path, Path],
    fake: FakeEngineAdapter,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    runner,  # noqa: ANN001
) -> None:
    """M1：请求 DTO 构造抛 TypeError/ValueError 时，detail 是固定文案，不再是 str(exc)。"""

    def boom(**_kwargs: Any) -> None:
        raise ValueError(f"leaky message {FAKE_SECRET} {FAKE_PARTNER}")

    monkeypatch.setattr(execution_service, "ApiExecutionRequest", boom)
    monkeypatch.setattr(execution_service, "CaseExecutionRequest", boom)
    project_id = _project(dirs)
    with caplog.at_level(logging.DEBUG):
        response = runner(project_id)
    assert response.status_code == 422
    assert response.json()["detail"] == "执行请求无效：参数或环境配置不合法"
    assert_no_secret([response.text, *log_text(caplog.records)])
    assert fake.calls == []


def test_successful_runs_leave_no_secret_in_logs_or_rows(
    dirs: tuple[Path, Path], fake: FakeEngineAdapter, caplog: pytest.LogCaptureFixture
) -> None:
    project_id = _project(dirs)
    with caplog.at_level(logging.DEBUG):
        responses = [_run_api(project_id), _run_case(project_id)]
    assert all(r.status_code == 200 for r in responses)
    assert_no_secret(
        [*(r.text for r in responses), *log_text(caplog.records), *_raw_rows(project_id)]
    )
