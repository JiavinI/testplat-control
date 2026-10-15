"""审查打回项：文件库跨进程持久化，以及 revision 的真实并发冲突。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from testplat_control.config import settings
from testplat_control.database.models import (
    ConfigChange,
    Project,
    ProjectEnvironment,
    Repo,
    TestAccount,
)
from testplat_control.database.session import init_engine_schema, make_engine
from testplat_control.services import environment_store
from testplat_control.services.environment_store import (
    create_account,
    create_environment,
    update_account,
    update_environment,
)
from testplat_control.services.run_config import resolve_run_config

SECRET = "pw-persist-process-91"
ACCOUNT_SECRET = "pw-account-persist-91"


def _child_env(db_path: Path, key: str) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["TESTPLAT_MASTER_KEY"] = key
    env.pop("TESTPLAT_REPOS_FILE", None)
    return env


def _run_child(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """子进程沿用当前工作目录。脚本路径是绝对路径，不依赖某台机器的检出位置。"""
    return subprocess.run(
        [sys.executable, str(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_r1_file_database_survives_a_second_process(tmp_path: Path) -> None:
    """两个独立进程共用同一个文件库：第二个进程能读到并解密账号。"""
    db_path = tmp_path / "control.db"
    key = Fernet.generate_key().decode("ascii")
    env = _child_env(db_path, key)
    writer = tmp_path / "write_db.py"
    reader = tmp_path / "read_db.py"
    writer.write_text(
        f"""
from datetime import UTC, datetime
from testplat_control.database.models import Project, Repo
from testplat_control.database.session import SessionLocal
from testplat_control.services.environment_store import create_account, create_environment
from testplat_control.services.platform_auth import register_user

now = datetime.now(UTC).replace(tzinfo=None)
with SessionLocal() as db:
    db.add(Repo(key="main", branch="main"))
    db.commit()
    db.add(Project(
        id="main/demo", repo="main", project_key="demo", name="Demo",
        envs=[], archived=False, created_at=now, updated_at=now,
    ))
    db.commit()
    register_user(db, "alice", {SECRET!r})
    create_environment(
        db, project_id="main/demo", env="test",
        api_hosts={{"local": "http://127.0.0.1:9"}},
        timeout_seconds=None, case_params={{}}, enabled=True, operator="alice",
    )
    create_account(
        db, project_id="main/demo", env="test", account_name="gsb",
        display_name="采购员", business_role=None, login_profile="gsb_login",
        credentials={{"username": "buyer-user", "password": {ACCOUNT_SECRET!r}}},
        enabled=True, operator="alice",
    )
print("wrote")
""",
        encoding="utf-8",
    )
    reader.write_text(
        """
import json
from sqlalchemy import text
from testplat_control.database.session import SessionLocal
from testplat_control.services.crypto import decrypt_credentials

with SessionLocal() as db:
    users = db.execute(text("SELECT COUNT(*) FROM platform_users")).scalar()
    envs = db.execute(text("SELECT COUNT(*) FROM project_environments")).scalar()
    accounts = db.execute(text("SELECT COUNT(*) FROM test_accounts")).scalar()
    cipher = db.execute(text("SELECT encrypted_credentials FROM test_accounts")).scalar()
creds = decrypt_credentials(cipher)
print(json.dumps({
    "counts": [users, envs, accounts],
    "password": creds["password"],
    "username": creds["username"],
    "cipher_has_password": creds["password"] in cipher,
}))
""",
        encoding="utf-8",
    )
    wrote = _run_child(writer, env)
    assert wrote.returncode == 0, wrote.stderr
    assert db_path.is_file() and db_path.stat().st_size > 0
    read = _run_child(reader, env)
    assert read.returncode == 0, read.stderr
    payload = json.loads(read.stdout.strip().splitlines()[-1])
    assert payload["counts"] == [1, 1, 1]
    assert payload["password"] == ACCOUNT_SECRET
    assert payload["username"] == "buyer-user"
    assert payload["cipher_has_password"] is False


def _seed(factory: sessionmaker) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    db = factory()
    db.add(Repo(key="main", branch="main"))
    db.commit()
    db.add(
        Project(
            id="main/demo",
            repo="main",
            project_key="demo",
            name="Demo",
            envs=[],
            archived=False,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    create_environment(
        db,
        project_id="main/demo",
        env="test",
        api_hosts={"local": "http://127.0.0.1:9"},
        timeout_seconds=None,
        case_params={},
        enabled=True,
        operator="tester",
    )
    db.close()


def test_r2_concurrent_environment_update_conflicts(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'env.db'}")
    init_engine_schema(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    _seed(factory)

    recorded: list[tuple] = []
    barrier = threading.Barrier(2)
    real_get = environment_store.get_environment

    def blocking_get(db, project_id, env):  # noqa: ANN001
        row = real_get(db, project_id, env)
        barrier.wait(5)
        return row

    environment_store.get_environment = blocking_get
    lock = threading.Lock()

    def worker(seconds: float) -> None:
        db = factory()
        try:
            updated = update_environment(
                db,
                project_id="main/demo",
                env="test",
                expected_revision=1,
                operator="tester",
                fields={"timeout_seconds": seconds},
            )
            with lock:
                recorded.append(("ok", float(updated.timeout_seconds), int(updated.revision)))
        except HTTPException as exc:
            with lock:
                recorded.append(("err", exc.status_code))
        finally:
            db.close()

    threads = [
        threading.Thread(target=worker, args=(8.0,)),
        threading.Thread(target=worker, args=(9.0,)),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
    finally:
        environment_store.get_environment = real_get

    assert sorted(kind for kind, *_rest in recorded) == ["err", "ok"]
    assert any(item[0] == "err" and item[1] == 409 for item in recorded)
    winner = next(item for item in recorded if item[0] == "ok")
    db = factory()
    try:
        row = db.query(ProjectEnvironment).one()
        changes = db.query(ConfigChange).filter(ConfigChange.action == "update").all()
        assert int(row.revision) == 2
        assert float(row.timeout_seconds) == winner[1]
        assert len(changes) == 1
        assert changes[0].revision == 2
    finally:
        db.close()


def test_r2_concurrent_account_update_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "testplat_master_key", Fernet.generate_key().decode("ascii"))
    engine = make_engine(f"sqlite:///{tmp_path / 'acct.db'}")
    init_engine_schema(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    _seed(factory)
    db = factory()
    create_account(
        db,
        project_id="main/demo",
        env="test",
        account_name="gsb",
        display_name="初始",
        business_role=None,
        login_profile="gsb_login",
        credentials={"password": ACCOUNT_SECRET},
        enabled=True,
        operator="tester",
    )
    db.close()

    recorded: list[tuple] = []
    barrier = threading.Barrier(2)
    real_get = environment_store.get_environment

    def blocking_get(db, project_id, env):  # noqa: ANN001
        row = real_get(db, project_id, env)
        barrier.wait(5)
        return row

    environment_store.get_environment = blocking_get
    lock = threading.Lock()

    def worker(display_name: str) -> None:
        session = factory()
        try:
            updated = update_account(
                session,
                project_id="main/demo",
                env="test",
                name="gsb",
                expected_revision=1,
                operator="tester",
                fields={"display_name": display_name},
                credentials=None,
            )
            with lock:
                recorded.append(("ok", updated.display_name, int(updated.revision)))
        except HTTPException as exc:
            with lock:
                recorded.append(("err", exc.status_code))
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker, args=("甲",)),
        threading.Thread(target=worker, args=("乙",)),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
    finally:
        environment_store.get_environment = real_get

    assert sorted(item[0] for item in recorded) == ["err", "ok"]
    assert any(item[0] == "err" and item[1] == 409 for item in recorded)
    winner = next(item for item in recorded if item[0] == "ok")
    db = factory()
    try:
        account = db.query(TestAccount).one()
        env_row = db.query(ProjectEnvironment).one()
        updates = (
            db.query(ConfigChange)
            .filter(ConfigChange.action == "update", ConfigChange.object_type == "account")
            .all()
        )
        assert account.display_name == winner[1]
        assert int(account.revision) == 2
        # 创建账号把环境从 1 增到 2，只有胜出的更新再加 1。
        assert int(env_row.revision) == 3
        assert len(updates) == 1
        assert ACCOUNT_SECRET not in repr(updates)
    finally:
        db.close()


def _revisions_are_contiguous(start: int, revisions: list[int]) -> bool:
    return revisions == list(range(start, start + len(revisions)))


def test_r2a_concurrent_account_creates_each_bump_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两个不同账号并发创建都成功，环境 revision 各加一，修改记录不复用版本。"""
    monkeypatch.setattr(settings, "testplat_master_key", Fernet.generate_key().decode("ascii"))
    engine = make_engine(f"sqlite:///{tmp_path / 'create.db'}")
    init_engine_schema(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    _seed(factory)

    recorded: list[tuple] = []
    barrier = threading.Barrier(2)
    real_get = environment_store.get_environment

    def blocking_get(db, project_id, env):  # noqa: ANN001
        row = real_get(db, project_id, env)
        barrier.wait(5)
        return row

    environment_store.get_environment = blocking_get
    lock = threading.Lock()

    def worker(account_name: str) -> None:
        session = factory()
        try:
            create_account(
                session,
                project_id="main/demo",
                env="test",
                account_name=account_name,
                display_name=account_name,
                business_role=None,
                login_profile="gsb_login",
                credentials={"password": ACCOUNT_SECRET},
                enabled=True,
                operator="tester",
            )
            with lock:
                recorded.append(("ok", account_name))
        except HTTPException as exc:
            with lock:
                recorded.append(("err", exc.status_code))
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker, args=("buyer",)),
        threading.Thread(target=worker, args=("seller",)),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
    finally:
        environment_store.get_environment = real_get

    assert sorted(recorded) == [("ok", "buyer"), ("ok", "seller")]
    db = factory()
    try:
        env_row = db.query(ProjectEnvironment).one()
        creates = (
            db.query(ConfigChange)
            .filter(ConfigChange.object_type == "account", ConfigChange.action == "create")
            .order_by(ConfigChange.revision)
            .all()
        )
        assert int(env_row.revision) == 3
        assert [int(item.revision) for item in creates] == [2, 3]
        assert len({item.object_name for item in creates}) == 2
        assert ACCOUNT_SECRET not in repr(creates)
    finally:
        db.close()


def test_r2a_create_account_and_environment_update_do_not_reuse_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """创建账号与环境更新并发时，成功写入的环境版本不重复、不倒退。"""
    monkeypatch.setattr(settings, "testplat_master_key", Fernet.generate_key().decode("ascii"))
    engine = make_engine(f"sqlite:///{tmp_path / 'mix.db'}")
    init_engine_schema(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    _seed(factory)

    recorded: list[tuple] = []
    barrier = threading.Barrier(2)
    real_get = environment_store.get_environment

    def blocking_get(db, project_id, env):  # noqa: ANN001
        row = real_get(db, project_id, env)
        barrier.wait(5)
        return row

    environment_store.get_environment = blocking_get
    lock = threading.Lock()

    def create_worker() -> None:
        session = factory()
        try:
            create_account(
                session,
                project_id="main/demo",
                env="test",
                account_name="buyer",
                display_name="买家",
                business_role=None,
                login_profile="gsb_login",
                credentials={"password": ACCOUNT_SECRET},
                enabled=True,
                operator="tester",
            )
            with lock:
                recorded.append(("ok", "create"))
        except HTTPException as exc:
            with lock:
                recorded.append(("err", "create", exc.status_code))
        finally:
            session.close()

    def update_worker() -> None:
        session = factory()
        try:
            update_environment(
                session,
                project_id="main/demo",
                env="test",
                expected_revision=1,
                operator="tester",
                fields={"timeout_seconds": 8.0},
            )
            with lock:
                recorded.append(("ok", "update"))
        except HTTPException as exc:
            with lock:
                recorded.append(("err", "update", exc.status_code))
        finally:
            session.close()

    threads = [threading.Thread(target=create_worker), threading.Thread(target=update_worker)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
    finally:
        environment_store.get_environment = real_get

    assert ("ok", "create") in recorded
    assert all(item[0] == "ok" or (item[0] == "err" and item[2] == 409) for item in recorded)
    db = factory()
    try:
        env_row = db.query(ProjectEnvironment).one()
        touched = (
            db.query(ConfigChange)
            .filter(ConfigChange.revision > 1)
            .order_by(ConfigChange.revision)
            .all()
        )
        revisions = [int(item.revision) for item in touched]
        final = int(env_row.revision)
        assert final == 1 + len(touched)
        assert _revisions_are_contiguous(2, revisions)
        assert ACCOUNT_SECRET not in repr(touched)
    finally:
        db.close()


def _seed_gsb(factory: sessionmaker) -> None:
    db = factory()
    create_account(
        db,
        project_id="main/demo",
        env="test",
        account_name="gsb",
        display_name="初始",
        business_role=None,
        login_profile="gsb_login",
        credentials={"password": ACCOUNT_SECRET},
        enabled=True,
        operator="tester",
    )
    db.close()


@pytest.mark.parametrize("preload_environment", [False, True])
def test_r4_read_between_selects_is_not_a_mixed_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, preload_environment: bool
) -> None:
    """环境查询和账号查询之间提交账号修改时，不能拼出旧环境加新账号。"""
    monkeypatch.setattr(settings, "testplat_master_key", Fernet.generate_key().decode("ascii"))
    db_engine = make_engine(f"sqlite:///{tmp_path / 'r4.db'}")
    init_engine_schema(db_engine)
    factory = sessionmaker(bind=db_engine, autoflush=False)
    _seed(factory)
    _seed_gsb(factory)

    release = threading.Event()
    committed = threading.Event()
    opened = False
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            assert release.wait(5)
            session = factory()
            try:
                update_account(
                    session,
                    project_id="main/demo",
                    env="test",
                    name="gsb",
                    expected_revision=1,
                    operator="tester",
                    fields={"display_name": "已更新"},
                    credentials=None,
                )
            finally:
                session.close()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            committed.set()

    def before_account_select(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        del conn, cursor, parameters, context, executemany
        normalized = " ".join(statement.lower().split())
        if not normalized.startswith("select") or "test_accounts" not in normalized:
            return
        nonlocal opened
        if opened:
            return
        opened = True
        release.set()
        assert committed.wait(5)

    reader = factory()
    if preload_environment:
        preloaded = reader.query(ProjectEnvironment).filter_by(env="test").one()
        assert int(preloaded.revision) == 2
    project = reader.query(Project).one()
    event.listen(db_engine, "before_cursor_execute", before_account_select)
    worker = threading.Thread(target=writer)
    worker.start()
    try:
        resolved = resolve_run_config(
            reader,
            project,
            "test",
            tmp_path,
            request_params={},
            request_timeout=None,
        )
    finally:
        event.remove(db_engine, "before_cursor_execute", before_account_select)
        committed.set()
        worker.join(5)
        reader.close()

    assert not errors
    assert opened
    pair = (resolved.config_revision, resolved.account_revisions["gsb"])
    assert pair in {(2, 1), (3, 2)}
    saved = resolved.snapshot["accounts"][0]
    assert saved["revision"] == pair[1]
    assert resolved.snapshot["config_revision"] == pair[0]
    assert saved["display_name"] == ("初始" if pair == (2, 1) else "已更新")
    fresh = factory()
    try:
        assert int(fresh.query(ProjectEnvironment).one().revision) == 3
        assert int(fresh.query(TestAccount).one().revision) == 2
    finally:
        fresh.close()
