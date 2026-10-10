"""数据库会话管理"""
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base

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

# 创建所有表
Base.metadata.create_all(engine)


def get_db() -> Session:
    """获取数据库会话的依赖注入函数

    Yields:
        Session: SQLAlchemy 数据库会话
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_session(db_path: str) -> sessionmaker:
    """创建数据库会话工厂

    Args:
        db_path: SQLite 数据库文件路径

    Returns:
        sessionmaker 工厂对象
    """
    db_engine = prepare_engine(create_engine(f"sqlite:///{db_path}", echo=False))
    return sessionmaker(bind=db_engine, class_=Session)


def get_engine(db_path: str):
    """获取数据库引擎

    Args:
        db_path: SQLite 数据库文件路径

    Returns:
        SQLAlchemy Engine 对象
    """
    return prepare_engine(create_engine(f"sqlite:///{db_path}", echo=False))
