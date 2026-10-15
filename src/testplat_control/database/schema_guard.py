"""启动时检测旧表结构；不兼容则清晰报错，提示删除数据库文件。"""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

OLD_PROJECT_COLUMNS = frozenset({"assets_root", "config_root"})
REQUIRED_PROJECT_COLUMNS = frozenset({"repo", "project_key", "envs", "archived"})
REQUIRED_EXEC_COLUMNS = frozenset({"env", "repo", "commit_sha", "operator"})

SCHEMA_HINT = (
    "数据库表结构与 Phase 4.0 不兼容（项目已改为 Git 清单驱动）。"
    "请删除当前 SQLite 数据库文件后重启；开发期数据可接受重建。"
)


class IncompatibleSchemaError(RuntimeError):
    """旧库结构无法自动迁移。"""


def assert_schema_compatible(engine: Engine) -> None:
    """若 ``projects`` 仍含旧列或缺少新列，抛出 ``IncompatibleSchemaError``。

    空库（尚无表）视为兼容，由 ``create_all`` 建新表。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "projects" not in tables:
        return

    project_cols = {col["name"] for col in inspector.get_columns("projects")}
    if project_cols & OLD_PROJECT_COLUMNS:
        raise IncompatibleSchemaError(SCHEMA_HINT)
    if not REQUIRED_PROJECT_COLUMNS.issubset(project_cols):
        raise IncompatibleSchemaError(SCHEMA_HINT)

    if "execution_records" in tables:
        exec_cols = {col["name"] for col in inspector.get_columns("execution_records")}
        if not REQUIRED_EXEC_COLUMNS.issubset(exec_cols):
            raise IncompatibleSchemaError(SCHEMA_HINT)

    if "repos" not in tables:
        raise IncompatibleSchemaError(SCHEMA_HINT)
