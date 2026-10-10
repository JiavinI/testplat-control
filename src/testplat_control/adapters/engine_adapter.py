"""testplat-engine 适配器

提供 testplat-control 与 testplat-engine 的集成接口，封装了与引擎的通信逻辑。
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from testplat_control.database.models import ExecutionRecord, Project

# 动态导入 testplat-engine
_engine_path = Path(__file__).parent.parent.parent.parent / "testplat-engine" / "src"
if str(_engine_path) not in sys.path:
    sys.path.insert(0, str(_engine_path))

from testplat_engine import run_api
from testplat_engine.adapters.filesystem import Registry
from testplat_engine.domain.result import ApiResult


class EngineAdapter:
    """testplat-engine 适配器。

    调用 testplat-engine 执行 API 和 Case，并将执行结果转换为 control 层的执行记录。

    Attributes:
        engine_root: testplat-engine 的根目录路径，默认为相邻的 testplat-engine 目录

    Examples:
        >>> adapter = EngineAdapter()
        >>> result, record = await adapter.run_api(
        ...     api_id="api.common.health_check",
        ...     project=project
        ... )
    """

    def __init__(self, engine_root: Path | None = None) -> None:
        """初始化 EngineAdapter。

        Args:
            engine_root: testplat-engine 根目录路径。如果未指定，默认使用相邻的
                testplat-engine 目录
        """
        self.engine_root = engine_root or (
            Path(__file__).parent.parent.parent.parent / "testplat-engine"
        )

    async def run_api(
        self,
        api_id: str,
        project: Project,
        params: dict[str, Any] | None = None,
    ) -> tuple[ApiResult, ExecutionRecord]:
        """执行单个 API，返回引擎结果和执行记录。

        将 testplat-engine 的 API 执行与 testplat-control 的数据库记录关联起来。

        Args:
            api_id: API 标识，如 "api.common.health_check"
            project: Project 数据库对象，包含 assets_root 和 config_root 路径
            params: 请求参数字典，用于变量渲染，默认为空字典

        Returns:
            tuple[ApiResult, ExecutionRecord]: 返回元组，包含：
                - ApiResult: 引擎的执行结果
                - ExecutionRecord: 保存到数据库的执行记录

        Examples:
            >>> adapter = EngineAdapter()
            >>> result, record = await adapter.run_api(
            ...     api_id="api.common.health_check",
            ...     project=project,
            ...     params={"user_id": "123"}
            ... )
            >>> assert result.is_success
            >>> assert record.status == "success"
        """
        # 1. 创建资产注册表
        registry = Registry(assets_root=Path(project.assets_root))

        # 2. 创建执行记录
        record = ExecutionRecord(
            id=str(uuid4()),
            project_id=project.id,
            asset_type="api",
            asset_id=api_id,
            status="running",
            start_time=datetime.utcnow(),
        )

        try:
            # 3. 调用引擎执行 API
            result = await run_api(
                api_id=api_id,
                registry=registry,
                env=project.env,
                params=params or {},
            )

            # 4. 更新执行记录
            record.status = "success" if result.is_success else "failed"
            record.end_time = datetime.utcnow()
            record.duration = (record.end_time - record.start_time).total_seconds()

            # 5. 序列化执行结果
            result_dict = {
                "status": result.status,
                "response": (
                    result.response.dict() if hasattr(result.response, "dict")
                    else result.response
                ),
                "error": result.error,
            }
            record.result_json = json.dumps(result_dict, default=str)

            return result, record

        except Exception as e:
            # 执行异常处理
            record.status = "failed"
            record.end_time = datetime.utcnow()
            record.duration = (record.end_time - record.start_time).total_seconds()

            error_msg = f"{type(e).__name__}: {e}"
            result_dict = {
                "status": "failed",
                "response": None,
                "error": error_msg,
            }
            record.result_json = json.dumps(result_dict)

            # 返回失败的 ApiResult
            failed_result = ApiResult.failed(error=error_msg)
            return failed_result, record
