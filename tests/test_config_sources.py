"""正常 Web 配置与显式历史兼容模式的隔离边界。"""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from testplat_control.config import settings
from testplat_control.database.models import Project
from testplat_control.database.session import SessionLocal
from testplat_control.main import app
from testplat_control.services.run_config import resolve_run_config
from tests.repo_support import bootstrap_synced_project


@pytest.fixture
def project_context(tmp_path: Path):
    with TestClient(app) as client:
        ctx = bootstrap_synced_project(client, tmp_path, repo_key=f"sources-{uuid4().hex[:8]}")
        yield client, ctx


@pytest.fixture
def forbid_legacy_loaders(monkeypatch: pytest.MonkeyPatch):
    def forbidden(*args, **kwargs):
        pytest.fail("正常 Web 路径不可读取 Git 环境或历史 auth")

    monkeypatch.setattr("testplat_control.services.run_config.load_auth", forbidden)
    monkeypatch.setattr("testplat_control.services.run_config.load_project_environment", forbidden)


def test_default_web_without_database_environment_rejects_api_and_case(
    project_context,
    forbid_legacy_loaders,
) -> None:
    client, ctx = project_context
    assert settings.testplat_legacy_git_config is False
    detail = client.get(ctx["base"]).json()
    assert detail["envs"] == []
    assert detail["default_env"] is None
    for route in ("assets/api.common.health_check/run", "cases/case.user.login/run"):
        response = client.post(f"{ctx['base']}/{route}", json={"env": "test"})
        assert response.status_code == 422
        assert "配置" in response.json()["detail"]
    with SessionLocal() as db:
        project = db.get(Project, ctx["project_id"])
        with pytest.raises(HTTPException, match="数据库环境未配置"):
            resolve_run_config(
                db, project, "test", Path("/unused"), request_params={}, request_timeout=None
            )


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_database_project_never_falls_back_for_missing_or_disabled_environment(
    project_context,
    forbid_legacy_loaders,
    monkeypatch: pytest.MonkeyPatch,
    legacy: bool,
    enabled: bool,
) -> None:
    client, ctx = project_context
    monkeypatch.setattr(settings, "testplat_legacy_git_config", legacy)
    created = client.post(
        f"{ctx['base']}/environments",
        json={
            "env": "test",
            "api_hosts": {},
            "enabled": enabled,
        },
    )
    assert created.status_code == 201
    detail = client.get(ctx["base"]).json()
    assert detail["envs"] == (["test"] if enabled else [])
    with SessionLocal() as db:
        project = db.get(Project, ctx["project_id"])
        for env in ["staging"] if enabled else ["staging", "test"]:
            with pytest.raises(HTTPException) as error:
                resolve_run_config(
                    db, project, env, Path("/unused"), request_params={}, request_timeout=None
                )
            assert error.value.status_code == 422
    blocked = client.post(
        f"{ctx['base']}/assets/api.common.health_check/run", json={"env": "staging"}
    )
    assert blocked.status_code == 422
