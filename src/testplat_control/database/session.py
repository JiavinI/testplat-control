"""数据库会话管理。

连接串来自 ``settings.database_url``（环境变量 ``DATABASE_URL``）。
默认 ``sqlite:///:memory:`` 只给测试和未配置的本地进程；文件 URL 会真正落盘。
内存库用 StaticPool，否则每次连接都是空库。文件库不用 StaticPool，以便多进程打开同一文件。
"""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from testplat_control.config import settings

from .models import Base
from .schema_guard import assert_schema_compatible

# 与配置默认值一致，供尚未读配置的旧调用辨认内存库。实际引擎以 settings 为准。
DATABASE_URL = "sqlite:///:memory:"


def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """打开 SQLite 外键，并在锁冲突时等待，而不是立刻失败。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def prepare_engine(db_engine: Engine) -> Engine:
    """为 SQLite 引擎登记外键开关。"""
    if db_engine.dialect.name == "sqlite":
        event.listen(db_engine, "connect", enable_sqlite_foreign_keys)
    return db_engine


def _is_memory_url(url: str) -> bool:
    return ":memory:" in url


def make_engine(url: str) -> Engine:
    """按 URL 建引擎。内存库固定一条连接；文件库每个会话可以各自连接。"""
    kwargs: dict = {"echo": False}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if _is_memory_url(url):
            kwargs["poolclass"] = StaticPool
    return prepare_engine(create_engine(url, **kwargs))


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 已有旧表时这里失败并提示删库，不会 DROP。空库则建当前表。
assert_schema_compatible(engine)
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
