"""数据库会话管理。"""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base
from .schema_guard import assert_schema_compatible

# 使用内存 SQLite 作为演示数据库
DATABASE_URL = "sqlite:///:memory:"


def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """打开 SQLite 外键约束。默认关闭，ExecutionRecord.project_id 否则不会生效。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def prepare_engine(db_engine: Engine) -> Engine:
    """为 SQLite 引擎登记外键开关。"""
    if db_engine.dialect.name == "sqlite":
        event.listen(db_engine, "connect", enable_sqlite_foreign_keys)
    return db_engine


# 内存库按连接隔离。StaticPool 让各请求共用 create_all 建好的同一份表，
# 否则执行记录写入后再次查询会落到空库。
engine = prepare_engine(
    create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 空内存库：先 create_all。若将来改为文件库且已有旧表，create_all 不会改列，
# 需在启动路径调用 assert_schema_compatible。
Base.metadata.create_all(engine)


def get_db() -> Session:
    """获取数据库会话的依赖注入函数。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_session(db_path: str) -> sessionmaker:
    """创建数据库会话工厂。"""
    db_engine = prepare_engine(create_engine(f"sqlite:///{db_path}", echo=False))
    return sessionmaker(bind=db_engine, class_=Session)


def get_engine(db_path: str):
    """获取数据库引擎。"""
    return prepare_engine(create_engine(f"sqlite:///{db_path}", echo=False))


def init_engine_schema(db_engine: Engine) -> None:
    """对文件库：检测旧结构 → create_all。"""
    assert_schema_compatible(db_engine)
    Base.metadata.create_all(db_engine)
