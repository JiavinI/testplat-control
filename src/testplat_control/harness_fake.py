"""FakeEngine 验收入口。

仅供本地门禁 / 演示显式启动，**不是**默认生产路径。

用法::

    uv run uvicorn testplat_control.harness_fake:app --host 127.0.0.1 --port 8000

启动时仍会校验已安装的 ``testplat-engine`` Interface（Fake 依赖其 DTO/异常），
但路由层的 ``EnginePort`` 被替换为 ``FakeEngineAdapter``，不访问真实目标网络。
"""

from __future__ import annotations

from testplat_control.adapters.fake_engine import FakeEngineAdapter
from testplat_control.deps import get_engine_port
from testplat_control.main import app

_fake = FakeEngineAdapter()
app.dependency_overrides[get_engine_port] = lambda: _fake

__all__ = ["app"]
