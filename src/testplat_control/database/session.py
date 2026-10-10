"""数据库会话管理"""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

# 使用内存 SQLite 作为演示数据库
DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
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
    db_engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return sessionmaker(bind=db_engine, class_=Session)


def get_engine(db_path: str):
    """获取数据库引擎

    Args:
        db_path: SQLite 数据库文件路径

    Returns:
        SQLAlchemy Engine 对象
    """
    return create_engine(f"sqlite:///{db_path}", echo=False)
