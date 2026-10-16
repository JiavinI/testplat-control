"""按仓库键 + 项目键解析项目，并定位当前/指定 SHA 快照目录。"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from testplat_control.config import settings
from testplat_control.database.models import Project, ProjectEnvironment, Repo
from testplat_control.services.repo_sync import (
    RepoSyncService,
    materialize_snapshot,
    mirror_path,
    project_dirs,
    snapshot_path,
)
from testplat_control.services.repos_config import ReposConfig


def get_sync_service(request: Request) -> RepoSyncService:
    service = getattr(request.app.state, "repo_sync", None)
    if service is None:
        raise HTTPException(status_code=503, detail="仓库同步服务未初始化")
    return service  # type: ignore[no-any-return]


def get_repos_config(request: Request) -> ReposConfig:
    return get_sync_service(request).config


def get_project(db: Session, repo: str, project: str) -> Project:
    """读取项目；不存在 → 404。"""
    project_id = f"{repo}/{project}"
    row = db.query(Project).filter(Project.id == project_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


def visible_envs(db: Session, project: Project) -> tuple[list[str], str | None]:
    """响应里的 envs / default_env。

    默认只返回数据库环境。显式兼容模式且项目没有数据库环境时才展示 Git 模板名。
    """
    rows = db.query(ProjectEnvironment).filter(ProjectEnvironment.project_id == project.id).all()
    if rows:
        names = sorted(row.env for row in rows if row.enabled)
        default = (
            project.default_env if project.default_env in names else (names[0] if names else None)
        )
        return names, default
    if settings.testplat_legacy_git_config:
        return list(project.envs or []), project.default_env
    return [], None


def require_env(db: Session, project: Project, env: str) -> str:
    """校验运行环境。Web 环境存在时以数据库为准（停用则 422）。"""
    if not env or not str(env).strip():
        raise HTTPException(status_code=422, detail="env 为必填项")
    env = str(env).strip()
    rows = db.query(ProjectEnvironment).filter(ProjectEnvironment.project_id == project.id).all()
    if rows:
        match = next((row for row in rows if row.env == env), None)
        if match is None:
            raise HTTPException(status_code=422, detail=f"环境不在可选列表中: {env}")
        if not match.enabled:
            raise HTTPException(status_code=422, detail=f"环境已停用: {env}")
        return env
    if not settings.testplat_legacy_git_config:
        raise HTTPException(status_code=422, detail="请先在配置中创建并启用项目环境")
    envs = list(project.envs or [])
    if env not in envs:
        raise HTTPException(status_code=422, detail=f"环境不在可选列表中: {env}")
    return env


def ensure_snapshot_dirs(
    config: ReposConfig, project: Project, *, commit_sha: str | None = None
) -> tuple[str, Path, Path]:
    """确保快照存在，返回 (sha, assets_root, config_root)。

    执行开始时传入当时的 ``commit_sha`` 并全程复用；浏览资产时用项目当前 SHA。
    """
    sha = commit_sha or project.commit_sha
    if not sha:
        raise HTTPException(status_code=404, detail="项目尚无可用快照，请先同步仓库")
    data_dir = config.data_dir
    snap = snapshot_path(data_dir, project.repo, sha)
    if not snap.is_dir():
        mirror = mirror_path(data_dir, project.repo)
        if not (mirror / "HEAD").exists():
            raise HTTPException(status_code=404, detail="项目尚无可用快照，请先同步仓库")
        try:
            materialize_snapshot(mirror, sha, snap)
        except Exception:
            raise HTTPException(status_code=404, detail="项目尚无可用快照，请先同步仓库") from None
    try:
        assets, config_root = project_dirs(data_dir, project.repo, project.project_key, sha)
    except Exception:
        raise HTTPException(status_code=404, detail="快照内项目路径无效") from None
    return sha, assets, config_root


def get_repo_row(db: Session, repo_key: str) -> Repo | None:
    return db.query(Repo).filter(Repo.key == repo_key).first()
