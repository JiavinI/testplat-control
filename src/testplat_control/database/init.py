"""数据库初始化。"""

from .session import init_engine_schema, make_engine


def init_database(db_path: str) -> None:
    """初始化文件库：与进程启动相同，先检测旧结构再 create_all。

    Args:
        db_path: SQLite 数据库文件路径

    Raises:
        IncompatibleSchemaError: 已有旧表结构时
    """
    engine = make_engine(f"sqlite:///{db_path}")
    try:
        init_engine_schema(engine)
    finally:
        engine.dispose()
