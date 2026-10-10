"""资产API路由测试"""

import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from testplat_control.main import app
from testplat_control.database.models import Project
from testplat_control.database.session import get_db, SessionLocal


client = TestClient(app)


@pytest.fixture
def db_session():
    """创建临时数据库会话"""
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def temp_assets_dir():
    """创建临时资产目录结构"""
    with tempfile.TemporaryDirectory() as tmpdir:
        assets_dir = Path(tmpdir) / "assets"
        assets_dir.mkdir()

        # 创建资产树结构
        api_dir = assets_dir / "api"
        api_dir.mkdir()

        common_dir = api_dir / "common"
        common_dir.mkdir()

        # 创建示例文件
        health_check_file = common_dir / "health_check.yaml"
        health_check_file.write_text("type: get\nurl: /health")

        yield str(assets_dir)


def test_create_project_and_get_assets_tree(db_session, temp_assets_dir):
    """测试: 创建项目并获取资产树"""
    # 创建项目
    project_data = {
        "name": "Assets Test Project",
        "env": "test",
        "assets_root": temp_assets_dir,
        "config_root": "/config",
    }
    create_response = client.post("/projects", json=project_data)
    assert create_response.status_code == 200
    project_id = create_response.json()["id"]

    # 获取资产树
    response = client.get(f"/projects/{project_id}/assets")

    # 验证响应
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "assets"
    assert data["type"] == "directory"
    assert data["name"] == "assets"
    assert isinstance(data["children"], list)

    # 验证树结构包含 api 目录
    api_found = False
    for child in data.get("children", []):
        if child["id"] == "api":
            api_found = True
            assert child["type"] == "directory"
            break
    assert api_found, "API directory should be in assets tree"


def test_get_assets_tree_project_not_found():
    """测试: 不存在的项目返回 404"""
    response = client.get("/projects/non-existent-project/assets")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_get_asset_details_file(db_session, temp_assets_dir):
    """测试: 获取单个文件资产详情"""
    # 创建项目
    project_data = {
        "name": "Asset Details Test",
        "env": "test",
        "assets_root": temp_assets_dir,
        "config_root": "/config",
    }
    create_response = client.post("/projects", json=project_data)
    project_id = create_response.json()["id"]

    # 获取资产详情 (健康检查文件)
    response = client.get(f"/projects/{project_id}/assets/api.common.health_check")

    # 验证响应
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "api.common.health_check"
    assert data["type"] == "file"
    assert data["name"] == "health_check.yaml"
    assert data["path"] == "api/common/health_check.yaml"
    assert isinstance(data["metadata"], dict)


def test_get_asset_details_directory(db_session, temp_assets_dir):
    """测试: 获取目录资产详情"""
    # 创建项目
    project_data = {
        "name": "Directory Details Test",
        "env": "test",
        "assets_root": temp_assets_dir,
        "config_root": "/config",
    }
    create_response = client.post("/projects", json=project_data)
    project_id = create_response.json()["id"]

    # 获取资产详情 (api 目录)
    response = client.get(f"/projects/{project_id}/assets/api")

    # 验证响应
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "api"
    assert data["type"] == "directory"
    assert data["name"] == "api"


def test_get_asset_details_project_not_found():
    """测试: 不存在的项目返回 404"""
    response = client.get("/projects/non-existent/assets/api.common.health_check")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_get_asset_details_asset_not_found(db_session, temp_assets_dir):
    """测试: 不存在的资产返回 404"""
    # 创建项目
    project_data = {
        "name": "Non-existent Asset Test",
        "env": "test",
        "assets_root": temp_assets_dir,
        "config_root": "/config",
    }
    create_response = client.post("/projects", json=project_data)
    project_id = create_response.json()["id"]

    # 获取不存在的资产
    response = client.get(f"/projects/{project_id}/assets/non.existent.asset")
    assert response.status_code == 404
    assert response.json()["detail"] == "Asset not found"


def test_nested_asset_structure(db_session, temp_assets_dir):
    """测试: 资产树嵌套结构"""
    # 创建项目
    project_data = {
        "name": "Nested Structure Test",
        "env": "test",
        "assets_root": temp_assets_dir,
        "config_root": "/config",
    }
    create_response = client.post("/projects", json=project_data)
    project_id = create_response.json()["id"]

    # 获取资产树
    response = client.get(f"/projects/{project_id}/assets")
    data = response.json()

    # 验证树可以完全导航
    assert data["type"] == "directory"

    # 找到 api 目录
    api_node = None
    for child in data.get("children", []):
        if child["id"] == "api":
            api_node = child
            break

    assert api_node is not None
    assert api_node["type"] == "directory"

    # 找到 api.common 目录
    common_node = None
    for child in api_node.get("children", []):
        if child["id"] == "api.common":
            common_node = child
            break

    assert common_node is not None
    assert common_node["type"] == "directory"

    # 找到文件
    file_node = None
    for child in common_node.get("children", []):
        if child["id"] == "api.common.health_check":
            file_node = child
            break

    assert file_node is not None
    assert file_node["type"] == "file"
    assert file_node["path"] == "api/common/health_check.yaml"
