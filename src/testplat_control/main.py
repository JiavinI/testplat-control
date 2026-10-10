"""FastAPI 主应用"""

from fastapi import FastAPI
from testplat_control.api import projects, execution, assets

app = FastAPI(
    title="testplat-control",
    description="通用接口自动化测试平台 - 控制层",
    version="0.1.0",
)

# 注册路由
app.include_router(projects.router)
app.include_router(execution.router)
app.include_router(assets.router)


@app.get("/health")
async def health() -> dict:
    """健康检查端点

    Returns:
        dict: 健康状态
    """
    return {"status": "ok"}
