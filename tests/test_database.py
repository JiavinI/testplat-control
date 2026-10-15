"""数据库模型测试（Phase 4.0）。"""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from testplat_control.database.init import init_database
from testplat_control.database.models import ExecutionRecord, Project, Repo
from testplat_control.database.schema_guard import IncompatibleSchemaError, assert_schema_compatible
from testplat_control.database.session import create_session, get_engine


@pytest.fixture
def temp_db() -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "test.db")


class TestDatabaseInit:
    def test_init_database_creates_file(self, temp_db: str) -> None:
        init_database(temp_db)
        assert Path(temp_db).exists()

    def test_init_database_creates_tables(self, temp_db: str) -> None:
        init_database(temp_db)
        engine = get_engine(temp_db)
        inspector = __import__("sqlalchemy").inspect(engine)
        tables = inspector.get_table_names()
        assert "projects" in tables
        assert "execution_records" in tables
        assert "repos" in tables


class TestSchemaGuard:
    def test_rejects_old_project_columns(self, temp_db: str) -> None:
        engine = get_engine(temp_db)
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE projects ("
                "id VARCHAR(36) PRIMARY KEY, name VARCHAR(255), env VARCHAR(50), "
                "assets_root VARCHAR(500), config_root VARCHAR(500), "
                "created_at DATETIME, updated_at DATETIME)"
            )
        with pytest.raises(IncompatibleSchemaError):
            assert_schema_compatible(engine)


class TestProjectModel:
    def test_insert_project(self, temp_db: str) -> None:
        init_database(temp_db)
        session = create_session(temp_db)()
        session.add(Repo(key="main", branch="main", current_sha="a" * 40, last_sync_result="ok"))
        session.commit()
        now = datetime.now()
        session.add(
            Project(
                id="main/demo",
                repo="main",
                project_key="demo",
                name="Demo",
                envs=["test"],
                default_env="test",
                archived=False,
                commit_sha="a" * 40,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
        row = session.query(Project).filter(Project.id == "main/demo").first()
        assert row is not None
        assert row.project_key == "demo"
        assert row.envs == ["test"]
        session.close()


class TestExecutionRecordModel:
    def test_insert_with_env_and_sha(self, temp_db: str) -> None:
        init_database(temp_db)
        session = create_session(temp_db)()
        session.add(Repo(key="main", branch="main"))
        session.flush()
        now = datetime.now()
        session.add(
            Project(
                id="main/demo",
                repo="main",
                project_key="demo",
                name="Demo",
                envs=["test"],
                default_env="test",
                archived=False,
                commit_sha="b" * 40,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
        session.add(
            ExecutionRecord(
                id="rec-1",
                project_id="main/demo",
                asset_type="api",
                asset_id="api.x",
                status="success",
                start_time=now,
                end_time=now,
                duration=0.1,
                result_json="{}",
                env="test",
                repo="main",
                commit_sha="b" * 40,
                operator=None,
            )
        )
        session.commit()
        row = session.query(ExecutionRecord).first()
        assert row.env == "test"
        assert row.commit_sha == "b" * 40
        assert row.operator is None
        session.close()

    def test_fk_requires_project(self, temp_db: str) -> None:
        init_database(temp_db)
        session = create_session(temp_db)()
        now = datetime.now()
        session.add(
            ExecutionRecord(
                id="rec-2",
                project_id="missing/x",
                asset_type="api",
                asset_id="api.x",
                status="success",
                start_time=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.close()
