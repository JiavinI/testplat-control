"""测试引导。

未安装 sibling 包 testplat-engine 时注入最小桩，让适配器单测可以 mock
``run_api``，而不必把引擎仓库放在本仓库旁边。
"""

from __future__ import annotations

import sys
from types import ModuleType


def _install_engine_stub() -> None:
    """在导入失败时注册 testplat_engine 桩模块。"""
    try:
        import testplat_engine  # noqa: F401
    except ImportError:
        pass
    else:
        return

    engine = ModuleType("testplat_engine")
    adapters = ModuleType("testplat_engine.adapters")
    filesystem = ModuleType("testplat_engine.adapters.filesystem")
    domain = ModuleType("testplat_engine.domain")
    result_mod = ModuleType("testplat_engine.domain.result")

    class ApiResult:
        """引擎结果桩，覆盖适配器单测用到的字段。"""

        def __init__(self, status: str, response: object = None, error: str | None = None) -> None:
            self.status = status
            self.response = response
            self.error = error

        @property
        def is_success(self) -> bool:
            return self.status == "success"

        @property
        def is_failed(self) -> bool:
            return self.status == "failed"

        @classmethod
        def success(cls, response: object = None, error: str | None = None) -> ApiResult:
            return cls(status="success", response=response, error=error)

        @classmethod
        def failed(cls, error: str | None = None, response: object = None) -> ApiResult:
            return cls(status="failed", response=response, error=error)

    class Registry:
        """文件系统注册表桩。"""

        def __init__(self, assets_root: object) -> None:
            self.assets_root = assets_root

    async def run_api(*args: object, **kwargs: object) -> ApiResult:
        raise RuntimeError("testplat-engine stub: run_api should be mocked")

    engine.run_api = run_api
    filesystem.Registry = Registry
    result_mod.ApiResult = ApiResult
    adapters.filesystem = filesystem
    domain.result = result_mod
    engine.adapters = adapters
    engine.domain = domain

    sys.modules["testplat_engine"] = engine
    sys.modules["testplat_engine.adapters"] = adapters
    sys.modules["testplat_engine.adapters.filesystem"] = filesystem
    sys.modules["testplat_engine.domain"] = domain
    sys.modules["testplat_engine.domain.result"] = result_mod


_install_engine_stub()
