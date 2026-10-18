"""FastAPI 主应用。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from testplat_control.api import (
    assets,
    cases,
    environments,
    execution,
    parameter_sets,
    platform_session,
    projects,
    repos,
    run,
)
from testplat_control.api.platform_session import require_user
from testplat_control.config import settings
from testplat_control.database.schema_guard import IncompatibleSchemaError, assert_schema_compatible
from testplat_control.database.session import SessionLocal
from testplat_control.database.session import engine as db_engine
from testplat_control.deps import create_default_engine_port
from testplat_control.engine_bootstrap import EngineBootstrapError, ensure_engine_compatible
from testplat_control.services.repo_sync import RepoSyncService
from testplat_control.services.repos_config import ReposConfigError, load_repos_config

logger = logging.getLogger(__name__)


def _build_repo_sync() -> RepoSyncService:
    """加载服务端仓库配置；未配置时得到空列表。配置非法则 fail-fast。"""
    try:
        config = load_repos_config(settings.testplat_repos_file)
    except ReposConfigError as exc:
        logger.error("仓库配置无效: %s", exc.message)
        raise
    return RepoSyncService(config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时校验表结构与 Engine、挂载适配器，并对已配置仓库同步一次（失败不阻塞）。

    表结构不兼容时只说明需要显式删库，不会清空数据库。
    """
    try:
        assert_schema_compatible(db_engine)
    except IncompatibleSchemaError as exc:
        logger.error("数据库结构不兼容: %s", exc)
        raise
    try:
        version = ensure_engine_compatible()
    except EngineBootstrapError as exc:
        logger.error("Engine 启动诊断失败: exc_type=%s", type(exc).__name__)
        raise
    app.state.engine_port = create_default_engine_port()
    logger.info("已挂载默认 PackageEngineAdapter（engine %s）", version)

    sync_service = getattr(app.state, "repo_sync", None)
    if sync_service is None:
        sync_service = _build_repo_sync()
        app.state.repo_sync = sync_service

    db = SessionLocal()
    try:
        results = await sync_service.sync_all(db)
        for item in results:
            logger.info(
                "启动同步 repo=%s category=%s sha=%s",
                item.repo,
                item.category,
                (item.commit_sha or "-")[:12],
            )
    finally:
        db.close()

    yield


app = FastAPI(
    title="testplat-control",
    description="通用接口自动化测试平台 - 控制层",
    version="0.1.0",
    lifespan=lifespan,
)


def _public_validation_errors(exc: RequestValidationError) -> list[dict[str, object]]:
    """校验错误只保留位置和类型。不回显 input，避免 password / credentials 进响应。"""
    public: list[dict[str, object]] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        public.append(
            {
                "type": err.get("type"),
                "loc": list(loc) if isinstance(loc, (list, tuple)) else [loc],
                "msg": err.get("msg"),
            }
        )
    return public


@app.exception_handler(RequestValidationError)
async def hide_validation_input(request: Request, exc: RequestValidationError) -> JSONResponse:
    """请求体校验失败时不返回提交的字段值或 ctx。"""
    del request
    return JSONResponse(status_code=422, content={"detail": _public_validation_errors(exc)})


# 测试在 lifespan 外构造 TestClient 时也能拿到同步服务；lifespan 会再替换配置。
app.state.repo_sync = _build_repo_sync()

# 配置与执行接口都要登录。health / register / login 不挂这个依赖。
_AUTH = [Depends(require_user)]

# 注册路由（项目 POST/PUT/DELETE 已移除）
app.include_router(platform_session.router)
app.include_router(repos.router, dependencies=_AUTH)
app.include_router(projects.router, dependencies=_AUTH)
app.include_router(execution.router, dependencies=_AUTH)
app.include_router(assets.router, dependencies=_AUTH)
app.include_router(run.router, dependencies=_AUTH)
app.include_router(cases.router, dependencies=_AUTH)
app.include_router(environments.router, dependencies=_AUTH)
app.include_router(parameter_sets.router, dependencies=_AUTH)


@app.get("/health")
async def health() -> dict:
    """健康检查端点。"""
    return {"status": "ok"}
