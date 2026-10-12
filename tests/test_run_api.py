"""单次 API 参数表单与执行路由测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from testplat_engine import (
    AssetNotFoundError,
    EngineInternalError,
    EngineTimeoutError,
    EngineTransportError,
    EngineUnavailableError,
    InvalidAssetError,
    InvalidEnvironmentError,
)

from testplat_control.adapters.fake_engine import FakeEngineAdapter
from testplat_control.deps import get_engine_port
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
schema_version: "0.2"
id: case.user.login
name: 登录流程
steps:
  - step_id: login
    type: api
    api_id: api.user.login
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

ENV_YAML = """\
api_hosts:
  main: http://127.0.0.1:9
timeout:
  default: 30
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
def config_dir() -> Path:
    """临时环境配置目录。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "config"
        _write(root, "envs/test.yaml", ENV_YAML)
        yield root


@pytest.fixture
def fake_engine() -> FakeEngineAdapter:
    """通过 DI 注入 Fake，避免 monkeypatch 路由全局。"""
    fake = FakeEngineAdapter()
    app.dependency_overrides[get_engine_port] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_engine_port, None)


@pytest.fixture
def project_id(assets_dir: Path, config_dir: Path, fake_engine: FakeEngineAdapter) -> str:
    """创建指向临时资产与配置目录的项目。"""
    response = client.post(
        "/projects",
        json={
            "name": f"run-api-{uuid4().hex[:8]}",
            "env": "test",
            "assets_root": str(assets_dir),
            "config_root": str(config_dir),
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


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


def test_get_params_project_not_found(fake_engine: FakeEngineAdapter) -> None:
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


def test_run_success_persists_record(project_id: str, fake_engine: FakeEngineAdapter) -> None:
    """执行成功时经 EnginePort 返回结果并写入执行记录。"""
    asset_id = "api.user.create"
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
    assert body["status"] == "success"
    assert isinstance(body["record_id"], str) and body["record_id"]
    assert body["duration"] is not None
    assert body["result"]["status"] == "success"
    assert body["result"]["response"]["status_code"] == 200
    assert len(fake_engine.calls) == 1
    assert fake_engine.calls[0].api_id == asset_id
    assert dict(fake_engine.calls[0].params) == payload
    assert "api_hosts" in fake_engine.calls[0].environment

    detail = client.get(f"/projects/{project_id}/execution-records/{body['record_id']}")
    assert detail.status_code == 200
    saved = detail.json()
    assert saved["project_id"] == project_id
    assert saved["asset_type"] == "api"
    assert saved["asset_id"] == asset_id
    assert saved["status"] == "success"
    assert saved["result"]["status"] == "success"
    assert saved["response"] == body["result"]["response"]


def test_run_failure_persists_record(project_id: str, fake_engine: FakeEngineAdapter) -> None:
    """引擎判定业务失败时返回 failed，并仍然保存执行记录。"""
    asset_id = "api.user.login"

    response = client.post(
        f"/projects/{project_id}/assets/{asset_id}/run",
        json={"params": {"password": "wrong-password"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["result"]["error"]["message"] == "assertion failed"

    detail = client.get(f"/projects/{project_id}/execution-records/{body['record_id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "failed"


def test_run_rejects_missing_required_param(
    project_id: str,
    fake_engine: FakeEngineAdapter,
) -> None:
    """缺少必填参数时返回 422，且不调用引擎。"""
    response = client.post(
        f"/projects/{project_id}/assets/api.user.create/run",
        json={"params": {"username": "alice"}},
    )

    assert response.status_code == 422
    assert "email" in response.json()["detail"]
    assert fake_engine.calls == []


def test_run_rejects_wrong_param_type(project_id: str, fake_engine: FakeEngineAdapter) -> None:
    """参数类型与表单不一致时返回 422。"""
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
    assert fake_engine.calls == []


def test_run_rejects_unknown_param(project_id: str, fake_engine: FakeEngineAdapter) -> None:
    """未在 inputs 中声明的参数返回 422。"""
    response = client.post(
        f"/projects/{project_id}/assets/api.common.health_check/run",
        json={"params": {"extra": 1}},
    )

    assert response.status_code == 422
    assert "unknown param 'extra'" in response.json()["detail"]
    assert fake_engine.calls == []


def test_run_rejects_invalid_body(project_id: str) -> None:
    """params 不是对象时由请求模型返回 422。"""
    response = client.post(
        f"/projects/{project_id}/assets/api.common.health_check/run",
        json={"params": ["username"]},
    )
    assert response.status_code == 422


def test_run_project_not_found(fake_engine: FakeEngineAdapter) -> None:
    """项目不存在时执行返回 404。"""
    response = client.post(
        "/projects/missing-project/assets/api.user.login/run",
        json={"params": {}},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fake_engine.calls == []


def test_run_asset_not_found(project_id: str, fake_engine: FakeEngineAdapter) -> None:
    """资产不存在时执行返回 404。"""
    response = client.post(
        f"/projects/{project_id}/assets/api.missing/run",
        json={"params": {}},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Asset not found"
    assert fake_engine.calls == []


@pytest.mark.parametrize(
    ("error", "status", "creates_record"),
    [
        (AssetNotFoundError("资产不存在"), 404, False),
        (InvalidAssetError("资产无效"), 422, False),
        (InvalidEnvironmentError("环境无效"), 422, False),
        (EngineUnavailableError("引擎不可用"), 503, False),
        (EngineInternalError("preflight", "内部错误"), 500, False),
        (EngineTimeoutError("超时"), 504, True),
        (EngineTransportError("传输失败"), 502, True),
        (EngineInternalError("execution", "内部错误"), 500, True),
    ],
)
def test_run_system_errors_map_and_record_by_stage(
    project_id: str,
    fake_engine: FakeEngineAdapter,
    error: object,
    status: int,
    creates_record: bool,
) -> None:
    """系统错误按 kind/stage 映射 HTTP，并遵守记录规则。"""
    fake_engine.system_error = error  # type: ignore[assignment]

    before = client.get(f"/projects/{project_id}/execution-records").json()
    response = client.post(
        f"/projects/{project_id}/assets/api.common.health_check/run",
        json={"params": {}},
    )

    assert response.status_code == status
    assert error.public_message in response.json()["detail"]  # type: ignore[attr-defined]

    after = client.get(f"/projects/{project_id}/execution-records").json()
    if creates_record:
        assert len(after) == len(before) + 1
        assert after[0]["status"] == "failed"
        detail = client.get(f"/projects/{project_id}/execution-records/{after[0]['id']}")
        assert detail.status_code == 200
        assert detail.json()["result"]["error"]["kind"] == error.kind  # type: ignore[attr-defined]
    else:
        assert after == before


def test_run_unexpected_exception_returns_500_without_record(
    project_id: str,
    fake_engine: FakeEngineAdapter,
) -> None:
    """未分类异常返回 500，且不写入执行记录。"""

    class BoomEngine:
        async def execute(self, request):  # noqa: ANN001
            raise RuntimeError("boom")

    app.dependency_overrides[get_engine_port] = lambda: BoomEngine()
    try:
        response = client.post(
            f"/projects/{project_id}/assets/api.common.health_check/run",
            json={"params": {}},
        )
    finally:
        app.dependency_overrides[get_engine_port] = lambda: fake_engine

    assert response.status_code == 500
    assert "RuntimeError" in response.json()["detail"]

    listed = client.get(f"/projects/{project_id}/execution-records")
    assert listed.status_code == 200
    assert listed.json() == []


def test_run_missing_env_config_returns_422_without_record(
    assets_dir: Path,
    fake_engine: FakeEngineAdapter,
) -> None:
    """config_root 缺少环境文件时 422，不调用引擎、不写记录。"""
    with tempfile.TemporaryDirectory() as tmp:
        empty_config = Path(tmp)
        created = client.post(
            "/projects",
            json={
                "name": f"no-env-{uuid4().hex[:8]}",
                "env": "test",
                "assets_root": str(assets_dir),
                "config_root": str(empty_config),
            },
        )
        assert created.status_code == 200
        pid = created.json()["id"]

        response = client.post(
            f"/projects/{pid}/assets/api.common.health_check/run",
            json={"params": {}},
        )
        assert response.status_code == 422
        assert "环境配置不存在" in response.json()["detail"]
        assert fake_engine.calls == []
        assert client.get(f"/projects/{pid}/execution-records").json() == []
