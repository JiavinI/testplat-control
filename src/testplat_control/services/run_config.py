"""运行配置解析。

入参是项目、环境名和已经固定的资产 commit 目录。返回 Engine 的 environment、
AuthTable、有效超时与参数，以及可持久化的非秘密摘要。

已有 Web 环境时：api_hosts 与账号只来自数据库；``${secret:字段名}`` 按账号凭据
字典解析，不读 ``TESTPLAT_*``，也不把凭据写进 ``os.environ``。
正常 Web 缺少数据库环境时拒绝运行；仅显式兼容模式允许无 Web 环境的旧项目读取 Git。
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from testplat_engine import AuthTable, UnavailableAuth

from testplat_control.config import settings
from testplat_control.database.models import Project, ProjectEnvironment, TestAccount
from testplat_control.services.auth_loader import (
    AuthLoadResult,
    build_auth_from_document,
    load_auth,
)
from testplat_control.services.crypto import MasterKeyError, decrypt_credentials
from testplat_control.services.env_loader import load_project_environment
from testplat_control.services.login_profiles import ProfileFileError, load_profile_catalog
from testplat_control.services.workspaces import configuration_project, workspace_response

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
# 账号保存会同时递增环境 revision。读完账号后若环境版本变了，说明两次查询跨过一次提交。
_CONSISTENT_READ_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class _AccountView:
    """从一次一致读取里复制出来的账号。之后不再碰 ORM。"""

    account_name: str
    display_name: str | None
    business_role: str | None
    login_profile: str
    enabled: bool
    revision: int
    encrypted_credentials: str


@dataclass(frozen=True, slots=True)
class _WebView:
    """同一环境 revision 下的环境与账号。"""

    revision: int
    enabled: bool
    api_hosts: dict[str, Any]
    case_params: dict[str, Any]
    timeout_seconds: float | None
    accounts: tuple[_AccountView, ...]


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
    """浅层覆盖：请求顶层键覆盖环境 case_params。"""
    merged = dict(case_params)
    merged.update(request_params)
    return merged


def merge_layered_params(
    asset_params: dict[str, Any],
    case_params: dict[str, Any],
    request_params: dict[str, Any],
) -> dict[str, Any]:
    """浅层覆盖：请求 > 环境 case_params > 资产默认值。"""
    merged = dict(asset_params)
    merged.update(case_params)
    merged.update(request_params)
    return merged


def params_for_run(
    case_params: dict[str, Any],
    request_params: dict[str, Any],
    *,
    declared_names: set[str] | None = None,
    asset_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """合成本次要交给 Engine 的参数。

    单接口传入 ``declared_names`` 时，只取该接口声明过的环境默认值和资产默认值。
    请求体里的键全部保留，以便调用方拒绝显式未知参数。
    Case 不传 ``declared_names``：环境默认值整份交给 Engine，由 Engine 再叠 case 资产参数。
    """
    if declared_names is None:
        return merge_params(case_params, request_params)
    defaults = {
        key: value for key, value in (asset_defaults or {}).items() if key in declared_names
    }
    applicable = {key: value for key, value in case_params.items() if key in declared_names}
    return merge_layered_params(defaults, applicable, request_params)


def effective_timeout(request_timeout: float | None, env_timeout: float | None) -> float:
    """请求显式值优先于环境值，再否则 30。None 表示省略，不是显式 30。"""
    if request_timeout is not None:
        return float(request_timeout)
    if env_timeout is not None:
        return float(env_timeout)
    return DEFAULT_TIMEOUT


def _load_consistent_web(db: Session, project_id: str, env: str) -> _WebView | None:
    """读出同一次提交里的环境和账号。

    SQLite 默认不为 SELECT 开启数据库读事务，Session 标志也不能证明两次查询
    看到同一快照。路由可能已经把环境放进身份映射；这里用 ``populate_existing``
    强制按查询结果覆盖。读完账号后再查环境 revision，变了就丢掉这次结果重读。
    """
    for _ in range(_CONSISTENT_READ_ATTEMPTS):
        web = (
            db.query(ProjectEnvironment)
            .filter(ProjectEnvironment.project_id == project_id, ProjectEnvironment.env == env)
            .execution_options(populate_existing=True)
            .first()
        )
        if web is None:
            return None
        seen = int(web.revision)
        accounts = (
            db.query(TestAccount)
            .filter(TestAccount.project_id == project_id, TestAccount.env == env)
            .order_by(TestAccount.account_name)
            .execution_options(populate_existing=True)
            .all()
        )
        # 列查询走数据库，不拿身份映射里的旧 revision。
        current = db.execute(
            text("SELECT revision FROM project_environments WHERE id = :id"),
            {"id": web.id},
        ).scalar()
        if current is None or int(current) != seen:
            db.expire(web)
            for account in accounts:
                db.expire(account)
            continue
        return _WebView(
            revision=seen,
            enabled=bool(web.enabled),
            api_hosts=dict(web.api_hosts or {}),
            case_params=dict(web.case_params or {}),
            timeout_seconds=None if web.timeout_seconds is None else float(web.timeout_seconds),
            accounts=tuple(
                _AccountView(
                    account_name=item.account_name,
                    display_name=item.display_name,
                    business_role=item.business_role,
                    login_profile=item.login_profile,
                    enabled=bool(item.enabled),
                    revision=int(item.revision),
                    encrypted_credentials=item.encrypted_credentials,
                )
                for item in accounts
            ),
        )
    raise HTTPException(status_code=409, detail="配置刚刚被更新，请重新运行")


def resolve_run_config(
    db: Session,
    project: Project,
    env: str,
    config_root: Path,
    *,
    request_params: dict[str, Any],
    request_timeout: float | None,
    declared_names: set[str] | None = None,
    asset_defaults: dict[str, Any] | None = None,
) -> ResolvedRunConfig:
    """冻结同一环境版本下的账号、参数和摘要。调用方读完后结束会话事务。"""
    owner = configuration_project(db, project)
    web = _load_consistent_web(db, owner.id, env)
    if web is None:
        has_web = (
            db.query(ProjectEnvironment.id)
            .filter(ProjectEnvironment.project_id == owner.id)
            .first()
            is not None
        )
        if not settings.testplat_legacy_git_config or has_web:
            raise HTTPException(
                status_code=422, detail=f"数据库环境未配置: {env}，请到配置中创建并启用"
            )
        return _legacy(
            project,
            env,
            config_root,
            request_params,
            request_timeout,
            declared_names,
            asset_defaults,
        )
    if not web.enabled:
        raise HTTPException(status_code=422, detail=f"环境已停用: {env}")
    accounts = web.accounts
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
    context = workspace_response(db, project)
    auth = _auth_from_accounts(
        env=env,
        project=project,
        accounts=accounts,
        decrypted=decrypted,
        catalog_profiles={item.name: item.body for item in catalog.profiles},
        login_plugins=catalog.login_plugins,
        workspace_project=None if context is None else context["project"],
    )
    timeout = effective_timeout(request_timeout, web.timeout_seconds)
    case_params = dict(web.case_params)
    params = params_for_run(
        case_params,
        request_params,
        declared_names=declared_names,
        asset_defaults=asset_defaults,
    )
    api_hosts = dict(web.api_hosts)
    account_revisions = {item.account_name: item.revision for item in accounts}
    snapshot = _snapshot(
        env=env,
        api_hosts=api_hosts,
        timeout_seconds=timeout,
        case_params=case_params,
        config_revision=int(web.revision),
        accounts=accounts,
        catalog_fields={item.name: list(item.credential_fields) for item in catalog.profiles},
    )
    if context is not None:
        snapshot["workspace"] = context
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
    declared_names: set[str] | None = None,
    asset_defaults: dict[str, Any] | None = None,
) -> ResolvedRunConfig:
    """仅显式兼容且项目完全没有数据库环境时读取 Git。"""
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
    params = params_for_run(
        {},
        request_params,
        declared_names=declared_names,
        asset_defaults=asset_defaults,
    )
    hosts = environment.get("api_hosts")
    safe_hosts = dict(hosts) if isinstance(hosts, dict) else {}
    return ResolvedRunConfig(
        environment=environment,
        auth=loaded,
        params=params,
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
    accounts: tuple[_AccountView, ...],
    decrypted: dict[str, dict[str, str]],
    catalog_profiles: dict[str, dict[str, Any]],
    login_plugins: tuple[str, ...],
    workspace_project: str | None = None,
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
        if "unavailable" in profile:
            identities[name] = UnavailableAuth(public_reason=profile["unavailable"]["reason"])
            continue
        document = {
            "identities": {name: _workspace_values(deepcopy(profile), workspace_project)},
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


def _workspace_values(node: Any, project: str | None) -> Any:
    """只替换独立的业务项目占位符，不渲染 URL、凭据或业务请求参数。"""
    if isinstance(node, dict):
        return {key: _workspace_values(value, project) for key, value in node.items()}
    if isinstance(node, list):
        return [_workspace_values(value, project) for value in node]
    if node == "${workspace:project}":
        if project is None:
            raise HTTPException(status_code=422, detail="登录流程需要明确的平台项目关系")
        return project
    return node


def _snapshot(
    *,
    env: str,
    api_hosts: dict[str, Any],
    timeout_seconds: float,
    case_params: dict[str, Any],
    config_revision: int,
    accounts: tuple[_AccountView, ...],
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
