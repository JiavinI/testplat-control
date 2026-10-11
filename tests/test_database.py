"""数据库模型测试"""
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from testplat_control.database.init import init_database
from testplat_control.database.models import ExecutionRecord, Project
from testplat_control.database.session import create_session, get_engine


@pytest.fixture
def temp_db() -> str:
    """创建临时数据库

    Returns:
        临时数据库文件路径
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        yield db_path


class TestDatabaseInit:
    """数据库初始化测试"""

    def test_init_database_creates_file(self, temp_db: str) -> None:
        """测试数据库初始化创建文件"""
        init_database(temp_db)
        assert Path(temp_db).exists()

    def test_init_database_creates_tables(self, temp_db: str) -> None:
        """测试数据库初始化创建表"""
        init_database(temp_db)
        engine = get_engine(temp_db)
        inspector = __import__("sqlalchemy").inspect(engine)
        tables = inspector.get_table_names()
        assert "projects" in tables
        assert "execution_records" in tables


class TestProjectModel:
    """Project 模型测试"""

    def test_insert_project(self, temp_db: str) -> None:
        """测试插入 Project 记录"""
        init_database(temp_db)
        session_factory = create_session(temp_db)
        session = session_factory()

        project = Project(
            id=str(uuid.uuid4()),
            name="test_project",
            env="test",
            assets_root="/path/to/assets",
            config_root="/path/to/config",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(project)
        session.commit()

        retrieved = session.query(Project).filter(Project.name == "test_project").first()
        assert retrieved is not None
        assert retrieved.name == "test_project"
        assert retrieved.env == "test"
        session.close()

    def test_project_unique_name(self, temp_db: str) -> None:
        """测试 Project name 唯一性"""
        init_database(temp_db)
        session_factory = create_session(temp_db)
        session = session_factory()

        project1 = Project(
            id=str(uuid.uuid4()),
            name="unique_project",
            env="test",
            assets_root="/path/to/assets",
            config_root="/path/to/config",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(project1)
        session.commit()

        project2 = Project(
            id=str(uuid.uuid4()),
            name="unique_project",
            env="staging",
            assets_root="/path/to/assets2",
            config_root="/path/to/config2",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(project2)

        with pytest.raises(Exception):  # IntegrityError
            session.commit()

        session.close()

    def test_project_repr(self, temp_db: str) -> None:
        """测试 Project __repr__ 方法"""
        now = datetime.now()
        project = Project(
            id="test-id",
            name="test_project",
            env="test",
            assets_root="/path/to/assets",
            config_root="/path/to/config",
            created_at=now,
            updated_at=now,
        )
        repr_str = repr(project)
        assert "Project" in repr_str
        assert "test_project" in repr_str
        assert "test" in repr_str


class TestExecutionRecordModel:
    """ExecutionRecord 模型测试"""

    def test_insert_execution_record(self, temp_db: str) -> None:
        """测试插入 ExecutionRecord 记录"""
        init_database(temp_db)
        session_factory = create_session(temp_db)
        session = session_factory()

        # 先插入 Project
        project_id = str(uuid.uuid4())
        project = Project(
            id=project_id,
            name="test_project",
            env="test",
            assets_root="/path/to/assets",
            config_root="/path/to/config",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(project)
        session.commit()

        # 插入 ExecutionRecord
        record = ExecutionRecord(
            id=str(uuid.uuid4()),
            project_id=project_id,
            asset_type="api",
            asset_id="test_api_001",
            status="success",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration=1.5,
            result_json='{"result": "ok"}',
        )
        session.add(record)
        session.commit()

        retrieved = (
            session.query(ExecutionRecord)
            .filter(ExecutionRecord.asset_id == "test_api_001")
            .first()
        )
        assert retrieved is not None
        assert retrieved.asset_type == "api"
        assert retrieved.status == "success"
        assert retrieved.duration == 1.5
        session.close()

    def test_execution_record_foreign_key(self, temp_db: str) -> None:
        """测试 ExecutionRecord 外键约束"""
        init_database(temp_db)
        session_factory = create_session(temp_db)
        session = session_factory()

        # 尝试插入不存在的 project_id
        record = ExecutionRecord(
            id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),  # 不存在的 project_id
            asset_type="api",
            asset_id="test_api_001",
            status="success",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration=1.5,
        )
        session.add(record)

        with pytest.raises(Exception):  # IntegrityError
            session.commit()

        session.close()

    def test_execution_record_repr(self, temp_db: str) -> None:
        """测试 ExecutionRecord __repr__ 方法"""
        now = datetime.now()
        record = ExecutionRecord(
            id="record-id",
            project_id="project-id",
            asset_type="case",
            asset_id="test_case_001",
            status="failed",
            start_time=now,
            end_time=now,
        )
        repr_str = repr(record)
        assert "ExecutionRecord" in repr_str
        assert "project-id" in repr_str
        assert "case" in repr_str
        assert "failed" in repr_str


class TestQueryRecords:
    """查询记录测试"""

    def test_query_projects(self, temp_db: str) -> None:
        """测试查询 Project 记录"""
        init_database(temp_db)
        session_factory = create_session(temp_db)
        session = session_factory()

        # 插入多条记录
        for i in range(3):
            project = Project(
                id=str(uuid.uuid4()),
                name=f"project_{i}",
                env="test",
                assets_root=f"/path/to/assets{i}",
                config_root=f"/path/to/config{i}",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            session.add(project)
        session.commit()

        # 查询所有
        projects = session.query(Project).all()
        assert len(projects) == 3

        # 条件查询
        project = session.query(Project).filter(Project.name == "project_1").first()
        assert project is not None
        assert project.name == "project_1"

        session.close()

    def test_query_execution_records(self, temp_db: str) -> None:
        """测试查询 ExecutionRecord 记录"""
        init_database(temp_db)
        session_factory = create_session(temp_db)
        session = session_factory()

        # 插入 Project
        project_id = str(uuid.uuid4())
        project = Project(
            id=project_id,
            name="test_project",
            env="test",
            assets_root="/path/to/assets",
            config_root="/path/to/config",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(project)
        session.commit()

        # 插入多条 ExecutionRecord
        for i in range(3):
            record = ExecutionRecord(
                id=str(uuid.uuid4()),
                project_id=project_id,
                asset_type="api" if i % 2 == 0 else "case",
                asset_id=f"test_asset_{i}",
                status="success" if i % 2 == 0 else "failed",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration=float(i + 1),
            )
            session.add(record)
        session.commit()

        # 查询所有
        records = session.query(ExecutionRecord).all()
        assert len(records) == 3

        # 条件查询
        success_records = (
            session.query(ExecutionRecord).filter(ExecutionRecord.status == "success").all()
        )
        assert len(success_records) == 2

        # 按 project_id 查询
        project_records = (
            session.query(ExecutionRecord).filter(ExecutionRecord.project_id == project_id).all()
        )
        assert len(project_records) == 3

        session.close()
