"""仓库列表与同步路由（设计稿 §5.3）。API 响应永不包含仓库 URL。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from testplat_control.api.schemas import RepoResponse, SyncResponse
from testplat_control.database.models import Repo
from testplat_control.database.session import get_db
from testplat_control.services.project_access import get_sync_service

router = APIRouter(prefix="/repos", tags=["repos"])


@router.get("", response_model=list[RepoResponse])
async def list_repos(
    request: Request,
    db: Session = Depends(get_db),
) -> list[RepoResponse]:
    """列出已配置仓库的同步状态（不含 URL）。

    仅返回服务端配置中的键；尚未同步成功的仓库也会出现（若启动时已写入行），
    配置有但库中无行时补一条「尚未同步」视图。
    """
    service = get_sync_service(request)
    configured = service.config.repos
    rows = {r.key: r for r in db.query(Repo).all()}
    result: list[RepoResponse] = []
    for key, entry in configured.items():
        row = rows.get(key)
        if row is None:
            result.append(
                RepoResponse(
                    key=key,
                    branch=entry.branch,
                    current_sha=None,
                    last_sync_at=None,
                    last_sync_result=None,
                )
            )
        else:
            result.append(
                RepoResponse(
                    key=row.key,
                    branch=row.branch,
                    current_sha=row.current_sha,
                    last_sync_at=row.last_sync_at,
                    last_sync_result=row.last_sync_result,
                )
            )
    return result


@router.post("/{repo}/sync", response_model=SyncResponse)
async def sync_repo(
    repo: str,
    request: Request,
    db: Session = Depends(get_db),
) -> SyncResponse:
    """触发仓库同步；失败只返回类别，保留旧 SHA。"""
    service = get_sync_service(request)
    if service.config.get(repo) is None:
        raise HTTPException(status_code=404, detail="Repo not found")
    outcome = await service.sync_repo(db, repo)
    return SyncResponse(
        repo=outcome.repo,
        ok=outcome.ok,
        category=outcome.category,
        commit_sha=outcome.commit_sha,
    )
