"""Case 测试共用夹具：资产文件、环境、项目创建与结果形状断言。

资产内容沿用 Engine 0.2 Golden fixtures 的 schema（无秘密、仅本地）。
Fake 路径下 Control 不读取这些文件内容（只用于详情定位）；真实 Engine 路径下由 Engine 解析。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from fastapi.testclient import TestClient

API_ASSETS: dict[str, str] = {
    "api/demo/create.yaml": """\
id: api.demo.create
name: 创建资源
host: local
method: POST
url: /demo/resources
request:
  headers:
    Content-Type: application/json
  body:
    name: "${name}"
success:
  status_code: 201
""",
    "api/demo/get.yaml": """\
id: api.demo.get
name: 查询资源
host: local
method: GET
url: /demo/resources/item
request:
  headers:
    X-Resource-Id: "${resource_id}"
success:
  status_code: 200
""",
    "api/demo/always_fail_assert.yaml": """\
id: api.demo.always_fail_assert
name: 故意断言失败
host: local
method: GET
url: /status/200
request: {}
success:
  status_code: 999
""",
    "api/demo/slow.yaml": """\
id: api.demo.slow
name: 慢接口
host: local
method: GET
url: /demo/slow
request: {}
success:
  status_code: 200
""",
    "api/demo/dead.yaml": """\
id: api.demo.dead
name: 不可达主机
host: dead
method: GET
url: /demo/dead
request: {}
success:
  status_code: 200
""",
}

CASE_ASSETS: dict[str, str] = {
    "scenarios/demo/create_then_get.case.yaml": """\
schema_version: "0.2"
id: case.demo.create_then_get
name: 创建并查询资源
desc: 创建资源后用返回 ID 查询
tags: [smoke]
params:
  resource_name: demo
steps:
  - step_id: create
    type: api
    api_id: api.demo.create
    name: 创建资源
    params:
      name: "${params.resource_name}"
    output: created
  - step_id: get
    type: api
    api_id: api.demo.get
    params:
      resource_id: "${created.body.id}"
""",
    "scenarios/demo/assert_failed.case.yaml": """\
schema_version: "0.2"
id: case.demo.assert_failed
steps:
  - step_id: bad_assert
    type: api
    api_id: api.demo.always_fail_assert
  - step_id: after
    type: api
    api_id: api.demo.get
    params:
      resource_id: "x"
""",
    "scenarios/demo/missing_runtime_path.case.yaml": """\
schema_version: "0.2"
id: case.demo.missing_runtime_path
steps:
  - step_id: create
    type: api
    api_id: api.demo.create
    params:
      name: demo
    output: created
  - step_id: consume
    type: api
    api_id: api.demo.get
    params:
      resource_id: "${created.body.missing}"
  - step_id: after
    type: api
    api_id: api.demo.get
    params:
      resource_id: "x"
""",
    "scenarios/demo/undeclared_alias.case.yaml": """\
schema_version: "0.2"
id: case.demo.undeclared_alias
steps:
  - step_id: only
    type: api
    api_id: api.demo.get
    params:
      resource_id: "${missing.body.id}"
""",
    "scenarios/demo/missing_params.case.yaml": """\
schema_version: "0.2"
id: case.demo.missing_params
steps:
  - step_id: only
    type: api
    api_id: api.demo.create
    params:
      name: "${params.missing}"
""",
    "scenarios/demo/unsupported_step.case.yaml": """\
schema_version: "0.2"
id: case.demo.unsupported_step
steps:
  - step_id: first
    type: api
    api_id: api.demo.get
    params:
      resource_id: "x"
  - step_id: ui
    type: ui
    api_id: api.demo.get
""",
    "scenarios/demo/timeout.case.yaml": """\
schema_version: "0.2"
id: case.demo.timeout
steps:
  - step_id: create
    type: api
    api_id: api.demo.create
    params:
      name: demo
  - step_id: slow
    type: api
    api_id: api.demo.slow
  - step_id: after
    type: api
    api_id: api.demo.get
    params:
      resource_id: "x"
""",
    "scenarios/demo/transport.case.yaml": """\
schema_version: "0.2"
id: case.demo.transport
steps:
  - step_id: create
    type: api
    api_id: api.demo.create
    params:
      name: demo
  - step_id: dead
    type: api
    api_id: api.demo.dead
  - step_id: after
    type: api
    api_id: api.demo.get
    params:
      resource_id: "x"
""",
    "scenarios/demo/legacy_v1.case.yaml": """\
id: case.demo.legacy_v1
name: legacy
kind: scenario
steps:
  - use: api.common.get_status
""",
}


def write_files(root: Path, files: dict[str, str]) -> None:
    """把相对路径 → 内容映射写入 root。"""
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def write_assets(assets_root: Path) -> None:
    """写入全部 API 与 Case 资产。"""
    write_files(assets_root, API_ASSETS)
    write_files(assets_root, CASE_ASSETS)


def write_env(config_root: Path, base_url: str, *, env: str = "test") -> None:
    """写入环境配置；``dead`` 主机指向必拒绝连接的本地端口（不访问公网）。"""
    path = config_root / "envs" / f"{env}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {"api_hosts": {"local": base_url, "dead": "http://127.0.0.1:1"}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def create_project(client: TestClient, assets_root: Path, config_root: Path, **extra: Any) -> str:
    """把已写好的 assets/config 打成 git 资产仓并同步，返回 ``{repo}/{project}``。"""
    import os
    import shutil
    import subprocess

    from tests.repo_support import attach_repos_config, sync_repo

    repo_key = str(extra.get("repo", f"r{uuid4().hex[:8]}"))
    project_key = str(extra.get("project", "demo"))
    name = str(extra.get("name", f"case-{uuid4().hex[:10]}"))
    staging = assets_root.parent / f"git-{uuid4().hex[:8]}"
    proj = staging / "projects" / project_key
    proj.mkdir(parents=True)
    for child in assets_root.iterdir():
        dest = proj / child.name
        if child.is_dir():
            shutil.copytree(child, dest)
        else:
            shutil.copy2(child, dest)
    shutil.copytree(config_root, proj / "config")
    (staging / "testplat.yaml").write_text(
        "\n".join(
            [
                'schema_version: "1"',
                "projects:",
                f"  {project_key}:",
                f"    name: {name}",
                f"    assets: projects/{project_key}",
                f"    config: projects/{project_key}/config",
                "    default_env: test",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    for args in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "add", "-A"],
        ["git", "commit", "-m", "init"],
    ):
        subprocess.run(args, cwd=str(staging), env=env, capture_output=True, timeout=30, check=True)
    data_dir = assets_root.parent / f"data-{uuid4().hex[:8]}"
    data_dir.mkdir()
    attach_repos_config(data_dir=data_dir, url=staging.resolve().as_uri(), repo_key=repo_key)
    sync_repo(client, repo_key)
    return f"{repo_key}/{project_key}"


def project_api_base(project_id: str) -> str:
    """``main/demo`` → ``/repos/main/projects/demo``。"""
    if "/" not in project_id:
        raise ValueError(f"invalid project_id (expect repo/project): {project_id!r}")
    repo, project = project_id.split("/", 1)
    return f"/repos/{repo}/projects/{project}"


def assert_case_result_invariants(
    result: dict[str, Any], declared_step_ids: list[str] | None = None
) -> None:
    """Fake 与真实 Engine 共用的 Case 结果不变量（顺序、计数、fail-fast、秘密）。"""
    steps = result["steps"]
    if declared_step_ids is not None:
        assert [s["step_id"] for s in steps] == declared_step_ids
    summary = result["summary"]
    assert summary == {
        "total": len(steps),
        "success": sum(s["status"] == "success" for s in steps),
        "failed": sum(s["status"] == "failed" for s in steps),
        "skipped": sum(s["status"] == "skipped" for s in steps),
    }
    expected = "success" if steps and all(s["status"] == "success" for s in steps) else "failed"
    assert result["status"] == expected
    failed_indexes = [i for i, s in enumerate(steps) if s["status"] == "failed"]
    assert len(failed_indexes) <= 1
    if failed_indexes:
        assert all(s["status"] == "success" for s in steps[: failed_indexes[0]])
        assert all(s["status"] == "skipped" for s in steps[failed_indexes[0] + 1 :])
    for step in steps:
        if step["status"] == "skipped":
            assert step["duration_seconds"] == 0
            assert step["request"] is None and step["response"] is None
            assert step["error"] is None
            assert step["skip_reason"] == "fail_fast"
        elif step["status"] == "failed":
            assert step["error"]
        else:
            assert step["error"] is None
