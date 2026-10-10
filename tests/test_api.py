"""API 测试"""

import pytest
from fastapi.testclient import TestClient
from testplat_control.main import app


client = TestClient(app)


def test_health() -> None:
    """测试健康检查端点"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_project() -> None:
    """测试创建项目"""
    project_data = {
        "name": "Test Project",
        "env": "test",
        "assets_root": "/assets",
        "config_root": "/config",
    }
    response = client.post("/projects", json=project_data)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Project"
    assert data["env"] == "test"
    assert data["assets_root"] == "/assets"
    assert data["config_root"] == "/config"
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_list_projects() -> None:
    """测试列出项目"""
    # 创建两个项目
    for i in range(2):
        project_data = {
            "name": f"Project {i}",
            "env": "test",
            "assets_root": f"/assets{i}",
            "config_root": f"/config{i}",
        }
        client.post("/projects", json=project_data)
    
    response = client.get("/projects")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2


def test_get_project() -> None:
    """测试获取项目详情"""
    # 先创建项目
    project_data = {
        "name": "Get Test",
        "env": "test",
        "assets_root": "/assets",
        "config_root": "/config",
    }
    create_response = client.post("/projects", json=project_data)
    project_id = create_response.json()["id"]
    
    # 获取项目
    response = client.get(f"/projects/{project_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == project_id
    assert data["name"] == "Get Test"


def test_get_project_not_found() -> None:
    """测试获取不存在的项目"""
    response = client.get("/projects/nonexistent-id")
    assert response.status_code == 404


def test_update_project() -> None:
    """测试更新项目"""
    # 先创建项目
    project_data = {
        "name": "Update Test",
        "env": "test",
        "assets_root": "/assets",
        "config_root": "/config",
    }
    create_response = client.post("/projects", json=project_data)
    project_id = create_response.json()["id"]
    
    # 更新项目
    update_data = {
        "name": "Updated Project",
        "env": "production",
    }
    response = client.put(f"/projects/{project_id}", json=update_data)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Project"
    assert data["env"] == "production"
    assert data["assets_root"] == "/assets"  # 未修改的字段保持不变


def test_update_project_not_found() -> None:
    """测试更新不存在的项目"""
    update_data = {"name": "Updated"}
    response = client.put("/projects/nonexistent-id", json=update_data)
    assert response.status_code == 404


def test_delete_project() -> None:
    """测试删除项目"""
    # 先创建项目
    project_data = {
        "name": "Delete Test",
        "env": "test",
        "assets_root": "/assets",
        "config_root": "/config",
    }
    create_response = client.post("/projects", json=project_data)
    project_id = create_response.json()["id"]
    
    # 删除项目
    response = client.delete(f"/projects/{project_id}")
    assert response.status_code == 200
    assert response.json()["message"] == "Project deleted successfully"
    
    # 验证项目已删除
    get_response = client.get(f"/projects/{project_id}")
    assert get_response.status_code == 404


def test_delete_project_not_found() -> None:
    """测试删除不存在的项目"""
    response = client.delete("/projects/nonexistent-id")
    assert response.status_code == 404


def test_list_execution_records() -> None:
    """测试列出执行记录"""
    project_data = {
        "name": "Execution List",
        "env": "test",
        "assets_root": "/assets",
        "config_root": "/config",
    }
    create_response = client.post("/projects", json=project_data)
    project_id = create_response.json()["id"]

    response = client.get(f"/projects/{project_id}/execution-records")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_list_execution_records_project_not_found() -> None:
    """不存在的项目没有执行记录可列"""
    response = client.get("/projects/test-project/execution-records")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_get_execution_record_not_found() -> None:
    """测试获取不存在的执行记录"""
    response = client.get("/projects/test-project/execution-records/nonexistent-id")
    assert response.status_code == 404
