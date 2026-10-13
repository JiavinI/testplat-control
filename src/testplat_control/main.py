"""FastAPI 主应用。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from testplat_control.api import assets, cases, execution, projects, run
from testplat_control.deps import create_default_engine_port
from testplat_control.engine_bootstrap import EngineBootstrapError, ensure_engine_compatible

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时校验 Engine 依赖并挂载默认真实适配器。"""
    try:
        version = ensure_engine_compatible()
    except EngineBootstrapError as exc:
        logger.error("Engine 启动诊断失败: exc_type=%s", type(exc).__name__)
        raise
    app.state.engine_port = create_default_engine_port()
    logger.info("已挂载默认 PackageEngineAdapter（engine %s）", version)
    yield


app = FastAPI(
    title="testplat-control",
    description="通用接口自动化测试平台 - 控制层",
    version="0.1.0",
    lifespan=lifespan,
)

# 注册路由
app.include_router(projects.router)
app.include_router(execution.router)
app.include_router(assets.router)
app.include_router(run.router)
app.include_router(cases.router)


@app.get("/health")
async def health() -> dict:
    """健康检查端点。

    Returns:
        dict: 健康状态
    """
    return {"status": "ok"}
