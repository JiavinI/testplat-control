"""资产参数的保存、隔离、兼容合成和真实 Engine 请求验收。"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

from testplat_control.database.models import (
    Base,
    ConfigChange,
    ExecutionRecord,
    ParameterSet,
    Project,
    ProjectEnvironment,
    Repo,
    WorkspaceBinding,
)
from testplat_control.database.models import (
    TestAccount as AccountRow,
)
from testplat_control.database.session import SessionLocal, get_engine, init_engine_schema
from testplat_control.services.parameter_sets import begin_snapshot, save_parameter_set
from tests.repo_support import commit_all, sync_repo, write_tree
from tests.test_phase4_1a_fake_target import _env
from tests.test_phase4_1a_fake_target import master_key as master_key
from tests.test_phase4_1a_fake_target import world as world


def _prepare(world):
    ctx, client = world["ctx"], world["client"]
    write_tree(
        ctx["repo_path"],
        {
            "projects/demo/api/gsb/parameters.yaml": """\
id: api.gsb.parameters
type: api
name: Parameter fixture
method: POST
host: gsb
url: /balance
auth: none
request:
  type: json
  inputs:
    keyword: {type: string, required: true, default: git}
    count: {type: number, default: 3}
    active: {type: boolean, default: true}
  body:
    keyword: "${keyword}"
    count: "${count}"
    active: "${active}"
success: {status_code: 200}
""",
            "projects/demo/scenarios/gsb/parameters.case.yaml": """\
schema_version: "0.2"
id: case.gsb.parameters
name: Parameter case fixture
params: {keyword: git-case, filter: {a: 1, b: 2}, active: true}
steps:
  - step_id: send
    type: api
    api_id: api.gsb.parameters
    params:
      keyword: "${params.keyword}"
      count: "${params.filter.a}"
      active: "${params.active}"
""",
        },
    )
    commit_all(ctx["repo_path"], "parameter fixtures")
    sync_repo(client, ctx["repo"])
    base = ctx["base"]
    for env in ("test", "pre"):
        _env(
            client,
            base,
            world["login"].base,
            world["business"].base,
            env=env,
            case_params={"keyword": "shared", "active": True},
        )
    return client, base


def _context(client, base, kind="api", asset="api.gsb.parameters", env="test"):
    response = client.get(f"{base}/parameter-sets/{kind}/{asset}", params={"env": env})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def _save(
    client,
    base,
    values,
    scope="asset_default",
    *,
    kind="api",
    asset="api.gsb.parameters",
    env="test",
    context=None,
):
    context = context or _context(client, base, kind, asset, env)
    return client.put(
        f"{base}/parameter-sets/{kind}/{asset}/{scope}",
        params={"env": env} if scope == "environment_override" else {},
        json={
            "values": values,
            "revision": context[scope]["revision"],
            "commit_sha": context["commit_sha"],
        },
    )


def _body(world):
    return json.loads(
        [e["body"] for e in world["business"].capture.snapshot() if e["path"] == "/balance"][-1]
    )


def test_saved_parameters_layers_real_engine_and_immutable_history(world):
    client, base = _prepare(world)
    assert _save(client, base, {"keyword": "saved", "count": 0, "active": False}).status_code == 200
    assert (
        _save(
            client, base, {"keyword": "env-only", "active": False}, "environment_override"
        ).status_code
        == 200
    )
    context = _context(client, base)
    assert context["effective"] == {"keyword": "env-only", "count": 0, "active": False}
    assert context["sources"]["keyword"] == "environment_override"
    assert _context(client, base, env="pre")["effective"]["keyword"] == "shared"
    response = client.post(
        f"{base}/assets/api.gsb.parameters/run", json={"env": "test", "params": {}}
    )
    assert response.status_code == 200 and response.json()["status"] == "success"
    assert _body(world) == {"keyword": "env-only", "count": "0", "active": "False"}
    with SessionLocal() as db:
        from testplat_control.database.models import ExecutionRecord

        before = db.get(ExecutionRecord, response.json()["record_id"]).config_snapshot["parameters"]
    assert before["effective"] == context["effective"]
    assert before["revisions"] == {"asset_default": 1, "environment_override": 1}
    assert _save(client, base, {}, "environment_override").status_code == 200
    assert _context(client, base)["effective"]["keyword"] == "shared"
    result = client.post(
        f"{base}/assets/api.gsb.parameters/run",
        json={"env": "test", "params": {"keyword": "", "active": False}},
    )
    assert result.status_code == 200
    assert _body(world)["keyword"] == ""
    with SessionLocal() as db:
        from testplat_control.database.models import ExecutionRecord

        assert (
            db.get(ExecutionRecord, response.json()["record_id"]).config_snapshot["parameters"]
            == before
        )
    # 原共享配置未迁移或清空，另一 API 也不继承当前资产保存值。
    assert client.get(f"{base}/environments/test").json()["case_params"]["keyword"] == "shared"
    other = _context(client, base, asset="api.gsb.anon")
    assert other["asset_default"]["values"] == {}


def test_case_parameters_shallow_replace_null_and_temporary(world):
    client, base = _prepare(world)
    options = {"kind": "case", "asset": "case.gsb.parameters"}
    assert _save(client, base, {"filter": {"a": 5}, "optional": None}, **options).status_code == 200
    assert (
        _save(
            client, base, {"filter": {"a": 0}, "active": False}, "environment_override", **options
        ).status_code
        == 200
    )
    context = _context(client, base, **options)
    assert context["effective"]["filter"] == {"a": 0}
    assert context["effective"]["optional"] is None
    response = client.post(
        f"{base}/cases/case.gsb.parameters/run", json={"env": "test", "params": {"keyword": "once"}}
    )
    assert response.status_code == 200 and response.json()["status"] == "success"
    assert _body(world) == {"keyword": "once", "count": 0, "active": False}
    with SessionLocal() as db:
        from testplat_control.database.models import ExecutionRecord

        snapshot = db.get(ExecutionRecord, response.json()["record_id"]).config_snapshot[
            "parameters"
        ]
    assert snapshot["effective"]["filter"] == {"a": 0}
    assert snapshot["effective"]["optional"] is None
    assert snapshot["sources"]["keyword"] == "temporary"


def test_revision_commit_validation_and_no_secret_storage(world):
    client, base = _prepare(world)
    original = _context(client, base)
    assert _save(client, base, {"count": 0}, context=original).status_code == 200
    assert _save(client, base, {"count": 2}, context=original).status_code == 409
    assert _save(client, base, {}, "environment_override").status_code == 200
    stale = _context(client, base)
    assert _save(client, base, {}, context=stale).status_code == 200
    assert _save(client, base, {"count": 2}, context=stale).status_code == 409
    for values in ({"count": False}, {"missing": 2}, {"count": None}):
        assert _save(client, base, values).status_code == 422
    for values in ({"password": "fake-secret"}, {"filter": {"Cookie": "fake-secret"}}):
        blocked = _save(client, base, values, kind="case", asset="case.gsb.parameters")
        assert blocked.status_code == 422 and "fake-secret" not in blocked.text
    assert client.get(f"{base}/parameter-sets/api/api.not.found?env=test").status_code == 404
    assert client.get(f"{base}/parameter-sets/case/case.not.found?env=test").status_code == 404
    assert (
        client.get(f"{base}/parameter-sets/api/api.gsb.parameters?env=missing").status_code == 404
    )
    write_tree(world["ctx"]["repo_path"], {"README.md": "new commit"})
    commit_all(world["ctx"]["repo_path"])
    sync_repo(client, world["ctx"]["repo"])
    assert _save(client, base, {}, context=original).status_code == 409
    with SessionLocal() as db:
        changes = (
            db.query(ConfigChange)
            .filter(
                ConfigChange.project_id == world["ctx"]["project_id"],
                ConfigChange.object_type == "parameter_set",
            )
            .all()
        )
        assert len(changes) == 3
        assert all(c.field_names == ["values"] for c in changes)


def test_shared_configuration_owner_does_not_share_asset_parameters(world):
    client, base = _prepare(world)
    ctx = world["ctx"]
    path = "projects/other/api/gsb/parameters.yaml"
    write_tree(
        ctx["repo_path"],
        {path: (ctx["repo_path"] / "projects/demo/api/gsb/parameters.yaml").read_text()},
    )
    commit_all(ctx["repo_path"])
    sync_repo(client, ctx["repo"])
    other = f"/repos/{ctx['repo']}/projects/other"
    with SessionLocal() as db:
        db.add(
            WorkspaceBinding(
                project_id=f"{ctx['repo']}/other",
                platform="website",
                platform_name="Website",
                business_project="go2",
                business_project_name="GO2",
                configuration_project_id=ctx["project_id"],
            )
        )
        db.commit()
    assert _save(client, base, {"count": 5}).status_code == 200
    assert _context(client, other)["asset_default"]["values"] == {}
    assert _save(client, other, {"count": 9}).status_code == 200
    assert _context(client, base)["effective"]["count"] == 5
    response = client.post(f"{other}/assets/api.gsb.parameters/run", json={"env": "test"})
    assert response.status_code == 200
    assert _body(world)["count"] == "9"
    assert (
        client.get(f"{other}/environments/test").json()
        == client.get(f"{base}/environments/test").json()
    )


def test_parameter_changes_after_freeze_only_affect_next_run(world, monkeypatch):
    from testplat_control.adapters.package_engine import PackageEngineAdapter

    client, base = _prepare(world)
    assert _save(client, base, {"count": 4}).status_code == 200
    original = PackageEngineAdapter.execute
    changed = False

    async def execute(self, request):
        nonlocal changed
        if not changed:
            changed = True
            # 进入 Engine 时读取事务已结束，新提交不能改写这次请求／历史快照。
            with SessionLocal() as db:
                begin_snapshot(db, write=True)
                project = db.get(Project, world["ctx"]["project_id"])
                save_parameter_set(
                    db,
                    project=project,
                    asset_type="api",
                    asset_id="api.gsb.parameters",
                    scope="asset_default",
                    env_key="",
                    values={"count": 8},
                    revision=1,
                    commit_sha=project.commit_sha,
                    operator="other",
                )
        return await original(self, request)

    monkeypatch.setattr(PackageEngineAdapter, "execute", execute)
    response = client.post(f"{base}/assets/api.gsb.parameters/run", json={"env": "test"})
    assert response.status_code == 200
    assert _body(world)["count"] == "4"
    with SessionLocal() as db:
        record = db.get(ExecutionRecord, response.json()["record_id"])
        assert record.config_snapshot["parameters"]["effective"]["count"] == 4
        assert record.config_snapshot["parameters"]["revisions"]["asset_default"] == 1
    assert _context(client, base)["effective"]["count"] == 8


def test_file_database_upgrade_and_two_writers(tmp_path: Path):
    engine = get_engine(str(tmp_path / "isolated.db"))
    # 模拟升级前的完整库，仅缺新增参数表；原行必须逐字段保留。
    Base.metadata.create_all(
        engine, tables=[t for t in Base.metadata.sorted_tables if t.name != "parameter_sets"]
    )
    sessions = sessionmaker(bind=engine)
    now = datetime.now(UTC).replace(tzinfo=None)
    with sessions() as db:
        db.add(Repo(key="repo", branch="main"))
        db.commit()
        db.add(
            Project(
                id="repo/demo",
                repo="repo",
                project_key="demo",
                name="demo",
                envs=[],
                archived=False,
                commit_sha="a" * 40,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        db.add(
            ProjectEnvironment(
                id="env",
                project_id="repo/demo",
                env="test",
                enabled=True,
                api_hosts={"local": "http://127.0.0.1:9"},
                case_params={"count": 2},
                revision=7,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        db.add(
            AccountRow(
                id="account",
                project_id="repo/demo",
                env="test",
                account_name="primary",
                login_profile="login",
                encrypted_credentials="fake-opaque-ciphertext",
                enabled=True,
                revision=3,
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            ExecutionRecord(
                id="history",
                project_id="repo/demo",
                asset_type="api",
                asset_id="api.demo",
                status="success",
                start_time=now,
                config_snapshot={"parameters": {"count": 2}},
            )
        )
        db.commit()
        existing_tables = inspect(engine).get_table_names()
        before = {
            table: db.execute(text(f'SELECT * FROM "{table}"')).all() for table in existing_tables
        }
    init_engine_schema(engine)
    init_engine_schema(engine)
    assert "parameter_sets" in inspect(engine).get_table_names()
    with sessions() as db:
        assert {
            table: db.execute(text(f'SELECT * FROM "{table}"')).all() for table in existing_tables
        } == before
    barrier = threading.Barrier(2)
    results = []

    def writer():
        with sessions() as db:
            barrier.wait()
            try:
                begin_snapshot(db, write=True)
                project = db.get(Project, "repo/demo")
                save_parameter_set(
                    db,
                    project=project,
                    asset_type="api",
                    asset_id="api.demo",
                    scope="asset_default",
                    env_key="",
                    values={"count": 0},
                    revision=0,
                    commit_sha="a" * 40,
                    operator="tester",
                )
                results.append(200)
            except HTTPException as exc:
                results.append(exc.status_code)

    threads = [threading.Thread(target=writer) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert sorted(results) == [200, 409]
    with sessions() as db:
        assert db.query(ParameterSet).count() == 1
    engine.dispose()
    reopened = get_engine(str(tmp_path / "isolated.db"))
    with sessionmaker(bind=reopened)() as db:
        assert db.query(ParameterSet).one().values == {"count": 0}
    reopened.dispose()
