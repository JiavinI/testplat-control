"""假登录策略：产出命名值；可选抛异常 / 超时，供矩阵 §6.17–18。

秘密常量与 Engine FakePlugin / 本地 target 对齐，便于泄密搜索。
插件只拿 LoginContext，不访问资产、不触碰业务步骤。
"""

from __future__ import annotations

import asyncio
from typing import Any

PLUGIN_KEY = "tp-fake-plugin-key-11aa"
PLUGIN_TOKEN = "plug-token-5f5f5f5f5f"


class FakeLoginStrategy:
    """测试用插件：values → 产出 token；raise → strategy_error；sleep → 超时。"""

    name = "fake_login"

    def validate(self, auth: Any) -> None:
        params = getattr(auth, "params", None) or {}
        if "behavior" not in params:
            # 异常文本故意含秘密：公开面不得外泄
            raise ValueError(f"missing behavior {PLUGIN_KEY}")

    async def login(self, ctx: Any) -> Any:
        from testplat_engine import LoginResult

        behavior = ctx.params["behavior"]
        api_key = ctx.params["api_key"]
        revealed = api_key.reveal() if hasattr(api_key, "reveal") else str(api_key)
        ctx.record(
            {
                "method": "POST",
                "url": f"{ctx.host_url}/plugin/login?k={revealed}",
                "headers": {},
                "body": {"key": revealed},
            },
            {"status_code": 200, "headers": {}, "body": {"issued": PLUGIN_TOKEN}},
            name="plugin_login",
        )
        if behavior == "raise":
            raise RuntimeError(f"plugin exploded with {revealed}")
        if behavior == "sleep":
            await asyncio.sleep(5)
        return LoginResult(values={"token": PLUGIN_TOKEN})
