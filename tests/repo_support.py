"""Phase 4.0 共用 fixture：本地 ``git init`` 资产仓库 + 同步建立项目。

测试一律 ``file://`` URL，不连外网。git 调用使用参数列表。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from fastapi.testclient import TestClient

from testplat_control.main import app
from testplat_control.services.repo_sync import RepoSyncService
from testplat_control.services.repos_config import ReposConfig, parse_repos_config

DEFAULT_REPO_KEY = "main"
DEFAULT_PROJECT_KEY = "demo"

# 最小可同步资产树（含 api / case / envs / auth）
DEFAULT_FILES: dict[str, str] = {
    "testplat.yaml": """\
schema_version: "1"
projects:
  demo:
    name: Demo Project
    assets: projects/demo
    config: projects/demo/config
    default_env: test
""",
    "projects/demo/api/common/health_check.yaml": """\
id: api.common.health_check
type: api
name: 健康检查
host: local
method: GET
url: /health
request: {}
success:
  status_code: 200
""",
    "projects/demo/api/user/create.yaml": """\
id: api.user.create
type: api
name: 创建用户
host: local
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
success:
  status_code: 201
""",
    "projects/demo/api/user/login.yaml": """\
id: api.user.login
type: api
name: 登录
host: local
method: POST
url: /login
request:
  inputs:
    username: 用户名
    email: 邮箱
    password: 密码 (required)
success:
  status_code: 200
""",
    "projects/demo/api/common/typed.yaml": """\
id: api.common.typed
type: api
name: 类型列表
host: local
method: POST
url: /typed
request:
  inputs:
    - name: count
      type: integer
      required: true
    - name: flag
      type: bool
      required: false
success:
  status_code: 200
""",
    "projects/demo/api/broken/bad.yaml": """\
id: api.broken.bad
type: api
name: bad
host: local
method: GET
url: /bad
request:
  inputs: not-a-mapping
success:
  status_code: 200
""",
    "projects/demo/api/bad/object_param.yaml": """\
id: api.bad.object_param
type: api
name: bad object
host: local
method: POST
url: /bad
request:
  inputs:
    nested:
      type: object
      required: false
success:
  status_code: 200
""",
    "projects/demo/notes/readme.txt": "not yaml\n",
    "projects/demo/scenarios/user/login.case.yaml": """\
schema_version: "0.2"
id: case.user.login
name: 登录流程
steps:
  - step_id: login
    type: api
    api_id: api.user.login
    name: 登录
""",
    "projects/demo/config/envs/test.yaml": """\
api_hosts:
  local: http://127.0.0.1:9
  dead: http://127.0.0.1:1
""",
    "projects/demo/config/envs/staging.yaml": """\
api_hosts:
  local: http://127.0.0.1:19
  dead: http://127.0.0.1:1
""",
}


def _run_git(args: list[str], *, cwd: Path) -> None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git failed: {args[0]} code={result.returncode}")


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def init_asset_repo(
    tmp_path: Path,
    files: dict[str, str] | None = None,
    *,
    branch: str = "main",
) -> tuple[str, Path]:
    """在 ``tmp_path`` 下 ``git init`` 并提交资产，返回 ``(file:// URL, repo_path)``。"""
    repo = tmp_path / f"assets-{uuid4().hex[:8]}"
    repo.mkdir(parents=True)
    write_tree(repo, files if files is not None else DEFAULT_FILES)
    _run_git(["init", "-b", branch], cwd=repo)
    _run_git(["config", "user.email", "test@example.com"], cwd=repo)
    _run_git(["config", "user.name", "Test"], cwd=repo)
    _run_git(["add", "-A"], cwd=repo)
    _run_git(["commit", "-m", "init assets"], cwd=repo)
    url = repo.resolve().as_uri()
    return url, repo


def commit_all(repo: Path, message: str = "update") -> str:
    """提交仓库全部变更并返回新 SHA。"""
    _run_git(["add", "-A"], cwd=repo)
    _run_git(["commit", "-m", message], cwd=repo)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        env=env,
        capture_output=True,
        timeout=30,
        check=True,
    )
    return result.stdout.decode().strip()


def write_repos_file(
    path: Path,
    *,
    data_dir: Path,
    repo_key: str = DEFAULT_REPO_KEY,
    url: str,
    branch: str = "main",
) -> Path:
    """写入服务端仓库登记 YAML。"""
    payload = {
        "data_dir": str(data_dir.resolve()),
        "repos": {repo_key: {"url": url, "branch": branch}},
    }
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def attach_repos_config(
    *,
    data_dir: Path,
    url: str,
    repo_key: str = DEFAULT_REPO_KEY,
    branch: str = "main",
) -> ReposConfig:
    """把配置挂到 ``app.state.repo_sync``（供 TestClient 使用）。"""
    config = parse_repos_config(
        {
            "data_dir": str(data_dir.resolve()),
            "repos": {repo_key: {"url": url, "branch": branch}},
        }
    )
    service = getattr(app.state, "repo_sync", None)
    if isinstance(service, RepoSyncService):
        service.replace_config(config)
    else:
        app.state.repo_sync = RepoSyncService(config)
    return config


def project_base(repo: str = DEFAULT_REPO_KEY, project: str = DEFAULT_PROJECT_KEY) -> str:
    return f"/repos/{repo}/projects/{project}"


def sync_repo(client: TestClient, repo: str = DEFAULT_REPO_KEY) -> dict[str, Any]:
    response = client.post(f"/repos/{repo}/sync")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True, body
    return body


def bootstrap_synced_project(
    client: TestClient,
    tmp_path: Path,
    files: dict[str, str] | None = None,
    *,
    repo_key: str = DEFAULT_REPO_KEY,
    project_key: str = DEFAULT_PROJECT_KEY,
) -> dict[str, Any]:
    """创建 fixture 仓库、挂配置、同步，返回上下文。"""
    url, repo_path = init_asset_repo(tmp_path / "git", files)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    attach_repos_config(data_dir=data_dir, url=url, repo_key=repo_key)
    sync_body = sync_repo(client, repo_key)
    project_id = f"{repo_key}/{project_key}"
    return {
        "url": url,
        "repo_path": repo_path,
        "data_dir": data_dir,
        "repo": repo_key,
        "project": project_key,
        "project_id": project_id,
        "base": project_base(repo_key, project_key),
        "commit_sha": sync_body["commit_sha"],
    }
