"""Phase 4.1a Control 后端：会话、环境、账号、revision 与运行配置。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import text
from testplat_engine import UnavailableAuth

from testplat_control.adapters.fake_engine import FakeEngineAdapter
from testplat_control.config import settings
from testplat_control.database.session import SessionLocal, get_db
from testplat_control.deps import get_engine_port
from testplat_control.main import app
from testplat_control.services.auth_loader import build_auth_from_document
from tests.repo_support import DEFAULT_FILES, bootstrap_synced_project

pytestmark_auth = pytest.mark.platform_auth

ORIGIN = {"Origin": "http://testserver"}
PASSWORD = "pw-phase41a-secret"
OTHER_PASSWORD = "pw-other-project-99"


@pytest.fixture
def master_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "testplat_master_key", key)
    return key


@pytest.fixture
def fake() -> FakeEngineAdapter:
    engine = FakeEngineAdapter()
    app.dependency_overrides[get_engine_port] = lambda: engine
    yield engine
    app.dependency_overrides.pop(get_engine_port, None)


def _client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient, username: str = "alice", password: str = "password-1") -> None:
    response = client.post(
        "/auth/register",
        json={"username": username, "password": password},
        headers=ORIGIN,
    )
    assert response.status_code == 200, response.text
    assert response.json()["username"] == username


@pytest.mark.platform_auth
def test_a1_register_login_logout_and_401(master_key: str) -> None:
    """A1：注册、登录、注销；未登录访问配置返回 401；health 不依赖会话。"""
    del master_key
    client = _client()
    assert client.get("/health").status_code == 200
    assert client.get("/projects").status_code == 401
    assert client.get("/auth/me").status_code == 401

    bad_origin = client.post(
        "/auth/register",
        json={"username": "alice", "password": "password-1"},
        headers={"Origin": "http://evil.example"},
    )
    assert bad_origin.status_code == 403

    _register(client)
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json() == {"username": "alice"}
    cookie = client.cookies.get("testplat_session")
    assert cookie
    listed = client.get("/projects")
    assert listed.status_code == 200

    logged_out = client.post("/auth/logout", headers=ORIGIN)
    assert logged_out.status_code == 204
    assert client.get("/projects").status_code == 401
    assert client.get("/health").status_code == 200

    again = client.post(
        "/auth/login",
        json={"username": "alice", "password": "password-1"},
        headers=ORIGIN,
    )
    assert again.status_code == 200
    wrong = client.post(
        "/auth/login",
        json={"username": "alice", "password": "nope-nope"},
        headers=ORIGIN,
    )
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "用户名或密码错误"
    assert "password" not in wrong.text.lower() or "密码" in wrong.json()["detail"]

    set_cookie = again.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    token = client.cookies.get("testplat_session")
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT token_hash, password_hash FROM platform_sessions s "
                "JOIN platform_users u ON u.id = s.user_id"
            )
        ).fetchall()
    # 会话表只有哈希；用户表没有明文密码列被上面的查询用到 password_hash。
    hashes = [row[0] for row in rows]
    assert token not in hashes
    with SessionLocal() as db:
        stored = db.execute(text("SELECT password_hash FROM platform_users")).scalars().all()
    assert all(item != "password-1" and "password-1" not in item for item in stored)


@pytest.mark.platform_auth
def test_a1_registered_user_can_manage_config(tmp_path: Path, master_key: str) -> None:
    """普通注册用户可以维护环境，没有超管字段。"""
    del master_key
    client = _client()
    _register(client, "bob", "password-2")
    ctx = bootstrap_synced_project(client, tmp_path, repo_key="r1", project_key="demo")
    created = client.post(
        f"{ctx['base']}/environments",
        json={"env": "pre", "api_hosts": {"gsb": "http://127.0.0.1:9"}, "enabled": True},
        headers=ORIGIN,
    )
    assert created.status_code == 201, created.text
    other = _client()
    _register(other, "cara", "password-3")
    edited = other.put(
        f"{ctx['base']}/environments/pre",
        json={"revision": 1, "enabled": False},
        headers=ORIGIN,
    )
    assert edited.status_code == 200
    assert edited.json()["enabled"] is False
    assert "is_admin" not in created.text


def test_env_and_account_rules(tmp_path: Path, master_key: str) -> None:
    """环境名/账号名不可改名；none 保留；中文展示名可用；列表不含密码。"""
    client = _client()
    ctx = bootstrap_synced_project(client, tmp_path, repo_key="rules", project_key="demo")
    base = ctx["base"]
    created = client.post(
        f"{base}/environments",
        json={
            "env": "pre",
            "api_hosts": {"gsb": "http://127.0.0.1:9", "unified_login": "http://127.0.0.1:9"},
            "timeout_seconds": 12,
            "case_params": {"keywords": "衬衫"},
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["revision"] == 1
    bad_name = client.post(f"{base}/environments", json={"env": "Pre"})
    assert bad_name.status_code == 422
    duplicate = client.post(f"{base}/environments", json={"env": "pre"})
    assert duplicate.status_code == 409

    account = client.post(
        f"{base}/environments/pre/accounts",
        json={
            "account_name": "gsb",
            "display_name": "采购员",
            "business_role": "买家",
            "login_profile": "gsb_login",
            "credentials": {"username": "user-name", "password": PASSWORD},
        },
    )
    assert account.status_code == 201, account.text
    body = account.json()
    assert body["display_name"] == "采购员"
    assert "password" not in body
    assert PASSWORD not in account.text
    reserved = client.post(
        f"{base}/environments/pre/accounts",
        json={
            "account_name": "none",
            "login_profile": "gsb_login",
            "credentials": {"password": PASSWORD},
        },
    )
    assert reserved.status_code == 422

    listed = client.get(f"{base}/environments/pre/accounts")
    assert listed.status_code == 200
    assert PASSWORD not in listed.text
    creds = client.get(f"{base}/environments/pre/accounts/gsb/credentials")
    assert creds.status_code == 200
    assert creds.json()["credentials"]["password"] == PASSWORD
    assert creds.headers["cache-control"] == "no-store"


def test_a11_revision_conflict(tmp_path: Path, master_key: str) -> None:
    """A11：同一 revision 后保存的一方得到 409。"""
    del master_key
    client = _client()
    ctx = bootstrap_synced_project(client, tmp_path, repo_key="rev", project_key="demo")
    base = ctx["base"]
    client.post(
        f"{base}/environments", json={"env": "test", "api_hosts": {"local": "http://127.0.0.1:9"}}
    )
    first = client.put(
        f"{base}/environments/test",
        json={"revision": 1, "timeout_seconds": 8},
    )
    assert first.status_code == 200
    assert first.json()["revision"] == 2
    second = client.put(
        f"{base}/environments/test",
        json={"revision": 1, "timeout_seconds": 9},
    )
    assert second.status_code == 409
    assert "刷新" in second.json()["detail"]

    client.post(
        f"{base}/environments/test/accounts",
        json={
            "account_name": "gsb",
            "login_profile": "gsb_login",
            "credentials": {"password": PASSWORD},
        },
    )
    ok = client.put(
        f"{base}/environments/test/accounts/gsb",
        json={"revision": 1, "display_name": "甲"},
    )
    assert ok.status_code == 200
    stale = client.put(
        f"{base}/environments/test/accounts/gsb",
        json={"revision": 1, "display_name": "乙"},
    )
    assert stale.status_code == 409


def test_a8_sync_does_not_overwrite_web(tmp_path: Path, master_key: str) -> None:
    """A8：同步更新 commit，但不覆盖 Web 环境与启停。"""
    del master_key
    client = _client()
    ctx = bootstrap_synced_project(client, tmp_path, repo_key="syncweb", project_key="demo")
    base = ctx["base"]
    client.post(
        f"{base}/environments",
        json={"env": "test", "api_hosts": {"local": "http://10.0.0.8"}, "enabled": False},
    )
    # Git 新增一个环境文件并改掉 test.yaml，同步后 Web 仍是停用的 10.0.0.8。
    envs = ctx["repo_path"] / "projects" / "demo" / "config" / "envs"
    (envs / "test.yaml").write_text("api_hosts:\n  local: http://10.9.9.9\n", encoding="utf-8")
    (envs / "pre.yaml").write_text("api_hosts:\n  local: http://10.1.1.1\n", encoding="utf-8")
    from tests.repo_support import commit_all, sync_repo

    new_sha = commit_all(ctx["repo_path"], "template envs")
    body = sync_repo(client, ctx["repo"])
    assert body["commit_sha"] == new_sha
    detail = client.get(f"{base}/environments/test")
    assert detail.status_code == 200
    saved = detail.json()
    assert saved["enabled"] is False
    assert saved["api_hosts"]["local"] == "http://10.0.0.8"
    project = client.get(base).json()
    assert project["envs"] == []  # test 已停用，下拉只含启用环境
    assert "pre" not in project["envs"]
    assert project["commit_sha"] == new_sha


def test_login_profiles_lists_fields_not_secrets(tmp_path: Path) -> None:
    files = dict(DEFAULT_FILES)
    files["projects/demo/config/auth/_profiles.yaml"] = """\
identities:
  gsb_login:
    login:
      host: unified_login
      steps:
        - name: login
          method: GET
          path: /site/login
          body:
            type: query
            fields:
              username: "${secret:username}"
              password: "${secret:password}"
              source: go2
"""
    client = _client()
    ctx = bootstrap_synced_project(client, tmp_path, files, repo_key="prof", project_key="demo")
    response = client.get(f"{ctx['base']}/login-profiles")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["commit_sha"] == ctx["commit_sha"]
    assert body["profiles"] == [
        {"name": "gsb_login", "credential_fields": ["username", "password"]}
    ]
    assert "go2" not in response.text or "secret" not in response.text
    assert PASSWORD not in response.text


def test_a5_a7_frozen_config_and_overrides(
    tmp_path: Path, master_key: str, fake: FakeEngineAdapter
) -> None:
    """A5/A7：请求参数与显式超时覆盖环境；进行中的请求保持旧快照。"""
    del master_key
    import asyncio
    import threading

    client = _client()
    ctx = bootstrap_synced_project(client, tmp_path, repo_key="freeze", project_key="demo")
    base = ctx["base"]
    client.post(
        f"{base}/environments",
        json={
            "env": "test",
            "api_hosts": {"local": "http://10.0.0.1"},
            "timeout_seconds": 11,
            "case_params": {"age": 7},
        },
    )
    omitted = client.post(
        f"{base}/assets/api.user.create/run",
        json={"env": "test", "params": {"username": "a", "email": "a@b.c"}},
    )
    assert omitted.status_code == 200, omitted.text
    first = fake.calls[-1]
    assert first.environment["api_hosts"]["local"] == "http://10.0.0.1"
    assert first.timeout_seconds == 11
    assert first.params["age"] == 7
    assert first.params["username"] == "a"

    explicit = client.post(
        f"{base}/assets/api.user.create/run",
        json={
            "env": "test",
            "params": {"username": "a", "email": "a@b.c", "age": 9},
            "timeout_seconds": 30,
        },
    )
    assert explicit.status_code == 200, explicit.text
    second = fake.calls[-1]
    assert second.timeout_seconds == 30
    assert second.params["age"] == 9

    release = threading.Event()
    started = threading.Event()
    original = fake.execute

    async def blocking(request):  # noqa: ANN001
        started.set()
        for _ in range(200):
            if release.is_set():
                break
            await asyncio.sleep(0.01)
        return await original(request)

    fake.execute = blocking  # type: ignore[method-assign]
    holder: dict[str, object] = {}

    def runner() -> None:
        holder["response"] = client.post(
            f"{base}/assets/api.common.health_check/run",
            json={"env": "test", "params": {}},
        )

    thread = threading.Thread(target=runner)
    thread.start()
    assert started.wait(5)
    client.put(
        f"{base}/environments/test",
        json={"revision": 1, "api_hosts": {"local": "http://10.0.0.2"}, "timeout_seconds": 3},
    )
    release.set()
    thread.join(10)
    assert holder["response"].status_code == 200  # type: ignore[union-attr]
    frozen = fake.calls[-1]
    assert frozen.environment["api_hosts"]["local"] == "http://10.0.0.1"
    later = client.post(
        f"{base}/assets/api.common.health_check/run",
        json={"env": "test", "params": {}},
    )
    assert later.status_code == 200
    assert fake.calls[-1].environment["api_hosts"]["local"] == "http://10.0.0.2"
    assert fake.calls[-1].timeout_seconds == 3


def test_a10_history_keeps_snapshot(
    tmp_path: Path, master_key: str, fake: FakeEngineAdapter
) -> None:
    """A10：历史保留操作人、版本与非秘密快照；之后的编辑不改历史。"""
    del fake
    client = _client()
    ctx = bootstrap_synced_project(client, tmp_path, repo_key="hist", project_key="demo")
    base = ctx["base"]
    client.post(
        f"{base}/environments",
        json={"env": "test", "api_hosts": {"local": "http://10.0.0.3"}, "case_params": {}},
    )
    client.post(
        f"{base}/environments/test/accounts",
        json={
            "account_name": "gsb",
            "login_profile": "gsb_login",
            "credentials": {"password": PASSWORD},
        },
    )
    run = client.post(
        f"{base}/assets/api.common.health_check/run",
        json={"env": "test", "params": {}},
    )
    assert run.status_code == 200, run.text
    assert run.json()["operator"] == "tester"
    record_id = run.json()["record_id"]
    client.put(
        f"{base}/environments/test",
        json={"revision": 2, "api_hosts": {"local": "http://10.0.0.4"}},
    )
    detail = client.get(f"{base}/execution-records/{record_id}")
    assert detail.status_code == 200
    saved = detail.json()
    assert saved["operator"] == "tester"
    assert saved["env"] == "test"
    assert saved["commit_sha"]
    assert saved["config_revision"] == 2  # 建账号时环境 revision 已加到 2，运行时冻结
    assert saved["account_revisions"]["gsb"] == 1
    snapshot = saved["config_snapshot"]
    assert snapshot["api_hosts"]["local"] == "http://10.0.0.3"
    assert PASSWORD not in detail.text
    with SessionLocal() as db:
        notes = db.execute(
            text("SELECT field_names, credential_note FROM config_changes")
        ).fetchall()
    blob = str(notes)
    assert PASSWORD not in blob
    assert any(row[1] == "已修改" for row in notes)


def test_a12_ciphertext_and_logs(
    tmp_path: Path, master_key: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A12：重启后同一密钥仍能解密；库与日志没有明文密码。"""
    client = _client()
    ctx = bootstrap_synced_project(client, tmp_path, repo_key="crypt", project_key="demo")
    base = ctx["base"]
    with caplog.at_level(logging.DEBUG):
        client.post(f"{base}/environments", json={"env": "test", "api_hosts": {}})
        client.post(
            f"{base}/environments/test/accounts",
            json={
                "account_name": "gsb",
                "login_profile": "gsb_login",
                "credentials": {"username": "user-name", "password": PASSWORD},
            },
        )
    assert PASSWORD not in caplog.text
    with SessionLocal() as db:
        cipher = db.execute(text("SELECT encrypted_credentials FROM test_accounts")).scalar()
        pw_hash = db.execute(text("SELECT password_hash FROM platform_users")).scalar()
    assert isinstance(cipher, str)
    assert PASSWORD not in cipher
    if pw_hash:
        assert PASSWORD not in pw_hash
    # 新会话仍能读出凭据（进程内“重启”后的读取）。
    SessionLocal.remove() if hasattr(SessionLocal, "remove") else None
    again = client.get(f"{base}/environments/test/accounts/gsb/credentials")
    assert again.json()["credentials"]["password"] == PASSWORD
    missing = settings.testplat_master_key
    assert missing
    # 错误密钥不能解密，且响应不含密文或原密码。
    from testplat_control.services import crypto

    try:
        settings.testplat_master_key = Fernet.generate_key().decode("ascii")
        failed = client.get(f"{base}/environments/test/accounts/gsb/credentials")
        assert failed.status_code == 500
        assert PASSWORD not in failed.text
        assert cipher not in failed.text
        assert "TESTPLAT_MASTER_KEY" in failed.json()["detail"]
    finally:
        settings.testplat_master_key = missing
        del crypto


def test_credential_builder_does_not_read_process_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """平台构造入口不回退 TESTPLAT_GSB_*。历史 load_auth 仍由既有夹具覆盖。"""
    monkeypatch.setenv("TESTPLAT_GSB_PASSWORD", "should-not-be-used-99")
    document = {
        "identities": {
            "gsb": {
                "login": {
                    "host": "unified_login",
                    "steps": [
                        {
                            "name": "login",
                            "method": "GET",
                            "path": "/site/login",
                            "body": {
                                "type": "query",
                                "fields": {
                                    "username": "${secret:username}",
                                    "password": "${secret:password}",
                                },
                            },
                            "extract": [
                                {"source": "body_json", "path": "$.data.hash", "as": "token"}
                            ],
                        }
                    ],
                    "inject": {"headers": {"X-TOKEN": "${login:token}"}},
                }
            }
        }
    }
    built = build_auth_from_document(
        document,
        env="test",
        secrets={"username": "user-name", "password": PASSWORD},
        cache_scope="repo:proj:test",
    )
    material = built.table.identities["gsb"]
    assert not isinstance(material, UnavailableAuth)
    revealed = material.flow.steps[0].body.fields["password"].reveal()  # type: ignore[union-attr]
    assert revealed == PASSWORD
    assert "should-not-be-used-99" not in revealed

    fallback = build_auth_from_document(
        document,
        env="test",
        secrets={"username": "user-name"},
        cache_scope="repo:proj:test",
    )
    unavailable = fallback.table.identities["gsb"]
    assert isinstance(unavailable, UnavailableAuth)
    assert "TESTPLAT_GSB_PASSWORD" not in unavailable.public_reason
    assert "should-not-be-used-99" not in unavailable.public_reason


def test_master_key_missing_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "testplat_master_key", None)
    client = _client()
    ctx = bootstrap_synced_project(client, tmp_path, repo_key="nokey", project_key="demo")
    client.post(f"{ctx['base']}/environments", json={"env": "test"})
    response = client.post(
        f"{ctx['base']}/environments/test/accounts",
        json={
            "account_name": "gsb",
            "login_profile": "gsb_login",
            "credentials": {"password": PASSWORD},
        },
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "服务配置错误：TESTPLAT_MASTER_KEY 未配置"
    assert PASSWORD not in response.text


_CREATE_WITH_DEFAULT = """\
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
      default: from-asset
      description: 用户名
    email:
      type: string
      required: true
      description: 邮箱
success:
  status_code: 201
"""


def test_r3_merges_before_required_check(
    tmp_path: Path, master_key: str, fake: FakeEngineAdapter
) -> None:
    """环境 case_params 能补齐必填；请求覆盖环境；资产默认值垫底；合并后仍缺则 422。"""
    del master_key
    from tests.repo_support import DEFAULT_FILES

    files = dict(DEFAULT_FILES)
    files["projects/demo/api/user/create.yaml"] = _CREATE_WITH_DEFAULT
    client = _client()
    ctx = bootstrap_synced_project(client, tmp_path, files, repo_key="mergep", project_key="demo")
    base = ctx["base"]

    missing_email = client.post(
        f"{base}/assets/api.user.create/run",
        json={"env": "test", "params": {}},
    )
    assert missing_email.status_code == 422
    assert "email" in missing_email.json()["detail"]
    assert fake.calls == []

    created = client.post(
        f"{base}/environments",
        json={
            "env": "test",
            "api_hosts": {"local": "http://10.0.0.5"},
            "case_params": {"username": "from-env", "email": "env@b.c"},
        },
    )
    assert created.status_code == 201, created.text
    filled = client.post(
        f"{base}/assets/api.user.create/run",
        json={"env": "test", "params": {}},
    )
    assert filled.status_code == 200, filled.text
    assert fake.calls[-1].params["username"] == "from-env"
    assert fake.calls[-1].params["email"] == "env@b.c"

    overridden = client.post(
        f"{base}/assets/api.user.create/run",
        json={"env": "test", "params": {"username": "from-req"}},
    )
    assert overridden.status_code == 200, overridden.text
    assert fake.calls[-1].params["username"] == "from-req"
    assert fake.calls[-1].params["email"] == "env@b.c"

    client.put(
        f"{base}/environments/test",
        json={"revision": created.json()["revision"], "case_params": {"username": "only-name"}},
    )
    still_missing = client.post(
        f"{base}/assets/api.user.create/run",
        json={"env": "test", "params": {}},
    )
    assert still_missing.status_code == 422
    assert "email" in still_missing.json()["detail"]


def test_r3b_shared_defaults_do_not_block_other_apis(
    tmp_path: Path, master_key: str, fake: FakeEngineAdapter
) -> None:
    """环境默认值只补本接口声明的字段；请求体里的未知参数仍然拒绝。"""
    del master_key
    client = _client()
    ctx = bootstrap_synced_project(client, tmp_path, repo_key="share", project_key="demo")
    base = ctx["base"]
    created = client.post(
        f"{base}/environments",
        json={
            "env": "test",
            "api_hosts": {"local": "http://10.0.0.5"},
            "case_params": {"username": "from-env", "email": "env@b.c"},
        },
    )
    assert created.status_code == 201, created.text

    created_run = client.post(
        f"{base}/assets/api.user.create/run",
        json={"env": "test", "params": {}},
    )
    assert created_run.status_code == 200, created_run.text
    assert fake.calls[-1].params["username"] == "from-env"
    assert fake.calls[-1].params["email"] == "env@b.c"

    health = client.post(
        f"{base}/assets/api.common.health_check/run",
        json={"env": "test", "params": {}},
    )
    assert health.status_code == 200, health.text
    assert "username" not in fake.calls[-1].params
    assert "email" not in fake.calls[-1].params

    unknown = client.post(
        f"{base}/assets/api.common.health_check/run",
        json={"env": "test", "params": {"username": "explicit"}},
    )
    assert unknown.status_code == 422
    assert "unknown param 'username'" in unknown.json()["detail"]


def test_r3a_record_uses_the_frozen_params(
    tmp_path: Path, master_key: str, fake: FakeEngineAdapter
) -> None:
    """执行期间改环境后，记录版本、快照和实际参数仍是同一次冻结结果。"""
    del master_key
    import asyncio
    import threading

    client = _client()
    ctx = bootstrap_synced_project(client, tmp_path, repo_key="once", project_key="demo")
    base = ctx["base"]
    created = client.post(
        f"{base}/environments",
        json={
            "env": "test",
            "api_hosts": {"local": "http://10.0.0.1"},
            "case_params": {"username": "from-env", "email": "env@b.c", "age": 1},
        },
    )
    assert created.status_code == 201, created.text
    frozen_revision = created.json()["revision"]

    release = threading.Event()
    started = threading.Event()
    original = fake.execute

    async def blocking(request):  # noqa: ANN001
        started.set()
        for _ in range(200):
            if release.is_set():
                break
            await asyncio.sleep(0.01)
        return await original(request)

    fake.execute = blocking  # type: ignore[method-assign]
    holder: dict[str, object] = {}

    def runner() -> None:
        holder["response"] = client.post(
            f"{base}/assets/api.user.create/run",
            json={"env": "test", "params": {}},
        )

    thread = threading.Thread(target=runner)
    thread.start()
    assert started.wait(5)
    updated = client.put(
        f"{base}/environments/test",
        json={
            "revision": frozen_revision,
            "case_params": {"username": "from-env", "email": "env@b.c", "age": 99},
        },
    )
    assert updated.status_code == 200, updated.text
    release.set()
    thread.join(10)
    response = holder["response"]
    assert response.status_code == 200, response.text  # type: ignore[attr-defined]
    sent = fake.calls[-1]
    assert sent.params["age"] == 1
    assert sent.params["username"] == "from-env"
    assert sent.params["email"] == "env@b.c"
    detail = client.get(f"{base}/execution-records/{response.json()['record_id']}")  # type: ignore[attr-defined]
    assert detail.status_code == 200, detail.text
    saved = detail.json()
    assert saved["config_revision"] == frozen_revision
    assert saved["config_snapshot"]["config_revision"] == frozen_revision
    assert saved["config_snapshot"]["case_params"]["age"] == 1


def test_d1_engine_entry_does_not_hold_read_transaction(
    tmp_path: Path, master_key: str, fake: FakeEngineAdapter
) -> None:
    """API 与 Case 进入 Engine 时，配置读取事务已经结束，结果仍能落库。"""
    del master_key
    sessions: list = []

    def tracking_get_db():
        db = SessionLocal()
        sessions.append(db)
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = tracking_get_db
    flags: dict[str, bool] = {}
    original = fake.execute

    async def spy(request):  # noqa: ANN001
        open_sessions = [item for item in sessions if item.is_active]
        flags[type(request).__name__] = bool(open_sessions) and all(
            not item.in_transaction() for item in open_sessions
        )
        return await original(request)

    fake.execute = spy  # type: ignore[method-assign]
    try:
        client = _client()
        ctx = bootstrap_synced_project(client, tmp_path, repo_key="notx", project_key="demo")
        base = ctx["base"]
        assert (
            client.post(
                f"{base}/environments",
                json={"env": "test", "api_hosts": {"local": "http://10.0.0.8"}},
            ).status_code
            == 201
        )
        api_run = client.post(
            f"{base}/assets/api.common.health_check/run",
            json={"env": "test", "params": {}},
        )
        case_run = client.post(
            f"{base}/cases/case.user.login/run",
            json={"env": "test", "params": {}},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert api_run.status_code == 200, api_run.text
    assert case_run.status_code == 200, case_run.text
    assert flags["ApiExecutionRequest"] is True
    assert flags["CaseExecutionRequest"] is True
    assert api_run.json()["record_id"]
    assert case_run.json()["record_id"]


@pytest.mark.platform_auth
def test_s1_validation_errors_hide_secrets(tmp_path: Path, master_key: str) -> None:
    """缺字段或类型错误的 422 不回显 password / credentials。"""
    secret = "pw-should-not-echo-91"
    client = _client()
    missing_user = client.post("/auth/register", json={"password": secret})
    assert missing_user.status_code == 422
    assert secret not in missing_user.text
    assert "input" not in missing_user.text
    wrong_type = client.post(
        "/auth/register",
        json={"username": 1, "password": secret},
    )
    assert wrong_type.status_code == 422
    assert secret not in wrong_type.text
    assert "input" not in wrong_type.text

    _register(client, "s1hide", "password-1")
    ctx = bootstrap_synced_project(client, tmp_path, repo_key="hideme", project_key="demo")
    base = ctx["base"]
    client.post(f"{base}/environments", json={"env": "test", "api_hosts": {}})
    missing_name = client.post(
        f"{base}/environments/test/accounts",
        json={
            "login_profile": "gsb_login",
            "credentials": {"username": "buyer-user", "password": secret},
        },
    )
    assert missing_name.status_code == 422
    assert secret not in missing_name.text
    assert "buyer-user" not in missing_name.text
    detail = missing_name.json()["detail"]
    assert isinstance(detail, list)
    assert all("input" not in item and "ctx" not in item for item in detail)
