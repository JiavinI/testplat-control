"""资产参数存储、覆盖与冻结；不迁移兼容共享环境值，不读取账号凭据。"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from testplat_control.database.models import ConfigChange, ParameterSet, Project

AssetType = Literal["api", "case"]
Scope = Literal["asset_default", "environment_override"]
CONFLICT = "参数集版本冲突，请刷新后再保存"
SENSITIVE = re.compile(
    r"password|passwd|pwd|secret|token|cookie|authorization|master.?key|api[-_]?key", re.I
)


def begin_snapshot(db: Session, *, write: bool = False) -> None:
    """pysqlite 的 SELECT 默认不 BEGIN，显式开启以保证跨表一致读取。

    保存用 IMMEDIATE，串行化提交 SHA 校验和 CAS；运行仅持有短读取事务，
    进入 Engine 前由既有 release_read_transaction 结束。
    """
    connection = db.connection()
    if connection.dialect.name == "sqlite":
        driver = connection.connection.driver_connection
        if not driver.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")


def validate_values(value: object) -> dict[str, Any]:
    def visit(node: object) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if not isinstance(key, str) or SENSITIVE.search(key):
                    raise ValueError
                visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    try:
        if not isinstance(value, dict):
            raise ValueError
        visit(value)
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError, RecursionError):
        raise HTTPException(
            status_code=422, detail="请输入普通业务参数 JSON 对象；凭据请在测试账号中维护"
        ) from None


def redact_parameters(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "******" if SENSITIVE.search(str(key)) else redact_parameters(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_parameters(item) for item in value]
    return deepcopy(value)


def read_parameter_layers(
    db: Session,
    *,
    project_id: str,
    asset_type: str,
    asset_id: str,
    env: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]]:
    rows = (
        db.query(ParameterSet)
        .filter(
            ParameterSet.project_id == project_id,
            ParameterSet.asset_type == asset_type,
            ParameterSet.asset_id == asset_id,
            ParameterSet.env_key.in_(["", env]),
        )
        .execution_options(populate_existing=True)
        .all()
    )
    values = {row.scope: deepcopy(row.values or {}) for row in rows}
    revisions = {row.scope: int(row.revision) for row in rows}
    return values.get("asset_default", {}), values.get("environment_override", {}), revisions


def compose_parameters(
    git: dict[str, Any],
    saved: dict[str, Any],
    shared: dict[str, Any],
    environment: dict[str, Any],
    temporary: dict[str, Any],
    *,
    names: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    effective: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for source, layer in [
        ("git", git),
        ("asset_default", saved),
        ("shared_environment", shared),
        ("environment_override", environment),
        ("temporary", temporary),
    ]:
        for name, value in layer.items():
            # 显式未知输入保留给既有运行预检拒绝，不能静默丢掉。
            if names is None or name in names or source == "temporary":
                effective[name] = deepcopy(value)
                sources[name] = source
    return effective, sources


def save_parameter_set(
    db: Session,
    *,
    project: Project,
    asset_type: AssetType,
    asset_id: str,
    scope: Scope,
    env_key: str,
    values: dict[str, Any],
    revision: int,
    commit_sha: str,
    operator: str,
) -> dict[str, Any]:
    """调用方已校验资产与所属环境。整份替换，空对象保留行及 revision。"""
    payload = validate_values(values)
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        # scalar 查询不使用路由之前缓存的 Project 对象。
        current_sha = db.query(Project.commit_sha).filter(Project.id == project.id).scalar()
        if current_sha != commit_sha:
            raise HTTPException(status_code=409, detail="资产版本已变化，请刷新后再保存")
        row = (
            db.query(ParameterSet)
            .filter(
                ParameterSet.project_id == project.id,
                ParameterSet.asset_type == asset_type,
                ParameterSet.asset_id == asset_id,
                ParameterSet.scope == scope,
                ParameterSet.env_key == env_key,
            )
            .execution_options(populate_existing=True)
            .first()
        )
        if row is None:
            if revision != 0:
                raise HTTPException(status_code=409, detail=CONFLICT)
            new_revision = 1
            db.add(
                ParameterSet(
                    id=str(uuid4()),
                    project_id=project.id,
                    asset_type=asset_type,
                    asset_id=asset_id,
                    scope=scope,
                    env_key=env_key,
                    values=payload,
                    revision=new_revision,
                    updated_by=operator,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            new_revision = revision + 1
            changed = db.execute(
                update(ParameterSet)
                .where(
                    ParameterSet.id == row.id,
                    ParameterSet.revision == revision,
                )
                .values(values=payload, revision=new_revision, updated_by=operator, updated_at=now)
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise HTTPException(status_code=409, detail=CONFLICT)
        db.add(
            ConfigChange(
                id=str(uuid4()),
                operator=operator,
                project_id=project.id,
                env=env_key,
                object_type="parameter_set",
                object_name=str(row.id) if row is not None else asset_id[:64],
                action="update" if row is not None else "create",
                field_names=["values"],
                credential_note=None,
                revision=new_revision,
                created_at=now,
            )
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=CONFLICT) from None
    except OperationalError:
        db.rollback()
        raise HTTPException(status_code=409, detail="参数保存遇到并发更新，请刷新后重试") from None
    return {"values": payload, "revision": new_revision, "updated_by": operator}
