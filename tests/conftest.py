"""测试引导。

Engine 通过正式/editable 包依赖安装；不再注入 sys.path 桩。
集成与路由测试用 ``app.dependency_overrides[get_engine_port]`` 注入 Fake。

配置与执行接口需要平台会话。默认注入测试操作人，避免改写全部既有用例。
标记 ``platform_auth`` 的用例走真实 cookie。
"""

from __future__ import annotations

import os

import pytest

# 必须在导入应用前覆盖 .env 中的数据库配置，防止测试夹具写入本机预览库。
# 文件库持久化与并发测试由各自 fixture / 子进程显式创建临时库。
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["TESTPLAT_LEGACY_GIT_CONFIG"] = "false"

from testplat_control.api.platform_session import require_user  # noqa: E402
from testplat_control.main import app  # noqa: E402
from testplat_control.services.platform_auth import PlatformPrincipal  # noqa: E402

_TEST_PRINCIPAL = PlatformPrincipal(id="test-user", username="tester")


@pytest.fixture(autouse=True)
def _default_platform_user(request: pytest.FixtureRequest):
    """让既有用例以登录用户调用配置/执行接口。"""
    if request.node.get_closest_marker("platform_auth"):
        yield
        return
    app.dependency_overrides[require_user] = lambda: _TEST_PRINCIPAL
    yield
    app.dependency_overrides.pop(require_user, None)


@pytest.fixture(autouse=True)
def _explicit_legacy_config(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """仅历史兼容用例显式启用 Git 配置，正常 Web 测试保持生产默认值。"""
    from testplat_control.config import settings

    monkeypatch.setattr(
        settings,
        "testplat_legacy_git_config",
        request.node.get_closest_marker("legacy_git_config") is not None,
    )
