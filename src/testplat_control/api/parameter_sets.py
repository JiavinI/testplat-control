"""资产参数上下文及带版本的保存接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from testplat_control.api.platform_session import require_user
from testplat_control.api.run import (
    _load_api_document,
    _matches_type,
    asset_default_params,
    build_param_infos,
)
from testplat_control.database.session import get_db
from testplat_control.services.case_asset_service import case_parameter_defaults
from testplat_control.services.environment_store import get_environment
from testplat_control.services.parameter_sets import (
    AssetType,
    Scope,
    begin_snapshot,
    compose_parameters,
    read_parameter_layers,
    save_parameter_set,
)
from testplat_control.services.platform_auth import PlatformPrincipal
from testplat_control.services.project_access import (
    ensure_snapshot_dirs,
    get_project,
    get_repos_config,
)
from testplat_control.services.workspaces import configuration_project

router = APIRouter(prefix="/repos/{repo}/projects/{project}", tags=["parameter-sets"])


class ParameterSetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, Any]
    revision: int = Field(..., ge=0, strict=True)
    commit_sha: str = Field(..., min_length=1)


class ParameterState(BaseModel):
    values: dict[str, Any]
    revision: int


class ParameterContext(BaseModel):
    project_id: str
    asset_type: AssetType
    asset_id: str
    env: str
    commit_sha: str
    environment_revision: int
    git_defaults: dict[str, Any]
    shared_environment: dict[str, Any]
    asset_default: ParameterState
    environment_override: ParameterState
    effective: dict[str, Any]
    sources: dict[str, str]


def _definition(asset_type: AssetType, asset_id: str, assets_root):
    if asset_type == "api":
        document = _load_api_document(assets_root, asset_id)
        try:
            specs = build_param_infos(document.get("inputs"))
        except ValueError:
            raise HTTPException(status_code=422, detail="接口参数定义无效") from None
        return asset_default_params(document.get("inputs")), specs
    return case_parameter_defaults(assets_root, asset_id, required=True), None


@router.get("/parameter-sets/{asset_type}/{asset_id}", response_model=ParameterContext)
async def get_parameter_context(
    repo: str,
    project: str,
    asset_type: AssetType,
    asset_id: str,
    request: Request,
    response: Response,
    env: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> ParameterContext:
    begin_snapshot(db)
    row = get_project(db, repo, project)
    sha, root, _ = ensure_snapshot_dirs(get_repos_config(request), row)
    defaults, specs = _definition(asset_type, asset_id, root)
    owner = configuration_project(db, row)
    web = get_environment(db, owner.id, env)
    saved, override, revisions = read_parameter_layers(
        db,
        project_id=row.id,
        asset_type=asset_type,
        asset_id=asset_id,
        env=env,
    )
    shared = dict(web.case_params or {})
    names = None if specs is None else {item.name for item in specs}
    effective, sources = compose_parameters(defaults, saved, shared, override, {}, names=names)
    response.headers["Cache-Control"] = "no-store"
    return ParameterContext(
        project_id=row.id,
        asset_type=asset_type,
        asset_id=asset_id,
        env=env,
        commit_sha=sha,
        environment_revision=web.revision,
        git_defaults=defaults,
        shared_environment=shared,
        asset_default=ParameterState(values=saved, revision=revisions.get("asset_default", 0)),
        environment_override=ParameterState(
            values=override, revision=revisions.get("environment_override", 0)
        ),
        effective=effective,
        sources=sources,
    )


@router.put("/parameter-sets/{asset_type}/{asset_id}/{scope}", response_model=ParameterState)
async def put_parameter_set(
    repo: str,
    project: str,
    asset_type: AssetType,
    asset_id: str,
    scope: Scope,
    body: ParameterSetUpdate,
    request: Request,
    env: str | None = Query(None),
    db: Session = Depends(get_db),
    user: PlatformPrincipal = Depends(require_user),
) -> ParameterState:
    begin_snapshot(db, write=True)
    row = get_project(db, repo, project)
    if body.commit_sha != row.commit_sha:
        raise HTTPException(status_code=409, detail="资产版本已变化，请刷新后再保存")
    _, root, _ = ensure_snapshot_dirs(get_repos_config(request), row)
    _, specs = _definition(asset_type, asset_id, root)
    if scope == "asset_default":
        if env is not None:
            raise HTTPException(status_code=422, detail="资产默认值不接受环境名")
        env_key = ""
    else:
        if not env:
            raise HTTPException(status_code=422, detail="环境覆盖必须指定环境")
        owner = configuration_project(db, row)
        get_environment(db, owner.id, env)
        env_key = env
    if specs is not None:
        by_name = {item.name: item for item in specs}
        for name, value in body.values.items():
            if name not in by_name or not _matches_type(by_name[name].type, value):
                raise HTTPException(status_code=422, detail="参数名或类型与当前接口声明不符")
    saved = save_parameter_set(
        db,
        project=row,
        asset_type=asset_type,
        asset_id=asset_id,
        scope=scope,
        env_key=env_key,
        values=body.values,
        revision=body.revision,
        commit_sha=body.commit_sha,
        operator=user.username,
    )
    return ParameterState(values=saved["values"], revision=saved["revision"])
