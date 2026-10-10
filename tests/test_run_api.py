"""单次 API 参数表单与执行路由测试。"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from testplat_control.database.models import ExecutionRecord, Project
from testplat_control.main import app

client = TestClient(app)

STRUCTURED_API = """\
id: api.user.create
name: 创建用户
method: POST
url: /users
request:
  inputs:
    username:
      type: string
      required: true
      description: 用户名
    email:
      type: string
      required: true
      description: 邮箱
    age:
      type: integer
      required: false
      description: 年龄
    active:
      type: bool
      required: false
      description: 是否启用
"""

SIMPLE_API = """\
id: api.user.login
name: 登录
method: POST
url: /login
request:
  inputs:
    username: 用户名
    email: 邮箱
    password: 密码 (required)
"""

EMPTY_API = """\
id: api.common.health_check
name: 健康检查
method: GET
url: /health
"""

CASE_YAML = """\
id: case.user.login
name: 登录流程
steps:
  - api_id: api.user.login
    name: 登录
"""

ALIAS_API = """\
id: api.common.typed
name: 类型别名
method: POST
url: /typed
request:
  inputs:
    - name: title
      type: text
      required: true
      description: 标题
    - name: retries
      type: float
      required: false
      desc: 重试次数
"""

BAD_TYPE_API = """\
id: api.bad.object_param
name: 非法类型
method: POST
url: /bad
request:
  inputs:
    payload:
      type: object
      required: true
      description: 请求体
"""


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def assets_dir() -> Path:
    """构造包含 API、Case 和非法 YAML 的临时资产目录。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "assets"
        root.mkdir()
        _write(root, "api/user/create.yaml", STRUCTURED_API)
        _write(root, "api/user/login.yaml", SIMPLE_API)
        _write(root, "api/common/health_check.yaml", EMPTY_API)
        _write(root, "api/common/typed.yaml", ALIAS_API)
        _write(root, "api/bad/object_param.yaml", BAD_TYPE_API)
        _write(root, "case/user/login.yaml", CASE_YAML)
        _write(root, "api/broken/bad.yaml", "id: broken\nname: [\n")
        _write(root, "notes/readme.txt", "not yaml")
        yield root


@pytest.fixture
def project_id(assets_dir: Path) -> str:
    """创建指向临时资产目录的项目。"""
    response = client.post(
        "/projects",
        json={
            "name": f"run-api-{uuid4().hex[:8]}",
            "env": "test",
            "assets_root": str(assets_dir),
            "config_root": "/config",
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


def _record(
    project_id: str,
    asset_id: str,
    status: str,
    result: dict,
    duration: float = 1.5,
) -> ExecutionRecord:
    now = datetime.utcnow()
    return ExecutionRecord(
        id=str(uuid4()),
        project_id=project_id,
        asset_type="api",
        asset_id=asset_id,
        status=status,
        start_time=now,
        end_time=now,
        duration=duration,
        result_json=json.dumps(result),
    )


def _patch_adapter(
    monkeypatch: pytest.MonkeyPatch,
    record: ExecutionRecord | None = None,
    error: Exception | None = None,
) -> MagicMock:
    adapter = MagicMock()
    if error is not None:
        adapter.run_api = AsyncMock(side_effect=error)
    else:
        adapter.run_api = AsyncMock(return_value=(MagicMock(), record))
    monkeypatch.setattr(
        "testplat_control.api.run.EngineAdapter",
        MagicMock(return_value=adapter),
    )
    return adapter


def test_get_params_from_structured_inputs(project_id: str) -> None:
    """结构化 inputs 提取名称、归一化类型、必填和说明。"""
    response = client.get(f"/projects/{project_id}/assets/api.user.create/params")

    assert response.status_code == 200
    data = response.json()
    assert data["asset_id"] == "api.user.create"
    assert [item["name"] for item in data["params"]] == [
        "username",
        "email",
        "age",
        "active",
    ]
    by_name = {item["name"]: item for item in data["params"]}
    assert by_name["username"] == {
        "name": "username",
        "type": "string",
        "required": True,
        "description": "用户名",
    }
    assert by_name["email"]["type"] == "string"
    assert by_name["email"]["required"] is True
    assert by_name["email"]["description"] == "邮箱"
    assert by_name["age"]["type"] == "number"
    assert by_name["age"]["required"] is False
    assert by_name["active"]["type"] == "boolean"
    assert by_name["active"]["description"] == "是否启用"


def test_get_params_from_string_inputs(project_id: str) -> None:
    """说明字符串默认为 string，(required) 标记必填。"""
    response = client.get(f"/projects/{project_id}/assets/api.user.login/params")

    assert response.status_code == 200
    by_name = {item["name"]: item for item in response.json()["params"]}
    assert by_name["username"]["type"] == "string"
    assert by_name["username"]["required"] is False
    assert by_name["username"]["description"] == "用户名"
    assert by_name["email"]["description"] == "邮箱"
    assert by_name["email"]["required"] is False
    assert by_name["password"]["required"] is True
    assert by_name["password"]["description"] == "密码"
    assert by_name["password"]["type"] == "string"


def test_get_params_normalizes_list_inputs(project_id: str) -> None:
    """列表形式的 inputs 同样归一化类型别名。"""
    response = client.get(f"/projects/{project_id}/assets/api.common.typed/params")

    assert response.status_code == 200
    by_name = {item["name"]: item for item in response.json()["params"]}
    assert by_name["title"]["type"] == "string"
    assert by_name["title"]["required"] is True
    assert by_name["retries"]["type"] == "number"
    assert by_name["retries"]["description"] == "重试次数"


def test_get_params_empty_inputs(project_id: str) -> None:
    """没有 inputs 的 API 返回空表单。"""
    response = client.get(f"/projects/{project_id}/assets/api.common.health_check/params")

    assert response.status_code == 200
    assert response.json()["params"] == []


def test_get_params_project_not_found() -> None:
    """项目不存在时获取参数表单返回 404。"""
    response = client.get("/projects/missing-project/assets/api.user.login/params")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_get_params_asset_not_found(project_id: str) -> None:
    """资产不存在时获取参数表单返回 404。"""
    response = client.get(f"/projects/{project_id}/assets/api.missing/params")
    assert response.status_code == 404
    assert response.json()["detail"] == "Asset not found"


def test_get_params_rejects_non_api_assets(project_id: str) -> None:
    """目录、Case、非 YAML 和非法 YAML 不能生成参数表单。"""
    directory = client.get(f"/projects/{project_id}/assets/api/params")
    assert directory.status_code == 422
    assert directory.json()["detail"] == "Asset is not a file"

    case = client.get(f"/projects/{project_id}/assets/case.user.login/params")
    assert case.status_code == 422
    assert case.json()["detail"] == "Asset is not an API"

    text = client.get(f"/projects/{project_id}/assets/notes.readme/params")
    assert text.status_code == 422
    assert text.json()["detail"] == "Asset is not a YAML file"

    broken = client.get(f"/projects/{project_id}/assets/api.broken.bad/params")
    assert broken.status_code == 422
    assert "Invalid YAML" in broken.json()["detail"]

    bad_type = client.get(f"/projects/{project_id}/assets/api.bad.object_param/params")
    assert bad_type.status_code == 422
    assert "unsupported param type" in bad_type.json()["detail"]


def test_run_success_persists_record(project_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """执行成功时调用 EngineAdapter，返回结果并写入执行记录。"""
    asset_id = "api.user.create"
    result = {
        "status": "success",
        "response": {"status_code": 201, "body": {"id": "u1"}},
        "error": None,
    }
    record = _record(project_id, asset_id, "success", result)
    captured: dict[str, object] = {}

    async def _run_api(
        api_id: str,
        project: Project,
        params: dict,
    ) -> tuple[MagicMock, ExecutionRecord]:
        captured["api_id"] = api_id
        captured["project_id"] = project.id
        captured["params"] = params
        return MagicMock(), record

    adapter = _patch_adapter(monkeypatch, record=record)
    adapter.run_api = AsyncMock(side_effect=_run_api)
    payload = {
        "username": "alice",
        "email": "alice@example.com",
        "age": 0,
        "active": False,
    }

    response = client.post(
        f"/projects/{project_id}/assets/{asset_id}/run",
        json={"params": payload},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["record_id"] == record.id
    assert body["status"] == "success"
    assert body["duration"] == 1.5
    assert body["result"] == result

    adapter.run_api.assert_awaited_once()
    assert captured == {"api_id": asset_id, "project_id": project_id, "params": payload}

    detail = client.get(f"/projects/{project_id}/execution-records/{record.id}")
    assert detail.status_code == 200
    saved = detail.json()
    assert saved["project_id"] == project_id
    assert saved["asset_type"] == "api"
    assert saved["asset_id"] == asset_id
    assert saved["status"] == "success"
    assert json.loads(saved["result_json"]) == result


def test_run_failure_persists_record(project_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """引擎判定失败时返回 failed，并仍然保存执行记录。"""
    asset_id = "api.user.login"
    result = {"status": "failed", "response": None, "error": "assertion failed"}
    record = _record(project_id, asset_id, "failed", result, duration=0.2)
    _patch_adapter(monkeypatch, record=record)

    response = client.post(
        f"/projects/{project_id}/assets/{asset_id}/run",
        json={"params": {"password": "secret"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["record_id"] == record.id
    assert body["duration"] == 0.2
    assert body["result"]["error"] == "assertion failed"

    detail = client.get(f"/projects/{project_id}/execution-records/{record.id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "failed"


def test_run_rejects_missing_required_param(
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺少必填参数时返回 422，且不调用引擎。"""
    record = _record(project_id, "api.user.create", "success", {})
    adapter = _patch_adapter(monkeypatch, record=record)

    response = client.post(
        f"/projects/{project_id}/assets/api.user.create/run",
        json={"params": {"username": "alice"}},
    )

    assert response.status_code == 422
    assert "email" in response.json()["detail"]
    adapter.run_api.assert_not_called()


def test_run_rejects_wrong_param_type(project_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """参数类型与表单不一致时返回 422。"""
    adapter = _patch_adapter(monkeypatch)

    response = client.post(
        f"/projects/{project_id}/assets/api.user.create/run",
        json={
            "params": {
                "username": "alice",
                "email": "alice@example.com",
                "age": "twelve",
                "active": "yes",
            }
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "age" in detail
    assert "number" in detail
    assert "active" in detail
    assert "boolean" in detail
    adapter.run_api.assert_not_called()


def test_run_rejects_unknown_param(project_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """未在 inputs 中声明的参数返回 422。"""
    adapter = _patch_adapter(monkeypatch)

    response = client.post(
        f"/projects/{project_id}/assets/api.common.health_check/run",
        json={"params": {"extra": 1}},
    )

    assert response.status_code == 422
    assert "unknown param 'extra'" in response.json()["detail"]
    adapter.run_api.assert_not_called()


def test_run_rejects_invalid_body(project_id: str) -> None:
    """params 不是对象时由请求模型返回 422。"""
    response = client.post(
        f"/projects/{project_id}/assets/api.common.health_check/run",
        json={"params": ["username"]},
    )
    assert response.status_code == 422


def test_run_project_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """项目不存在时执行返回 404。"""
    adapter = _patch_adapter(monkeypatch)
    response = client.post(
        "/projects/missing-project/assets/api.user.login/run",
        json={"params": {}},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    adapter.run_api.assert_not_called()


def test_run_asset_not_found(project_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """资产不存在时执行返回 404。"""
    adapter = _patch_adapter(monkeypatch)
    response = client.post(
        f"/projects/{project_id}/assets/api.missing/run",
        json={"params": {}},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Asset not found"
    adapter.run_api.assert_not_called()


def test_run_engine_error_returns_500_without_record(
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """适配器抛错时返回 500，且不写入执行记录。"""
    _patch_adapter(monkeypatch, error=RuntimeError("boom"))

    response = client.post(
        f"/projects/{project_id}/assets/api.common.health_check/run",
        json={"params": {}},
    )

    assert response.status_code == 500
    assert "boom" in response.json()["detail"]

    listed = client.get(f"/projects/{project_id}/execution-records")
    assert listed.status_code == 200
    assert listed.json() == []
