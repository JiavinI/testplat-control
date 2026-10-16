"""Phase 4.0 OpenAPI：两段式路由与 env / commit_sha 契约。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from testplat_control.main import app


@pytest.fixture(scope="module")
def current() -> dict[str, Any]:
    return json.loads(json.dumps(app.openapi(), sort_keys=True))


REQUIRED_PATHS = {
    "/repos": {"get"},
    "/repos/{repo}/sync": {"post"},
    "/projects": {"get"},
    "/repos/{repo}/projects/{project}": {"get"},
    "/repos/{repo}/projects/{project}/assets": {"get"},
    "/repos/{repo}/projects/{project}/assets/{asset_id}": {"get"},
    "/repos/{repo}/projects/{project}/assets/{asset_id}/params": {"get"},
    "/repos/{repo}/projects/{project}/assets/{asset_id}/run": {"post"},
    "/repos/{repo}/projects/{project}/cases/{case_id}": {"get"},
    "/repos/{repo}/projects/{project}/cases/{case_id}/run": {"post"},
    "/repos/{repo}/projects/{project}/execution-records": {"get"},
    "/repos/{repo}/projects/{project}/execution-records/{record_id}": {"get"},
    "/repos/{repo}/projects/{project}/case-execution-records/{record_id}": {"get"},
}


def test_phase4_paths_present(current: dict[str, Any]) -> None:
    paths = current["paths"]
    for path, methods in REQUIRED_PATHS.items():
        assert path in paths, path
        assert methods <= set(paths[path])
    assert "/projects/{project_id}" not in paths or "post" not in paths.get("/projects", {})
    # 旧写接口不得再出现
    for method in ("post", "put", "delete"):
        assert method not in paths.get("/projects", {})


def test_run_request_requires_env(current: dict[str, Any]) -> None:
    schemas = current["components"]["schemas"]
    for name in ("RunRequest", "CaseRunRequest"):
        assert name in schemas
        assert "env" in schemas[name]["properties"]
        assert "env" in schemas[name].get("required", [])


def test_execution_records_expose_env_and_sha(current: dict[str, Any]) -> None:
    schemas = current["components"]["schemas"]
    for name in ("ExecutionRecordListResponse", "ExecutionRecordDetailResponse"):
        props = schemas[name]["properties"]
        assert "env" in props and "commit_sha" in props


def test_list_records_supports_env_filter(current: dict[str, Any]) -> None:
    params = {
        p["name"]: p
        for p in current["paths"]["/repos/{repo}/projects/{project}/execution-records"]["get"][
            "parameters"
        ]
    }
    assert "env" in params
    assert params["env"]["required"] is False


def test_flat_project_detail_is_deprecated(current: dict[str, Any]) -> None:
    """扁平项目详情只读别名保留，但 OpenAPI 标为 deprecated。"""
    operation = current["paths"]["/projects/{project_id}"]["get"]
    assert operation["deprecated"] is True
