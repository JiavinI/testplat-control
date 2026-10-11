"""测试引导。

Engine 通过正式/editable 包依赖安装；不再注入 sys.path 桩。
集成与路由测试用 ``app.dependency_overrides[get_engine_port]`` 注入 Fake。
"""

from __future__ import annotations
