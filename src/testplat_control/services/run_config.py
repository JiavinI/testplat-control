"""运行配置解析。

入参是项目、环境名和已经固定的资产 commit 目录。返回 Engine 的 environment、
AuthTable、有效超时与参数，以及可持久化的非秘密摘要。

已有 Web 环境时：api_hosts 与账号只来自数据库；``${secret:字段名}`` 按账号凭据
字典解析，不读 ``TESTPLAT_*``，也不把凭据写进 ``os.environ``。
尚无 Web 环境时：仍走 Git 环境文件与历史 auth 文件，供 4.0 夹具继续运行。
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session
from testplat_engine import AuthTable, UnavailableAuth

from testplat_control.database.models import Project, ProjectEnvironment, TestAccount
from testplat_control.services.auth_loader import (
    AuthLoadResult,
    build_auth_from_document,
    load_auth,
)
from testplat_control.services.crypto import MasterKeyError, decrypt_credentials
from testplat_control.services.env_loader import load_project_environment
from testplat_control.services.login_profiles import ProfileFileError, load_profile_catalog

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True, slots=True)
class ResolvedRunConfig:
    """一次运行冻结的材料。调用方在事务结束后才拿去发网络请求。"""

    environment: dict[str, Any]
    auth: AuthLoadResult | None
    params: dict[str, Any]
    timeout_seconds: float
    config_revision: int | None
    account_revisions: dict[str, int]
    snapshot: dict[str, Any]


def merge_params(case_params: dict[str, Any], request_params: dict[str, Any]) -> dict[str, Any]:
    """浅层覆盖：请求顶层键覆盖环境 case_params。资产 params 由 Engine 再叠一层。"""
    merged = dict(case_params)
    merged.update(request_params)
    return merged


def effective_timeout(request_timeout: float | None, env_timeout: float | None) -> float:
    """请求显式值优先于环境值，再否则 30。None 表示省略，不是显式 30。"""
    if request_timeout is not None:
        return float(request_timeout)
    if env_timeout is not None:
        return float(env_timeout)
    return DEFAULT_TIMEOUT


def resolve_run_config(
    db: Session,
    project: Project,
    env: str,
    config_root: Path,
    *,
    request_params: dict[str, Any],
    request_timeout: float | None,
) -> ResolvedRunConfig:
    """在一次数据库读取里冻结环境、账号和版本。"""
    web = (
        db.query(ProjectEnvironment)
        .filter(ProjectEnvironment.project_id == project.id, ProjectEnvironment.env == env)
        .first()
    )
    if web is None:
        return _legacy(project, env, config_root, request_params, request_timeout)
    if not web.enabled:
        raise HTTPException(status_code=422, detail=f"环境已停用: {env}")
    accounts = (
        db.query(TestAccount)
        .filter(TestAccount.project_id == project.id, TestAccount.env == env)
        .order_by(TestAccount.account_name)
        .all()
    )
    # 读完再构造，避免构造失败后还握着半截明文。解密只在本函数内短暂存在。
    decrypted: dict[str, dict[str, str]] = {}
    for account in accounts:
        if not account.enabled:
            continue
        try:
            decrypted[account.account_name] = decrypt_credentials(account.encrypted_credentials)
        except MasterKeyError as exc:
            raise HTTPException(status_code=500, detail=exc.message) from None
    try:
        catalog = load_profile_catalog(config_root)
    except ProfileFileError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from None
    auth = _auth_from_accounts(
        env=env,
        project=project,
        accounts=accounts,
        decrypted=decrypted,
        catalog_profiles={item.name: item.body for item in catalog.profiles},
        login_plugins=catalog.login_plugins,
    )
    timeout = effective_timeout(request_timeout, web.timeout_seconds)
    case_params = dict(web.case_params or {})
    params = merge_params(case_params, request_params)
    api_hosts = dict(web.api_hosts or {})
    account_revisions = {item.account_name: int(item.revision) for item in accounts}
    snapshot = _snapshot(
        env=env,
        api_hosts=api_hosts,
        timeout_seconds=timeout,
        case_params=case_params,
        config_revision=int(web.revision),
        accounts=accounts,
        catalog_fields={item.name: list(item.credential_fields) for item in catalog.profiles},
    )
    # 明文凭据不要留在返回值上；AuthTable 内是 SecretStr。
    decrypted.clear()
    return ResolvedRunConfig(
        environment={"api_hosts": api_hosts},
        auth=auth,
        params=params,
        timeout_seconds=timeout,
        config_revision=int(web.revision),
        account_revisions=account_revisions,
        snapshot=snapshot,
    )


def _legacy(
    project: Project,
    env: str,
    config_root: Path,
    request_params: dict[str, Any],
    request_timeout: float | None,
) -> ResolvedRunConfig:
    """没有 Web 环境行时沿用 Git 文件。平台账号路径不会进入这里。"""
    from testplat_engine import EngineError

    try:
        environment = load_project_environment(config_root, env)
    except EngineError as exc:
        raise HTTPException(status_code=422, detail=exc.public_message) from exc
    cache_scope = f"{project.repo}:{project.project_key}:{env}"
    try:
        loaded = load_auth(config_root, env, cache_scope=cache_scope)
    except EngineError as exc:
        raise HTTPException(status_code=422, detail=exc.public_message) from exc
    timeout = effective_timeout(request_timeout, None)
    hosts = environment.get("api_hosts")
    safe_hosts = dict(hosts) if isinstance(hosts, dict) else {}
    return ResolvedRunConfig(
        environment=environment,
        auth=loaded,
        params=dict(request_params),
        timeout_seconds=timeout,
        config_revision=None,
        account_revisions={},
        snapshot={
            "source": "git",
            "env": env,
            "api_hosts": safe_hosts,
            "timeout_seconds": timeout,
            "case_params": {},
            "config_revision": None,
            "accounts": [],
        },
    )


def _auth_from_accounts(
    *,
    env: str,
    project: Project,
    accounts: list[TestAccount],
    decrypted: dict[str, dict[str, str]],
    catalog_profiles: dict[str, dict[str, Any]],
    login_plugins: tuple[str, ...],
) -> AuthLoadResult | None:
    """每个启用账号单独解析自己的凭据，身份名是账号名。"""
    if not accounts:
        return None
    cache_scope = f"{project.repo}:{project.project_key}:{env}"
    identities: dict[str, Any] = {}
    for account in accounts:
        name = account.account_name
        if not account.enabled:
            identities[name] = UnavailableAuth(public_reason=f"账号 {name} 在环境 {env} 已停用")
            continue
        profile = catalog_profiles.get(account.login_profile)
        if profile is None:
            identities[name] = UnavailableAuth(
                public_reason=f"账号 {name} 的登录流程 {account.login_profile} 不存在"
            )
            continue
        document = {
            "identities": {name: deepcopy(profile)},
            "login_plugins": list(login_plugins),
        }
        secrets = decrypted.get(name, {})
        try:
            built = build_auth_from_document(
                document, env=env, secrets=secrets, cache_scope=cache_scope
            )
        except Exception as exc:
            # 单个账号的模板错误不阻断其他账号；被引用时由 UnavailableAuth 预检失败。
            logger.error(
                "登录流程构造失败 env=%s account=%s exc_type=%s",
                env,
                name,
                type(exc).__name__,
            )
            identities[name] = UnavailableAuth(public_reason=f"账号 {name} 的登录流程无法加载")
            continue
        identities[name] = built.table.identities[name]
    try:
        table = AuthTable(
            identities=identities,
            default_identity=None,
            connections={},
            cache_scope=cache_scope,
        )
    except (TypeError, ValueError) as exc:
        logger.error("构造账号身份表失败 env=%s exc_type=%s", env, type(exc).__name__)
        raise HTTPException(status_code=422, detail="鉴权配置无效") from None
    return AuthLoadResult(table=table, login_plugins=login_plugins)


def _snapshot(
    *,
    env: str,
    api_hosts: dict[str, Any],
    timeout_seconds: float,
    case_params: dict[str, Any],
    config_revision: int,
    accounts: list[TestAccount],
    catalog_fields: dict[str, list[str]],
) -> dict[str, Any]:
    """非秘密摘要。只列凭据字段名，不列值。"""
    account_rows = []
    for item in accounts:
        fields = list(catalog_fields.get(item.login_profile, []))
        account_rows.append(
            {
                "account_name": item.account_name,
                "display_name": item.display_name,
                "business_role": item.business_role,
                "login_profile": item.login_profile,
                "enabled": bool(item.enabled),
                "revision": int(item.revision),
                "credential_fields": fields,
            }
        )
    return {
        "source": "database",
        "env": env,
        "api_hosts": api_hosts,
        "timeout_seconds": timeout_seconds,
        "case_params": case_params,
        "config_revision": config_revision,
        "accounts": account_rows,
    }
