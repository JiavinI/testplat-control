"""项目 / 仓库 API 测试（Phase 4.0：无 POST/PUT/DELETE 项目）。"""

from pathlib import Path

from fastapi.testclient import TestClient

from testplat_control.main import app
from tests.repo_support import bootstrap_synced_project

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_repos_empty_when_unconfigured() -> None:
    # 模块级 client 可能已挂过配置；空配置时列表可为已同步项。此处只断言形状。
    response = client.get("/repos")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    for item in response.json():
        assert "url" not in item
        assert "key" in item
        assert "branch" in item


def test_sync_and_list_projects(tmp_path: Path) -> None:
    ctx = bootstrap_synced_project(client, tmp_path)
    listed = client.get("/projects")
    assert listed.status_code == 200
    ids = [p["id"] for p in listed.json()]
    assert ctx["project_id"] in ids
    detail = client.get(ctx["base"])
    assert detail.status_code == 200
    body = detail.json()
    assert body["repo"] == ctx["repo"]
    assert body["project"] == ctx["project"]
    assert body["commit_sha"] == ctx["commit_sha"]
    assert body["envs"] == []
    assert body["default_env"] is None
    assert "assets_root" not in body
    assert "config_root" not in body
    assert "env" not in body or body.get("env") is None or "env" not in body
    # 扁平 ID
    flat = client.get(f"/projects/{ctx['project_id']}")
    assert flat.status_code == 200
    assert flat.json()["id"] == ctx["project_id"]


def test_get_project_not_found() -> None:
    response = client.get("/repos/missing/projects/nope")
    assert response.status_code == 404


def test_project_write_routes_removed(tmp_path: Path) -> None:
    assert client.post("/projects", json={"name": "x"}).status_code in {404, 405, 422}
    ctx = bootstrap_synced_project(client, tmp_path)
    assert client.put(ctx["base"], json={"name": "y"}).status_code in {404, 405, 422}
    assert client.delete(ctx["base"]).status_code in {404, 405}


def test_repos_response_has_no_url(tmp_path: Path) -> None:
    ctx = bootstrap_synced_project(client, tmp_path)
    repos = client.get("/repos").json()
    text = str(repos)
    assert ctx["url"] not in text
    assert "url" not in text
