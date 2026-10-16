"""门禁脚本的平台会话。

配置和执行接口未登录会返回 401。pytest 的依赖覆盖只在测试进程里生效，
独立脚本必须自己注册或登录。新建客户端时显式复制 cookie，不共享 CookieJar。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

COOKIE_NAME = "testplat_session"
GATE_USERNAME = "gateop"
GATE_PASSWORD = "gate-pass-1"


def establish(
    client: Any,
    *,
    username: str = GATE_USERNAME,
    password: str = GATE_PASSWORD,
    auth_base: str = "",
) -> str:
    """注册；用户名已存在则登录。返回会话 token，不写入日志。"""
    registered = client.post(
        f"{auth_base}/auth/register",
        json={"username": username, "password": password},
    )
    if registered.status_code == 409:
        registered = client.post(
            f"{auth_base}/auth/login",
            json={"username": username, "password": password},
        )
    if registered.status_code != 200:
        raise RuntimeError(f"平台会话失败 HTTP {registered.status_code}")
    return inherit_cookies(client, client)


def inherit_cookies(source: Any, dest: Any) -> str:
    """把源客户端的会话 cookie 逐枚复制到目标客户端。"""
    token: str | None = None
    jar = getattr(source.cookies, "jar", None)
    if jar is not None:
        for cookie in jar:
            if cookie.name != COOKIE_NAME:
                continue
            token = cookie.value
            dest.cookies.set(
                cookie.name,
                cookie.value,
                domain=cookie.domain,
                path=cookie.path or "/",
            )
    if not token:
        token = source.cookies.get(COOKIE_NAME)
        if not token:
            raise RuntimeError("平台会话 cookie 缺失")
        dest.cookies.set(COOKIE_NAME, token)
    return str(token)


def inherit_httpx(source: Any, **kwargs: Any) -> Any:
    """新建 httpx 客户端并显式带上源会话。调用方负责关闭。"""
    import httpx

    child = httpx.Client(**kwargs)
    inherit_cookies(source, child)
    return child


def default_assets_checkout(control_root: Path) -> Path:
    """资产仓默认在 Control 的兄弟目录；也接受 PHASE4_ASSETS_SRC。"""
    import os

    configured = os.environ.get("PHASE4_ASSETS_SRC")
    if configured:
        return Path(configured)
    sibling = control_root.parent / "testplat-assets"
    if sibling.is_dir():
        return sibling
    return Path.home() / "testplat-assets"
