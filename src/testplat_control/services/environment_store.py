"""项目环境与测试账号的持久化。

环境名、账号名保存后不可改。账号与环境的修改在同一事务里递增环境 revision。
ConfigChange 只记字段名；凭据变更记「已修改」，不记原值。
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from testplat_control.database.models import ConfigChange, ProjectEnvironment, TestAccount
from testplat_control.services.crypto import (
    MasterKeyError,
    decrypt_credentials,
    encrypt_credentials,
)

ENV_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ACCOUNT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
HOST_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
PROFILE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
CREDENTIAL_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
RESERVED_ACCOUNT = "none"
CREDENTIAL_NOTE = "已修改"
CONFLICT = "配置版本冲突，请刷新后再保存"
MIN_SECRET = 8


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def validate_env_name(env: str) -> str:
    if not isinstance(env, str) or not ENV_NAME_RE.fullmatch(env) or env.startswith("_"):
        raise HTTPException(
            status_code=422, detail="环境名需匹配 ^[a-z0-9][a-z0-9_-]{0,63}$，且不能以 _ 开头"
        )
    return env


def validate_account_name(name: str) -> str:
    if not isinstance(name, str) or not ACCOUNT_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="账号名需匹配 ^[a-z][a-z0-9_]*$")
    if name == RESERVED_ACCOUNT:
        raise HTTPException(status_code=422, detail="none 是保留账号名")
    return name


def validate_profile_name(name: str) -> str:
    if not isinstance(name, str) or not PROFILE_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="login_profile 名称非法")
    if name == RESERVED_ACCOUNT:
        raise HTTPException(status_code=422, detail="none 是保留名")
    return name


def validate_api_hosts(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail="api_hosts 必须是对象")
    out: dict[str, str] = {}
    for key, url in value.items():
        if not isinstance(key, str) or not HOST_NAME_RE.fullmatch(key):
            raise HTTPException(status_code=422, detail="api_hosts 含非法服务名")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="api_hosts 的地址必须是 http(s) URL")
        hostport = url.split("://", 1)[1].split("/", 1)[0]
        if "@" in hostport:
            raise HTTPException(status_code=422, detail="api_hosts 的地址不得包含用户信息")
        out[key] = url
    return out


def validate_case_params(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail="case_params 必须是对象")
    try:
        encoded = json.dumps(value)
        parsed = json.loads(encoded)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="case_params 必须是 JSON 对象") from None
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="case_params 必须是对象")
    return parsed


def validate_timeout(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(status_code=422, detail="timeout_seconds 必须是数字")
    if not 0 < float(value) <= 300:
        raise HTTPException(status_code=422, detail="timeout_seconds 必须在 (0, 300] 内")
    return float(value)


def validate_credentials(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise HTTPException(status_code=422, detail="credentials 必须是非空对象")
    out: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not CREDENTIAL_FIELD_RE.fullmatch(key):
            raise HTTPException(status_code=422, detail="凭据字段名非法")
        if not isinstance(item, str):
            raise HTTPException(status_code=422, detail="凭据字段必须是字符串")
        if len(item) < MIN_SECRET:
            raise HTTPException(status_code=422, detail="凭据字段长度不足 8")
        if any(ch in item for ch in "\r\n\x00"):
            raise HTTPException(status_code=422, detail="凭据字段含非法控制字符")
        out[key] = item
    return out


def validate_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{field} 必须是字符串")
    text = value.strip()
    if len(text) > 255:
        raise HTTPException(status_code=422, detail=f"{field} 过长")
    return text or None


def _record_change(
    db: Session,
    *,
    operator: str,
    project_id: str,
    env: str,
    object_type: str,
    object_name: str,
    action: str,
    field_names: list[str],
    credentials_changed: bool,
    revision: int,
) -> None:
    db.add(
        ConfigChange(
            id=_new_id(),
            operator=operator,
            project_id=project_id,
            env=env,
            object_type=object_type,
            object_name=object_name,
            action=action,
            field_names=list(field_names),
            credential_note=CREDENTIAL_NOTE if credentials_changed else None,
            revision=revision,
            created_at=_now(),
        )
    )


def _new_id() -> str:
    import secrets

    return secrets.token_hex(16)


def list_environments(db: Session, project_id: str) -> list[ProjectEnvironment]:
    return (
        db.query(ProjectEnvironment)
        .filter(ProjectEnvironment.project_id == project_id)
        .order_by(ProjectEnvironment.env)
        .all()
    )


def get_environment(db: Session, project_id: str, env: str) -> ProjectEnvironment:
    row = (
        db.query(ProjectEnvironment)
        .filter(ProjectEnvironment.project_id == project_id, ProjectEnvironment.env == env)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    return row


def create_environment(
    db: Session,
    *,
    project_id: str,
    env: str,
    api_hosts: dict[str, str],
    timeout_seconds: float | None,
    case_params: dict[str, Any],
    enabled: bool,
    operator: str,
) -> ProjectEnvironment:
    env = validate_env_name(env)
    exists = (
        db.query(ProjectEnvironment)
        .filter(ProjectEnvironment.project_id == project_id, ProjectEnvironment.env == env)
        .first()
    )
    if exists is not None:
        raise HTTPException(status_code=409, detail="环境已存在")
    now = _now()
    row = ProjectEnvironment(
        id=_new_id(),
        project_id=project_id,
        env=env,
        enabled=enabled,
        api_hosts=api_hosts,
        timeout_seconds=timeout_seconds,
        case_params=case_params,
        revision=1,
        updated_by=operator,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    _record_change(
        db,
        operator=operator,
        project_id=project_id,
        env=env,
        object_type="environment",
        object_name=env,
        action="create",
        field_names=["api_hosts", "timeout_seconds", "case_params", "enabled"],
        credentials_changed=False,
        revision=1,
    )
    db.commit()
    db.refresh(row)
    return row


def _update_where_revision(
    db: Session,
    *,
    row_id: str,
    expected_revision: int,
    values: dict[str, Any],
    model: type[ProjectEnvironment] | type[TestAccount],
) -> None:
    """条件更新：只有库里的 revision 仍是预期值才写入。冲突则回滚并 409。"""
    now = _now()
    stmt = (
        update(model)
        .where(model.id == row_id, model.revision == expected_revision)
        .values(revision=expected_revision + 1, updated_at=now, **values)
        .execution_options(synchronize_session=False)
    )
    result = db.execute(stmt)
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail=CONFLICT)


def _bump_environment_sql(db: Session, env_row: ProjectEnvironment, operator: str) -> int:
    """同一事务里原子递增环境 revision。调用方在冲突时回滚本语句。"""
    now = _now()
    result = db.execute(
        update(ProjectEnvironment)
        .where(ProjectEnvironment.id == env_row.id)
        .values(
            revision=ProjectEnvironment.revision + 1,
            updated_by=operator,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail=CONFLICT)
    db.expire(env_row)
    db.refresh(env_row)
    return int(env_row.revision)


def update_environment(
    db: Session,
    *,
    project_id: str,
    env: str,
    expected_revision: int,
    operator: str,
    fields: dict[str, Any],
) -> ProjectEnvironment:
    """按 revision 条件更新。``fields`` 只含本次要改的列。"""
    row = get_environment(db, project_id, env)
    changed = sorted(fields)
    _update_where_revision(
        db,
        row_id=row.id,
        expected_revision=expected_revision,
        values={**fields, "updated_by": operator},
        model=ProjectEnvironment,
    )
    new_revision = expected_revision + 1
    _record_change(
        db,
        operator=operator,
        project_id=project_id,
        env=env,
        object_type="environment",
        object_name=env,
        action="update",
        field_names=changed,
        credentials_changed=False,
        revision=new_revision,
    )
    db.commit()
    db.expire(row)
    db.refresh(row)
    return row


def list_accounts(db: Session, project_id: str, env: str) -> list[TestAccount]:
    get_environment(db, project_id, env)
    return (
        db.query(TestAccount)
        .filter(TestAccount.project_id == project_id, TestAccount.env == env)
        .order_by(TestAccount.account_name)
        .all()
    )


def get_account(db: Session, project_id: str, env: str, name: str) -> TestAccount:
    get_environment(db, project_id, env)
    row = (
        db.query(TestAccount)
        .filter(
            TestAccount.project_id == project_id,
            TestAccount.env == env,
            TestAccount.account_name == name,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    return row


def _bump_environment(env_row: ProjectEnvironment, operator: str) -> int:
    env_row.revision = int(env_row.revision) + 1
    env_row.updated_by = operator
    env_row.updated_at = _now()
    return int(env_row.revision)


def create_account(
    db: Session,
    *,
    project_id: str,
    env: str,
    account_name: str,
    display_name: str | None,
    business_role: str | None,
    login_profile: str,
    credentials: dict[str, str],
    enabled: bool,
    operator: str,
) -> TestAccount:
    env_row = get_environment(db, project_id, env)
    account_name = validate_account_name(account_name)
    login_profile = validate_profile_name(login_profile)
    exists = (
        db.query(TestAccount)
        .filter(
            TestAccount.project_id == project_id,
            TestAccount.env == env,
            TestAccount.account_name == account_name,
        )
        .first()
    )
    if exists is not None:
        raise HTTPException(status_code=409, detail="账号已存在")
    try:
        ciphertext = encrypt_credentials(credentials)
    except MasterKeyError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from None
    now = _now()
    row = TestAccount(
        id=_new_id(),
        project_id=project_id,
        env=env,
        account_name=account_name,
        display_name=display_name,
        business_role=business_role,
        login_profile=login_profile,
        encrypted_credentials=ciphertext,
        enabled=enabled,
        revision=1,
        updated_by=operator,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    env_revision = _bump_environment(env_row, operator)
    _record_change(
        db,
        operator=operator,
        project_id=project_id,
        env=env,
        object_type="account",
        object_name=account_name,
        action="create",
        field_names=["display_name", "business_role", "login_profile", "credentials", "enabled"],
        credentials_changed=True,
        revision=env_revision,
    )
    db.commit()
    db.refresh(row)
    return row


def update_account(
    db: Session,
    *,
    project_id: str,
    env: str,
    name: str,
    expected_revision: int,
    operator: str,
    fields: dict[str, Any],
    credentials: dict[str, str] | None,
) -> TestAccount:
    """更新账号。``credentials is None`` 表示本次不改凭据。"""
    env_row = get_environment(db, project_id, env)
    row = get_account(db, project_id, env, name)
    changed = sorted(fields)
    values = {**fields, "updated_by": operator}
    if credentials is not None:
        try:
            values["encrypted_credentials"] = encrypt_credentials(credentials)
        except MasterKeyError as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=exc.message) from None
        changed = sorted({*changed, "credentials"})
    _update_where_revision(
        db,
        row_id=row.id,
        expected_revision=expected_revision,
        values=values,
        model=TestAccount,
    )
    env_revision = _bump_environment_sql(db, env_row, operator)
    _record_change(
        db,
        operator=operator,
        project_id=project_id,
        env=env,
        object_type="account",
        object_name=name,
        action="update",
        field_names=changed,
        credentials_changed=credentials is not None,
        revision=env_revision,
    )
    db.commit()
    db.expire(row)
    db.refresh(row)
    return row


def read_credentials(row: TestAccount) -> dict[str, str]:
    try:
        return decrypt_credentials(row.encrypted_credentials)
    except MasterKeyError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from None
