"""Git 仓库镜像同步与只读快照物化（设计稿 §4.2–§4.3）。

快照方案：``git archive`` 写出 tar 字节，再 ``tar -x`` 解压到
``{data_dir}/{repo}/snap/{sha}/``（两步均 ``subprocess`` 参数列表，无 ``shell=True``）。

选择理由：快照目录无 ``.git``、天然只读树、不占用 worktree 槽位，清理只需删目录；
与正在执行的路径解耦——同步只更新「当前 SHA」，已物化的旧 SHA 目录继续服务进行中的执行。

安全：Git stdout/stderr 可能含凭据 URL，不进日志、不进异常消息、不进 HTTP；
对外只暴露失败类别 ``network|auth|invalid_manifest|timeout``。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from testplat_control.database.models import Project, Repo
from testplat_control.services.manifest import (
    ManifestError,
    envs_for_project,
    load_manifest,
    safe_resolve,
)
from testplat_control.services.repos_config import RepoEntry, ReposConfig

logger = logging.getLogger(__name__)

GIT_TIMEOUT_SECONDS = 60
SNAPSHOT_KEEP = 10
SYNC_OK = "ok"
SYNC_NETWORK = "network"
SYNC_AUTH = "auth"
SYNC_INVALID_MANIFEST = "invalid_manifest"
SYNC_TIMEOUT = "timeout"

_AUTH_KEYWORDS = (
    "authentication",
    "permission denied",
    "could not read username",
    "invalid credentials",
    "access denied",
    "publickey",
    "authentication failed",
    "403",
    "401",
    "denied",
)


@dataclass(frozen=True)
class SyncResult:
    """单次同步结果（不含 URL / git 原文）。"""

    repo: str
    ok: bool
    category: str  # ok|network|auth|invalid_manifest|timeout
    commit_sha: str | None


class SyncError(Exception):
    """同步失败；``category`` 为对外类别，``args`` 不含 git 原文。"""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = GIT_TIMEOUT_SECONDS,
    check: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    """参数列表调用 git；超时抛 ``SyncError(timeout)``。不记录 stdout/stderr。"""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd is not None else None,
            env=_git_env(),
            capture_output=True,
            timeout=timeout,
            check=check,
        )
    except subprocess.TimeoutExpired as exc:
        raise SyncError(SYNC_TIMEOUT) from exc


def classify_git_failure(stderr: bytes) -> str:
    """根据 git stderr 关键词判断 auth；判不出归 network。不把原文向外传。"""
    text = stderr.decode("utf-8", errors="replace").lower()
    if any(keyword in text for keyword in _AUTH_KEYWORDS):
        return SYNC_AUTH
    return SYNC_NETWORK


def mirror_path(data_dir: Path, repo_key: str) -> Path:
    return data_dir / repo_key / "mirror.git"


def snap_root(data_dir: Path, repo_key: str) -> Path:
    return data_dir / repo_key / "snap"


def snapshot_path(data_dir: Path, repo_key: str, sha: str) -> Path:
    return snap_root(data_dir, repo_key) / sha


def short_sha(sha: str | None) -> str:
    if not sha:
        return "-"
    return sha[:12]


def materialize_snapshot(mirror: Path, sha: str, dest: Path) -> None:
    """把 ``sha`` 物化为 ``dest``；已存在则复用。使用 git archive | tar。"""
    if dest.is_dir() and any(dest.iterdir()):
        return
    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".tmp-{sha}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    archive = _run_git(["archive", "--format=tar", sha], cwd=mirror)
    if archive.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SyncError(classify_git_failure(archive.stderr))

    try:
        extracted = subprocess.run(
            ["tar", "-x", "-C", str(tmp)],
            input=archive.stdout,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SyncError(SYNC_TIMEOUT) from exc

    if extracted.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SyncError(SYNC_NETWORK)

    if dest.exists():
        shutil.rmtree(dest)
    tmp.rename(dest)


def cleanup_snapshots(data_dir: Path, repo_key: str, keep_shas: set[str]) -> None:
    """保留最近 ``SNAPSHOT_KEEP`` 个快照以及 ``keep_shas`` 中的 SHA。"""
    root = snap_root(data_dir, repo_key)
    if not root.is_dir():
        return
    entries: list[tuple[float, Path]] = []
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name in keep_shas:
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        entries.append((mtime, child))
    # 已跳过 keep_shas；对其余按时间倒序，超出配额的删除
    kept_count = len(keep_shas)
    budget = max(SNAPSHOT_KEEP - kept_count, 0)
    entries.sort(key=lambda item: item[0], reverse=True)
    for _, path in entries[budget:]:
        shutil.rmtree(path, ignore_errors=True)


def resolve_branch_sha(mirror: Path, branch: str) -> str:
    """解析镜像中分支当前 SHA（40 位）。"""
    result = _run_git(["rev-parse", f"refs/heads/{branch}"], cwd=mirror)
    if result.returncode != 0:
        # 某些 mirror 用 refs/heads；再试 FETCH_HEAD / 裸分支名
        result = _run_git(["rev-parse", branch], cwd=mirror)
    if result.returncode != 0:
        raise SyncError(classify_git_failure(result.stderr))
    sha = result.stdout.decode("utf-8", errors="replace").strip()
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha.lower()):
        raise SyncError(SYNC_NETWORK)
    return sha.lower()


def ensure_mirror(entry: RepoEntry, data_dir: Path) -> Path:
    """镜像不存在则 ``clone --mirror``，否则 ``fetch --prune``。"""
    mirror = mirror_path(data_dir, entry.key)
    if not (mirror / "HEAD").exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        if mirror.exists():
            shutil.rmtree(mirror)
        # URL 只传给 git，不记日志
        result = _run_git(
            ["clone", "--mirror", entry.url, str(mirror)],
            cwd=None,
        )
        if result.returncode != 0:
            shutil.rmtree(mirror, ignore_errors=True)
            raise SyncError(classify_git_failure(result.stderr))
        return mirror

    # 配置 URL 可能变更：先改 origin 再 fetch（否则仍打旧远程）
    set_url = _run_git(["remote", "set-url", "origin", entry.url], cwd=mirror)
    if set_url.returncode != 0:
        raise SyncError(classify_git_failure(set_url.stderr))
    result = _run_git(["fetch", "--prune"], cwd=mirror)
    if result.returncode != 0:
        raise SyncError(classify_git_failure(result.stderr))
    return mirror


def project_dirs(
    data_dir: Path, repo_key: str, project_key: str, commit_sha: str
) -> tuple[Path, Path]:
    """返回某 commit 快照下项目的 assets_root / config_root（已做前缀校验）。"""
    snap = snapshot_path(data_dir, repo_key, commit_sha)
    if not snap.is_dir():
        raise FileNotFoundError("snapshot_missing")
    manifest = load_manifest(snap)
    project = manifest.projects.get(project_key)
    if project is None:
        raise FileNotFoundError("project_missing_in_manifest")
    root = snap.resolve()
    assets = safe_resolve(root, project.assets)
    config = safe_resolve(root, project.config)
    return assets, config


class RepoSyncService:
    """每仓库 ``asyncio.Lock`` 串行同步；可挂到 ``app.state``。"""

    def __init__(self, config: ReposConfig) -> None:
        self.config = config
        self._locks: dict[str, asyncio.Lock] = {}

    def replace_config(self, config: ReposConfig) -> None:
        """测试或热加载时替换配置（不清理旧锁）。"""
        self.config = config

    def _lock_for(self, repo_key: str) -> asyncio.Lock:
        lock = self._locks.get(repo_key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[repo_key] = lock
        return lock

    async def sync_repo(self, db: Session, repo_key: str) -> SyncResult:
        """同步单个仓库并 upsert 项目；失败保留旧 SHA。"""
        entry = self.config.get(repo_key)
        if entry is None:
            return SyncResult(repo=repo_key, ok=False, category=SYNC_NETWORK, commit_sha=None)
        async with self._lock_for(repo_key):
            return await asyncio.to_thread(self._sync_repo_blocking, db, entry)

    def _sync_repo_blocking(self, db: Session, entry: RepoEntry) -> SyncResult:
        repo_row = db.query(Repo).filter(Repo.key == entry.key).first()
        if repo_row is None:
            repo_row = Repo(
                key=entry.key,
                branch=entry.branch,
                current_sha=None,
                last_sync_at=None,
                last_sync_result=None,
            )
            db.add(repo_row)
            db.flush()
        else:
            repo_row.branch = entry.branch

        previous_sha = repo_row.current_sha
        try:
            mirror = ensure_mirror(entry, self.config.data_dir)
            sha = resolve_branch_sha(mirror, entry.branch)
            dest = snapshot_path(self.config.data_dir, entry.key, sha)
            materialize_snapshot(mirror, sha, dest)
            manifest = load_manifest(dest)
            now = datetime.now(UTC).replace(tzinfo=None)
            self._upsert_projects(db, entry.key, sha, dest, manifest, now)
            repo_row.current_sha = sha
            repo_row.last_sync_at = now
            repo_row.last_sync_result = SYNC_OK
            db.commit()
            keep = {sha}
            if previous_sha:
                keep.add(previous_sha)
            cleanup_snapshots(self.config.data_dir, entry.key, keep)
            logger.info(
                "仓库同步成功 repo=%s category=%s sha=%s",
                entry.key,
                SYNC_OK,
                short_sha(sha),
            )
            return SyncResult(repo=entry.key, ok=True, category=SYNC_OK, commit_sha=sha)
        except SyncError as exc:
            return self._fail(db, repo_row, previous_sha, exc.category)
        except ManifestError:
            return self._fail(db, repo_row, previous_sha, SYNC_INVALID_MANIFEST)
        except Exception:
            # 未知错误归 network，不记录异常原文（可能间接含 URL）
            return self._fail(db, repo_row, previous_sha, SYNC_NETWORK)

    def _fail(
        self, db: Session, repo_row: Repo, previous_sha: str | None, category: str
    ) -> SyncResult:
        now = datetime.now(UTC).replace(tzinfo=None)
        repo_row.last_sync_at = now
        repo_row.last_sync_result = category
        # 保留旧 current_sha
        db.commit()
        logger.warning(
            "仓库同步失败 repo=%s category=%s sha=%s",
            repo_row.key,
            category,
            short_sha(previous_sha),
        )
        return SyncResult(
            repo=repo_row.key,
            ok=False,
            category=category,
            commit_sha=previous_sha,
        )

    def _upsert_projects(
        self,
        db: Session,
        repo_key: str,
        sha: str,
        snap: Path,
        manifest,
        now: datetime,
    ) -> None:
        seen: set[str] = set()
        for key, spec in manifest.projects.items():
            project_id = f"{repo_key}/{key}"
            seen.add(project_id)
            envs = envs_for_project(snap, spec)
            default_env = spec.default_env
            if default_env is not None and default_env not in envs:
                default_env = envs[0] if envs else None
            elif default_env is None and envs:
                default_env = envs[0]
            row = db.query(Project).filter(Project.id == project_id).first()
            if row is None:
                row = Project(
                    id=project_id,
                    repo=repo_key,
                    project_key=key,
                    name=spec.name,
                    envs=list(envs),
                    default_env=default_env,
                    archived=False,
                    commit_sha=sha,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            else:
                row.name = spec.name
                row.envs = list(envs)
                row.default_env = default_env
                row.archived = False
                row.commit_sha = sha
                row.updated_at = now

        # 清单消失的项目标记 archived，不删
        existing = db.query(Project).filter(Project.repo == repo_key).all()
        for row in existing:
            if row.id not in seen:
                row.archived = True
                row.updated_at = now

    async def sync_all(self, db: Session) -> list[SyncResult]:
        """启动时同步全部已配置仓库；单个失败不阻塞其余。"""
        results: list[SyncResult] = []
        for key in self.config.repos:
            try:
                results.append(await self.sync_repo(db, key))
            except Exception:
                logger.warning("仓库同步异常 repo=%s category=%s sha=-", key, SYNC_NETWORK)
                results.append(
                    SyncResult(repo=key, ok=False, category=SYNC_NETWORK, commit_sha=None)
                )
        return results
