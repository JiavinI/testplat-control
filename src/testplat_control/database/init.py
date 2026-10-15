"""数据库初始化。"""

from sqlalchemy import create_engine

from .models import Base
from .schema_guard import assert_schema_compatible
from .session import prepare_engine


def init_database(db_path: str) -> None:
    """初始化数据库：检测旧结构后 create_all。

    Args:
        db_path: SQLite 数据库文件路径

    Raises:
        IncompatibleSchemaError: 已有旧表结构时
    """
    engine = prepare_engine(create_engine(f"sqlite:///{db_path}", echo=False))
    assert_schema_compatible(engine)
    Base.metadata.create_all(engine)
    engine.dispose()
