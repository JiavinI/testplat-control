"""数据库初始化"""
from sqlalchemy import create_engine

from .models import Base
from .session import prepare_engine


def init_database(db_path: str) -> None:
    """初始化数据库

    创建 SQLite 数据库文件并执行所有表的创建操作。

    Args:
        db_path: SQLite 数据库文件路径
    """
    engine = prepare_engine(create_engine(f"sqlite:///{db_path}", echo=False))
    Base.metadata.create_all(engine)
    engine.dispose()
