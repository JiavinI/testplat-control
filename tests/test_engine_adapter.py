"""testplat-engine 适配器的单元测试

测试 EngineAdapter 与 testplat-engine 的集成。
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from testplat_control.adapters.engine_adapter import EngineAdapter
from testplat_control.database.models import ExecutionRecord, Project
from testplat_engine.domain.result import ApiResult


@pytest.fixture
def mock_project() -> Project:
    """创建测试用的 Project 对象。

    Returns:
        Project: 模拟的项目配置对象
    """
    project = Project(
        id="proj-001",
        name="test_project",
        env="test",
        assets_root="/path/to/assets",
        config_root="/path/to/config",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    return project


@pytest.fixture
def engine_adapter() -> EngineAdapter:
    """创建 EngineAdapter 实例。

    Returns:
        EngineAdapter: 适配器实例
    """
    return EngineAdapter()


class TestEngineAdapterInit:
    """测试 EngineAdapter 初始化"""

    def test_init_with_default_engine_root(self) -> None:
        """测试默认 engine_root 初始化"""
        adapter = EngineAdapter()
        assert adapter.engine_root is not None
        assert isinstance(adapter.engine_root, Path)

    def test_init_with_custom_engine_root(self) -> None:
        """测试自定义 engine_root 初始化"""
        custom_path = Path("/custom/engine/path")
        adapter = EngineAdapter(engine_root=custom_path)
        assert adapter.engine_root == custom_path


class TestEngineAdapterRunApi:
    """测试 EngineAdapter.run_api 方法"""

    @pytest.mark.asyncio
    async def test_run_api_success(self, mock_project: Project) -> None:
        """测试成功执行 API"""
        adapter = EngineAdapter()

        # Mock 执行结果
        mock_response = {"status_code": 200, "body": {"message": "ok"}}
        expected_result = ApiResult.success(response=mock_response)

        # Mock run_api 函数
        with patch("testplat_control.adapters.engine_adapter.run_api") as mock_run_api:
            mock_run_api.return_value = expected_result

            result, record = await adapter.run_api(
                api_id="api.common.health_check",
                project=mock_project,
                params={"timeout": 30},
            )

        # 验证结果
        assert result.is_success is True
        assert result.status == "success"

        # 验证执行记录
        assert record.status == "success"
        assert record.project_id == "proj-001"
        assert record.asset_type == "api"
        assert record.asset_id == "api.common.health_check"
        assert record.end_time is not None
        assert record.duration is not None

        # 验证结果 JSON
        result_json = json.loads(record.result_json)
        assert result_json["status"] == "success"
        assert result_json["response"]["status_code"] == 200
        assert result_json["error"] is None

    @pytest.mark.asyncio
    async def test_run_api_failed(self, mock_project: Project) -> None:
        """测试执行失败的 API"""
        adapter = EngineAdapter()

        # Mock 失败结果
        expected_result = ApiResult.failed(
            error="断言失败: 响应不符合成功条件",
            response={"status_code": 500}
        )

        with patch("testplat_control.adapters.engine_adapter.run_api") as mock_run_api:
            mock_run_api.return_value = expected_result

            result, record = await adapter.run_api(
                api_id="api.common.health_check",
                project=mock_project,
            )

        # 验证结果
        assert result.is_failed is True
        assert result.status == "failed"

        # 验证执行记录
        assert record.status == "failed"
        assert "断言失败" in record.result_json

    @pytest.mark.asyncio
    async def test_run_api_exception(self, mock_project: Project) -> None:
        """测试执行异常的 API"""
        adapter = EngineAdapter()

        # Mock 异常
        with patch(
            "testplat_control.adapters.engine_adapter.run_api"
        ) as mock_run_api:
            mock_run_api.side_effect = FileNotFoundError("API 文件不存在")

            result, record = await adapter.run_api(
                api_id="api.not.found",
                project=mock_project,
            )

        # 验证结果
        assert result.is_failed is True
        assert "FileNotFoundError" in result.error

        # 验证执行记录
        assert record.status == "failed"
        assert record.duration is not None

        result_json = json.loads(record.result_json)
        assert result_json["status"] == "failed"
        assert "FileNotFoundError" in result_json["error"]

    @pytest.mark.asyncio
    async def test_run_api_with_empty_params(self, mock_project: Project) -> None:
        """测试传入空参数的 API 执行"""
        adapter = EngineAdapter()

        mock_response = {"status_code": 200}
        expected_result = ApiResult.success(response=mock_response)

        with patch("testplat_control.adapters.engine_adapter.run_api") as mock_run_api:
            mock_run_api.return_value = expected_result

            result, record = await adapter.run_api(
                api_id="api.common.health_check",
                project=mock_project,
            )

        # 验证 run_api 被调用时传入空字典
        mock_run_api.assert_called_once()
        call_args = mock_run_api.call_args
        assert call_args.kwargs["params"] == {}


class TestExecutionRecordCreation:
    """测试执行记录的创建"""

    @pytest.mark.asyncio
    async def test_execution_record_fields(self, mock_project: Project) -> None:
        """测试执行记录的所有必需字段"""
        adapter = EngineAdapter()

        expected_result = ApiResult.success(response={"status_code": 200})

        with patch("testplat_control.adapters.engine_adapter.run_api") as mock_run_api:
            mock_run_api.return_value = expected_result

            result, record = await adapter.run_api(
                api_id="api.test.method",
                project=mock_project,
            )

        # 验证所有字段
        assert record.id  # UUID 字符串
        assert record.project_id == mock_project.id
        assert record.asset_type == "api"
        assert record.asset_id == "api.test.method"
        assert record.status in {"success", "failed"}
        assert record.start_time is not None
        assert record.end_time is not None
        assert record.duration >= 0
        assert record.result_json is not None

    @pytest.mark.asyncio
    async def test_execution_record_uuid_unique(self, mock_project: Project) -> None:
        """测试每个执行记录的 UUID 都不同"""
        adapter = EngineAdapter()

        expected_result = ApiResult.success(response={"status_code": 200})

        with patch("testplat_control.adapters.engine_adapter.run_api") as mock_run_api:
            mock_run_api.return_value = expected_result

            result1, record1 = await adapter.run_api(
                api_id="api.common.health_check",
                project=mock_project,
            )

            result2, record2 = await adapter.run_api(
                api_id="api.common.health_check",
                project=mock_project,
            )

        # 验证 UUID 不同
        assert record1.id != record2.id
        # 验证都是有效的 UUID
        assert UUID(record1.id)
        assert UUID(record2.id)


class TestRegistryCreation:
    """测试 Registry 的创建"""

    @pytest.mark.asyncio
    async def test_registry_initialization(self, mock_project: Project) -> None:
        """测试 Registry 使用 project 的 assets_root 正确初始化"""
        adapter = EngineAdapter()

        expected_result = ApiResult.success(response={"status_code": 200})

        with patch("testplat_control.adapters.engine_adapter.Registry") as mock_registry_class:
            with patch("testplat_control.adapters.engine_adapter.run_api") as mock_run_api:
                mock_run_api.return_value = expected_result

                await adapter.run_api(
                    api_id="api.common.health_check",
                    project=mock_project,
                )

        # 验证 Registry 被正确初始化
        mock_registry_class.assert_called_once()
        call_args = mock_registry_class.call_args
        assert call_args.kwargs["assets_root"] == Path(mock_project.assets_root)
