"""Platform selection/config ownership and actual Engine requests against isolated targets."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import yaml
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import text

from testplat_control.config import settings
from testplat_control.database.models import Project, WorkspaceBinding
from testplat_control.database.models import TestAccount as AccountRow
from testplat_control.database.session import SessionLocal, get_engine, init_engine_schema
from testplat_control.main import app
from testplat_control.platform_import import ImportConflictError, build_plan, import_plan
from testplat_control.services.environment_store import read_credentials
from testplat_control.services.manifest import ManifestError, parse_manifest_dict
from testplat_control.services.project_access import ensure_snapshot_dirs
from testplat_control.services.run_config import resolve_run_config
from tests.repo_support import bootstrap_synced_project
from tests.test_phase4_1a_fake_target import PROFILE


def manifest():
    projects = {}
    for key, platform, business, owner in [
        ("gsb", "gsb", "go2", "gsb"),
        ("go2", "go2", "go2", "gsb"),
        ("gsb_e3e3", "gsb", "e3e3", "gsb_e3e3"),
        ("e3e3", "e3e3", "e3e3", "gsb_e3e3"),
        *[
            (key + suffix, key, business, key)
            for key in ("daifa_admin", "daifa_picker", "admin_go2")
            for suffix, business in (("", "go2"), ("_e3e3", "e3e3"))
        ],
    ]:
        projects[key] = {
            "name": key,
            "assets": f"projects/{key}",
            "config": f"config/{owner}",
            "default_env": "test",
            "workspace": {
                "platform": platform,
                "platform_name": platform,
                "project": business,
                "project_name": business.upper(),
                "configuration": owner,
            },
        }
    return {"schema_version": "1", "projects": projects}


@pytest.mark.parametrize(
    "change,code",
    [
        ("duplicate", "duplicate_workspace"),
        ("missing", "missing_configuration_project"),
        ("chain", "chained_configuration_project"),
        ("path", "configuration_path_mismatch"),
    ],
)
def test_manifest_rejects_invalid_config_ownership(change, code):
    value = manifest()
    spec = value["projects"]["go2"]
    if change == "duplicate":
        spec["workspace"]["platform"] = "gsb"
    elif change == "missing":
        spec["workspace"]["configuration"] = "absent"
    elif change == "chain":
        spec["workspace"]["configuration"] = "e3e3"
    else:
        spec["config"] = "different"
    with pytest.raises(ManifestError) as caught:
        parse_manifest_dict(value)
    assert caught.value.code == code


def source_tree(root: Path, base: str):
    def write(rel, value):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(value, allow_unicode=True))

    write(
        "envs/test.yaml",
        {
            "api_hosts": {
                key: base
                for key in ("gsb", "unified_login", "daifa_admin", "daifa_picker", "admin_go2")
            }
        },
    )
    for project in ("go2", "e3e3"):
        write(f"envs/test/{project}.yaml", {"web_hosts": {"sso": base, "gsb": base}})
    write(
        "secrets/test.secrets.yaml",
        {
            "accounts": {
                "go2": {"b1": {"primary": {"username": "18583220150", "password": "fake-go2"}}},
                "e3e3": {
                    "b1": {"primary": {"username": "泡泡象", "password": "fake-e3-b1"}},
                    "b2": {"primary": {"username": "legacy-name", "password": "fake-e3-b2"}},
                },
            },
            "logins": {
                "daifa_admin": {
                    "default": {
                        "username": "dispatch",
                        "password": "fake-da",
                        "login_password": "fake-login",
                        "refund_password_ciphertext": "not-imported",
                    }
                },
                "daifa_picker": {"default": {"phone": "picker", "verification_code": "fake-code"}},
                "admin_go2": {"default": {"username": "manager", "password": "fake-manager"}},
            },
        },
    )


def asset_files():
    files = {"testplat.yaml": yaml.safe_dump(manifest())}
    for key, spec in manifest()["projects"].items():
        platform = spec["workspace"]["platform"]
        auth = {
            "gsb": "gsb.b2.primary",
            "go2": "gsb.b1.primary",
            "e3e3": "gsb.b1.primary",
            "daifa_admin": "df_admin.default",
            "daifa_picker": "df_picker.default",
            "admin_go2": "admin_go2.default",
        }[platform]
        files[f"projects/{key}/api/probe.yaml"] = yaml.safe_dump(
            {
                "id": "api.probe",
                "name": "fake protected probe",
                "host": platform
                if platform in ("daifa_admin", "daifa_picker", "admin_go2")
                else "gsb",
                "method": "POST",
                "url": "/balance",
                "auth": auth,
                "request": {"type": "json", "inputs": {}, "body": {}},
                "success": {"status_code": 200},
            }
        )
        config = spec["config"]
        files[f"{config}/envs/test.yaml"] = "api_hosts: {}"
        if platform in ("go2", "e3e3", "gsb"):
            business = spec["workspace"]["project"]
            files[f"{config}/auth/_profiles.yaml"] = PROFILE.replace(
                "source: go2", f"source: {business}"
            )
        elif platform == "daifa_admin":
            files[f"{config}/auth/_profiles.yaml"] = yaml.safe_dump(
                {
                    "identities": {
                        "df_admin_pending": {
                            "unavailable": {
                                "reason": "验证码 Redis 待适配",
                                "credentials": {
                                    field: "${secret:" + field + "}"
                                    for field in ("username", "password", "login_password")
                                },
                            }
                        }
                    }
                }
            )
        else:
            # Exercise form payload, context source and independently owned credentials.
            profile_name = "df_picker_login" if platform == "daifa_picker" else "admin_go2_login"
            files[f"{config}/auth/_profiles.yaml"] = (
                PROFILE.replace("gsb_login:", profile_name + ":")
                .replace("host: unified_login", f"host: {platform}")
                .replace("method: GET", "method: POST")
                .replace("path: /site/login", "path: /form-login")
                .replace("type: query", "type: form")
                .replace("source: go2", 'source: "${workspace:project}"')
            )
    return files


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.respond()

    def do_POST(self):  # noqa: N802
        self.respond()

    def respond(self):
        parsed = urlsplit(self.path)
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = parse_qs(parsed.query if self.command == "GET" else raw.decode())
        self.server.events.append((parsed.path, payload, self.headers.get("X-TOKEN")))
        data = (
            {"data": {"hash": "fake-token", "userId": "fake-uid"}}
            if parsed.path in ("/site/login", "/form-login")
            else {"ok": True}
        )
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "testplat_master_key", Fernet.generate_key().decode())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.events = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    source_tree(tmp_path / "old", base)
    try:
        with TestClient(app) as client:
            ctx = bootstrap_synced_project(
                client, tmp_path, asset_files(), repo_key="p" + uuid4().hex[:8], project_key="gsb"
            )
            yield client, ctx, server, tmp_path / "old"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_import_preflight_requires_explicit_password_correspondence(tmp_path):
    source_tree(tmp_path, "http://127.0.0.1:9")
    with pytest.raises(ImportConflictError, match="旧用户名不同"):
        build_plan(tmp_path)
    plans = build_plan(tmp_path, allow_e3e3_b2_rename=True)
    account = plans[1].accounts[1]
    assert account.credentials == {"username": "张建雨", "password": "fake-e3-b2"}
    assert "fake-e3" not in repr(plans)
    assert "refund_password_ciphertext" not in plans[3].accounts[0].credentials
    pending = build_plan(tmp_path, skip_e3e3_b2=True)
    assert [account.name for account in pending[1].accounts] == ["gsb.b1.primary"]


def test_shared_web_config_actual_engine_and_idempotent_import(world):
    client, ctx, server, source = world
    repo = ctx["repo"]
    base = f"/repos/{repo}/projects"
    # An existing account/history must survive sync and import unchanged.
    response = client.post(
        f"{base}/gsb/environments",
        json={
            "env": "test",
            "api_hosts": {
                "gsb": f"http://127.0.0.1:{server.server_port}",
                "unified_login": f"http://127.0.0.1:{server.server_port}",
            },
        },
    )
    assert response.status_code == 201
    response = client.post(
        f"{base}/gsb/environments/test/accounts",
        json={
            "account_name": "gsb.b2.primary",
            "login_profile": "gsb_login",
            "credentials": {"username": "retained", "password": "retained-fake"},
        },
    )
    assert response.status_code == 201
    with SessionLocal() as db:
        prior = (
            db.query(AccountRow)
            .filter_by(project_id=f"{repo}/gsb", account_name="gsb.b2.primary")
            .one()
            .encrypted_credentials
        )
        plans = build_plan(source, allow_e3e3_b2_rename=True)
        preview = import_plan(db, plans, repo=repo, operator="tester", apply=False)
        assert preview["accounts_created"] == 6
        assert client.get(f"{base}/e3e3/environments").json() == []
        result = import_plan(db, plans, repo=repo, operator="tester", apply=True)
        assert result["accounts_created"] == 6
        again = import_plan(db, plans, repo=repo, operator="tester", apply=True)
        assert again["accounts_created"] == again["hosts_added"] == 0
        assert (
            db.query(AccountRow)
            .filter_by(project_id=f"{repo}/gsb", account_name="gsb.b2.primary")
            .one()
            .encrypted_credentials
            == prior
        )
    listed = [p for p in client.get("/projects?limit=10000").json() if p["repo"] == repo]
    assert len(listed) == 10
    assert len({p["workspace"]["platform"] for p in listed}) == 6
    assert all(p["envs"] == ["test"] for p in listed)
    # Shared write through website route is visible to GSB, with common revision checking.
    env = client.get(f"{base}/go2/environments/test").json()
    edited = client.put(
        f"{base}/go2/environments/test", json={"revision": env["revision"], "timeout_seconds": 2}
    )
    assert edited.status_code == 200
    assert (
        client.get(f"{base}/gsb/environments/test").json()["revision"] == edited.json()["revision"]
    )
    assert (
        client.put(
            f"{base}/gsb/environments/test",
            json={"revision": env["revision"], "timeout_seconds": 3},
        ).status_code
        == 409
    )
    identities = {}
    for key in (
        "gsb",
        "go2",
        "gsb_e3e3",
        "e3e3",
        "daifa_picker",
        "daifa_picker_e3e3",
        "admin_go2",
        "admin_go2_e3e3",
    ):
        response = client.post(
            f"{base}/{key}/assets/api.probe/run",
            json={"env": "test", "params": {}, "request_override": {"body": {"scope": key}}},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "success"
        identities[key] = result["auth"]["identity"]
        assert result["auth"]["session_source"] == "login"
        assert "retained-fake" not in response.text
        detail = client.get(f"{base}/{key}/execution-records/{result['record_id']}")
        assert detail.status_code == 200
        assert detail.json()["config_snapshot"]["workspace"]["project"] == (
            "e3e3" if "e3e3" in key else "go2"
        )
    logins = [event for event in server.events if event[0] in ("/site/login", "/form-login")]
    assert len(logins) == 8  # workspaces do not borrow one another's cached identity
    assert [event[1]["source"][0] for event in logins] == [
        "go2",
        "go2",
        "e3e3",
        "e3e3",
        "go2",
        "e3e3",
        "go2",
        "e3e3",
    ]
    assert [event[1]["username"][0] for event in logins] == [
        "retained",
        "18583220150",
        "张建雨",
        "泡泡象",
        "picker",
        "picker",
        "manager",
        "manager",
    ]
    assert identities["daifa_picker"] == "df_picker.default"
    # Pending auth has a specific failure; config remains editable, never a wrong fallback login.
    before = len(server.events)
    response = client.post(
        f"{base}/daifa_admin/assets/api.probe/run", json={"env": "test", "params": {}}
    )
    assert "待适配" in response.text
    assert len(server.events) == before
    with SessionLocal() as db:
        project = db.get(Project, f"{repo}/daifa_admin_e3e3")
        _, _, config = ensure_snapshot_dirs(app.state.repo_sync.config, project)
        resolved = resolve_run_config(
            db, project, "test", config, request_params={}, request_timeout=None
        )
        assert resolved.snapshot["workspace"]["configuration_project_id"] == f"{repo}/daifa_admin"
        assert set(resolved.auth.table.identities) == {"df_admin.default"}
    # Normal Web never falls back to the Git template for a missing environment.
    assert (
        client.post(
            f"{base}/e3e3/assets/api.probe/run", json={"env": "missing", "params": {}}
        ).status_code
        == 422
    )


def test_additive_schema_preserves_existing_account_and_history(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from testplat_control.database.models import ExecutionRecord, Repo
    from testplat_control.services.environment_store import create_account, create_environment

    monkeypatch.setattr(settings, "testplat_master_key", Fernet.generate_key().decode())
    engine = get_engine(str(tmp_path / "old.db"))
    init_engine_schema(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE workspace_bindings"))
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(Repo(key="main", branch="main"))
        db.flush()
        db.add(
            Project(
                id="main/gsb",
                repo="main",
                project_key="gsb",
                name="old",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        create_environment(
            db,
            project_id="main/gsb",
            env="test",
            api_hosts={"gsb": "http://localhost"},
            timeout_seconds=7,
            case_params={},
            enabled=True,
            operator="old",
        )
        create_account(
            db,
            project_id="main/gsb",
            env="test",
            account_name="gsb.b2.primary",
            display_name=None,
            business_role=None,
            login_profile="gsb_login",
            credentials={"username": "existing", "password": "existing-fake"},
            enabled=True,
            operator="old",
        )
        db.add(
            ExecutionRecord(
                id="old-run",
                project_id="main/gsb",
                asset_type="api",
                asset_id="api.old",
                status="success",
                start_time=now,
                result_json='{"retained": true}',
            )
        )
        db.commit()

    def snapshot():
        with engine.connect() as conn:
            return {
                table: conn.execute(text(f"SELECT * FROM {table}")).fetchall()
                for table in (
                    "projects",
                    "project_environments",
                    "test_accounts",
                    "execution_records",
                    "config_changes",
                )
            }

    before = snapshot()
    init_engine_schema(engine)
    assert snapshot() == before
    with Session(engine) as db:
        account = db.query(AccountRow).one()
        assert read_credentials(account) == {"username": "existing", "password": "existing-fake"}
        assert db.query(WorkspaceBinding).count() == 0
    engine.dispose()


def test_config_browser_uses_manifest_config_instead_of_shared_api_directory(tmp_path):
    from testplat_control.services.asset_service import AssetService

    assets = tmp_path / "shared-api"
    wrong = assets / "config/auth/_profiles.yaml"
    right = tmp_path / "e3e3-config/auth/_profiles.yaml"
    for path, source in ((wrong, "go2"), (right, "e3e3")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PROFILE.replace("source: go2", f"source: {source}"))
    service = AssetService(assets, right.parent.parent)
    tree = service.scan_assets()
    assert len([child for child in tree.children if child.id == "config"]) == 1
    node = service.get_asset("config.auth._profiles")
    assert node is not None
    assert "e3e3" in json.dumps(node.metadata)
    assert "go2" not in json.dumps(node.metadata)


def test_pending_profile_does_not_accept_inline_secret(tmp_path):
    from testplat_control.services.login_profiles import ProfileFileError, load_profile_catalog

    path = tmp_path / "auth/_profiles.yaml"
    path.parent.mkdir()
    path.write_text(
        yaml.safe_dump(
            {
                "identities": {
                    "pending": {
                        "unavailable": {
                            "reason": "Pending adapter",
                            "credentials": {"password": "inline-value"},
                        }
                    }
                }
            }
        )
    )
    with pytest.raises(ProfileFileError, match="待适配"):
        load_profile_catalog(tmp_path)


def test_failed_owner_preflight_does_not_partially_import(world):
    client, ctx, _, source = world
    from testplat_control.database.models import ProjectEnvironment

    with SessionLocal() as db:
        plans = build_plan(source, allow_e3e3_b2_rename=True)
        plans[-1].key = "absent"
        with pytest.raises(ImportConflictError, match="未同步"):
            import_plan(db, plans, repo=ctx["repo"], operator="tester", apply=True)
        assert (
            db.query(ProjectEnvironment)
            .filter(ProjectEnvironment.project_id.like(ctx["repo"] + "/%"))
            .count()
            == 0
        )
