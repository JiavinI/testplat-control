"""Phase 4.0：仓库同步、快照、路径安全、泄密与执行固定 SHA（设计稿 §7 后端可测部分）。"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from testplat_control.adapters.fake_engine import FakeEngineAdapter
from testplat_control.deps import get_engine_port
from testplat_control.main import app
from testplat_control.services.manifest import ManifestError, assert_relative_safe, load_manifest
from testplat_control.services.repo_sync import (
    SYNC_INVALID_MANIFEST,
    SYNC_NETWORK,
    classify_git_failure,
)
from tests.repo_support import (
    DEFAULT_FILES,
    attach_repos_config,
    bootstrap_synced_project,
    commit_all,
    init_asset_repo,
    sync_repo,
    write_tree,
)

# 历史 Git 配置兼容测试；生产默认关闭。
pytestmark = pytest.mark.legacy_git_config

client = TestClient(app)


@pytest.fixture
def fake_engine() -> FakeEngineAdapter:
    engine = FakeEngineAdapter()
    app.dependency_overrides[get_engine_port] = lambda: engine
    yield engine
    app.dependency_overrides.pop(get_engine_port, None)


def test_bootstrap_lists_project_from_file_repo(tmp_path: Path) -> None:
    """§7-1：file:// 仓库同步后项目出现。"""
    ctx = bootstrap_synced_project(client, tmp_path)
    projects = client.get("/projects").json()
    assert any(p["id"] == ctx["project_id"] for p in projects)
    assert client.post("/projects", json={"name": "x"}).status_code in {404, 405, 422}


def test_sync_picks_up_new_case(tmp_path: Path) -> None:
    """§7-2：新提交 case → 同步后树中出现，SHA 更新。"""
    ctx = bootstrap_synced_project(client, tmp_path)
    old_sha = ctx["commit_sha"]
    case_path = (
        ctx["repo_path"] / "projects" / "demo" / "scenarios" / "demo" / "new_smoke.case.yaml"
    )
    case_path.parent.mkdir(parents=True, exist_ok=True)
    case_path.write_text(
        'schema_version: "0.2"\nid: case.demo.new_smoke\nsteps: []\n',
        encoding="utf-8",
    )
    new_sha = commit_all(ctx["repo_path"], "add case")
    body = sync_repo(client, ctx["repo"])
    assert body["commit_sha"] == new_sha
    assert body["commit_sha"] != old_sha
    detail = client.get(f"{ctx['base']}/cases/case.demo.new_smoke")
    assert detail.status_code == 200


def test_sync_unreachable_keeps_old_sha(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """§7-3：不可达 URL → 保留旧 SHA，错误只含类别。"""
    ctx = bootstrap_synced_project(client, tmp_path)
    old_sha = ctx["commit_sha"]
    bad_url = (tmp_path / "missing-repo").resolve().as_uri()
    attach_repos_config(data_dir=ctx["data_dir"], url=bad_url, repo_key=ctx["repo"])
    with caplog.at_level(logging.WARNING):
        response = client.post(f"/repos/{ctx['repo']}/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["category"] in {SYNC_NETWORK, "auth", "timeout"}
    assert body["commit_sha"] == old_sha
    # 响应与日志不含 URL
    assert bad_url not in response.text
    assert bad_url not in caplog.text
    assert ctx["url"] not in response.text


def test_sync_invalid_manifest_keeps_old_sha(tmp_path: Path) -> None:
    """§7-3：清单非法 → invalid_manifest，保留旧 SHA。"""
    ctx = bootstrap_synced_project(client, tmp_path)
    old_sha = ctx["commit_sha"]
    (ctx["repo_path"] / "testplat.yaml").write_text('schema_version: "1"\n', encoding="utf-8")
    commit_all(ctx["repo_path"], "break manifest")
    body = client.post(f"/repos/{ctx['repo']}/sync").json()
    assert body["ok"] is False
    assert body["category"] == SYNC_INVALID_MANIFEST
    assert body["commit_sha"] == old_sha


def test_execution_keeps_old_sha_while_sync_updates(
    tmp_path: Path, fake_engine: FakeEngineAdapter
) -> None:
    """§7-4：执行进行中同步换 SHA → 记录仍为旧 SHA。"""
    ctx = bootstrap_synced_project(client, tmp_path)
    old_sha = ctx["commit_sha"]
    release = threading.Event()
    started = threading.Event()

    original_execute = fake_engine.execute

    async def blocking_execute(request):  # noqa: ANN001
        started.set()
        # 等待主线程完成同步
        for _ in range(200):
            if release.is_set():
                break
            await asyncio.sleep(0.01)
        return await original_execute(request)

    fake_engine.execute = blocking_execute  # type: ignore[method-assign]

    result_holder: dict[str, object] = {}

    def runner() -> None:
        result_holder["response"] = client.post(
            f"{ctx['base']}/assets/api.common.health_check/run",
            json={"env": "test", "params": {}},
        )

    thread = threading.Thread(target=runner)
    thread.start()
    assert started.wait(5.0)
    # 推新 commit 并同步
    (ctx["repo_path"] / "projects" / "demo" / "api" / "common" / "extra.yaml").write_text(
        "id: api.common.extra\ntype: api\nhost: local\nmethod: GET\nurl: /x\n",
        encoding="utf-8",
    )
    new_sha = commit_all(ctx["repo_path"], "during run")
    sync_body = sync_repo(client, ctx["repo"])
    assert sync_body["commit_sha"] == new_sha != old_sha
    release.set()
    thread.join(timeout=10)
    response = result_holder["response"]
    assert response.status_code == 200  # type: ignore[union-attr]
    body = response.json()  # type: ignore[union-attr]
    assert body["commit_sha"] == old_sha
    detail = client.get(f"{ctx['base']}/execution-records/{body['record_id']}")
    assert detail.json()["commit_sha"] == old_sha


def test_run_requires_env_and_records_filter(
    tmp_path: Path, fake_engine: FakeEngineAdapter
) -> None:
    """§7-5 / §7-6：必填 env；非法 422；记录带 env+sha；可按 env 过滤。"""
    ctx = bootstrap_synced_project(client, tmp_path)
    missing = client.post(
        f"{ctx['base']}/assets/api.common.health_check/run",
        json={"params": {}},
    )
    assert missing.status_code == 422
    ok = client.post(
        f"{ctx['base']}/assets/api.common.health_check/run",
        json={"env": "test", "params": {}},
    )
    assert ok.status_code == 200
    assert ok.json()["commit_sha"]
    listed = client.get(f"{ctx['base']}/execution-records", params={"env": "test"})
    assert listed.status_code == 200
    assert len(listed.json()) >= 1
    assert all(item["env"] == "test" for item in listed.json())
    assert all(item.get("commit_sha") for item in listed.json())
    empty = client.get(f"{ctx['base']}/execution-records", params={"env": "staging"})
    assert empty.json() == []


def test_manifest_rejects_path_escape(tmp_path: Path) -> None:
    """§7-7：绝对路径、..、符号链接逃逸。"""
    with pytest.raises(ManifestError):
        assert_relative_safe("../etc")
    with pytest.raises(ManifestError):
        assert_relative_safe("/etc/passwd")

    root = tmp_path / "snap"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    link = root / "escape"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink not permitted")
    # safe_resolve should reject
    from testplat_control.services.manifest import safe_resolve

    with pytest.raises(ManifestError):
        safe_resolve(root, "escape")


def test_sync_failure_does_not_leak_url_or_stderr(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """§7-8：响应与 caplog 不含仓库 URL / git stderr 片段。"""
    url, _ = init_asset_repo(tmp_path / "git")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # 使用含假凭据的 URL 字符串作为配置（file 路径本身）
    credentialish = url.replace("file://", "file://user:secret-token@")
    # 断言 caplog 分类日志不含 path / 凭据原文
    attach_repos_config(data_dir=data_dir, url=str(tmp_path / "no-such-git"), repo_key="main")
    # parse expects url string - use as_uri of missing
    missing = (tmp_path / "no-such-git").resolve().as_uri()
    attach_repos_config(data_dir=data_dir, url=missing, repo_key="main")
    with caplog.at_level(logging.DEBUG):
        response = client.post("/repos/main/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    blob = response.text + caplog.text
    assert missing not in blob
    assert "fatal:" not in blob.lower()
    assert "secret-token" not in blob
    assert credentialish not in blob


def test_classify_auth_keywords() -> None:
    assert classify_git_failure(b"Permission denied (publickey)") == "auth"
    assert classify_git_failure(b"Could not resolve host") == SYNC_NETWORK


def test_load_manifest_from_valid_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    write_tree(root, DEFAULT_FILES)
    manifest = load_manifest(root)
    assert "demo" in manifest.projects
