"""读取资产 ``config/auth/_profiles.yaml``。

流程名不是账号名。本模块只抽出流程名与 ``${secret:字段名}``，不渲染凭据。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from testplat_control.services.auth_loader import _SECRET_RE, IDENTITY_NAME_RE

logger = logging.getLogger(__name__)

PROFILES_FILE = Path("auth") / "_profiles.yaml"
_RESERVED = "none"


@dataclass(frozen=True, slots=True)
class LoginProfileSpec:
    """一个可复用登录流程。``body`` 是身份对象（含 login 或 headers），不含已解析秘密。"""

    name: str
    body: dict[str, Any]
    credential_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProfileCatalog:
    """当前 commit 下的流程目录。``plugins`` 原样交给 auth 构造，不在此渲染。"""

    profiles: tuple[LoginProfileSpec, ...]
    login_plugins: tuple[str, ...]
    connections: dict[str, Any] | None


class ProfileFileError(Exception):
    """流程文件无法读取。``message`` 不含文件原文。"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def profiles_path(config_root: str | Path) -> Path:
    return Path(config_root) / PROFILES_FILE


def _secret_fields(node: object) -> list[str]:
    found: list[str] = []
    if isinstance(node, str):
        found.extend(_SECRET_RE.findall(node))
    elif isinstance(node, dict):
        for value in node.values():
            found.extend(_secret_fields(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_secret_fields(value))
    return list(dict.fromkeys(found))


def load_profile_catalog(config_root: str | Path) -> ProfileCatalog:
    """读取流程文件。文件不存在时返回空目录，不视为错误。"""
    path = profiles_path(config_root)
    if not path.is_file():
        return ProfileCatalog(profiles=(), login_plugins=(), connections=None)
    try:
        loaded: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        logger.error("登录流程 YAML 无效 exc_type=%s", type(exc).__name__)
        raise ProfileFileError("登录流程文件无效") from None
    except (OSError, UnicodeDecodeError) as exc:
        logger.error("读取登录流程失败 exc_type=%s", type(exc).__name__)
        raise ProfileFileError("无法读取登录流程文件") from None
    if not isinstance(loaded, dict):
        raise ProfileFileError("登录流程文件无效")
    identities = loaded.get("identities")
    if not isinstance(identities, dict):
        raise ProfileFileError("登录流程文件无效")
    plugins_raw = loaded.get("login_plugins") or []
    if not isinstance(plugins_raw, list) or any(not isinstance(item, str) for item in plugins_raw):
        raise ProfileFileError("登录流程文件无效")
    connections = loaded.get("connections")
    if connections is not None and not isinstance(connections, dict):
        raise ProfileFileError("登录流程文件无效")
    profiles: list[LoginProfileSpec] = []
    for name, body in identities.items():
        if (
            not isinstance(name, str)
            or not IDENTITY_NAME_RE.fullmatch(name)
            or name == _RESERVED
            or not isinstance(body, dict)
        ):
            raise ProfileFileError("登录流程文件无效")
        profiles.append(
            LoginProfileSpec(
                name=name,
                body=dict(body),
                credential_fields=tuple(_secret_fields(body)),
            )
        )
    return ProfileCatalog(
        profiles=tuple(profiles),
        login_plugins=tuple(plugins_raw),
        connections=connections,
    )


def profile_names_pattern() -> re.Pattern[str]:
    return IDENTITY_NAME_RE
