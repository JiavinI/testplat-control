"""项目环境、登录流程与测试账号。

列表与详情仅返回登录用户名，不返回完整凭据。显式查看凭据的响应禁止缓存。
PUT 必须带 revision，不一致返回 409。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from testplat_control.api.platform_session import require_user
from testplat_control.database.models import ProjectEnvironment, TestAccount
from testplat_control.database.session import get_db
from testplat_control.services.environment_store import (
    create_account,
    create_environment,
    get_account,
    get_environment,
    list_accounts,
    list_environments,
    read_credentials,
    update_account,
    update_environment,
    validate_account_name,
    validate_api_hosts,
    validate_case_params,
    validate_credentials,
    validate_env_name,
    validate_profile_name,
    validate_text,
    validate_timeout,
)
from testplat_control.services.login_profiles import ProfileFileError, load_profile_catalog
from testplat_control.services.platform_auth import PlatformPrincipal
from testplat_control.services.project_access import (
    ensure_snapshot_dirs,
    get_project,
    get_repos_config,
)
from testplat_control.services.workspaces import configuration_project

router = APIRouter(prefix="/repos/{repo}/projects/{project}", tags=["environments"])


class EnvironmentBody(BaseModel):
    env: str = Field(..., description="环境名，保存后不可改")
    api_hosts: dict[str, str] = Field(default_factory=dict, description="逻辑服务名到 URL")
    timeout_seconds: float | None = Field(
        None, description="省略表示使用默认 30 秒；显式数字则写入环境"
    )
    case_params: dict[str, Any] = Field(default_factory=dict, description="非秘密业务默认参数")
    enabled: bool = Field(True, description="是否启用")


class EnvironmentUpdate(BaseModel):
    revision: int = Field(..., ge=1, description="读取时的环境 revision")
    api_hosts: dict[str, str] | None = None
    timeout_seconds: float | None = None
    case_params: dict[str, Any] | None = None
    enabled: bool | None = None


class EnvironmentResponse(BaseModel):
    env: str
    enabled: bool
    api_hosts: dict[str, Any]
    timeout_seconds: float | None
    case_params: dict[str, Any]
    revision: int
    updated_by: str | None


class LoginProfileResponse(BaseModel):
    name: str
    credential_fields: list[str] = Field(..., description="模板中的 ${secret:字段名}，不含值")
    unavailable_reason: str | None = None


class LoginProfilesResponse(BaseModel):
    commit_sha: str
    profiles: list[LoginProfileResponse]


class AccountBody(BaseModel):
    account_name: str = Field(..., description="账号名，保存后不可改")
    display_name: str | None = None
    business_role: str | None = None
    login_profile: str
    credentials: dict[str, str]
    enabled: bool = True


class AccountUpdate(BaseModel):
    revision: int = Field(..., ge=1, description="读取时的账号 revision")
    display_name: str | None = None
    business_role: str | None = None
    login_profile: str | None = None
    credentials: dict[str, str] | None = None
    enabled: bool | None = None


class AccountResponse(BaseModel):
    account_name: str
    login_username: str | None
    display_name: str | None
    business_role: str | None
    login_profile: str
    enabled: bool
    revision: int
    updated_by: str | None


class CredentialsResponse(BaseModel):
    account_name: str
    credentials: dict[str, str]


def _env_response(row: ProjectEnvironment) -> EnvironmentResponse:
    return EnvironmentResponse(
        env=row.env,
        enabled=bool(row.enabled),
        api_hosts=dict(row.api_hosts or {}),
        timeout_seconds=None if row.timeout_seconds is None else float(row.timeout_seconds),
        case_params=dict(row.case_params or {}),
        revision=int(row.revision),
        updated_by=row.updated_by,
    )


def _account_response(row: TestAccount) -> AccountResponse:
    return AccountResponse(
        account_name=row.account_name,
        # 只允许 username 进入列表 DTO，其他凭据字段不能透传。
        login_username=read_credentials(row).get("username"),
        display_name=row.display_name,
        business_role=row.business_role,
        login_profile=row.login_profile,
        enabled=bool(row.enabled),
        revision=int(row.revision),
        updated_by=row.updated_by,
    )


@router.get("/environments", response_model=list[EnvironmentResponse])
async def get_environments(
    repo: str,
    project: str,
    db: Session = Depends(get_db),
    user: PlatformPrincipal = Depends(require_user),
) -> list[EnvironmentResponse]:
    del user
    row = configuration_project(db, get_project(db, repo, project))
    return [_env_response(item) for item in list_environments(db, row.id)]


@router.post("/environments", response_model=EnvironmentResponse, status_code=201)
async def post_environment(
    repo: str,
    project: str,
    body: EnvironmentBody,
    db: Session = Depends(get_db),
    user: PlatformPrincipal = Depends(require_user),
) -> EnvironmentResponse:
    row = configuration_project(db, get_project(db, repo, project))
    created = create_environment(
        db,
        project_id=row.id,
        env=validate_env_name(body.env),
        api_hosts=validate_api_hosts(body.api_hosts),
        timeout_seconds=validate_timeout(body.timeout_seconds),
        case_params=validate_case_params(body.case_params),
        enabled=body.enabled,
        operator=user.username,
    )
    return _env_response(created)


@router.get("/environments/{env}", response_model=EnvironmentResponse)
async def get_environment_detail(
    repo: str,
    project: str,
    env: str,
    db: Session = Depends(get_db),
    user: PlatformPrincipal = Depends(require_user),
) -> EnvironmentResponse:
    del user
    row = configuration_project(db, get_project(db, repo, project))
    return _env_response(get_environment(db, row.id, env))


@router.put("/environments/{env}", response_model=EnvironmentResponse)
async def put_environment(
    repo: str,
    project: str,
    env: str,
    body: EnvironmentUpdate,
    db: Session = Depends(get_db),
    user: PlatformPrincipal = Depends(require_user),
) -> EnvironmentResponse:
    row = configuration_project(db, get_project(db, repo, project))
    fields: dict[str, Any] = {}
    present = body.model_fields_set
    if "api_hosts" in present:
        fields["api_hosts"] = validate_api_hosts(body.api_hosts)
    if "timeout_seconds" in present:
        fields["timeout_seconds"] = validate_timeout(body.timeout_seconds)
    if "case_params" in present:
        fields["case_params"] = validate_case_params(body.case_params)
    if "enabled" in present:
        if body.enabled is None:
            raise HTTPException(status_code=422, detail="enabled 不能为空")
        fields["enabled"] = body.enabled
    if not fields:
        raise HTTPException(status_code=422, detail="没有可更新的字段")
    updated = update_environment(
        db,
        project_id=row.id,
        env=env,
        expected_revision=body.revision,
        operator=user.username,
        fields=fields,
    )
    return _env_response(updated)


@router.get(
    "/login-profiles", response_model=LoginProfilesResponse, response_model_exclude_none=True
)
async def get_login_profiles(
    repo: str,
    project: str,
    request: Request,
    db: Session = Depends(get_db),
    user: PlatformPrincipal = Depends(require_user),
) -> LoginProfilesResponse:
    """当前资产 commit 下的流程名与所需凭据字段名。不返回凭据。"""
    del user
    row = configuration_project(db, get_project(db, repo, project))
    commit_sha, _, config_root = ensure_snapshot_dirs(get_repos_config(request), row)
    try:
        catalog = load_profile_catalog(config_root)
    except ProfileFileError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from None
    return LoginProfilesResponse(
        commit_sha=commit_sha,
        profiles=[
            LoginProfileResponse(
                name=item.name,
                credential_fields=list(item.credential_fields),
                unavailable_reason=item.unavailable_reason,
            )
            for item in catalog.profiles
        ],
    )


@router.get("/environments/{env}/accounts", response_model=list[AccountResponse])
async def get_accounts(
    repo: str,
    project: str,
    env: str,
    response: Response,
    db: Session = Depends(get_db),
    user: PlatformPrincipal = Depends(require_user),
) -> list[AccountResponse]:
    del user
    response.headers["Cache-Control"] = "no-store"
    row = configuration_project(db, get_project(db, repo, project))
    return [_account_response(item) for item in list_accounts(db, row.id, env)]


@router.post("/environments/{env}/accounts", response_model=AccountResponse, status_code=201)
async def post_account(
    repo: str,
    project: str,
    env: str,
    body: AccountBody,
    db: Session = Depends(get_db),
    user: PlatformPrincipal = Depends(require_user),
) -> AccountResponse:
    row = configuration_project(db, get_project(db, repo, project))
    created = create_account(
        db,
        project_id=row.id,
        env=env,
        account_name=validate_account_name(body.account_name),
        display_name=validate_text(body.display_name, field="display_name"),
        business_role=validate_text(body.business_role, field="business_role"),
        login_profile=validate_profile_name(body.login_profile),
        credentials=validate_credentials(body.credentials),
        enabled=body.enabled,
        operator=user.username,
    )
    return _account_response(created)


@router.get("/environments/{env}/accounts/{name}", response_model=AccountResponse)
async def get_account_detail(
    repo: str,
    project: str,
    env: str,
    name: str,
    response: Response,
    db: Session = Depends(get_db),
    user: PlatformPrincipal = Depends(require_user),
) -> AccountResponse:
    del user
    response.headers["Cache-Control"] = "no-store"
    row = configuration_project(db, get_project(db, repo, project))
    return _account_response(get_account(db, row.id, env, name))


@router.put("/environments/{env}/accounts/{name}", response_model=AccountResponse)
async def put_account(
    repo: str,
    project: str,
    env: str,
    name: str,
    body: AccountUpdate,
    db: Session = Depends(get_db),
    user: PlatformPrincipal = Depends(require_user),
) -> AccountResponse:
    row = configuration_project(db, get_project(db, repo, project))
    fields: dict[str, Any] = {}
    present = body.model_fields_set
    if "display_name" in present:
        fields["display_name"] = validate_text(body.display_name, field="display_name")
    if "business_role" in present:
        fields["business_role"] = validate_text(body.business_role, field="business_role")
    if "login_profile" in present:
        if body.login_profile is None:
            raise HTTPException(status_code=422, detail="login_profile 不能为空")
        fields["login_profile"] = validate_profile_name(body.login_profile)
    if "enabled" in present:
        if body.enabled is None:
            raise HTTPException(status_code=422, detail="enabled 不能为空")
        fields["enabled"] = body.enabled
    credentials = None
    if "credentials" in present:
        credentials = validate_credentials(body.credentials)
    if not fields and credentials is None:
        raise HTTPException(status_code=422, detail="没有可更新的字段")
    updated = update_account(
        db,
        project_id=row.id,
        env=env,
        name=name,
        expected_revision=body.revision,
        operator=user.username,
        fields=fields,
        credentials=credentials,
    )
    return _account_response(updated)


@router.get("/environments/{env}/accounts/{name}/credentials")
async def get_account_credentials(
    repo: str,
    project: str,
    env: str,
    name: str,
    db: Session = Depends(get_db),
    user: PlatformPrincipal = Depends(require_user),
) -> Response:
    """显式查看凭据。禁止缓存。"""
    del user
    row = configuration_project(db, get_project(db, repo, project))
    account = get_account(db, row.id, env, name)
    payload = CredentialsResponse(
        account_name=account.account_name,
        credentials=read_credentials(account),
    )
    return JSONResponse(
        content=payload.model_dump(),
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )
