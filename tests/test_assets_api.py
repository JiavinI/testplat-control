"""资产 API 路由测试。"""

from pathlib import Path

from fastapi.testclient import TestClient

from testplat_control.main import app
from tests.repo_support import DEFAULT_FILES, bootstrap_synced_project

client = TestClient(app)


def test_create_project_and_get_assets_tree(tmp_path: Path) -> None:
    ctx = bootstrap_synced_project(client, tmp_path)
    response = client.get(f"{ctx['base']}/assets")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "assets"
    assert data["type"] == "directory"
    api_found = any(child["id"] == "api" for child in data.get("children") or [])
    assert api_found


def test_get_assets_tree_project_not_found() -> None:
    response = client.get("/repos/missing/projects/nope/assets")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_get_asset_details_file(tmp_path: Path) -> None:
    ctx = bootstrap_synced_project(client, tmp_path)
    response = client.get(f"{ctx['base']}/assets/api.common.health_check")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "api.common.health_check"
    assert data["type"] == "file"


def test_get_asset_details_directory(tmp_path: Path) -> None:
    ctx = bootstrap_synced_project(client, tmp_path)
    response = client.get(f"{ctx['base']}/assets/api")
    assert response.status_code == 200
    assert response.json()["type"] == "directory"


def test_get_asset_details_not_found(tmp_path: Path) -> None:
    ctx = bootstrap_synced_project(client, tmp_path)
    response = client.get(f"{ctx['base']}/assets/non.existent.asset")
    assert response.status_code == 404


def test_assets_tree_empty_api_dir(tmp_path: Path) -> None:
    files = {k: v for k, v in DEFAULT_FILES.items() if not k.startswith("projects/demo/api/")}
    # 仍保留空 api 目录占位：写一个 .gitkeep 式文件到 scenarios only
    files["projects/demo/api/.keep"] = ""
    ctx = bootstrap_synced_project(client, tmp_path, files=files)
    response = client.get(f"{ctx['base']}/assets")
    assert response.status_code == 200
